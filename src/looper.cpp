#include "looper.h"
#include "clock.h"
#include "display.h"
#include "pixels.h"
#include "settings.h"
#include "settingsmenu.h"
#include "ticks.h"
#include "utils.h"
#include <math.h>
#include <algorithm>

// Shared recording de-dup cache (item 6). Previously every MidiLoop carried its own
// int16_t[128][16] (~4 KB) + int16_t[16] — ~62 KB of standing RAM across 16 loops, even
// though the cache is only touched while add_cc()/add_aftertouch() run and both early-
// return unless is_recording. LoopManager enforces a single recorder at a time (it stops
// the current recording loop before starting a new one; recording_pad is one int), so one
// shared buffer is sufficient. Reset at the record-START transition (see toggle_record_state).
// -1 sentinel = "no prior value" (0xFF fill).
static int16_t s_last_cc_values[128][16];
static int16_t s_last_at_values[16];

// Finalized-loops event total accessor, registered by LoopManager (item 1). See looper.h.
static uint32_t (*s_events_base_fn)() = nullptr;
void midiloop_register_events_base(uint32_t (*fn)()) { s_events_base_fn = fn; }

uint8_t pack_pad_channel(uint8_t pad_idx, uint8_t midi_channel) {
    return ((midi_channel & 0x0F) << 4) | (pad_idx & 0x0F);
}

void unpack_pad_channel(uint8_t packed, uint8_t &pad_idx, uint8_t &midi_channel) {
    pad_idx = packed & 0x0F;
    midi_channel = (packed >> 4) & 0x0F;
}

static int32_t _calculate_quantized_tick(int32_t tick_count, float quantization_percent, int32_t ticks_per_unit) {
    if (ticks_per_unit <= 0) {
        return tick_count;
    }
    int32_t tick_remainder = tick_count % ticks_per_unit;
    if (tick_remainder > ticks_per_unit / 2.0f) {
        int32_t tick_update = (int32_t)roundf((ticks_per_unit - tick_remainder) * quantization_percent);
        return tick_count + tick_update;
    }
    int32_t tick_update = (int32_t)roundf(tick_remainder * quantization_percent);
    return tick_count - tick_update;
}

// ---------------- storage ----------------

void ArrayBasedEventStorage::add_event(uint8_t note, uint8_t velocity, uint8_t pad_idx, int32_t tick, uint8_t midi_channel) {
    // Grow capacity in fixed chunks so a large recording never triggers vector doubling's
    // transient 2x-size allocation mid-set (fragmentation containment; item 1). Flash-load
    // paths reserve() the exact count up front, so this only bites the live recording path.
    if (notes.size() == notes.capacity()) {
        reserve(notes.size() + C::EVENT_RESERVE_CHUNK);
    }
    if (tick < 0) {
        tick = 0;
    } else if (tick > MAX_TICK_VALUE) {
        tick = MAX_TICK_VALUE;
    }
    notes.push_back(note);
    velocities.push_back(velocity);
    packed_pad_channel.push_back(pack_pad_channel(pad_idx, midi_channel));
    ticks.push_back((uint16_t)tick);
}

void ArrayBasedEventStorage::clear() {
    notes.clear();
    velocities.clear();
    packed_pad_channel.clear();
    ticks.clear();
}

void ArrayBasedCCStorage::add_event(uint8_t cc_num, uint8_t value, int32_t tick, uint8_t midi_channel) {
    // Chunked growth (see ArrayBasedEventStorage::add_event) — fragmentation containment, item 1.
    if (cc_nums.size() == cc_nums.capacity()) {
        reserve(cc_nums.size() + C::EVENT_RESERVE_CHUNK);
    }
    if (tick < 0) {
        tick = 0;
    } else if (tick > MAX_TICK_VALUE) {
        tick = MAX_TICK_VALUE;
    }
    cc_nums.push_back(cc_num);
    values.push_back(value);
    ticks.push_back((uint16_t)tick);
    midi_channels.push_back(midi_channel);
}

void ArrayBasedCCStorage::clear() {
    cc_nums.clear();
    values.clear();
    ticks.clear();
    midi_channels.clear();
}

// ---------------- MidiLoop ----------------

MidiLoop::MidiLoop(const char *type, uint8_t pad_idx)
    : loop_type(type), assigned_pad_idx(pad_idx) {
    recording_bpm = clock_.bpm_current;
    // Recording de-dup cache is now a shared static, reset at record start (item 6).
}

void MidiLoop::reset(bool align_to_clock) {
    clear_notes_and_pixels();
    bool use_clock = settings.midi_sync && clock_.is_playing && playback_use_clock;

    // Sync with MIDI clock. Three cases for the tick origin:
    //
    //  1. PLAYBACK trigger under clock (snap_to_quarter): forward-snap to the next
    //     downbeat so a triggered loop begins cleanly on the beat.
    //  2. RECORDING under clock: back-snap to the CURRENT beat. The origin must sit
    //     at or before the first incoming note; snapping forward (or even landing at
    //     "now" when the record latch trails the downbeat) pushes the origin past the
    //     downbeat note, which then goes negative, gets clamped to 0 in add_event(),
    //     and silently defeats trim_silence. Back-snapping keeps every event >= 0 and
    //     lets trim_silence rebase cleanly to the first event.
    //  3. Everything else (incl. midi_sync == false / clock not running): origin = now.
    //     Note that when midi_sync is off, _get_current_tick() ignores start_tickstamp
    //     entirely and uses the millisecond timestamp, so this path is unaffected.
    static_assert(LOOPER_TICKS_PER_QUARTER_NOTE == Clock::TICKS_PER_QUARTER_NOTE,
                  "snap math below mixes both constants; they must stay equal (R12)");
    bool snap_to_quarter = use_clock && align_to_clock && !is_recording;
    int32_t ticks_until_next_quarter = 0;
    if (snap_to_quarter) {
        int32_t ticks_since_last_quarter = clock_.midi_ticks_elapsed % LOOPER_TICKS_PER_QUARTER_NOTE;
        if (ticks_since_last_quarter != 0) {
            ticks_until_next_quarter = Clock::TICKS_PER_QUARTER_NOTE - ticks_since_last_quarter;
        }
        start_tickstamp = clock_.midi_ticks_elapsed + ticks_until_next_quarter;
    } else if (use_clock && is_recording) {
        int32_t ticks_since_last_quarter = clock_.midi_ticks_elapsed % LOOPER_TICKS_PER_QUARTER_NOTE;
        start_tickstamp = clock_.midi_ticks_elapsed - ticks_since_last_quarter;
    } else {
        start_tickstamp = clock_.midi_ticks_elapsed;
    }

    // Reset queue positions
    queue_index_notes_on = 0;
    queue_index_notes_off = 0;
    queue_index_cc = 0;
    queue_index_at = 0;
    queue_index_oneshot_offs = 0;
    current_midi_ticks = 0;

    // Reset state flags
    ccs_complete = false;
    ats_complete = false;
    note_ons_complete = false;
    note_offs_complete = false;
    cc_sweep_complete = false;
    at_sweep_complete = false;

    // Configure timing
    if (snap_to_quarter) {
        current_midi_ticks = 0 - ticks_until_next_quarter; // start on next quarter note
    } else {
        current_midi_ticks = 0;
    }
    start_timestamp = ticks::ticks_ms();
}

