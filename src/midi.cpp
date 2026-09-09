#include "midi.h"
#include "test_hooks.h"
#include "settings.h"
#include "clock.h"
#include "ticks.h"
#include "display.h"
#include "pixels.h"
#include "utils.h"

Midi midi;
Adafruit_USBD_MIDI usb_midi_dev;

static const int MAX_MESSAGES_PER_PORT = 32; // cap to prevent main loop starvation

// Expected data-byte count for a status byte (0 = system/unsupported here)
static uint8_t data_len_for_status(uint8_t status) {
    if (status == 0xF2) { // Song Position Pointer (0xF0-mask switch below can't see it)
        return 2;
    }
    switch (status & 0xF0) {
    case 0x80: // NoteOff
    case 0x90: // NoteOn
    case 0xA0: // PolyPressure
    case 0xB0: // CC
    case 0xE0: // PitchBend
        return 2;
    case 0xC0: // ProgramChange
    case 0xD0: // ChannelPressure
        return 1;
    default:
        return 0;
    }
}

void Midi::setup_usb() {
    usb_midi_dev.begin();
    Serial1.setTX(C::PIN_UART_MIDI_TX);
    Serial1.setRX(C::PIN_UART_MIDI_RX);
    Serial1.setFIFOSize(256); // reduce overflow risk during dense MIDI bursts
    Serial1.begin(31250);

    clear_cc_cache();
    // midi_velocities are seeded in setup(), which runs after the startup preset
    // loads — seeding here would bake in the compile-time default_velocity.
}

int Midi::get_midi_bank_idx() const { return settings.midibank_idx; }
int Midi::get_scale_bank_idx() const { return settings.scale_idx; }
int Midi::get_scale_notes_idx() const { return settings.scalenotes_idx; }

String Midi::get_pad_offset_suffix() const {
    if (pad_group_offset == 0) {
        return "";
    }
    int steps = pad_group_offset / C::PAD_OFFSET_AMOUNT;
    String out = " ";
    for (int i = 0; i < steps; i++) {
        out += "+";
    }
    return out;
}

void Midi::set_all_midi_velocities(uint8_t value, bool check_default) {
    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        if (check_default) {
            if (midi_velocities[i] == settings.default_velocity) {
                midi_velocities[i] = value;
            }
        } else {
            midi_velocities[i] = value;
        }
    }
}

void Midi::set_midi_velocity_by_idx(uint8_t idx, uint8_t vel) {
    if (idx >= C::NUM_PADS || vel > 127) {
        return;
    }
    settings.mark_dirty();
    midi_velocities[idx] = vel;
    pixels.set_note_on(idx, vel);
}

uint8_t Midi::get_midi_note_by_idx(uint8_t idx) const {
    if (idx >= C::NUM_PADS || full_scale_notes.empty()) {
        return 0;
    }
    int base = bank_window_start + pad_group_offset + idx;
    int abs_idx = min(max(base, 0), (int)full_scale_notes.size() - 1);
    return full_scale_notes[abs_idx];
}

// ---------------- low-level transports ----------------

void Midi::_usb_write(const RawMsg &m) {
    uint8_t cin = (m.status >= 0xF8) ? 0x0F : (uint8_t)(m.status >> 4);
    uint8_t packet[4] = {cin, m.status, m.len > 1 ? m.d1 : 0, m.len > 2 ? m.d2 : 0};
    usb_midi_dev.writePacket(packet);
}

void Midi::_uart_write(const RawMsg &m) {
    Serial1.write(m.status);
    if (m.len > 1) Serial1.write(m.d1);
    if (m.len > 2) Serial1.write(m.d2);
}

void Midi::_send_msg(uint8_t status_hi, int channel, uint8_t d1, uint8_t d2, uint8_t len) {
    int ch = (channel >= 0 && channel <= 15) ? channel : settings.midi_channel_out;
    RawMsg m;
    m.status = status_hi | (uint8_t)ch;
    m.d1 = d1;
    m.d2 = d2;
    m.len = len;
    if (should_send("USB")) {
        _usb_write(m);
    }
    if (should_send("AUX")) {
        _uart_write(m);
    }
}

