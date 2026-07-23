// Port of src/useraddons.py — Colm's addons: MPU6050 tilt->CC, glove buttons,
// haptic motor, pedal integration. (Implementation ported in its own phase;
// this header is the stable API used by main.cpp and inputs.cpp.)
#pragma once
#include <Arduino.h>
#include <vector>
#include "midi.h"

namespace useraddons {

void init(); // hardware init; call from setup()

// Called from the main loop (code.py hooks)
void slow();
void check_addons_fast();
std::vector<CcMsg> get_accel_cc_data(); // accelerometer CCs to send (never recorded)
bool should_trigger_accelerometer_arp();

// Note/CC event hooks (haptic feedback etc.)
void handle_new_notes_on(uint8_t note, uint8_t velocity, uint8_t padidx, int channel);
void handle_new_notes_off(uint8_t note, uint8_t velocity, uint8_t padidx, int channel);
void handle_new_cc(uint8_t cc, uint8_t value, int channel);

} // namespace useraddons