void MidiLoop::clear_notes_and_pixels() {
    // De-dup note-offs on (note, resolved output channel) with a 256-byte stack bitmask
    // (2048 combos) instead of a 4 KB heap std::vector<bool> allocated on EVERY loop
    // stop / "loop"-mode wrap / oneshot completion. That per-stop alloc+free churn was a
    // heap-fragmentation source on the hottest path, where a failed allocation = panic
    // (item 7). Keying on the resolved output channel is strictly correct; the old key
    // also carried pad_idx, which only produced redundant (inaudible) duplicate offs.
    uint8_t seen[256] = {0};
    bool seen_pixels[C::NUM_PADS + 2] = {false};

    for (size_t i = 0; i < notes_on.size(); i++) {
        uint8_t note = notes_on.notes[i];
        uint8_t pad_idx, midi_channel;
        unpack_pad_channel(notes_on.packed_pad_channel[i], pad_idx, midi_channel);
        int output_channel = midi.get_midi_channel_for_pad(pad_idx, midi_channel);
        uint16_t bit_pos = ((uint16_t)(output_channel & 0x0F) << 7) | (note & 0x7F);
        if (!(seen[bit_pos >> 3] & (1 << (bit_pos & 7)))) {
            seen[bit_pos >> 3] |= (1 << (bit_pos & 7));
            midi.send_note_off(note, output_channel);
        }
        if (pad_idx < (C::NUM_PADS + 2)) {
            seen_pixels[pad_idx] = true;
        }
    }
    for (uint8_t p = 0; p < (C::NUM_PADS + 2); p++) {
        if (seen_pixels[p]) {
            pixels.set_note_off(p);
        }
    }
}

void MidiLoop::clear() {
    clear_notes_and_pixels();

    // Flash file reference dropped; orphan cleanup handles the file on next boot
    loop_file_path = "";
    loop_id = -1;

    notes_on.clear();
    notes_off.clear();
    cc_events.clear();
    aftertouch_events.clear();
    cc_oneshot.clear();
    first_cc_values.clear();
    oneshot_indices.clear();
    oneshot_indices.shrink_to_fit();
    oneshot_off_ticks.clear();
    oneshot_off_ticks.shrink_to_fit();
    cached_unique_ccs.clear();
    // Recording de-dup cache is a shared static now, reset at record start (item 6).

    total_time_seconds = 0;
    start_timestamp = 0;
    current_midi_ticks = 0;
    total_midi_ticks = 0;
    toggle_playstate(0);
    toggle_record_state(0);
    current_loop_time = 0;
    has_loop = false;
}

size_t MidiLoop::count_events() const {
    return notes_on.size() + notes_off.size() + cc_events.size() + aftertouch_events.size();
}

bool MidiLoop::_global_budget_reached() const {
    uint32_t base = s_events_base_fn ? s_events_base_fn() : 0; // finalized loops
    return (base + count_events()) >= C::TOTAL_LOOP_EVENTS_LIMIT;
}

bool MidiLoop::_tick_overflow_stop(int32_t tick) {
    if (tick > MAX_TICK_VALUE) {
        max_events_reached = true; // check_event_limits() finalizes the loop next poll
        display.show_notification("MAX LENGTH REACHED");
        return true;
    }
    return false;
}

int32_t MidiLoop::_get_current_tick() const {
    if (settings.midi_sync && clock_.is_playing) {
        return (int32_t)clock_.midi_ticks_elapsed - start_tickstamp;
    }
    return clock_.seconds_to_ticks(
        ticks::ticks_diff(ticks::ticks_ms(), start_timestamp) / 1000.0f,
        recording_bpm);
}

void MidiLoop::reset_timing() {
    start_timestamp = 0;
    start_tickstamp = 0;
    current_midi_ticks = 0;
}

void MidiLoop::toggle_playstate(int on_or_off, bool align_to_clock, int use_midi_clock) {
    loop_is_playing = (on_or_off == -1) ? !loop_is_playing : (on_or_off != 0);
    current_loop_time = 0;

    if (loop_type == "loop" || loop_type == "oneshot" || loop_type == "hold") {
        if (loop_is_playing) {
            if (use_midi_clock != -1) {
                playback_use_clock = (use_midi_clock != 0);
            }
            reset(align_to_clock);
            if (assigned_pad_idx <= 15 && !is_recording) {
                pixels.set_color(assigned_pad_idx, C::PIXEL_LOOP_PLAYING_COLOR);
                pixels.set_default_color(assigned_pad_idx, C::PIXEL_LOOP_PLAYING_COLOR, true);
            }
        } else {
            clear_notes_and_pixels();
            reset_timing();

            // Reset CC values based on settings and loop type
            bool should_reset = (settings.cc_reset_mode == "all" || settings.cc_reset_mode == loop_type);
            if (should_reset) {
                _reset_cc_values();
            }

            if (assigned_pad_idx <= 15) {
                pixels.set_color(assigned_pad_idx, C::LOOP_COLOR);
                pixels.set_default_color(assigned_pad_idx, C::LOOP_COLOR, true);
            }
        }
    }
}

