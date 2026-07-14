#include "arp.h"
#include "clock.h"
#include "settings.h"
#include "loopmanager.h"
#include "looper.h"
#include "ticks.h"

Arpeggiator arpeggiator;

void Arpeggiator::add_source(uint8_t pad_idx) {
    for (uint8_t p : held_pads) {
        if (p == pad_idx) {
            return;
        }
    }

    MidiLoop *loop = loop_manager.loops[pad_idx];
    uint8_t note_count, cc_count;
    if (loop) {
        note_count = (uint8_t)min(loop->notes_on.size(), (size_t)255);
        cc_count = (uint8_t)min(loop->cached_unique_ccs.size(), (size_t)255);
    } else {
        note_count = 1; // single pad note
        cc_count = 0;
    }

    held_pads.push_back(pad_idx);
    note_counts[pad_idx] = note_count;
    cc_counts[pad_idx] = cc_count;
    total_notes += note_count;
    total_ccs += cc_count;
}

void Arpeggiator::remove_source(uint8_t pad_idx) {
    bool found = false;
    for (size_t i = 0; i < held_pads.size(); i++) {
        if (held_pads[i] == pad_idx) {
            held_pads.erase(held_pads.begin() + i);
            found = true;
            break;
        }
    }
    if (!found) {
        return;
    }

    total_notes -= note_counts[pad_idx];
    total_ccs -= cc_counts[pad_idx];
    note_counts[pad_idx] = 0;
    cc_counts[pad_idx] = 0;

    // Clamp indices to valid range
    note_play_index = (total_notes > 0) ? note_play_index % total_notes : 0;
    cc_play_index = (total_ccs > 0) ? cc_play_index % total_ccs : 0;
}

std::vector<NoteMsg> Arpeggiator::flush_playing_notes() {
    std::vector<NoteMsg> notes_to_off;
    for (const QueuedOff &q : arp_note_off_queue) {
        notes_to_off.push_back(q.note);
    }
    arp_note_off_queue.clear();
    return notes_to_off;
}

bool Arpeggiator::_get_note_at_index(int flat_idx, NoteMsg &out) {
    int running_count = 0;
    for (uint8_t pad_idx : held_pads) {
        int pad_note_count = note_counts[pad_idx];
        if (flat_idx < running_count + pad_note_count) {
            return _read_note(pad_idx, flat_idx - running_count, out);
        }
        running_count += pad_note_count;
    }
    return false;
}

bool Arpeggiator::_read_note(uint8_t pad_idx, int local_idx, NoteMsg &out) {
    MidiLoop *loop = loop_manager.loops[pad_idx];

    if (loop && local_idx < (int)loop->notes_on.size()) {
        uint8_t pad_unused, recorded_ch;
        unpack_pad_channel(loop->notes_on.packed_pad_channel[local_idx], pad_unused, recorded_ch);
        int midi_ch = midi.get_midi_channel_for_pad(pad_idx, recorded_ch);
        out = {loop->notes_on.notes[local_idx], loop->notes_on.velocities[local_idx], pad_idx, (int8_t)midi_ch};
        return true;
    }
    // No loop — pad's default note with pad's channel setting
    out = {midi.get_midi_note_by_idx(pad_idx), midi.get_velocity_by_idx(pad_idx), pad_idx,
           (int8_t)midi.get_midi_channel_for_pad(pad_idx)};
    return true;
}

bool Arpeggiator::_get_cc_at_index(int flat_idx, CcMsg &out) {
    int running_count = 0;
    for (uint8_t pad_idx : held_pads) {
        MidiLoop *loop = loop_manager.loops[pad_idx];
        if (!loop || loop->cached_unique_ccs.empty()) {
            continue;
        }
        int pad_cc_count = (int)loop->cached_unique_ccs.size();
        if (flat_idx < running_count + pad_cc_count) {
            const CcMsg &cc = loop->cached_unique_ccs[flat_idx - running_count];
            out = {cc.cc, cc.value, (int8_t)midi.get_midi_channel_for_pad(pad_idx, cc.channel)};
            return true;
        }
        running_count += pad_cc_count;
    }
    return false;
}

