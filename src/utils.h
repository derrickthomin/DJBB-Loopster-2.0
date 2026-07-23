// Port of src/utils.py. free_memory() (a gc.collect wrapper) has no C++ counterpart
// and is intentionally dropped.
#pragma once
#include <stdint.h>

// Returns next/previous index, optionally wrapping around.
inline int next_or_previous_index(int current_index, int list_length, bool up_or_down, bool loop_around = true) {
    int direction = up_or_down ? 1 : -1;
    if (loop_around) {
        return (current_index + direction + list_length) % list_length;
    }
    int new_index = current_index + direction;
    if (new_index < 0 || new_index > list_length - 1) {
        return current_index;
    }
    return new_index;
}