void Midi::_send_realtime(uint8_t status) {
    RawMsg m;
    m.status = status;
    m.len = 1;
    if (should_send("USB")) {
        _usb_write(m);
    }
    if (should_send("AUX")) {
        _uart_write(m);
    }
}

bool Midi::_usb_receive(RawMsg &out) {
    uint8_t packet[4];
    while (usb_midi_dev.readPacket(packet)) {
        uint8_t cin = packet[0] & 0x0F;
        switch (cin) {
        case 0x8: case 0x9: case 0xA: case 0xB: case 0xE:
            out.status = packet[1];
            out.d1 = packet[2];
            out.d2 = packet[3];
            out.len = 3;
            return true;
        case 0xC: case 0xD:
            out.status = packet[1];
            out.d1 = packet[2];
            out.len = 2;
            return true;
        case 0xF: // single-byte (realtime)
            out.status = packet[1];
            out.len = 1;
            return true;
        case 0x3: // 3-byte system common — Song Position Pointer (0xF2)
            out.status = packet[1];
            out.d1 = packet[2];
            out.d2 = packet[3];
            out.len = 3;
            return true;
        default:
            continue; // sysex etc. — skipped (Python lib produced unknowns; unused)
        }
    }
    return false;
}

bool Midi::_uart_parse_byte(uint8_t b, RawMsg &out) {
    if (b >= 0xF8) { // realtime — can interleave anywhere
        out.status = b;
        out.len = 1;
        return true;
    }
    if (b & 0x80) { // new status byte
        if (b >= 0xF0) { // system common
            // SPP (0xF2) is the one we consume (Live resumes with SPP + Continue);
            // the rest reset running status and are skipped
            _rx_status = (b == 0xF2) ? b : 0;
            _rx_count = 0;
            return false;
        }
        _rx_status = b;
        _rx_count = 0;
        return false;
    }
    // data byte
    if (!_rx_status) {
        return false; // stray data byte
    }
    _rx_data[_rx_count++] = b;
    uint8_t need = data_len_for_status(_rx_status);
    if (_rx_count >= need) {
        out.status = _rx_status;
        out.d1 = _rx_data[0];
        out.d2 = need > 1 ? _rx_data[1] : 0;
        out.len = 1 + need;
        _rx_count = 0; // keep running status (channel voice only)
        if (_rx_status >= 0xF0) {
            _rx_status = 0; // no running status for system common (SPP)
        }
        return true;
    }
    return false;
}

#ifdef LOOPSTER_TEST_HOOKS
// Injected DIN bytes, drained by _uart_receive ahead of Serial1 so they go through
// the identical parser state machine (source "AUX"). Plain ring buffer; only ever
// touched from core 0 (CDC command handler + main loop), so no locking needed.
static uint8_t s_test_din_buf[256];
static uint16_t s_test_din_head = 0;
static uint16_t s_test_din_count = 0;

size_t Midi::test_inject_din(const uint8_t *bytes, size_t n) {
    size_t queued = 0;
    while (queued < n && s_test_din_count < sizeof(s_test_din_buf)) {
        s_test_din_buf[(s_test_din_head + s_test_din_count) % sizeof(s_test_din_buf)] =
            bytes[queued++];
        s_test_din_count++;
    }
    return queued;
}
#endif

bool Midi::_uart_receive(RawMsg &out) {
#ifdef LOOPSTER_TEST_HOOKS
    while (s_test_din_count > 0) {
        uint8_t b = s_test_din_buf[s_test_din_head];
        s_test_din_head = (s_test_din_head + 1) % sizeof(s_test_din_buf);
        s_test_din_count--;
        if (_uart_parse_byte(b, out)) {
            return true;
        }
    }
#endif
    while (Serial1.available()) {
        if (_uart_parse_byte((uint8_t)Serial1.read(), out)) {
            return true;
        }
    }
    return false;
}

