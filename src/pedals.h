// Port of src/pedals.py — 5 foot pedals + their NeoPixels, with bank switching.
// FakeKeypadEvent -> PedalEvent struct; the Python event list -> small ring buffer.
// The loopmanager dependency (_update_pixels_for_current_bank) is a registered
// callback to avoid an include cycle; loopmanager installs it during initialize().
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

// Per-pad loop state, provided by loopmanager for bank-switch pixel refresh
enum class PadLoopState : uint8_t { None, HasLoop, Playing };

class Pedals {
public:
    Pedals();

    void begin(); // hardware init (pins + pixels); call from setup(), not static-init

    // Update all pedal states and queue keypad-style events
    void update();

    void show_pedal_pixels();
    void set_pixel_on(uint8_t loopster_pad_idx, C::Rgb color = C::NOTE_COLOR);
    void set_pixel_off(uint8_t loopster_pad_idx);
    void reset_pedals();

    // Pop next event into `out`; returns false if queue empty (Python returned None)
    bool get_event(PedalEvent &out);

    void set_pedal_bank(int bank_idx); // 0-2
    // Convert loopster pad index to local pedal pixel index; -1 = not in current bank
    int get_pedal_pixel_index(uint8_t loopster_pad_idx) const;

    using LoopStateFn = PadLoopState (*)(uint8_t pad_idx);
    void set_loop_state_provider(LoopStateFn fn) { _loop_state = fn; }

    Button pedal_buttons[C::PEDAL_COUNT] = {Button(0), Button(1), Button(2), Button(3), Button(4)};
    volatile bool pixels_need_update = true; // set on core 0, cleared by core 1's show
    int current_bank = 0;
    int bank_offset = 0;

private:
    void _update_pixels_for_current_bank();

    Adafruit_NeoPixel _pixels;
    static const uint8_t _pedal_pins[C::PEDAL_COUNT];
    PedalEvent _queue[16];
    uint8_t _q_head = 0, _q_count = 0;
    LoopStateFn _loop_state = nullptr;

    void _push_event(uint8_t key, bool pressed);
};

extern Pedals pedals;

void update_pedal_pixels();
