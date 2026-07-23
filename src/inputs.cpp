#include "inputs.h"
#include "useraddons.h"
#include "pedals.h"
#include "settings.h"
#include "loopmanager.h"
#include "arp.h"
#include "menus.h"
#include "playmenu.h"
#include "pixels.h"
#include "display.h"
#include "ticks.h"

Inputs inputs;

// ---------------- KeyMatrix scanner (keypad.KeyMatrix replacement) ----------------

namespace {

struct KeyEvent {
    uint8_t key_number;
    bool pressed;
};

// Drive polarity/direction for this board's pad diodes:
//   Mode 0: drive column LOW,  rows pull-up,    pressed = row LOW
//   Mode 1: drive column HIGH, rows pull-down,  pressed = row HIGH
//   Mode 2: drive row LOW,     cols pull-up,    pressed = col LOW
//   Mode 3: drive row HIGH,    cols pull-down,  pressed = col HIGH
//
// Mode is now hardcoded to 2 (item 11). On-device logs showed autodetect locking
// only ever on modes 1 and 2 (never 0/3) → diodes anode-on-columns (matches Python
// columns_to_anodes=True). Modes 1 and 2 are the same column→row current direction;
// which one won was a race between finger contact and probe order, and either
// mislock or an ESD/noise hit during probing could lock a WRONG mode and leave all
// pads dead until reboot. Mode 2 (conventional active-low / pull-up) is chosen for
// its better noise margin. Set PAD_MATRIX_AUTODETECT to 1 to restore self-calibration
// for debugging on a different board revision.
#define PAD_MATRIX_AUTODETECT 0

class KeyMatrix {
public:
    void begin() {
        for (uint8_t i = 0; i < 4; i++) {
            pinMode(C::PAD_ROW_PINS[i], INPUT);
            pinMode(C::PAD_COL_PINS[i], INPUT);
        }
        memset(_state, 0, sizeof(_state));
        memset(_last_change, 0, sizeof(_last_change));
    }

    int locked_mode() const { return _mode; }

    void scan() {
        if (_mode < 0) {
            // Detection phase: probe modes until any key conducts
            for (uint8_t m = 0; m < 4; m++) {
                if (_scan_pass(m, nullptr)) {
                    _mode = m;
                    Serial.printf("[MATRIX] locked scan mode %d\n", m);
                    break;
                }
            }
            if (_mode < 0) {
                return; // nothing pressed yet anywhere
            }
        }

        bool raw[16];
        _scan_pass((uint8_t)_mode, raw);

        uint32_t now = ticks::ticks_ms();
        for (uint8_t key = 0; key < 16; key++) {
            if (raw[key] != _state[key] && (uint32_t)(now - _last_change[key]) >= 20) { // 20 ms debounce
                _state[key] = raw[key];
                _last_change[key] = now;
                if (_q_count < QUEUE_SIZE) {
                    _queue[(_q_head + _q_count) % QUEUE_SIZE] = {key, raw[key]};
                    _q_count++;
                }
            }
        }
    }

    bool get_event(KeyEvent &out) {
        if (_q_count == 0) {
            return false;
        }
        out = _queue[_q_head];
        _q_head = (_q_head + 1) % QUEUE_SIZE;
        _q_count--;
        return true;
    }

private:
    static const uint8_t QUEUE_SIZE = 32;
#if PAD_MATRIX_AUTODETECT
    int _mode = -1; // -1 = polarity not yet detected (probes on first press)
#else
    int _mode = 2; // hardcoded verified polarity (item 11)
#endif
    bool _state[16];
    uint32_t _last_change[16];
    KeyEvent _queue[QUEUE_SIZE];
    uint8_t _q_head = 0, _q_count = 0;

