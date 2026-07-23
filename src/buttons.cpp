#include "buttons.h"
#include "ticks.h"

void Button::update_all() {
    uint32_t now = ticks::ticks_ms();
    reset_actions();

    if (!value && !state) { // New press
        state = true;
        starttime = now;
        new_press = true;
        is_held = false;
        new_dbl_press = false;
        _check_double_press();
    }

    if (!value && state) { // Check for hold while pressed
        check_if_held();
    }

    if (value && state) { // New release
        new_release = true;
        state = false;
        if (is_held) {
            new_release_from_held = true;
            dbl_press_time = 0;
            held_time_ms = 0;
            is_held = false;
        } else if (ignore_next_release) {
            // pass
        } else {
            dbl_press_time = now;
        }
        ignore_next_release = false; // reset after processing
    }
}

int Button::process_keymatrix_event(bool pressed) {
    if (pressed) {
        if (!state) {
            new_press = true;
            starttime = ticks::ticks_ms();
            state = true;
            return pad_idx;
        }
        new_press = false;
        return -1;
    }
    if (state) { // just released
        new_release = true;
        state = false;
        starttime = 0;
    }
    return -1;
}

bool Button::_check_double_press() {
    new_dbl_press = false;

    // dbl_press_time == 0 is the "no prior release" sentinel; without this guard a
    // first press within DBL_PRESS_THRESH_MS of boot (small starttime, diff-from-0
    // under threshold) registers a spurious double-press (item 25).
    if (dbl_press_time != 0 &&
        ticks::ticks_diff(starttime, dbl_press_time) < (int32_t)C::DBL_PRESS_THRESH_MS) {
        new_dbl_press = true;
        dbl_press_time = 0;
        starttime = ticks::ticks_ms(); // avoid erroneous button holds
        new_press = false;
        ignore_next_release = true; // prevent immediate re-trigger on next click
    }
    return new_dbl_press;
}

bool Button::check_if_held() {
    uint32_t now = ticks::ticks_ms();
    if (!state) {
        is_held = false;
        held_time_ms = 0;
        return false;
    }

    held_time_ms = now - starttime;
    if (state && held_time_ms > hold_thresh_ms && !is_held) {
        is_held = true;
        new_dbl_press = false; // clear double press if held
    }
    return is_held;
}