void MidiLoop::toggle_record_state(int on_or_off) {
    bool was_recording = is_recording;
    is_recording = (on_or_off == -1) ? !is_recording : (on_or_off != 0);
    if (!is_recording) {
        max_events_reached = false;
    }

    // Reset the shared recording de-dup cache on the off->on transition — this loop now
    // owns it exclusively for the recording (single-recorder invariant; item 6). No overdub
    // exists, so no cache state needs to survive across recordings.
    if (is_recording && !was_recording) {
        memset(s_last_cc_values, 0xFF, sizeof(s_last_cc_values));
        memset(s_last_at_values, 0xFF, sizeof(s_last_at_values));
    }

    // --- STARTING RECORDING ---
    if (is_recording && !has_loop) {
        start_timestamp = ticks::ticks_ms();
        start_tickstamp = clock_.midi_ticks_elapsed;
        recording_bpm = clock_.bpm_current;
        toggle_playstate(1);
    }
    // --- STOPPING RECORDING ---
    // Guard on was_recording (item 14): loop_type is always one of loop/oneshot/hold, so
    // without it this branch fires on EVERY toggle_record_state(0) — including clear()/reset()
    // on a loop that was never (or is no longer) recording, which then computes garbage timing
    // (total_time_seconds = uptime) and burns a loop_id via get_next_loop_id() on each removal.
    else if (was_recording && !is_recording &&
             ((has_loop && on_or_off != 0) ||
              loop_type == "oneshot" || loop_type == "loop" || loop_type == "hold")) {
        float actual_recording_time = ticks::ticks_diff(ticks::ticks_ms(), start_timestamp) / 1000.0f;
        total_time_seconds = actual_recording_time;

        if (settings.midi_sync) {
            // Direct tick count (consistent with how events were recorded)
            total_midi_ticks = (int32_t)clock_.midi_ticks_elapsed - start_tickstamp;
            recording_bpm = clock_.bpm_current;
            // A transport restart mid-recording (fresh Start, no Stop — pattern-looping
            // sequencers do this every pattern wrap) resets midi_ticks_elapsed under us,
            // so the span can come out non-positive; a <=0 length instant-wraps playback
            // and machine-guns tick-0 events. Fall back to wall-clock length like the
            // unsynced path.
            if (total_midi_ticks <= 0) {
                total_midi_ticks = clock_.seconds_to_ticks(actual_recording_time, recording_bpm);
            }
        } else {
            total_midi_ticks = clock_.seconds_to_ticks(actual_recording_time, recording_bpm);
        }

        if (settings.midi_sync && !clock_.get_playstate()) {
            toggle_playstate(0);
        }

        // --- POST-PROCESSING ---
        trim_silence();
        quantize_events();
        quantize_loop();
        create_oneshot_ccs();

        if (loop_type == "oneshot" && settings.notes_all_at_once) {
            update_oneshot_notes();
        }

        cached_unique_ccs = _compute_unique_ccs();

        // Assign new loop ID for this recording
        loop_id = settings.get_next_loop_id();

        // (Flash streaming path removed — CCs/ATs stay in RAM, saved at preset save)
        // (Recording de-dup cache is a shared static, reset at next record start — item 6.)
    }
}

void MidiLoop::add_note(uint8_t midi_note, uint8_t velocity, uint8_t padidx, bool add_or_remove,
                        bool force_add, uint8_t midi_channel) {
    // NoteOn velocity 0 -> NoteOff (common MIDI convention, e.g. DX7)
    if (add_or_remove && velocity == 0) {
        add_or_remove = false;
    }

    if (!is_recording && !force_add) {
        return;
    }
    if (!force_add && start_timestamp == 0) {
        display.show_notification("Play loop to record");
        toggle_record_state(0);
        return;
    }

    int32_t tick_count = _get_current_tick();
    if (_tick_overflow_stop(tick_count)) { // recording exceeded uint16 tick range (item 15)
        return;
    }
    if (tick_count < 0) { // DAW Stop->Start zeroed the clock mid-recording; don't pile events at tick 0 (R15)
        return;
    }

    // Cap the vector we're about to grow. notes_off must be capped too: a stream of
    // unmatched note-offs from MIDI-in (stuck-note-clear spam, foot controllers)
    // would otherwise grow it without bound and feed OOM (item 13).
    size_t target_size = add_or_remove ? notes_on.size() : notes_off.size();
    if (target_size >= C::LOOP_NOTES_LIMIT) {
        display.show_notification("MAX NOTES REACHED");
        max_events_reached = true;
        return;
    }

    // Global RAM budget across all loops (item 1) — refuse before allocating so a failed
    // new/push_back (= panic on this platform) can never happen. max_events_reached lets
    // check_event_limits() finalize the loop cleanly, same as the per-loop cap above.
    if (_global_budget_reached()) {
        display.show_notification("MAX EVENTS REACHED");
        max_events_reached = true;
        return;
    }

    if (add_or_remove) {
        if (!has_loop) {
            has_loop = true;
        }
        notes_on.add_event(midi_note, velocity, padidx, tick_count, midi_channel);
    } else {
        notes_off.add_event(midi_note, velocity, padidx, tick_count, midi_channel);
    }
}

bool MidiLoop::has_events() const {
    // RAM is the source of truth: loads always fill all streams and the deferred save
    // writes from RAM, so the Python-era "events on flash but not in RAM" case is gone.
    return notes_on.size() > 0 || cc_events.size() > 0 || aftertouch_events.size() > 0;
}