    // One full 4x4 scan in the given mode. Fills raw[16] if non-null (indexed
    // row*4+col, matching CircuitPython key_number). Returns true if any key reads
    // pressed.
    bool _scan_pass(uint8_t mode, bool *raw) {
        bool drive_cols = (mode == 0 || mode == 1);
        bool drive_high = (mode == 1 || mode == 3);
        const uint8_t *drive_pins = drive_cols ? C::PAD_COL_PINS : C::PAD_ROW_PINS;
        const uint8_t *read_pins = drive_cols ? C::PAD_ROW_PINS : C::PAD_COL_PINS;
        int pressed_level = drive_high ? HIGH : LOW;

        for (uint8_t i = 0; i < 4; i++) {
            pinMode(read_pins[i], drive_high ? INPUT_PULLDOWN : INPUT_PULLUP);
        }

        bool any = false;
        for (uint8_t d = 0; d < 4; d++) {
            pinMode(drive_pins[d], OUTPUT);
            digitalWrite(drive_pins[d], drive_high ? HIGH : LOW);
            delayMicroseconds(5); // settle
            for (uint8_t s = 0; s < 4; s++) {
                bool pressed = (digitalRead(read_pins[s]) == pressed_level);
                any |= pressed;
                if (raw) {
                    uint8_t row = drive_cols ? s : d;
                    uint8_t col = drive_cols ? d : s;
                    raw[row * 4 + col] = pressed;
                }
            }
            pinMode(drive_pins[d], INPUT);
        }
        return any;
    }
};

KeyMatrix key_matrix;

// ---------------- Quadrature encoder (rotaryio replacement, divisor 4) ----------------

volatile int32_t enc_count = 0;
volatile uint8_t enc_prev = 0;

void enc_isr() {
    // Standard quadrature transition table. A/B assignment order sets rotation
    // direction — verified on hardware 2026-07-04 (DT first matches the knob).
    static const int8_t table[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};
    uint8_t a = digitalRead(C::PIN_ENCODER_DT);
    uint8_t b = digitalRead(C::PIN_ENCODER_CLK);
    uint8_t curr = (a << 1) | b;
    enc_count += table[(enc_prev << 2) | curr];
    enc_prev = curr;
}

// Read accumulated detents and consume them (Python: pos = encoder.position; encoder.position = 0)
int encoder_take_position() {
    noInterrupts();
    int32_t raw = enc_count;
    int detents = raw / 4;
    enc_count = raw - detents * 4; // keep sub-detent remainder
    interrupts();
    return detents;
}

} // namespace

// ---------------- Inputs ----------------

void Inputs::initialize() {
    key_matrix.begin();

    pinMode(C::PIN_FN_BTN, INPUT_PULLUP);
    pinMode(C::PIN_ENCODER_BTN, INPUT_PULLUP);
    pinMode(C::PIN_ENCODER_CLK, INPUT_PULLUP);
    pinMode(C::PIN_ENCODER_DT, INPUT_PULLUP);
    enc_prev = (digitalRead(C::PIN_ENCODER_DT) << 1) | digitalRead(C::PIN_ENCODER_CLK);
    attachInterrupt(digitalPinToInterrupt(C::PIN_ENCODER_CLK), enc_isr, CHANGE);
    attachInterrupt(digitalPinToInterrupt(C::PIN_ENCODER_DT), enc_isr, CHANGE);

    // Registered for midi.change_bank's stuck-note prevention (Python late import)
    midi.set_pad_held_provider([](uint8_t pad_idx) { return inputs.note_buttons[pad_idx].state; });
}

// Generic action dispatch helpers (Python call_function)
static bool call_encoder_button_held(bool released) {
    if (Menu::current_menu && Menu::current_menu->actions.encoder_button_held_function) {
        Menu::current_menu->actions.encoder_button_held_function(released);
        return true;
    }
    return false;
}

