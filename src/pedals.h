// Port of src/pedals.py — 5 foot pedals + their NeoPixels, with bank switching.
// FakeKeypadEvent -> PedalEvent struct; the Python event list -> small ring buffer.
// The loopmanager dependency (the loop-state provider) is a registered callback to
// avoid an include cycle; loopmanager installs it during initialize().
//
// DELIBERATE DIFF vs Python (2026-09-14): pedal LEDs no longer mirror the pad strip 1:1.
// They render LOOP STATE only (off / has-loop / playing / queued / recording / armed),
// polled from useraddons::slow() via refresh_from_loop_state(). Note flashes, CC flashes,
// arp-held and channel-assign colors stay on the pads — on the floor they were noise.
#pragma once
#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include "constants.h"
#include "buttons.h"

// Mimics CircuitPython's keypad event structure (key_number = loopster pad idx)
struct PedalEvent {
    uint8_t key_number;
    bool pressed;
};

// Per-pad loop state, provided by loopmanager. This enum IS the pedal LED filter:
// anything not representable here never reaches the pedal strip.
enum class PadLoopState : uint8_t { None, HasLoop, Playing, Queued, Recording, Armed };

class Pedals {
public:
    Pedals();

    void begin(); // hardware init (pins + pixels); call from setup(), not static-init

    // Update all pedal states and queue keypad-style events
    void update();

    void show_pedal_pixels();
    // Re-derive the 5 LEDs of the current bank from the loop-state provider. Writes the
    // strip (and dirties pixels_need_update) only when a state or the blink phase changed,
    // so core 1's 16 ms show() isn't re-triggered every poll. Blinking states borrow
    // pixels.blink_phase so pedal + pad blink in lockstep.
    void refresh_from_loop_state();
    void reset_pedals();

    // Pop next event into `out`; returns false if queue empty (Python returned None)
    bool get_event(PedalEvent &out);

    void set_pedal_bank(int bank_idx); // 0-2
    // Convert loopster pad index to local pedal pixel index; -1 = not in current bank
    int get_pedal_pixel_index(uint8_t loopster_pad_idx) const;

    using LoopStateFn = PadLoopState (*)(uint8_t pad_idx);
    void set_loop_state_provider(LoopStateFn fn) { _loop_state = fn; }

#ifdef LOOPSTER_TEST_HOOKS
    // Read-only for TEST_PIXELS: the last state rendered on local pedal LED i (0-4).
    PadLoopState test_state(uint8_t i) const { return _last_state[i]; }
#endif

    Button pedal_buttons[C::PEDAL_COUNT] = {Button(0), Button(1), Button(2), Button(3), Button(4)};
    volatile bool pixels_need_update = true; // set on core 0, cleared by core 1's show
    int current_bank = 0;
    int bank_offset = 0;

private:
    void _update_pixels_for_current_bank(); // cache-busting refresh (bank switch)
    static C::Rgb _color_for(PadLoopState st, bool blink_phase);

    PadLoopState _last_state[C::PEDAL_COUNT] = {};
    bool _last_phase = false;
    bool _rendered_once = false; // first refresh always writes (strip starts cleared)

    Adafruit_NeoPixel _pixels;
    static const uint8_t _pedal_pins[C::PEDAL_COUNT];
    PedalEvent _queue[16];
    uint8_t _q_head = 0, _q_count = 0;
    LoopStateFn _loop_state = nullptr;

    void _push_event(uint8_t key, bool pressed);
};

extern Pedals pedals;

void update_pedal_pixels();
