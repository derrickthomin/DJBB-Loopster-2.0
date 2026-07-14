// Port of src/inputs.py — pad matrix, encoder, FN button, note dispatch.
// keypad.KeyMatrix -> hand-rolled scanner (drive columns low, rows input-pullup,
// 20 ms per-key debounce, event queue; key_number = row * 4 + col like CircuitPython).
//   NOTE pre-mortem #9: verify diode polarity on hardware (test firmware phase 4).
// rotaryio.IncrementalEncoder -> IRQ quadrature decoder, divisor 4 (detents).
// Python None sentinels -> -1 (single_note_mode_midi_val, recording_start_pad).
#pragma once
#include <Arduino.h>
#include <vector>
#include "constants.h"
#include "buttons.h"
#include "midi.h"

class Inputs {
public:
    // State
    Button note_buttons[C::NUM_PADS] = {
        Button(0), Button(1), Button(2), Button(3), Button(4), Button(5), Button(6), Button(7),
        Button(8), Button(9), Button(10), Button(11), Button(12), Button(13), Button(14), Button(15)};
    Button fn_button = Button(-1, C::FN_HOLD_THRESH_MS);
    Button encoder_button = Button(-1, C::ENCODER_HOLD_THRESH_MS);
    int encoder_delta = 0;
    int single_note_mode_midi_val = -1; // -1 = off (Python None)
    bool is_any_pad_held = false;
    std::vector<NoteMsg> new_notes_on;
    std::vector<NoteMsg> new_notes_off;
    int recording_start_pad = -1;
    int pressed_count = 0;

    void initialize(); // hardware + buttons + midi pad-held provider

    void handle_velocity_mode(uint8_t pad_idx);
    bool process_nav_buttons();
    void handle_encoder_arp_mode(Button &button, const String &play_mode, uint8_t pad_idx);
    void process_inputs_slow();
    void process_inputs_fast();
    void reset_pads_and_notes();
    void get_button_states_list(bool out[C::NUM_PADS]);

#ifdef LOOPSTER_TEST_HOOKS
    // Test-harness input injection (scripts/loopster_test.py): virtual pad and
    // encoder events consumed by the normal pipeline exactly like pedal events,
    // so arp/menu/play-mode behavior is exercised through the real code path.
    void test_inject_pad(uint8_t pad_idx, bool pressed);
    void test_inject_encoder(int delta);
#endif

private:
    // Play mode latched per press-session: re-synced from settings only while no
    // pads are down, so a release is always dispatched under the same mode as its
    // press. Prevents stranded note-offs / hold-loops when the mode changes mid-hold
    // (FN double-click, preset load, test hook). Same hole exists in the Python
    // original — fixed on merit.
    String _latched_play_mode = "loop";

    // PANIC chord (FN + encoder both held >= C::PANIC_HOLD_MS) fired; stays set
    // until both buttons are up so the chord's releases can't trigger the bank
    // shift / nav toggle / held-release actions behind it.
    bool _panic_latched = false;

    void _do_panic();
    bool _handle_fn_button_release();
    bool _handle_fn_button_press();
    void _handle_fn_button_held();
    int _process_button_holds();
    // Returns new press indices; sets has_releases
    std::vector<uint8_t> _process_keymatrix(bool &has_releases);
    void _handle_fn_button_held_fast(const std::vector<uint8_t> &new_press_indices);
    void _play_arp_events(bool from_accelerometer = false);
    void _get_note_and_velocity(uint8_t pad_idx, uint8_t &note, uint8_t &velocity);

#ifdef LOOPSTER_TEST_HOOKS
    struct TestKeyEvent {
        uint8_t pad;
        bool pressed;
    };
    std::vector<TestKeyEvent> _test_key_events; // drained in _process_keymatrix
    int _test_encoder_delta = 0;                // added in process_inputs_slow
#endif
};

extern Inputs inputs;