void Inputs::handle_velocity_mode(uint8_t pad_idx) {
    // Off
    if (single_note_mode_midi_val != -1) {
        single_note_mode_midi_val = -1;
        settings.velocity_mapped = false;
        pixels.display_velocity_map(false);
        loop_manager.update_pad_pixels();
    }
    // On
    else {
        single_note_mode_midi_val = midi.get_midi_note_by_idx(pad_idx);
        pixels.display_velocity_map(true);
        settings.velocity_mapped = true;
    }
}

bool Inputs::process_nav_buttons() {
    fn_button.set_current_value(digitalRead(C::PIN_FN_BTN) == HIGH);
    encoder_button.set_current_value(digitalRead(C::PIN_ENCODER_BTN) == HIGH);
    fn_button.update_all();
    encoder_button.update_all();

    bool fn_new_release_from_held = fn_button.new_release_from_held;
    bool fn_new_release = fn_button.new_release;
    bool fn_new_dbl_press = fn_button.new_dbl_press;
    bool fn_new_press = fn_button.new_press;
    bool fn_is_held = fn_button.is_held;
    bool fn_is_down = fn_button.state; // currently pressed (no hold delay)
    bool encoder_new_release = encoder_button.new_release;
    bool encoder_new_release_from_held = encoder_button.new_release_from_held;
    bool encoder_new_dbl_press = encoder_button.new_dbl_press;
    bool encoder_is_held = encoder_button.is_held;
    bool encoder_is_down = encoder_button.state;

    bool fn_released = fn_new_release_from_held || fn_new_release;
    bool fn_pressed = fn_new_dbl_press || fn_new_press;

    // PANIC chord: FN + encoder both held >= PANIC_HOLD_MS. Checked before every
    // other gesture (including lock) so it always works, and latched until both
    // buttons are up so the unwind releases can't fire bank shift / nav toggle /
    // held-release actions.
    if (_panic_latched) {
        if (!fn_is_down && !encoder_is_down) {
            _panic_latched = false;
            fn_button.reset_double_press();
            encoder_button.reset_double_press();
        }
        return true; // swallow all FN/encoder events while the chord unwinds
    }
    if (fn_button.is_held && encoder_button.is_held &&
        fn_button.held_time_ms >= C::PANIC_HOLD_MS &&
        encoder_button.held_time_ms >= C::PANIC_HOLD_MS) {
        _do_panic();
        _panic_latched = true;
        return true;
    }

    if (fn_is_down && encoder_new_release) { // Up 1/4 bank (instant, no hold needed)
        midi.offset_pads(true);
        if (Menu::current_idx == C::MENU_PLAY && settings.get_play_mode() == "loop") {
            playmenu::display_bank_offset();
        }
        pixels.encoder_button_off();
        pixels.set_fn_button_off();
        encoder_button.reset_double_press(); // prevent double processing
        return true;
    }

    if (encoder_is_down && fn_released) { // Down 1/4 bank (instant, no hold needed)
        midi.offset_pads(false);
        if (Menu::current_idx == C::MENU_PLAY && settings.get_play_mode() == "loop") {
            playmenu::display_bank_offset();
        }
        pixels.encoder_button_off();
        pixels.set_fn_button_off();
        fn_button.reset_double_press();
        encoder_button.set_ignore_next_release(); // prevent nav mode toggle on release
        return true;
    }

    if (encoder_is_down && fn_new_dbl_press) { // prevent FN double-click when encoder down
        fn_button.reset_double_press();
        return true;
    }

    if (fn_released) {
        _handle_fn_button_release();
    }

    if (fn_pressed) {
        if (loop_manager.is_recording) {
            loop_manager.handle_fn_press();
            fn_button.set_ignore_next_release(); // prevent double processing
        } else {
            _handle_fn_button_press();
        }
        return true;
    }

    if (fn_is_held) {
        _handle_fn_button_held();
    }

    if (encoder_new_dbl_press) {
        Menu::toggle_nav_mode(); // account for first click changing this
        Menu::toggle_lock_mode();
    }

    if (Menu::is_locked) {
        return false;
    }

    if (encoder_is_held) {
        pixels.encoder_button_on(C::PAD_HELD_COLOR);
        call_encoder_button_held(false);
    }

    if (encoder_new_release) {
        if (encoder_new_release_from_held) {
            if (Menu::is_nav_mode) {
                pixels.encoder_button_on(C::NAV_MODE_COLOR);
            } else {
                pixels.encoder_button_off();
            }
            call_encoder_button_held(true);
        } else {
            Menu::toggle_nav_mode();
        }
    }

    return false;
}

