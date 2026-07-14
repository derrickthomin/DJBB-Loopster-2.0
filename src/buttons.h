// Port of src/buttons.py — press/release/hold/double-press state tracker.
// Python used float seconds (time.monotonic); here uint32_t ms (millis).
// NOTE: `value` keeps the Python/pull-up semantics: false = physically pressed.
#pragma once
#include <Arduino.h>
#include "constants.h"

class Button {
public:
    // States
    bool value = false;
    bool state = false;
    int pad_idx = -1; // -1 = none
    bool new_dbl_press = false;
    bool is_held = false;
    bool new_press = false;
    bool new_release = false;
    bool new_release_from_held = false;
    bool ignore_next_release = false; // ignore release after hold

    // Timing (ms)
    uint32_t hold_thresh_ms = C::BUTTON_HOLD_THRESH_MS;
    uint32_t starttime = 0;
    uint32_t dbl_press_time = 0;
    uint32_t held_time_ms = 0;

    explicit Button(int pad_index = -1, uint32_t hold_thresh = C::BUTTON_HOLD_THRESH_MS)
        : pad_idx(pad_index), hold_thresh_ms(hold_thresh) {}

    void reset_new_press() { new_press = false; }

    void reset_actions() {
        new_press = false;
        new_release = false;
        new_release_from_held = false;
        new_dbl_press = false;
    }

    void set_ignore_next_release() { ignore_next_release = true; }

    void set_current_value(bool v) {
        if (value != v) {
            value = v;
        }
    }

    // Update all button states based on current value.
    void update_all();

    // Process a keymatrix event. Returns pad_idx on new press, -1 otherwise.
    int process_keymatrix_event(bool pressed);

    void reset_double_press() {
        dbl_press_time = 0;
        new_dbl_press = false;
    }

    bool check_if_held();

private:
    bool _check_double_press();
};