// ---------------- sends ----------------

void Midi::send_note_on(uint8_t note, uint8_t velocity, int channel) {
    _send_msg(0x90, channel, note, velocity, 3);
}

void Midi::send_note_off(uint8_t note, int channel) {
    _send_msg(0x80, channel, note, 1, 3);
}

void Midi::track_pad_note_on(uint8_t pad_idx, uint8_t note, int channel) {
    if (pad_idx >= C::NUM_PADS) {
        return;
    }
    _active_pad_notes[pad_idx] = {note, (int8_t)channel, true};
}

void Midi::send_pad_note_off(uint8_t pad_idx, uint8_t fallback_note, int fallback_channel) {
    // Replay only when the tracked NOTE matches: the table corrects the CHANNEL a release
    // would otherwise recompute from the current mapping. A mismatched note means the entry
    // belongs to a different event than this off — arp gates outlast the step interval, so
    // a later step's on overwrites the entry while the earlier note still rings; replaying
    // it here would off the wrong pitch. Note changes from bank/offset moves are handled by
    // flush_active_pad_notes() at the moment of the change, not here.
    if (pad_idx < C::NUM_PADS && _active_pad_notes[pad_idx].active &&
        _active_pad_notes[pad_idx].note == fallback_note) {
        send_note_off(fallback_note, _active_pad_notes[pad_idx].channel);
        _active_pad_notes[pad_idx].active = false;
        return;
    }
    send_note_off(fallback_note, fallback_channel);
}

void Midi::flush_active_pad_notes() {
    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        if (_active_pad_notes[i].active) {
            send_note_off(_active_pad_notes[i].note, _active_pad_notes[i].channel);
            _active_pad_notes[i].active = false;
        }
    }
}

void Midi::clear_all_notes() {
    send_cc(123, 0);
}

void Midi::send_cc(uint8_t cc, uint8_t value, int channel) {
    cc = min((uint8_t)127, cc);
    value = min((uint8_t)127, value);

    // Duplicate suppression — skip if receiver already has this value.
    // CC 120-127 are channel-mode COMMANDS (All Notes Off, Reset Controllers, ...),
    // not value controllers — they must always be sent, never deduped (item R1).
    if (cc < 120) {
        int cache_ch = (channel >= -1 && channel <= 15) ? channel : -1;
        if (_cc_send_cache[cc][cache_ch + 1] == (int8_t)value) {
            return;
        }
        _cc_send_cache[cc][cache_ch + 1] = (int8_t)value;
    }

    _send_msg(0xB0, channel, cc, value, 3);
}

void Midi::clear_cc_cache() {
    memset(_cc_send_cache, 0xFF, sizeof(_cc_send_cache)); // -1 everywhere
}

void Midi::all_notes_off_all_channels() {
    // Loops and pads can be mapped to any channel, so a single CC 123 on the global channel
    // leaves notes ringing elsewhere. Clear the dup-suppression cache first so none of the
    // sends get skipped, then blast every channel (item 8). Order per channel matters:
    // CC64=0 first — damper-held notes ignore CC123 until the pedal lifts — then CC123
    // (All Notes Off), then CC120 (All Sound Off) as the conventional panic backstop for
    // synths that ignore 123. 120 stays out of clear_all_notes(): some synths hard-reset
    // envelopes on it, which is wanted in a panic but not on a routine bank change.
    clear_cc_cache();
    for (int ch = 0; ch <= 15; ch++) {
        send_cc(64, 0, ch);
        send_cc(123, 0, ch);
        send_cc(120, 0, ch);
    }
}

void Midi::send_aftertouch(uint8_t pressure, int channel) {
    _send_msg(0xD0, channel, min((uint8_t)127, pressure), 0, 2);
}

void Midi::send_start_stop(bool start) {
    _send_realtime(start ? 0xFA : 0xFC);
}