void Inputs::_do_panic() {
    // Same seize-control sequence the web lock uses (item 8): stop + note-off every
    // loop, clear the play queue, abandon any in-progress recording — then flush the
    // arp's ringing notes and blast CC 123 on all 16 channels for live/held notes.
    loop_manager.silence_all_for_lock();
    for (const NoteMsg &off : arpeggiator.flush_playing_notes()) {
        midi.send_note_off(off.note, off.channel);
    }
    arpeggiator.clear_arp_notes();
    midi.all_notes_off_all_channels();

    display.show_notification("PANIC: all notes off", true);
    display.display_dot(0, true); // reset the held-gesture dots the chord armed
    pixels.flash_pixel(C::FN_LED_IDX, 0.8f, C::RED);
    pixels.flash_pixel(C::ENC_LED_IDX, 0.8f, C::RED);
}

bool Inputs::_handle_fn_button_release() {
    if (!(fn_button.new_release_from_held || fn_button.new_release)) {
        return false;
    }
    const MenuActions &actions = Menu::current_menu->actions;
    if (fn_button.new_release_from_held) {
        if (actions.fn_button_held_function) {
            actions.fn_button_held_function(true);
        }
    } else {
        if (actions.fn_button_press_function) {
            actions.fn_button_press_function("release");
        }
    }
    pixels.set_fn_button_off();
    return true;
}

bool Inputs::_handle_fn_button_press() {
    if (!(fn_button.new_dbl_press || fn_button.new_press)) {
        return false;
    }
    const MenuActions &actions = Menu::current_menu->actions;

    // double press
    if (fn_button.new_dbl_press) {
        bool action_fn_ran = false;
        if (actions.fn_button_dbl_press_function) {
            actions.fn_button_dbl_press_function();
            action_fn_ran = true;
        }
        if (action_fn_ran && Menu::current_idx == C::MENU_PLAY) {
            Menu::toggle_lock_mode(settings.get_play_mode() == "encoder");
        }
        return true;
    }

    // single press
    if (fn_button.new_press) {
        if (actions.fn_button_press_function) {
            actions.fn_button_press_function("press");
        }
        pixels.set_fn_button_on(C::FN_BUTTON_COLOR);
        return true;
    }
    return false;
}

void Inputs::_handle_fn_button_held() {
    const MenuActions &actions = Menu::current_menu->actions;
    if (actions.fn_button_held_function) {
        actions.fn_button_held_function(false);
    }
    pixels.set_fn_button_on(C::PAD_HELD_COLOR);
}

void Inputs::handle_encoder_arp_mode(Button &button, const String &play_mode, uint8_t pad_idx) {
    bool has_loop = loop_manager.loops[pad_idx] != nullptr;

    // Release — remove pad from arp
    if (button.new_release) {
        if (play_mode == "encoder") {
            C::Rgb color = has_loop ? C::LOOP_COLOR : C::BLACK;
            pixels.set_default_color(pad_idx, color, true);
            pixels.set_color(pad_idx, color);
        }
        arpeggiator.remove_source(pad_idx);
        return;
    }

    if (!button.state) {
        return;
    }

    // New press — add pad to arp
    if (button.new_press) {
        if (play_mode == "encoder") {
            pixels.set_default_color(pad_idx, C::PAD_HELD_COLOR, true);
            pixels.set_color(pad_idx, C::PAD_HELD_COLOR);
        }
        arpeggiator.add_source(pad_idx);
    }
}