void MidiLoop::add_cc(uint8_t cc_num, uint8_t cc_value, uint8_t midi_channel) {
    if (!is_recording) {
        return;
    }
    if (start_timestamp == 0) {
        display.show_notification("Play loop to record");
        toggle_record_state(0);
        return;
    }

    if (cc_events.size() >= C::CC_EVENTS_LIMIT) {
        max_events_reached = true;
        display.show_notification("MAX CCS REACHED");
        return;
    }
    if (_global_budget_reached()) { // global RAM budget (item 1)
        max_events_reached = true;
        display.show_notification("MAX EVENTS REACHED");
        return;
    }

    // Value change detection (O(1) lookup)
    int16_t last = s_last_cc_values[cc_num & 0x7F][midi_channel & 0x0F];

    // Only record if new CC or changed significantly
    if (last < 0 || abs((int)cc_value - last) > settings.cc_resolution) {
        int32_t tick_count = _get_current_tick();
        if (_tick_overflow_stop(tick_count)) { // item 15
            return;
        }
        if (tick_count < 0) { // clock zeroed mid-recording (R15)
            return;
        }
        if (!has_loop) {
            has_loop = true;
        }
        s_last_cc_values[cc_num & 0x7F][midi_channel & 0x0F] = cc_value;
        cc_events.add_event(cc_num, cc_value, tick_count, midi_channel);
    }
}

void MidiLoop::add_aftertouch(uint8_t pressure, uint8_t midi_channel) {
    if (!is_recording) {
        return;
    }
    if (start_timestamp == 0) {
        display.show_notification("Play loop to record");
        toggle_record_state(0);
        return;
    }

    if (aftertouch_events.size() >= C::CC_EVENTS_LIMIT) {
        max_events_reached = true;
        display.show_notification("MAX AT REACHED");
        return;
    }
    if (_global_budget_reached()) { // global RAM budget (item 1)
        max_events_reached = true;
        display.show_notification("MAX EVENTS REACHED");
        return;
    }

    int16_t last = s_last_at_values[midi_channel & 0x0F];
    if (last < 0 || abs((int)pressure - last) > settings.cc_resolution) {
        int32_t tick_count = _get_current_tick();
        if (_tick_overflow_stop(tick_count)) { // item 15
            return;
        }
        if (tick_count < 0) { // clock zeroed mid-recording (R15)
            return;
        }
        if (!has_loop) {
            has_loop = true;
        }
        s_last_at_values[midi_channel & 0x0F] = pressure;
        aftertouch_events.add_event(0, pressure, tick_count, midi_channel); // cc_num=0 for channel pressure
    }
}

void MidiLoop::_remove_leading_off_notes() {
    if (notes_on.size() == 0 || notes_off.size() == 0) {
        return;
    }
    uint16_t first_note_on_tick = notes_on.ticks[0];
    ArrayBasedEventStorage new_notes_off;

    // Only keep note-offs at or after the first note-on
    for (size_t i = 0; i < notes_off.size(); i++) {
        if (notes_off.ticks[i] >= first_note_on_tick) {
            uint8_t pad_idx, midi_channel;
            unpack_pad_channel(notes_off.packed_pad_channel[i], pad_idx, midi_channel);
            new_notes_off.add_event(notes_off.notes[i], notes_off.velocities[i], pad_idx,
                                    notes_off.ticks[i], midi_channel);
        }
    }
    notes_off = new_notes_off;
}

void MidiLoop::_trim_silence_start() {
    int32_t first_event_tick = -1;
    if (notes_on.size() > 0) {
        first_event_tick = notes_on.ticks[0];
    }
    if (cc_events.size() > 0) {
        int32_t cc_first = cc_events.ticks[0];
        if (first_event_tick < 0 || cc_first < first_event_tick) {
            first_event_tick = cc_first;
        }
    }
    // Aftertouch must shift with everything else or it plays late by the trim amount (R4)
    if (aftertouch_events.size() > 0) {
        int32_t at_first = aftertouch_events.ticks[0];
        if (first_event_tick < 0 || at_first < first_event_tick) {
            first_event_tick = at_first;
        }
    }
    if (first_event_tick <= 0) {
        return;
    }

    for (size_t i = 0; i < notes_on.size(); i++) {
        notes_on.ticks[i] = (notes_on.ticks[i] >= first_event_tick) ? notes_on.ticks[i] - first_event_tick : 0;
    }
    for (size_t i = 0; i < notes_off.size(); i++) {
        notes_off.ticks[i] = (notes_off.ticks[i] >= first_event_tick) ? notes_off.ticks[i] - first_event_tick : 0;
    }
    for (size_t i = 0; i < cc_events.size(); i++) {
        cc_events.ticks[i] = (cc_events.ticks[i] >= first_event_tick) ? cc_events.ticks[i] - first_event_tick : 0;
    }
    for (size_t i = 0; i < aftertouch_events.size(); i++) {
        aftertouch_events.ticks[i] = (aftertouch_events.ticks[i] >= first_event_tick) ? aftertouch_events.ticks[i] - first_event_tick : 0;
    }
    if (total_midi_ticks > first_event_tick) {
        total_midi_ticks -= first_event_tick;
    }
}

void MidiLoop::trim_loaded_ccs() {
    if (notes_on.size() > 0 || cc_events.size() == 0) { // only trim CC-only loops
        return;
    }
    total_midi_ticks = clock_.seconds_to_ticks(C::CC_ONLY_LOOP_LENGTH_MS / 1000.0f, recording_bpm);
    total_time_seconds = C::CC_ONLY_LOOP_LENGTH_MS / 1000.0f;
}