bool Midi::should_send(const char *midi_type) const {
    if (!strcasecmp(midi_type, "USB")) {
        return (settings.midi_type.equalsIgnoreCase("USB") || settings.midi_type.equalsIgnoreCase("ALL")) &&
               (settings.midi_usb_io == "both" || settings.midi_usb_io == "out");
    }
    if (!strcasecmp(midi_type, "AUX")) {
        return (settings.midi_type.equalsIgnoreCase("AUX") || settings.midi_type.equalsIgnoreCase("ALL")) &&
               (settings.midi_aux_io == "both" || settings.midi_aux_io == "out");
    }
    return false;
}

bool Midi::should_receive(const char *midi_type) const {
    if (!strcasecmp(midi_type, "USB")) {
        return (settings.midi_type.equalsIgnoreCase("USB") || settings.midi_type.equalsIgnoreCase("ALL")) &&
               (settings.midi_usb_io == "both" || settings.midi_usb_io == "in");
    }
    if (!strcasecmp(midi_type, "AUX")) {
        return (settings.midi_type.equalsIgnoreCase("AUX") || settings.midi_type.equalsIgnoreCase("ALL")) &&
               (settings.midi_aux_io == "both" || settings.midi_aux_io == "in");
    }
    return false;
}

// ---------------- receive path ----------------

bool Midi::_should_accept_channel(const RawMsg &m) const {
    if (m.status >= 0xF0) {
        return true; // non-channel messages (Start, Stop, Clock)
    }
    if (settings.midi_channel_in == -1) {
        return true; // ALL channels
    }
    return (m.status & 0x0F) == settings.midi_channel_in;
}

void Midi::_process_midi_in(const RawMsg &m, const char *midi_source, MidiInResult &result) {
    uint8_t type = m.status & 0xF0;
    int8_t ch = (int8_t)(m.status & 0x0F);

    // Transport OFF (free-run sync): the clock source sends only 0xF8 (e.g. Walrus Canvas
    // Clock), so Start/Stop/Continue/SPP are ignored outright — the first accepted tick
    // below starts the grid instead. Only applies under midi_sync; with sync off the
    // messages keep their old (inert) handling.
    bool transport_off = settings.midi_sync && settings.midi_transport == "off";

    if (m.status == 0xFA) { // Start
        if (transport_off) {
            return;
        }
        clock_.start_clock();
        result.transport = Transport::Start;
        return;
    }
    if (m.status == 0xFC) { // Stop
        if (transport_off) {
            return;
        }
        clock_.stop_clock();
        result.transport = Transport::Stop;
        return;
    }
    if (m.status == 0xFB) { // Continue — resume, treat like Start for recording
        if (transport_off) {
            return;
        }
        clock_.continue_clock();
        result.transport = Transport::Start;
        return;
    }
    if (m.status == 0xF2) { // Song Position Pointer — Live sends SPP right before Continue;
        // pins the tick counter (and thus beat-grid phase) to the master's song position
        if (transport_off) {
            return;
        }
        clock_.set_song_position(((uint16_t)m.d2 << 7) | m.d1);
        return;
    }
    if (m.status == 0xF8) { // TimingClock (Python: fell through to this check)
        // Seen-stamp regardless of acceptance: should_accept_clock's tiebreaker needs to
        // know whether the PREFERRED port is alive even while its ticks aren't consumed.
        if (!strcmp(midi_source, "AUX")) {
            _last_clock_seen_aux = ticks::ticks_ms();
        } else {
            _last_clock_seen_usb = ticks::ticks_ms();
        }
        if (should_accept_clock(midi_source)) {
            if (transport_off && !clock_.is_playing) {
                // Free-run: this very tick becomes the downbeat — start_clock() arms the
                // swallow, so update_clock() consumes it at counter 0 and seeds the BPM
                // window, exactly as if a Start had preceded it.
                clock_.start_clock();
            }
            if (clock_.is_playing) {
                clock_.update_clock();
            }
        }
        return;
    }

    switch (type) {
    case 0x90:
        result.notes_on.push_back({m.d1, m.d2, 0, ch});
        break;
    case 0x80:
        result.notes_off.push_back({m.d1, m.d2, 0, ch});
        break;
    case 0xB0:
        result.cc_events.push_back({m.d1, m.d2, ch});
        break;
    case 0xD0:
        result.at_events.push_back({m.d1, ch});
        break;
    default:
        break; // PitchBend/PolyPressure: passthru-only, same as Python
    }
}

