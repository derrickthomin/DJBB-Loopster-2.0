#include "midiscales.h"
#include "settings.h"

namespace midiscales {

// midi_banks_chromatic starting offsets: 0,4,20,36,52,68,84,100,111 (+0..15 each)
static const uint8_t CHROMATIC_STARTS[9] = {0, 4, 20, 36, 52, 68, 84, 100, 111};

const char *const SCALE_NAMES[NUM_SCALES] = {
    "chromatic", "maj", "min", "harm_min", "mel_min", "dorian", "phrygian", "lydian"
};

const char *const ROOT_NAMES[NUM_ROOTS] = {
    "C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"
};

// scale_intervals, same order as SCALE_NAMES[1..]
static const uint8_t SCALE_INTERVALS[NUM_SCALES - 1][7] = {
    {2, 2, 1, 2, 2, 2, 1}, // maj
    {2, 1, 2, 2, 1, 2, 2}, // min
    {2, 1, 2, 2, 1, 3, 1}, // harm_min
    {2, 1, 2, 2, 2, 2, 1}, // mel_min
    {2, 1, 2, 2, 2, 1, 2}, // dorian
    {1, 2, 2, 2, 1, 2, 2}, // phrygian
    {2, 2, 2, 1, 2, 2, 1}, // lydian
};

// generate_midi_notes_in_scale(), including the original's exact fill/pad behavior.
static uint8_t generate_banks(uint8_t root, const uint8_t intervals[7], ScaleBanks &out) {
    uint8_t midi_notes[160];
    int count = 0;
    int cur_note = root;

    midi_notes[count++] = root;
    for (int i = 0; i < 7; i++) {
        cur_note += intervals[i];
        midi_notes[count++] = (uint8_t)cur_note;
    }

    int base_count = count; // first-octave notes (root + 7 intervals)
    int octave = 1;
    while (cur_note < 127) {
        for (int i = 0; i < base_count; i++) {
            cur_note = midi_notes[i] + (12 * octave);
            if (cur_note > 127) {
                break;
            }
            midi_notes[count++] = (uint8_t)cur_note;
        }
        octave++;
    }

    // Split into banks of NUM_PADS, padding a short final bank with its last note
    uint8_t num_banks = (count + C::NUM_PADS - 1) / C::NUM_PADS;
    if (num_banks > MAX_BANKS) {
        num_banks = MAX_BANKS;
    }
    for (uint8_t b = 0; b < num_banks; b++) {
        int start = b * C::NUM_PADS;
        uint8_t last_valid = midi_notes[count - 1];
        for (uint8_t p = 0; p < C::NUM_PADS; p++) {
            int idx = start + p;
            if (idx < count) {
                out.notes[b][p] = midi_notes[idx];
                last_valid = midi_notes[idx];
            } else {
                out.notes[b][p] = last_valid;
            }
        }
    }
    out.numBanks = num_banks;
    return num_banks;
}

uint8_t get_scale_notes(uint8_t scale_idx, uint8_t root_idx, ScaleBanks &out) {
    if (scale_idx == 0) { // chromatic
        for (uint8_t b = 0; b < 9; b++) {
            for (uint8_t p = 0; p < C::NUM_PADS; p++) {
                out.notes[b][p] = CHROMATIC_STARTS[b] + p;
            }
        }
        out.numBanks = 9;
        return 9;
    }
    uint8_t root_note = root_idx; // scale_root_notes maps name -> 0..11
    return generate_banks(root_note, SCALE_INTERVALS[scale_idx - 1], out);
}

uint8_t get_current_scale_notes(ScaleBanks &out) {
    return get_scale_notes(settings.scale_idx, settings.rootnote_idx, out);
}

void get_scale_display_text(String out[3]) {
    if (settings.scale_idx == 0) { // special handling for chromatic
        out[0] = "     Chromatic";
        out[1] = "";
        out[2] = "        " + String(settings.scale_idx + 1) + "/" + String(NUM_SCALES);
    } else {
        out[0] = "     " + String(ROOT_NAMES[settings.rootnote_idx]) + " " + String(SCALE_NAMES[settings.scale_idx]);
        out[1] = "";
        out[2] = String(settings.rootnote_idx + 1) + "/" + String(NUM_ROOTS) + "           " +
                 String(settings.scale_idx + 1) + "/" + String(NUM_SCALES);
    }
}

} // namespace midiscales