ArpStep Arpeggiator::get_next_arp_events(bool forward) {
    ArpStep step;
    if (total_notes == 0 && total_ccs == 0) {
        return step;
    }

    const String &arp_type = settings.arpeggiator_type;

    // === NOTES ===
    if (total_notes > 0) {
        // Handle direction changes to avoid repeating notes
        if (!forward) {
            int steps_back = _last_forward ? 2 : 1;
            note_play_index = ((note_play_index - steps_back) % total_notes + total_notes) % total_notes;
        } else if (!_last_forward) {
            note_play_index = (note_play_index + 1) % total_notes;
        }

        int current_idx = note_play_index;
        step.has_note = _get_note_at_index(current_idx, step.note);

        if (forward) {
            int next_idx;
            if (arp_type == "up" || arp_type == "down") {
                int dir = (arp_type == "up") ? 1 : -1;
                next_idx = ((current_idx + dir) % total_notes + total_notes) % total_notes;
            } else if (arp_type == "random") {
                next_idx = random(0, total_notes);
            } else if (arp_type == "rand oct up" || arp_type == "rand oct dn") {
                int dir = (arp_type.indexOf("up") >= 0) ? 1 : -1;
                next_idx = ((current_idx + dir) % total_notes + total_notes) % total_notes;
                if (random(0, 2) == 1 && step.has_note) {
                    step.note = shift_note_octave(step.note, random(0, 2) == 1 ? 1 : -1);
                }
            } else if (arp_type == "rnd st up" || arp_type == "rnd st dn") {
                int dir = (arp_type.indexOf("up") >= 0) ? 1 : -1;
                next_idx = ((current_idx + dir) % total_notes + total_notes) % total_notes;
                if (next_idx == 0) {
                    next_idx = random(0, total_notes);
                }
            } else {
                next_idx = (current_idx + 1) % total_notes;
            }
            note_play_index = next_idx;
        }

        // Schedule note-off
        if (step.has_note) {
            uint32_t off_time = ticks::ticks_add(ticks::ticks_ms(), _get_note_duration_ms());
            arp_note_off_queue.push_back({step.note, off_time});
            last_played_note = step.note;
            has_last_played_note = true;
        }
    }

    // === CCs ===
    if (total_ccs > 0) {
        if (!forward) {
            int steps_back = _last_forward ? 2 : 1;
            cc_play_index = ((cc_play_index - steps_back) % total_ccs + total_ccs) % total_ccs;
        } else if (!_last_forward) {
            cc_play_index = (cc_play_index + 1) % total_ccs;
        }

        step.has_cc = _get_cc_at_index(cc_play_index, step.cc);

        if (forward) {
            cc_play_index = (cc_play_index + 1) % total_ccs;
        }
    }

    _last_forward = forward;
    return step;
}

uint32_t Arpeggiator::_get_note_duration_ms() const {
    return (uint32_t)(clock_.get_note_duration_seconds(settings.arpeggiator_length.c_str()) * C::MS_PER_SECOND);
}

NoteMsg Arpeggiator::shift_note_octave(const NoteMsg &note, int num_octaves) {
    int new_note_val = note.note + 12 * num_octaves;
    if (new_note_val < 0 || new_note_val > 127) {
        new_note_val = note.note;
    }
    NoteMsg out = note;
    out.note = (uint8_t)new_note_val;
    return out;
}

const std::vector<NoteMsg> &Arpeggiator::get_off_notes() {
    // Runs every fast pass: reuse one output buffer and compact the queue in
    // place instead of building two fresh vectors per call (item R14; same
    // pattern as loop_events/cc_coalesce).
    static std::vector<NoteMsg> off_notes;
    off_notes.clear();

    uint32_t current_time = ticks::ticks_ms();
    size_t keep = 0;
    for (size_t i = 0; i < arp_note_off_queue.size(); i++) {
        const QueuedOff &q = arp_note_off_queue[i];
        if (ticks::ticks_diff(current_time, q.off_time) >= 0) {
            off_notes.push_back(q.note);
        } else {
            arp_note_off_queue[keep++] = q;
        }
    }
    arp_note_off_queue.resize(keep); // shrinks size, keeps capacity
    return off_notes;
}

void Arpeggiator::clear_arp_notes() {
    held_pads.clear();
    memset(note_counts, 0, sizeof(note_counts));
    memset(cc_counts, 0, sizeof(cc_counts));
    total_notes = 0;
    total_ccs = 0;
    note_play_index = 0;
    cc_play_index = 0;
    _last_forward = true;
    arp_note_off_queue.clear();
}