void Midi::process_messages_in(MidiInResult &result) {
    R18_MARK(8); // USB/UART MIDI RX drain
    // clear() keeps each vector's capacity, so steady-state passes with MIDI
    // arriving stop churning small heap blocks (item R14; same pattern as
    // loop_events/cc_coalesce).
    result.notes_on.clear();
    result.notes_off.clear();
    result.cc_events.clear();
    result.at_events.clear();
    result.transport = Transport::None;
    RawMsg m;

    // USB messages — drain buffer with cap
    if (should_receive("USB")) {
        bool usb_passthru = (settings.passthru_mode == "usb" || settings.passthru_mode == "all"); // USB IN -> AUX OUT

        for (int i = 0; i < MAX_MESSAGES_PER_PORT; i++) {
            if (!_usb_receive(m)) {
                break;
            }

            // USB PASSTHROUGH — forwards to AUX output only (avoids USB feedback loops)
            if (usb_passthru) {
                if (m.status < 0xF0) {
                    _uart_write(m);
                } else if (m.status == 0xFA || m.status == 0xFC) {
                    RawMsg rt = m;
                    _uart_write(rt);
                }
            }

            if (!_should_accept_channel(m)) {
                continue;
            }
            _process_midi_in(m, "USB", result);
        }
    }

    // AUX messages — drain buffer with cap
    if (should_receive("AUX")) {
        bool aux_passthru = (settings.passthru_mode == "aux" || settings.passthru_mode == "all"); // AUX IN -> USB OUT

        for (int i = 0; i < MAX_MESSAGES_PER_PORT; i++) {
            if (!_uart_receive(m)) {
                break;
            }

            // PASSTHROUGH FIRST — forwards ALL channels (like hardware MIDI Thru),
            // before channel filtering so multi-channel data passes through
            if (aux_passthru) {
                if (m.status < 0xF0) {
                    // Skip consecutive duplicate messages (same bytes back-to-back)
                    bool dup = _has_last_passthru &&
                               _last_passthru_msg.status == m.status &&
                               _last_passthru_msg.d1 == m.d1 &&
                               _last_passthru_msg.d2 == m.d2 &&
                               _last_passthru_msg.len == m.len;
                    if (dup) {
                        continue;
                    }
                    _last_passthru_msg = m;
                    _has_last_passthru = true;
                    if (should_send("USB")) {
                        _usb_write(m);
                    }
                    if (should_send("AUX")) {
                        _uart_write(m);
                    }
                } else if (m.status == 0xFA) {
                    send_start_stop(true);
                } else if (m.status == 0xFC) {
                    send_start_stop(false);
                }
            }

            // Channel filter — only for recording/internal processing
            if (!_should_accept_channel(m)) {
                continue;
            }
            _process_midi_in(m, "AUX", result);
        }
    }
}

// How long the preferred port "owns" the clock after its last tick. Longer than the
// slowest real tick gap (30 BPM = 83 ms) by a wide margin, short enough that a dead
// preferred source hands over within a beat or two.
static const uint32_t CLOCK_SOURCE_HOLD_MS = 1000;

