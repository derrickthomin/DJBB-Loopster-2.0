// Port of src/midiscales.py — scale/bank note tables.
// Banks are generated into a fixed struct instead of Python's nested lists; the
// generation algorithm mirrors the Python original exactly (same padding behavior)
// so pad layouts match the CircuitPython device note-for-note.
#pragma once
#include <Arduino.h>
#include "constants.h"

namespace midiscales {

constexpr uint8_t MAX_BANKS = 12; // chromatic uses 9; generated scales use fewer

struct ScaleBanks {
    uint8_t notes[MAX_BANKS][C::NUM_PADS];
    uint8_t numBanks;
};

constexpr uint8_t NUM_SCALES = 8; // chromatic + 7 interval scales
constexpr uint8_t NUM_ROOTS = 12;

extern const char *const SCALE_NAMES[NUM_SCALES];      // "chromatic", "maj", ...
extern const char *const ROOT_NAMES[NUM_ROOTS];        // "C", "Db", ...

// get_scale_notes(scale_idx, root_idx) — fills `out`, returns bank count.
uint8_t get_scale_notes(uint8_t scale_idx, uint8_t root_idx, ScaleBanks &out);

// get_current_scale_notes() — uses settings.scale_idx / settings.rootnote_idx.
uint8_t get_current_scale_notes(ScaleBanks &out);

// get_scale_display_text() — 3 display lines for the scale menu.
void get_scale_display_text(String out[3]);

} // namespace midiscales
