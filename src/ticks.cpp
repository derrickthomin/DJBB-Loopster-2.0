#include "ticks.h"
#include <Arduino.h>

namespace ticks {

uint32_t ticks_ms() {
    return millis();
}

} // namespace ticks