bool Midi::should_accept_clock(const char *midi_source) const {
    if (!settings.midi_sync) {
        return false;
    }
    if (!should_receive(midi_source)) {
        return false;
    }
    // Preferred source always wins while it can receive.
    if (settings.clock_source == midi_source) {
        return true;
    }
    // Other port: clock_source is a TIEBREAKER for dual-clock rigs, not a filter — the
    // old hard filter silently muted the only clock present (e.g. MIDI Type = ALL +
    // Clock Source = USB dropped DIN clock while DIN Start/Stop still worked; Aug 2026
    // customer bug). Yield only while the preferred port is receivable AND actually
    // supplying ticks.
    bool pref_is_aux = settings.clock_source == "AUX";
    if (!should_receive(pref_is_aux ? "AUX" : "USB")) {
        return true;
    }
    uint32_t seen = pref_is_aux ? _last_clock_seen_aux : _last_clock_seen_usb;
    if (seen != 0 && ticks::ticks_diff(ticks::ticks_ms(), seen) < (int32_t)CLOCK_SOURCE_HOLD_MS) {
        return false;
    }
    return true;
}

bool Midi::should_passthru_midi() const {
    return settings.passthru_mode != "off";
}

void Midi::set_midi_channel_for_pad(uint8_t pad_idx, int8_t channel) {
    if (pad_idx >= C::NUM_PADS) {
        return;
    }
    if (channel < C::PAD_CH_GLOBAL || channel > 15) {
        return;
    }
    settings.midi_channel_pad_mapping[pad_idx] = channel;
    settings.mark_dirty();
}

int Midi::get_midi_channel_for_pad(int pad_idx, int recorded_channel) const {
    if (pad_idx < 0 || pad_idx >= C::NUM_PADS) {
        return settings.midi_channel_out;
    }
    int8_t pad_setting = settings.midi_channel_pad_mapping[pad_idx];

    if (pad_setting == C::PAD_CH_AS_RECORDED) {
        if (recorded_channel >= 0 && recorded_channel <= 15) {
            return recorded_channel;
        }
        return settings.midi_channel_out; // fallback for live presses
    }
    if (pad_setting == C::PAD_CH_GLOBAL) {
        return settings.midi_channel_out;
    }
    if (pad_setting >= 0 && pad_setting <= 15) {
        return pad_setting;
    }
    return settings.midi_channel_out;
}

// ---------------- scale/bank management ----------------

void Midi::_rebuild_full_scale_notes() {
    full_scale_notes.clear();
    for (uint8_t b = 0; b < current_midibank_set.numBanks; b++) {
        for (uint8_t p = 0; p < C::NUM_PADS; p++) {
            full_scale_notes.push_back(current_midibank_set.notes[b][p]);
        }
    }
}

// Presets clamp bank indices against MAX_BANKS (11), but chromatic generates 9 banks and
// interval scales ~6 — ScaleBanks.notes rows past numBanks are uninitialized memory. Clamp
// the active bank field to what get_scale_notes() actually generated and write it back so
// the sane value persists (item R8).
int Midi::_clamp_bank_to_generated() {
    int max_bank = (current_midibank_set.numBanks > 0) ? current_midibank_set.numBanks - 1 : 0;
    int &bank_field = (settings.scale_idx == 0) ? settings.midibank_idx : settings.scalenotes_idx;
    if (bank_field > max_bank) {
        bank_field = max_bank;
    }
    if (bank_field < 0) {
        bank_field = 0;
    }
    return bank_field;
}

void Midi::next_or_prev_scale(bool up_or_down, bool display_text) {
    settings.mark_dirty();
    settings.scale_idx = next_or_previous_index(settings.scale_idx, midiscales::NUM_SCALES, up_or_down);
    midiscales::get_scale_notes(settings.scale_idx, settings.rootnote_idx, current_midibank_set);

    int bank = _clamp_bank_to_generated(); // rows past numBanks are uninitialized (item R8)
    for (uint8_t p = 0; p < C::NUM_PADS; p++) {
        settings.midi_notes_default[p] = current_midibank_set.notes[bank][p];
    }
    _rebuild_full_scale_notes();
    bank_window_start = bank * C::NUM_PADS;

    if (display_text) {
        String lines[3];
        midiscales::get_scale_display_text(lines);
        display.show_text_middle(lines, 3);
    }
}