void MidiLoop::_ensure_all_notes_have_offs() {
    if (notes_on.size() == 0 || notes_on.size() == notes_off.size()) {
        return;
    }

    // Membership by (note, resolved output channel) in a 256-byte stack bitmask (2048
    // combos), replacing a 4 KB heap std::vector<bool> allocated on this post-record path.
    // Resolving to output channel is strictly correct: a stored note-off silences the note
    // on that channel at playback; the old (note|channel|pad) key only added inaudible
    // redundant offs. (item 7)
    uint8_t notes_with_offs[256] = {0};
    for (size_t i = 0; i < notes_off.size(); i++) {
        uint8_t padidx, midi_channel;
        unpack_pad_channel(notes_off.packed_pad_channel[i], padidx, midi_channel);
        int out_ch = midi.get_midi_channel_for_pad(padidx, midi_channel);
        uint16_t bit_pos = ((uint16_t)(out_ch & 0x0F) << 7) | (notes_off.notes[i] & 0x7F);
        notes_with_offs[bit_pos >> 3] |= (1 << (bit_pos & 7));
    }

    for (size_t i = 0; i < notes_on.size(); i++) {
        uint8_t padidx, midi_channel;
        unpack_pad_channel(notes_on.packed_pad_channel[i], padidx, midi_channel);
        int out_ch = midi.get_midi_channel_for_pad(padidx, midi_channel);
        uint16_t bit_pos = ((uint16_t)(out_ch & 0x0F) << 7) | (notes_on.notes[i] & 0x7F);
        if (!(notes_with_offs[bit_pos >> 3] & (1 << (bit_pos & 7)))) {
            notes_off.add_event(notes_on.notes[i], 0, padidx, total_midi_ticks - 1, midi_channel);
            notes_with_offs[bit_pos >> 3] |= (1 << (bit_pos & 7));
        }
    }
}

void MidiLoop::_trim_silence_end() {
    if (notes_on.size() == 0) {
        return;
    }
    int32_t last_event_ticks = 0;
    if (notes_off.size() > 0) {
        last_event_ticks = notes_off.ticks[notes_off.size() - 1];
    }
    if (cc_events.size() > 0) {
        int32_t last_cc = cc_events.ticks[cc_events.size() - 1];
        if (last_cc > last_event_ticks) {
            last_event_ticks = last_cc;
        }
    }
    // Aftertouch past the new loop end would be unreachable at playback (R4)
    if (aftertouch_events.size() > 0) {
        int32_t last_at = aftertouch_events.ticks[aftertouch_events.size() - 1];
        if (last_at > last_event_ticks) {
            last_event_ticks = last_at;
        }
    }
    total_midi_ticks = last_event_ticks + 1;
}

void MidiLoop::trim_silence() {
    // Only CCs — always trim both start and end
    if (notes_on.size() == 0 && cc_events.size() > 0) {
        _trim_silence_start();
        _trim_silence_end();
        return;
    }
    if (notes_on.size() == 0) {
        return;
    }
    if (notes_off.size() > 0) {
        _remove_leading_off_notes();
    }

    const String &trim_mode = settings.trim_silence_mode;
    if (trim_mode == "start" || trim_mode == "both") {
        _trim_silence_start();
    }
    if (trim_mode == "end" || trim_mode == "both") {
        _trim_silence_end();
    }
    _ensure_all_notes_have_offs(); // notes held at end get offs
}

void MidiLoop::_handle_loop_end() {
    bool has_cc = cc_events.size() > 0;
    bool has_at = aftertouch_events.size() > 0;
    bool is_controller_only = notes_on.size() == 0 && (has_cc || has_at);

    // Hold mode controller-only loops: play once then hold at final value
    if (loop_type == "hold" && is_controller_only) {
        cc_sweep_complete = true;
        at_sweep_complete = true;
        return;
    }

    if (loop_type == "loop" || loop_type == "hold") {
        reset();
    } else if (loop_type == "oneshot") {
        toggle_playstate(0);
    }
}

size_t MidiLoop::_process_note_queue(int32_t current_ticks, size_t queue_index,
                                     ArrayBasedEventStorage &storage, std::vector<NoteMsg> &out,
                                     bool is_note_on) {
    size_t events_len = storage.size();
    while (queue_index < events_len) {
        uint16_t tick = storage.ticks[queue_index];
        if ((int32_t)tick <= current_ticks) {
            uint8_t padidx, event_channel;
            unpack_pad_channel(storage.packed_pad_channel[queue_index], padidx, event_channel);
            out.push_back({storage.notes[queue_index], storage.velocities[queue_index], padidx, (int8_t)event_channel});
            if (is_note_on) {
                pixels.set_note_on(padidx);
            } else {
                pixels.set_note_off(padidx);
            }
            queue_index++;
        } else {
            break;
        }
    }
    return queue_index;
}

size_t MidiLoop::_process_cc_queue(int32_t current_ticks, size_t queue_index,
                                   ArrayBasedCCStorage &storage, std::vector<CcMsg> &out) {
    size_t events_len = storage.size();
    while (queue_index < events_len) {
        uint16_t tick = storage.ticks[queue_index];
        if ((int32_t)tick <= current_ticks) {
            out.push_back({storage.cc_nums[queue_index], storage.values[queue_index],
                           (int8_t)storage.midi_channels[queue_index]});
            queue_index++;
        } else {
            break;
        }
    }
    return queue_index;
}

