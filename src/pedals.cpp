#include "pedals.h"
#include "pixels.h" // blink_phase + core1_owns_pixels
#include "serial_config.h" // cdc_log (Q1 bounded prints)

Pedals pedals;

const uint8_t Pedals::_pedal_pins[C::PEDAL_COUNT] = {
    C::PIN_PEDAL_1, C::PIN_PEDAL_2, C::PIN_PEDAL_3, C::PIN_PEDAL_4, C::PIN_PEDAL_5
};

Pedals::Pedals()
    : _pixels(C::PEDAL_COUNT, C::PIN_PEDAL_NEOPIXEL, NEO_GRB + NEO_KHZ800) {}

void Pedals::begin() {
    _pixels.begin();
    _pixels.setBrightness((uint8_t)(C::PEDAL_BRIGHTNESS * 255));
    _pixels.clear();
    for (uint8_t i = 0; i < C::PEDAL_COUNT; i++) {
        pinMode(_pedal_pins[i], INPUT_PULLUP);
    }
}

void Pedals::_push_event(uint8_t key, bool pressed) {
    constexpr size_t N = sizeof(_queue) / sizeof(_queue[0]);
    if (_q_count >= N) {
        // Full: drop the OLDEST, never the incoming event. Dropping the newest could eat a
        // RELEASE, stranding note_buttons[].state as held — stuck note plus the encoder
        // routed to the pad-held handler until reboot. (Bounded vs Python's unbounded list.)
        _q_head = (_q_head + 1) % N;
        _q_count--;
    }
    _queue[(_q_head + _q_count) % N] = {key, pressed};
    _q_count++;
}

bool Pedals::get_event(PedalEvent &out) {
    if (_q_count == 0) {
        return false;
    }
    out = _queue[_q_head];
    _q_head = (_q_head + 1) % (sizeof(_queue) / sizeof(_queue[0]));
    _q_count--;
    return true;
}

void Pedals::update() {
    for (uint8_t i = 0; i < C::PEDAL_COUNT; i++) {
        pedal_buttons[i].set_current_value(digitalRead(_pedal_pins[i]) == HIGH);

        bool prev_state = pedal_buttons[i].state;
        pedal_buttons[i].update_all();

        if (!prev_state && pedal_buttons[i].state) { // new press
            _push_event((uint8_t)pedal_buttons[i].pad_idx, true);
        } else if (prev_state && !pedal_buttons[i].state) { // new release
            _push_event((uint8_t)pedal_buttons[i].pad_idx, false);
        }
    }
}

void Pedals::show_pedal_pixels() {
    if (pixels_need_update) {
        pixels_need_update = false; // clear first: a concurrent core-0 write re-dirties
        _pixels.show();
    }
}

void Pedals::reset_pedals() {
    for (uint8_t i = 0; i < C::PEDAL_COUNT; i++) {
        pedal_buttons[i].reset_actions();
    }
}

void Pedals::set_pedal_bank(int bank_idx) {
    if (bank_idx < 0 || bank_idx > 2) {
        return;
    }
    current_bank = bank_idx;
    bank_offset = bank_idx * 5;
    for (uint8_t i = 0; i < C::PEDAL_COUNT; i++) {
        // A pedal held across the bank change would otherwise deliver its release under the
        // NEW pad index: the old pad never sees the release, so it stays "held" forever —
        // stuck note, and every later encoder turn is routed to the pad-held handler
        // instead of menu nav. Close the press out on the index it opened on first.
        if (pedal_buttons[i].state) {
            _push_event((uint8_t)pedal_buttons[i].pad_idx, false);
        }
        pedal_buttons[i].pad_idx = bank_offset + i;
    }
    _update_pixels_for_current_bank();
    cdc_log("Switched to pedal bank %d (pads %d-%d)\n", bank_idx, bank_offset, bank_offset + 4);
}

int Pedals::get_pedal_pixel_index(uint8_t loopster_pad_idx) const {
    if (loopster_pad_idx >= bank_offset && loopster_pad_idx < bank_offset + 5) {
        return loopster_pad_idx - bank_offset;
    }
    return -1; // this pad doesn't correspond to any pedal
}

C::Rgb Pedals::_color_for(PadLoopState st, bool blink_phase) {
    switch (st) {
    case PadLoopState::Playing:
        return C::PIXEL_LOOP_PLAYING_COLOR;
    case PadLoopState::HasLoop:
        return C::LOOP_COLOR;
    case PadLoopState::Queued:
        return blink_phase ? C::PIXEL_LOOP_PLAYING_COLOR : C::BLACK;
    case PadLoopState::Recording:
        return C::RED;
    case PadLoopState::Armed:
        return blink_phase ? C::RED : C::BLACK;
    default:
        return C::BLACK;
    }
}

void Pedals::refresh_from_loop_state() {
    if (!_loop_state) {
        return; // loopmanager not initialized yet
    }
    // pixels.blink_phase only advances while some PAD pixel blinks; every Queued/Armed
    // pad blinks on the pad strip too, so the phase is always live when we need it.
    bool phase = pixels.blink_phase;
    bool phase_changed = (phase != _last_phase) || !_rendered_once;
    bool dirty = false;
    for (uint8_t i = 0; i < C::PEDAL_COUNT; i++) {
        PadLoopState st = _loop_state((uint8_t)(bank_offset + i));
        bool blinks = (st == PadLoopState::Queued || st == PadLoopState::Armed);
        if (st == _last_state[i] && _rendered_once && !(blinks && phase_changed)) {
            continue;
        }
        C::Rgb c = _color_for(st, phase);
        _pixels.setPixelColor(i, c.r, c.g, c.b);
        _last_state[i] = st;
        dirty = true;
    }
    _last_phase = phase;
    _rendered_once = true;
    if (dirty) {
        pixels_need_update = true;
    }
}

void Pedals::_update_pixels_for_current_bank() {
    _rendered_once = false; // bank changed: every LED must be re-derived
    refresh_from_loop_state();
}

void update_pedal_pixels() {
    if (pixels.core1_owns_pixels) {
        return; // core 1 shows pedal pixels from loop1; a core-0 show would race it
    }
    if (pedals.pixels_need_update) {
        pedals.show_pedal_pixels();
    }
}