void Midi::next_or_prev_root(bool up_or_down, bool display_text) {
    if (settings.scale_idx == 0) {
        return;
    }
    settings.mark_dirty();
    settings.rootnote_idx = next_or_previous_index(settings.rootnote_idx, midiscales::NUM_ROOTS, up_or_down);
    midiscales::get_scale_notes(settings.scale_idx, settings.rootnote_idx, current_midibank_set);
    int bank = _clamp_bank_to_generated(); // item R8
    for (uint8_t p = 0; p < C::NUM_PADS; p++) {
        settings.midi_notes_default[p] = current_midibank_set.notes[bank][p];
    }
    _rebuild_full_scale_notes();
    bank_window_start = bank * C::NUM_PADS;

    if (display_text) {
        String lines[3];
        midiscales::get_scale_display_text(lines);
        display.show_text_middle(lines, 3);
    }
}

void Midi::scale_fn_press_function(const char *action_type) {
    if (strcmp(action_type, "release") != 0) {
        return;
    }
    next_or_prev_root(true, true);
}

void Midi::scale_fn_held_function(bool trigger_on_release) {
    if (!trigger_on_release) {
        display.display_dot(0, true);
    } else {
        display.display_dot(0, false);
        display.display_dot(3, true);
    }
}

void Midi::scale_setup_function() {
    display.display_dot(3, true);
}

void Midi::change_bank(bool up_or_down) {
    // Send note-offs for held pads before bank changes (prevents stuck notes:
    // pad press -> bank change -> pad release). Replays the exact notes/channels that
    // went out at press: recomputing them here sent the off on the global channel while
    // the on had gone to the pad's mapped channel, so the note rang on (#265).
    flush_active_pad_notes();

    settings.mark_dirty(); // midibank_idx / scalenotes_idx persist in the preset
    if (settings.scale_idx == 0) {
        settings.midibank_idx = next_or_previous_index(settings.midibank_idx, current_midibank_set.numBanks, up_or_down, false);
        bank_window_start = settings.midibank_idx * C::NUM_PADS;
    } else {
        settings.scalenotes_idx = next_or_previous_index(settings.scalenotes_idx, current_midibank_set.numBanks, up_or_down, false);
        bank_window_start = settings.scalenotes_idx * C::NUM_PADS;
    }
    clear_all_notes();
}

void Midi::offset_pads(bool up_or_down) {
    int amount = C::PAD_OFFSET_AMOUNT;
    int delta = up_or_down ? amount : -amount;
    int new_offset = pad_group_offset + delta;

    int current_bank = (settings.scale_idx == 0) ? settings.midibank_idx : settings.scalenotes_idx;
    int max_bank = current_midibank_set.numBanks - 1;

    if (new_offset < 0) {
        if (current_bank == 0) {
            return; // at bank 0, can't go lower
        }
        pad_group_offset = C::NUM_PADS + new_offset;
        change_bank(false);
    } else if (new_offset >= C::NUM_PADS) {
        if (current_bank >= max_bank) {
            return; // at max bank, can't go higher
        }
        pad_group_offset = new_offset - C::NUM_PADS;
        change_bank(true);
    } else {
        // Within-bank nudge: change_bank isn't involved, so flush here or a held pad's
        // release recomputes its note against the new offset and strands the old pitch.
        flush_active_pad_notes();
        pad_group_offset = new_offset;
    }
}

void Midi::setup() {
    // Seed pad velocities from the (now loaded) preset's default_velocity.
    // Python did this in Midi.__init__, which ran after settings module init.
    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        midi_velocities[i] = settings.default_velocity;
    }

    midiscales::get_scale_notes(settings.scale_idx, settings.rootnote_idx, current_midibank_set);
    int bank = _clamp_bank_to_generated(); // item R8
    for (uint8_t p = 0; p < C::NUM_PADS; p++) {
        settings.midi_notes_default[p] = current_midibank_set.notes[bank][p];
    }
    _rebuild_full_scale_notes();
    bank_window_start = bank * C::NUM_PADS;
    pad_group_offset = 0;
}