bool MidiLoop::get_new_events(LoopEvents &out) {
    out.clear();

    // ===== EARLY EXITS =====
    if (!(total_time_seconds > 0) || !loop_is_playing) {
        return false;
    }
    bool has_cc_events = cc_events.size() > 0;
    bool has_at_events = aftertouch_events.size() > 0;
    if (notes_on.size() == 0 && notes_off.size() == 0 && !has_cc_events && !has_at_events) {
        return false;
    }
    if (notes_on.size() == 0 && ccs_complete && ats_complete) {
        toggle_playstate(0);
        return false;
    }

    // ===== ONESHOT IMMEDIATE EVENTS =====
    if (settings.notes_all_at_once && loop_type == "oneshot") {
        ensure_oneshot_notes();
    }

    // CCs
    if (loop_type == "oneshot" && !ccs_complete) {
        ccs_complete = true;
        for (const CcMsg &m : cc_oneshot) {
            out.cc.push_back(m);
        }
    }

    // Notes — read from indices into original notes_on arrays
    if (settings.notes_all_at_once && loop_type == "oneshot" && !note_ons_complete) {
        for (uint16_t idx : oneshot_indices) {
            uint8_t pad_idx, channel;
            unpack_pad_channel(notes_on.packed_pad_channel[idx], pad_idx, channel);
            out.notes_on.push_back({notes_on.notes[idx], notes_on.velocities[idx], pad_idx, (int8_t)channel});
        }
        note_ons_complete = true;
    }

    // ===== COMPLETION TRACKING =====
    if (settings.notes_all_at_once && loop_type == "oneshot") {
        note_offs_complete = queue_index_oneshot_offs >= oneshot_off_ticks.size();
    } else {
        if (!note_ons_complete && queue_index_notes_on >= notes_on.size()) {
            note_ons_complete = true;
        }
        if (!note_offs_complete && queue_index_notes_off >= notes_off.size()) {
            note_offs_complete = true;
        }
    }

    // Early exit for completed oneshot loops (aftertouch skips oneshot entirely)
    if (loop_type == "oneshot") {
        bool notes_completed = notes_on.size() == 0 || (note_ons_complete && note_offs_complete);
        bool ccs_completed = cc_events.size() == 0 || ccs_complete;
        if (notes_completed && ccs_completed) {
            toggle_playstate(0);
            return true; // Python returned the (possibly empty) lists here
        }
    }

    // ===== TIMING =====
    bool use_clock = settings.midi_sync && playback_use_clock && clock_.is_playing;
    if (use_clock && clock_.new_tick) {
        current_midi_ticks++;
    }

    uint32_t now_time = ticks::ticks_ms();
    current_loop_time = ticks::ticks_diff(now_time, start_timestamp) / 1000.0f;

    int32_t current_ticks_pos;
    if (use_clock) {
        current_ticks_pos = current_midi_ticks;
        if (current_ticks_pos >= total_midi_ticks) {
            _handle_loop_end();
            return false;
        }
    } else {
        current_ticks_pos = clock_.seconds_to_ticks(current_loop_time, recording_bpm);
        if (current_ticks_pos >= total_midi_ticks || current_loop_time >= total_time_seconds) {
            _handle_loop_end();
            return false;
        }
    }

    // ===== TIMED EVENT PROCESSING =====
    bool oneshot_all_at_once = settings.notes_all_at_once && loop_type == "oneshot";

    // Note-OFFs are emitted BEFORE note-ONs at the same tick. For a legato repeat of
    // the same pitch (note-off of one note coincides with note-on of the next), sending
    // the on first would let the trailing off cancel the just-started note, collapsing
    // it to zero length. Offs-first preserves both notes' durations.
    if (oneshot_all_at_once) {
        while (queue_index_oneshot_offs < oneshot_off_ticks.size()) {
            uint32_t tick_offset = oneshot_off_ticks[queue_index_oneshot_offs];
            if ((uint32_t)current_ticks_pos >= tick_offset) {
                uint16_t idx = oneshot_indices[queue_index_oneshot_offs];
                uint8_t pad_idx, channel;
                unpack_pad_channel(notes_on.packed_pad_channel[idx], pad_idx, channel);
                out.notes_off.push_back({notes_on.notes[idx], 0, pad_idx, (int8_t)channel});
                pixels.set_note_off(pad_idx);
                queue_index_oneshot_offs++;
            } else {
                break;
            }
        }
    } else {
        queue_index_notes_off = _process_note_queue(current_ticks_pos, queue_index_notes_off, notes_off, out.notes_off, false);
    }

    if (!oneshot_all_at_once && !note_ons_complete) {
        queue_index_notes_on = _process_note_queue(current_ticks_pos, queue_index_notes_on, notes_on, out.notes_on, true);
    }

    // CC events
    bool skip_cc = (ccs_complete && loop_type == "oneshot") || (cc_sweep_complete && loop_type == "hold");
    if (!skip_cc) {
        queue_index_cc = _process_cc_queue(current_ticks_pos, queue_index_cc, cc_events, out.cc);
    }

    // Aftertouch: skip for oneshot and after hold sweep completes
    bool skip_at = (loop_type == "oneshot") || (at_sweep_complete && loop_type == "hold");
    if (!skip_at) {
        queue_index_at = _process_cc_queue(current_ticks_pos, queue_index_at, aftertouch_events, out.at);
    }

    return out.any();
}

void MidiLoop::create_oneshot_ccs() {
    // Track first and latest value per CC number
    struct Entry {
        bool seen = false;
        uint8_t first_val = 0;
        int8_t first_ch = 0;
        uint8_t last_val = 0;
        int8_t last_ch = 0;
        int32_t last_tick = -1;
        uint16_t order = 0; // first-seen order for stable output
    };
    Entry entries[128];
    uint16_t order_counter = 0;

    for (size_t i = 0; i < cc_events.size(); i++) {
        uint8_t cc_num = cc_events.cc_nums[i] & 0x7F;
        uint8_t cc_val = cc_events.values[i];
        int32_t cc_tick = cc_events.ticks[i];
        int8_t ch = (int8_t)cc_events.midi_channels[i];

        Entry &e = entries[cc_num];
        if (!e.seen) {
            e.seen = true;
            e.first_val = cc_val;
            e.first_ch = ch;
            e.order = order_counter++;
        }
        if (cc_tick >= e.last_tick) {
            e.last_val = cc_val;
            e.last_ch = ch;
            e.last_tick = cc_tick;
        }
    }

    cc_oneshot.clear();
    first_cc_values.clear();
    for (uint16_t ord = 0; ord < order_counter; ord++) {
        for (int cc = 0; cc < 128; cc++) {
            if (entries[cc].seen && entries[cc].order == ord) {
                cc_oneshot.push_back({(uint8_t)cc, entries[cc].last_val, entries[cc].last_ch});
                first_cc_values.push_back({(uint8_t)cc, entries[cc].first_val, entries[cc].first_ch});
            }
        }
    }
}

