// Port of src/midi.py — MIDI I/O and scale/bank management.
// The adafruit_midi object layer is replaced with direct byte handling:
//   USB  -> Adafruit_USBD_MIDI 4-byte packets (TinyUSB)
//   AUX  -> Serial1 (UART0, GP16/17) @ 31250 with a running-status parser
// Python tuples -> the event structs below; channel_or_pad_idx=None -> channel = -1.
// Python's TimingClock fell through to the should_accept_clock branch; here 0xF8 is
// routed there explicitly. The (cc, channel) send-dedup dict -> flat int8 array.
#pragma once
#include <Arduino.h>
#include <Adafruit_TinyUSB.h>
#include <vector>
#include "constants.h"
#include "midiscales.h"

// (note, velocity, padidx, channel) — the 4/5-tuple shapes from Python unified
struct NoteMsg {
    uint8_t note;
    uint8_t velocity;
    uint8_t padidx;
    int8_t channel; // -1 = none/global
};

struct CcMsg {
    uint8_t cc;
    uint8_t value;
    int8_t channel;
};

struct AtMsg {
    uint8_t pressure;
    int8_t channel;
};

enum class Transport : uint8_t { None, Start, Stop };

// Result of process_messages_in() (Python's 5-element return tuple)
struct MidiInResult {
    std::vector<NoteMsg> notes_on;
    std::vector<NoteMsg> notes_off;
    std::vector<CcMsg> cc_events;
    std::vector<AtMsg> at_events;
    Transport transport = Transport::None;
};

class Midi {
public:
    midiscales::ScaleBanks current_midibank_set;
    uint8_t midi_velocities[C::NUM_PADS] = {}; // seeded from preset in setup()
    uint8_t current_assignment_velocity = 120;
    int current_assignment_channel = -999; // -999 = Python None (settingsmenu pad-channel assign)

    std::vector<uint8_t> full_scale_notes;
    int bank_window_start = 0;
    int pad_group_offset = 0;

    void setup_usb(); // TinyUSB MIDI + Serial1 init; call before USB enumeration
    void setup();     // scale/bank note mapping init (Python Midi.setup())

    void get_current_scale_display_text(String out[3]) { midiscales::get_scale_display_text(out); }
    int get_midi_bank_idx() const;
    int get_scale_bank_idx() const;
    int get_scale_notes_idx() const;
    String get_pad_offset_suffix() const; // " +", " ++", ... or ""

    void update_global_velocity(uint8_t v) { current_assignment_velocity = v; }
    uint8_t get_current_assignment_velocity() const { return current_assignment_velocity; }
    uint8_t get_velocity_by_idx(uint8_t idx) const { return midi_velocities[idx]; }
    void set_all_midi_velocities(uint8_t value, bool check_default = true);
    void set_midi_velocity_by_idx(uint8_t idx, uint8_t vel);
    uint8_t get_midi_note_by_idx(uint8_t idx) const;
    uint8_t get_velocity_singlenote_by_idx(uint8_t idx) const { return C::DEFAULT_SINGLENOTE_MODE_VELOCITIES[idx]; }

    // --- Sending (channel -1 = Python None -> settings.midi_channel_out) ---
    void send_note_on(uint8_t note, uint8_t velocity, int channel = -1);
    void send_note_off(uint8_t note, int channel = -1);
    void clear_all_notes(); // CC 123 (not CC 120; some synths reset envelopes on 120)
    void all_notes_off_all_channels(); // CC 123 on every channel — for seizing control (web lock)
    void send_cc(uint8_t cc, uint8_t value, int channel = -1);
    void clear_cc_cache();
    void send_aftertouch(uint8_t pressure, int channel = -1);
    void send_start_stop(bool start);

    bool should_send(const char *midi_type) const;
    bool should_receive(const char *midi_type) const;

    // Drain both ports; returns collected events (Python process_messages_in)
    void process_messages_in(MidiInResult &out); // fills a caller-owned result; vectors keep capacity across passes (R14)

    bool should_accept_clock(const char *midi_source) const;
    bool should_passthru_midi() const;

    void set_midi_channel_for_pad(uint8_t pad_idx, int8_t channel);
    // pad_idx 255/-1-ish = invalid -> global. recorded_channel -1 = none.
    int get_midi_channel_for_pad(int pad_idx, int recorded_channel = -1) const;

    void next_or_prev_scale(bool up_or_down = true, bool display_text = true);
    void next_or_prev_root(bool up_or_down = true, bool display_text = true);
    void scale_fn_press_function(const char *action_type);
    void scale_fn_held_function(bool trigger_on_release = false);
    void scale_setup_function();
    void change_bank(bool up_or_down = true);
    void offset_pads(bool up_or_down = true);

    // Registered by inputs: returns true if pad currently held (for change_bank's
    // stuck-note prevention; Python did a late `from inputs import inputs`)
    using PadHeldFn = bool (*)(uint8_t pad_idx);
    void set_pad_held_provider(PadHeldFn fn) { _pad_held = fn; }

private:
    struct RawMsg {
        uint8_t status = 0; // full status byte incl. channel; 0 = invalid
        uint8_t d1 = 0, d2 = 0;
        uint8_t len = 0; // total message length incl. status (1-3)
    };

    // Low-level transports
    bool _usb_receive(RawMsg &out);
    bool _uart_receive(RawMsg &out);
    void _usb_write(const RawMsg &m);
    void _uart_write(const RawMsg &m);
    void _send_msg(uint8_t status_hi, int channel, uint8_t d1, uint8_t d2, uint8_t len);
    void _send_realtime(uint8_t status);

    // Classify a raw message into the result lists; returns "start"/"stop" transport
    void _process_midi_in(const RawMsg &m, const char *midi_source, MidiInResult &result);
    bool _should_accept_channel(const RawMsg &m) const;

    void _rebuild_full_scale_notes();
    int _clamp_bank_to_generated();

    PadHeldFn _pad_held = nullptr;

    // UART parser state (running status)
    uint8_t _rx_status = 0;
    uint8_t _rx_data[2];
    uint8_t _rx_count = 0;

    RawMsg _last_passthru_msg;
    bool _has_last_passthru = false;

    int8_t _cc_send_cache[128][17]; // [cc][channel+1], -1 = unsent
};

extern Midi midi;
extern Adafruit_USBD_MIDI usb_midi_dev; // for main.cpp USB bring-up ordering