void Inputs::process_inputs_slow() {
    encoder_delta = encoder_take_position();
#ifdef LOOPSTER_TEST_HOOKS
    encoder_delta += _test_encoder_delta;
    _test_encoder_delta = 0;
#endif

    int hold_count = _process_button_holds();
    const MenuActions &actions = Menu::current_menu->actions;

    // Encoder change while pads held
    if (encoder_delta != 0 && hold_count > 0) {
        is_any_pad_held = true;
        if (actions.pad_held_function) {
            bool states[C::NUM_PADS];
            get_button_states_list(states);
            actions.pad_held_function(-1, states, encoder_delta);
        }
    }

    // Catch stray encoder turns meant for pads
    if (hold_count == 0 && is_any_pad_held) {
        is_any_pad_held = false;
        encoder_delta = 0;
    }

    process_nav_buttons();

    if (is_any_pad_held || encoder_delta == 0) { // already processed in pad_held_function
        return;
    }

    // Lock only blocks bare encoder turns (allows arp changes with FN/encoder held)
    if (Menu::is_locked && !fn_button.is_held && !encoder_button.is_held) {
        return;
    }

    bool encoder_direction = encoder_delta > 0;
    if (Menu::is_nav_mode && !encoder_button.is_held && !fn_button.is_held) {
        Menu::next_or_prev_menu(encoder_direction);
        return;
    }

    if (fn_button.is_held) {
        if (actions.fn_button_held_and_encoder_change_function) {
            actions.fn_button_held_and_encoder_change_function(encoder_direction);
        }
        return;
    }

    if (encoder_button.is_held) {
        if (actions.encoder_button_press_and_turn_function) {
            actions.encoder_button_press_and_turn_function(encoder_direction);
        }
        return;
    }

    // Default
    if (actions.encoder_change_function) {
        actions.encoder_change_function(encoder_direction);
    }
}

int Inputs::_process_button_holds() {
    int hold_count = 0;
    int pressed = 0; // reconciliation sync
    const MenuActions &actions = Menu::current_menu->actions;

    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        Button &button = note_buttons[i];
        if (button.state) {
            pressed++;
        }
        if (button.check_if_held()) {
            hold_count++;
            if (!is_any_pad_held) {
                is_any_pad_held = true;
                if (actions.pad_held_function) {
                    actions.pad_held_function(button.pad_idx, nullptr, 0);
                }
            }
        }
    }
    pressed_count = pressed; // sync point
    return hold_count;
}