void MidiLoop::_reset_cc_values() {
    for (const CcMsg &m : first_cc_values) {
        midi.send_cc(m.cc, m.value, m.channel);
    }
}

void MidiLoop::update_oneshot_notes() {
    // 256-byte bitmask for note x channel dedup (2048 combinations)
    uint8_t seen[256] = {0};
    std::vector<uint16_t> indices;
    std::vector<uint32_t> off_ticks;

    // Iterate BACKWARDS — keep the LAST occurrence (most recent velocity/timing)
    for (int i = (int)notes_on.size() - 1; i >= 0; i--) {
        uint8_t note = notes_on.notes[i];
        uint8_t packed_pc = notes_on.packed_pad_channel[i];
        uint8_t pad_unused, channel;
        unpack_pad_channel(packed_pc, pad_unused, channel);

        uint16_t bit_pos = ((uint16_t)channel << 7) | note;
        uint16_t byte_idx = bit_pos >> 3;
        uint8_t bit_mask = 1 << (bit_pos & 7);
        if (seen[byte_idx] & bit_mask) {
            continue;
        }
        seen[byte_idx] |= bit_mask;

        // Note-off tick offset
        uint16_t note_on_tick = notes_on.ticks[i];
        int32_t matching_off_tick = -1;
        for (size_t j = 0; j < notes_off.size(); j++) {
            if (notes_off.notes[j] == note && notes_off.ticks[j] > note_on_tick &&
                notes_off.packed_pad_channel[j] == packed_pc) {
                matching_off_tick = notes_off.ticks[j];
                break;
            }
        }

        int32_t tick_offset;
        if (matching_off_tick >= 0) {
            tick_offset = matching_off_tick - note_on_tick;
        } else {
            tick_offset = (total_midi_ticks > note_on_tick) ? total_midi_ticks - note_on_tick : 1;
        }
        tick_offset = max((int32_t)1, tick_offset);

        indices.push_back((uint16_t)i);
        off_ticks.push_back((uint32_t)tick_offset);
    }

    // Restore chronological order
    std::reverse(indices.begin(), indices.end());
    std::reverse(off_ticks.begin(), off_ticks.end());
    oneshot_indices = indices;
    oneshot_off_ticks = off_ticks;

    // Sort by tick offset (insertion sort — usually small arrays)
    size_t n = oneshot_off_ticks.size();
    for (size_t i = 1; i < n; i++) {
        uint32_t key_tick = oneshot_off_ticks[i];
        uint16_t key_idx = oneshot_indices[i];
        int j = (int)i - 1;
        while (j >= 0 && oneshot_off_ticks[j] > key_tick) {
            oneshot_off_ticks[j + 1] = oneshot_off_ticks[j];
            oneshot_indices[j + 1] = oneshot_indices[j];
            j--;
        }
        oneshot_off_ticks[j + 1] = key_tick;
        oneshot_indices[j + 1] = key_idx;
    }
}

void MidiLoop::quantize_loop() {
    const String &amount = settings.quantize_loop;
    if (amount == "none") {
        return;
    }

    // Parse "1/2", "1/4", or plain "1"
    float amount_float;
    int slash = amount.indexOf('/');
    if (slash >= 0) {
        amount_float = amount.substring(0, slash).toFloat() / amount.substring(slash + 1).toFloat();
    } else {
        amount_float = amount.toFloat();
    }

    int32_t quantization_ticks = (int32_t)(LOOPER_TICKS_PER_QUARTER_NOTE * 4 * amount_float);
    if (quantization_ticks <= 0) {
        return;
    }

    // Snap loop length to the NEAREST unit (up OR down), whichever is closer.
    // roundf breaks exact ties upward, biasing toward keeping the tail.
    int32_t nearest_units = max((int32_t)1, (int32_t)roundf((float)total_midi_ticks / quantization_ticks));

    // Guard: a down-snap must never end the loop before a note that was actually
    // struck. Find the fewest units that still contain the last note-ON and never
    // go below that. (Only note-ONs pin the minimum — note-offs past the end are
    // clamped back below, so a held tail may still be shortened.)
    int32_t last_note_on_tick = -1;
    for (size_t i = 0; i < notes_on.size(); i++) {
        if ((int32_t)notes_on.ticks[i] > last_note_on_tick) {
            last_note_on_tick = (int32_t)notes_on.ticks[i];
        }
    }
    int32_t min_units = 1;
    if (last_note_on_tick >= 0) {
        min_units = (int32_t)ceilf((float)(last_note_on_tick + 1) / quantization_ticks);
    }

    int32_t num_units = max(min_units, nearest_units);
    total_midi_ticks = num_units * quantization_ticks;
    total_time_seconds = clock_.ticks_to_seconds(total_midi_ticks, recording_bpm);

    // Clamp note-offs that exceed loop length
    int32_t max_tick = total_midi_ticks - 1;
    for (size_t i = 0; i < notes_off.size(); i++) {
        if (notes_off.ticks[i] > max_tick) {
            notes_off.ticks[i] = (uint16_t)max_tick;
        }
    }
}

