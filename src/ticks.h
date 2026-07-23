// Port of src/ticks_minimal.py. millis() is already ms-since-boot; the diff helper
// uses unsigned subtraction cast to signed, which stays correct across the 49-day
// uint32 wrap (better than the Python original, which punted on wraparound).
#pragma once
#include <stdint.h>

namespace ticks {

uint32_t ticks_ms();

inline int32_t ticks_diff(uint32_t t1, uint32_t t2) {
    return (int32_t)(t1 - t2);
}

inline uint32_t ticks_add(uint32_t t, int32_t delta) {
    return t + (uint32_t)delta;
}

inline bool ticks_less(uint32_t t1, uint32_t t2) {
    return ticks_diff(t1, t2) < 0;
}

} // namespace ticks