void Inputs::process_inputs_fast() {
    reset_pads_and_notes();
    for (const NoteMsg &n : arpeggiator.get_off_notes()) {
        new_notes_off.push_back(n);
    }

    // Re-sync the latched play mode only while no pads are down — must happen
    // BEFORE the keymatrix scan below mutates pressed_count, so pads pressed or
    // released this pass are still dispatched under last pass's mode.
    if (pressed_count == 0) {
        _latched_play_mode = settings.get_play_mode();
    }

    bool has_releases = false;
    std::vector<uint8_t> new_press_indices = _process_keymatrix(has_releases);

    if (new_press_indices.empty() && encoder_delta == 0) {
        if (!has_releases) {
            // Still need to check accelerometer arp in encoder mode
            if (_latched_play_mode == "encoder" && Menu::current_idx != C::MENU_MIDI &&
                arpeggiator.has_events()) {
                if (useraddons::should_trigger_accelerometer_arp()) {
                    _play_arp_events(true);
                }
            }
            return;
        }
    }

    // Latched, not live: releases must take the same path their press took, even if
    // settings.play_mode changed mid-hold. (Const ref, not a copy — Tier 3 Item 4.)
    const String &play_mode = _latched_play_mode;
    if (fn_button.is_held && !new_press_indices.empty()) {
        _handle_fn_button_held_fast(new_press_indices);
        return;
    }

    bool loop_recording = loop_manager.is_recording;

    // Arp notes
    if (play_mode == "encoder" && Menu::current_idx != C::MENU_MIDI) {
        for (uint8_t i = 0; i < C::NUM_PADS; i++) {
            Button &button = note_buttons[i];
            if (button.state || button.new_release) {
                handle_encoder_arp_mode(button, play_mode, (uint8_t)button.pad_idx);
            }
        }

        if (pressed_count == 0 && arpeggiator.has_events()) {
            // Flush queued note-offs BEFORE clearing — clear_arp_notes() drops the
            // arp_note_off_queue without sending it, so any notes still ringing would hang
            // forever (item 10). Reachable with sources still registered, e.g. pads released
            // while in the MIDI menu (the per-pad release handler doesn't run there). The offs
            // go out via new_notes_off in main step 5, exactly like a normal arp step.
            for (const NoteMsg &off : arpeggiator.flush_playing_notes()) {
                new_notes_off.push_back(off);
            }
            arpeggiator.clear_arp_notes();
        }

        // Encoder OR accelerometer triggers arp
        if (encoder_delta > 0 && arpeggiator.has_events()) {
            _play_arp_events();
        } else if (useraddons::should_trigger_accelerometer_arp() && arpeggiator.has_events()) {
            _play_arp_events(true);
        }
    }

    if (play_mode == "encoder") { // encoder mode skips regular note processing
        return;
    }

    // Regular note triggering
    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        Button &button = note_buttons[i];
        if (!(button.new_press || button.new_release)) {
            continue;
        }

        uint8_t pad_idx = (uint8_t)button.pad_idx;
        uint8_t note, velocity;
        _get_note_and_velocity(pad_idx, note, velocity);
        MidiLoop *loop = loop_manager.loops[pad_idx];

        // New press
        if (button.new_press) {
            if (loop && !loop_recording) {
                if (loop->loop_type == "hold") {
                    loop_manager.toggle_loop_playstate(pad_idx, true, false); // force play
                } else {
                    loop_manager.toggle_loop_playstate(pad_idx);
                }
            } else {
                // Current output channel for live input notes
                new_notes_on.push_back({note, velocity, pad_idx, (int8_t)settings.midi_channel_out});
            }
        }

        // New release
        if (button.new_release) {
            if (loop && !loop_recording && loop->loop_type == "hold") {
                loop_manager.toggle_loop_playstate(pad_idx, false, true); // force stop
            } else if (!(loop && !loop_recording) && pad_idx != recording_start_pad) {
                new_notes_off.push_back({note, 127, pad_idx, (int8_t)settings.midi_channel_out});
            }
        }

        // Recording start — FN held while recording to one pad after another
        if (pad_idx == recording_start_pad && (button.new_press || button.new_release)) {
            recording_start_pad = -1;
        }
    }
}

std::vector<uint8_t> Inputs::_process_keymatrix(bool &has_releases) {
    std::vector<uint8_t> new_press_indices;
    has_releases = false;

    // Physical keypad events first
    key_matrix.scan();
    KeyEvent event;
    while (key_matrix.get_event(event)) {
        uint8_t pad_idx = event.key_number;
        if (event.pressed) {
            pressed_count++;
        } else {
            // Clamp: an unmatched release (pedal ring-buffer drop / debounce edge) must not
            // drive the count negative (R16)
            if (pressed_count > 0) pressed_count--;
            has_releases = true;
        }
        if (note_buttons[pad_idx].process_keymatrix_event(event.pressed) >= 0) {
            new_press_indices.push_back(pad_idx);
        }
    }

    // Pedal events (Colm addition)
    if (C::USING_FOOT_PEDALS) {
        PedalEvent pedal_event;
        while (pedals.get_event(pedal_event)) {
            uint8_t pad_idx = pedal_event.key_number;
            if (pedal_event.pressed) {
                pressed_count++;
            } else {
                if (pressed_count > 0) pressed_count--; // clamp (R16)
                has_releases = true;
            }
            if (note_buttons[pad_idx].process_keymatrix_event(pedal_event.pressed) >= 0) {
                new_press_indices.push_back(pad_idx);
            }
        }
    }

#ifdef LOOPSTER_TEST_HOOKS
    // Injected test events, handled identically to pedal events
    for (const TestKeyEvent &ev : _test_key_events) {
        if (ev.pressed) {
            pressed_count++;
        } else {
            if (pressed_count > 0) pressed_count--; // clamp (R16)
            has_releases = true;
        }
        if (note_buttons[ev.pad].process_keymatrix_event(ev.pressed) >= 0) {
            new_press_indices.push_back(ev.pad);
        }
    }
    _test_key_events.clear();
#endif

    return new_press_indices;
}