void MidiLoop::quantize_events() {
    if (settings.quantize_time == "none") {
        return;
    }

    int32_t ticks_per_unit = clock_.seconds_to_ticks(
        clock_.get_note_duration_seconds(settings.quantize_time.c_str()), recording_bpm);
    float quantization_percent = get_quantization_percent();

    // (note, pad_idx) -> FIFO of deltas
    struct DeltaList {
        uint8_t note, pad;
        std::vector<int32_t> deltas;
        size_t next = 0;
    };
    std::vector<DeltaList> note_on_deltas;

    for (size_t i = 0; i < notes_on.size(); i++) {
        int32_t original_tick = notes_on.ticks[i];
        int32_t new_tick = _calculate_quantized_tick(original_tick, quantization_percent, ticks_per_unit);
        int32_t delta = new_tick - original_tick;
        notes_on.ticks[i] = (uint16_t)max((int32_t)0, min((int32_t)MAX_TICK_VALUE, new_tick));

        uint8_t note = notes_on.notes[i];
        uint8_t pad_idx, ch_unused;
        unpack_pad_channel(notes_on.packed_pad_channel[i], pad_idx, ch_unused);

        DeltaList *entry = nullptr;
        for (DeltaList &d : note_on_deltas) {
            if (d.note == note && d.pad == pad_idx) {
                entry = &d;
                break;
            }
        }
        if (!entry) {
            note_on_deltas.push_back({note, pad_idx, {}, 0});
            entry = &note_on_deltas.back();
        }
        entry->deltas.push_back(delta);
    }

    // Apply same delta to matching note-offs (preserves original duration)
    for (size_t i = 0; i < notes_off.size(); i++) {
        uint8_t note = notes_off.notes[i];
        uint8_t pad_idx, ch_unused;
        unpack_pad_channel(notes_off.packed_pad_channel[i], pad_idx, ch_unused);

        for (DeltaList &d : note_on_deltas) {
            if (d.note == note && d.pad == pad_idx && d.next < d.deltas.size()) {
                int32_t new_tick = (int32_t)notes_off.ticks[i] + d.deltas[d.next++];
                notes_off.ticks[i] = (uint16_t)max((int32_t)0, min((int32_t)MAX_TICK_VALUE, new_tick));
                break;
            }
        }
    }

    if (settings.quantize_cc) {
        for (size_t i = 0; i < cc_events.size(); i++) {
            int32_t new_tick = _calculate_quantized_tick(cc_events.ticks[i], quantization_percent, ticks_per_unit);
            cc_events.ticks[i] = (uint16_t)max((int32_t)0, min((int32_t)MAX_TICK_VALUE, new_tick));
        }
    }
}

String MidiLoop::change_loop_mode(bool forward) {
    if (forward) {
        // loop -> oneshot -> hold -> loop
        if (loop_type == "loop") loop_type = "oneshot";
        else if (loop_type == "oneshot") loop_type = "hold";
        else loop_type = "loop";
    } else {
        // loop -> hold -> oneshot -> loop
        if (loop_type == "loop") loop_type = "hold";
        else if (loop_type == "hold") loop_type = "oneshot";
        else loop_type = "loop";
    }

    if (loop_type == "oneshot" && settings.notes_all_at_once) {
        ensure_oneshot_notes();
    }
    reset();
    return loop_type;
}

bool MidiLoop::needs_oneshot_generation() const {
    return oneshot_indices.empty() && notes_on.size() > 0 &&
           loop_type == "oneshot" && settings.notes_all_at_once;
}

void MidiLoop::ensure_oneshot_notes() {
    if (needs_oneshot_generation()) {
        update_oneshot_notes();
    }
}

void MidiLoop::warm_unique_ccs() {
    // Fill the cache on first use: the arp reads cached_unique_ccs directly, and loops
    // restored from a preset never went through the record-stop path that populates it (R2).
    if (cached_unique_ccs.empty() && cc_events.size() > 0) {
        cached_unique_ccs = _compute_unique_ccs();
    }
}

std::vector<CcMsg> MidiLoop::_compute_unique_ccs() {
    // CC min/max pairs in chronological order
    struct Range {
        bool seen = false;
        uint8_t min_val = 0, max_val = 0;
        size_t min_idx = 0, max_idx = 0;
        uint16_t order = 0;
    };
    Range ranges[128];
    uint16_t order_counter = 0;

    for (size_t i = 0; i < cc_events.size(); i++) {
        uint8_t cc_num = cc_events.cc_nums[i] & 0x7F;
        uint8_t cc_value = cc_events.values[i];
        Range &r = ranges[cc_num];
        if (!r.seen) {
            r.seen = true;
            r.min_val = r.max_val = cc_value;
            r.min_idx = r.max_idx = i;
            r.order = order_counter++;
        } else {
            if (cc_value < r.min_val) {
                r.min_val = cc_value;
                r.min_idx = i;
            }
            if (cc_value > r.max_val) {
                r.max_val = cc_value;
                r.max_idx = i;
            }
        }
    }

    std::vector<CcMsg> unique_ccs;
    for (uint16_t ord = 0; ord < order_counter; ord++) {
        for (int cc = 0; cc < 128; cc++) {
            Range &r = ranges[cc];
            if (!r.seen || r.order != ord) {
                continue;
            }
            int8_t min_ch = (int8_t)cc_events.midi_channels[r.min_idx];
            int8_t max_ch = (int8_t)cc_events.midi_channels[r.max_idx];
            if (r.min_val == r.max_val) {
                unique_ccs.push_back({(uint8_t)cc, r.min_val, min_ch});
            } else if (r.min_idx < r.max_idx) {
                unique_ccs.push_back({(uint8_t)cc, r.min_val, min_ch});
                unique_ccs.push_back({(uint8_t)cc, r.max_val, max_ch});
            } else {
                unique_ccs.push_back({(uint8_t)cc, r.max_val, max_ch});
                unique_ccs.push_back({(uint8_t)cc, r.min_val, min_ch});
            }
        }
    }
    return unique_ccs;
}

// ---------------- module-level functions ----------------

void set_next_or_prev_quantization(bool up_or_down) {
    settingsmenu::set_next_or_prev_quantization_time(up_or_down);
}

String get_quantization_text() {
    return "Qnt: " + settings.quantize_time;
}

String get_quantization_display_value() {
    return settings.quantize_time;
}

void set_quantization_percent(bool up_or_down) {
    settings.quantize_strength = next_or_previous_index(settings.quantize_strength, 100, up_or_down, false);
}

float get_quantization_percent() {
    return settings.quantize_strength / 100.0f;
}

int get_quantization_percent_int() {
    return settings.quantize_strength;
}

MidiLoop *make_midi_loop(const char *loop_type, uint8_t pad_idx) {
    return new MidiLoop(loop_type, pad_idx);
}
