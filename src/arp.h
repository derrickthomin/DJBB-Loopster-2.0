// Port of src/arp.py — reference-based arpeggiator (stores pad indices, reads
// notes on demand). Python's lazy loop_manager/midi imports are plain includes in
// the .cpp (no cycle: arp is included by inputs, not by loopmanager/midi).
// NoteMsg.channel here is the RESOLVED output channel (get_midi_channel_for_pad),
// matching the Python tuples.
#pragma once
#include <Arduino.h>
#include <vector>
#include "constants.h"
#include "midi.h"

struct ArpStep {
    bool has_note = false;
    NoteMsg note = {};
    bool has_cc = false;
    CcMsg cc = {};
};

class Arpeggiator {
public:
    std::vector<uint8_t> held_pads; // press order preserved
    int total_notes = 0;
    int total_ccs = 0;
    int note_play_index = 0;
    int cc_play_index = 0;

    bool has_last_played_note = false;
    NoteMsg last_played_note = {};

    void add_source(uint8_t pad_idx);
    void remove_source(uint8_t pad_idx);
    // All currently-playing notes for immediate note-off; clears the queue.
    std::vector<NoteMsg> flush_playing_notes();
    // forward=false steps backward (polyphonic only)
    ArpStep get_next_arp_events(bool forward = true);
    NoteMsg shift_note_octave(const NoteMsg &note, int num_octaves = 1);
    const std::vector<NoteMsg> &get_off_notes(); // notes whose duration expired; reused buffer, valid until next call (R14)
    bool has_ccs() const { return total_ccs > 0; }
    void clear_arp_notes();
    bool has_events() const { return total_notes > 0 || total_ccs > 0; }

private:
    struct QueuedOff {
        NoteMsg note;
        uint32_t off_time;
    };
    std::vector<QueuedOff> arp_note_off_queue;
    uint8_t note_counts[C::NUM_PADS] = {0};
    uint8_t cc_counts[C::NUM_PADS] = {0};
    bool _last_forward = true;

    bool _get_note_at_index(int flat_idx, NoteMsg &out);
    bool _read_note(uint8_t pad_idx, int local_idx, NoteMsg &out);
    bool _get_cc_at_index(int flat_idx, CcMsg &out);
    uint32_t _get_note_duration_ms() const;
};

extern Arpeggiator arpeggiator;