#ifdef LOOPSTER_TEST_HOOKS
void Inputs::test_inject_pad(uint8_t pad_idx, bool pressed) {
    _test_key_events.push_back({pad_idx, pressed});
}

void Inputs::test_inject_encoder(int delta) {
    _test_encoder_delta += delta;
}
#endif

void Inputs::reset_pads_and_notes() {
    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        note_buttons[i].reset_actions();
    }
    new_notes_on.clear();
    new_notes_off.clear();
}

void Inputs::_handle_fn_button_held_fast(const std::vector<uint8_t> &new_press_indices) {
    const String &play_mode = _latched_play_mode; // latched per press-session — see process_inputs_fast
    for (uint8_t pad_idx : new_press_indices) {
        if (play_mode == "velocity") {
            handle_velocity_mode(pad_idx);
        }
        if (play_mode == "loop") {
            recording_start_pad = pad_idx;
            loop_manager.add_remove_loop(pad_idx);
            if (Menu::current_idx != C::MENU_PLAY) {
                Menu::next_or_prev_menu(false, C::MENU_PLAY); // jump to play menu
            }
        }
        note_buttons[pad_idx].reset_new_press(); // avoid double processing
    }
}

void Inputs::_play_arp_events(bool from_accelerometer) {
    bool has_events = arpeggiator.has_events();

    if (!(has_events || arpeggiator.has_ccs())) {
        return;
    }

    // Encoder mode requires encoder movement, unless triggered by accelerometer
    if (!from_accelerometer && encoder_delta == 0) {
        return;
    }

    // Backward only works in polyphonic mode
    bool forward = encoder_delta > 0;
    if (!forward && !settings.arp_is_polyphonic) {
        encoder_delta = 0;
        return; // CCW does nothing in monophonic mode
    }
    encoder_delta = 0;

    // Monophonic — turn off last note
    if (has_events && !settings.arp_is_polyphonic && arpeggiator.has_last_played_note) {
        new_notes_off.push_back(arpeggiator.last_played_note);
    }

    ArpStep step = arpeggiator.get_next_arp_events(forward);
    if (step.has_note) {
        new_notes_on.push_back(step.note);
    }
    // Send CCs immediately — channel was computed at add time
    if (step.has_cc) {
        midi.send_cc(step.cc.cc, step.cc.value, step.cc.channel);
    }
}

void Inputs::_get_note_and_velocity(uint8_t pad_idx, uint8_t &note, uint8_t &velocity) {
    if (single_note_mode_midi_val != -1) {
        note = (uint8_t)single_note_mode_midi_val;
        velocity = midi.get_velocity_singlenote_by_idx(pad_idx);
    } else {
        note = midi.get_midi_note_by_idx(pad_idx);
        velocity = midi.get_velocity_by_idx(pad_idx);
    }
}

void Inputs::get_button_states_list(bool out[C::NUM_PADS]) {
    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        out[i] = note_buttons[i].state;
    }
}
