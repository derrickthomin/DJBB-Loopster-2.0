// Port of src/looper.py — MidiLoop record/playback engine + event storage.
//
// DESIGN CHANGE (approved in plan.md): the CircuitPython flash-streaming path
// (CCPlaybackCache, cc_stream_to_flash, per-loop flash caches) is dropped. Loops
// live fully in RAM; *_file_path Strings remain only as "already saved" markers
// for preset save/load (loop_storage). All gc.collect()/low-memory checks removed.
//
// Python dicts/sets -> vectors + bitmasks; parallel array.array storage kept 1:1.
// Event tuples -> NoteMsg/CcMsg from midi.h (aftertouch rides in CcMsg with cc=0).
#pragma once
#include <Arduino.h>
#include <vector>
#include "constants.h"
#include "midi.h"

static const uint16_t MAX_TICK_VALUE = 65535;
static const int LOOPER_TICKS_PER_QUARTER_NOTE = 24;

uint8_t pack_pad_channel(uint8_t pad_idx, uint8_t midi_channel);
void unpack_pad_channel(uint8_t packed, uint8_t &pad_idx, uint8_t &midi_channel);

// Global recording budget (item 1): looper enforces TOTAL_LOOP_EVENTS_LIMIT live while
// recording, which needs the finalized-loops event total owned by LoopManager. Including
// loopmanager.h here would create an include cycle, so LoopManager registers an accessor
// at init (same callback pattern settings.h uses). Returns 0 until registered.
void midiloop_register_events_base(uint32_t (*fn)());

// Array-based MIDI note event storage (parallel arrays, matches .bin file layout)
class ArrayBasedEventStorage {
public:
    std::vector<uint8_t> notes;
    std::vector<uint8_t> velocities;
    std::vector<uint8_t> packed_pad_channel; // pad_idx(low 4) + midi_channel(high 4)
    std::vector<uint16_t> ticks;

    void add_event(uint8_t note, uint8_t velocity, uint8_t pad_idx, int32_t tick, uint8_t midi_channel = 0);
    size_t size() const { return notes.size(); }
    // Pre-size all columns for a known event count (flash load) to avoid
    // per-push_back reallocation churn, capacity slack, and heap fragmentation.
    void reserve(size_t n) {
        notes.reserve(n);
        velocities.reserve(n);
        packed_pad_channel.reserve(n);
        ticks.reserve(n);
    }
    void clear();
};

// Array-based MIDI CC/aftertouch event storage
class ArrayBasedCCStorage {
public:
    std::vector<uint8_t> cc_nums;
    std::vector<uint8_t> values;
    std::vector<uint16_t> ticks;
    std::vector<uint8_t> midi_channels;

    void add_event(uint8_t cc_num, uint8_t value, int32_t tick, uint8_t midi_channel = 0);
    size_t size() const { return cc_nums.size(); }
    // Pre-size all columns for a known event count (flash load) to avoid
    // per-push_back reallocation churn, capacity slack, and heap fragmentation.
    void reserve(size_t n) {
        cc_nums.reserve(n);
        values.reserve(n);
        ticks.reserve(n);
        midi_channels.reserve(n);
    }
    void clear();
};

// Output of get_new_events() (Python's 4-list tuple)
struct LoopEvents {
    std::vector<NoteMsg> notes_on;
    std::vector<NoteMsg> notes_off;
    std::vector<CcMsg> cc;
    std::vector<CcMsg> at; // aftertouch: cc field = 0, value = pressure

    bool any() const { return !notes_on.empty() || !notes_off.empty() || !cc.empty() || !at.empty(); }
    void clear() { notes_on.clear(); notes_off.clear(); cc.clear(); at.clear(); }
};

class MidiLoop {
public:
    explicit MidiLoop(const char *loop_type = "loop", uint8_t assigned_pad_idx = C::DEFAULT_LOOP_PAD_IDX);

    String loop_type; // "loop", "oneshot", "hold"
    uint8_t assigned_pad_idx;

    // Timing
    uint32_t start_timestamp = 0;
    int32_t start_tickstamp = 0;
    float total_time_seconds = 0;
    float current_loop_time = 0;
    int32_t total_midi_ticks = 0;
    int32_t current_midi_ticks = 0;
    float recording_bpm = 120;

    // Event storage
    ArrayBasedEventStorage notes_on;
    ArrayBasedEventStorage notes_off;
    ArrayBasedCCStorage cc_events;
    ArrayBasedCCStorage aftertouch_events;
    std::vector<CcMsg> cc_oneshot;
    std::vector<CcMsg> first_cc_values; // first recorded value per CC (hold-mode reset)
    std::vector<uint16_t> oneshot_indices;   // indices into notes_on (unique note+channel)
    std::vector<uint32_t> oneshot_off_ticks; // tick offset for each oneshot note-off
    std::vector<CcMsg> cached_unique_ccs;

    // Playback queue indices
    size_t queue_index_notes_on = 0;
    size_t queue_index_notes_off = 0;
    size_t queue_index_cc = 0;
    size_t queue_index_at = 0;
    size_t queue_index_oneshot_offs = 0;

    // Loop identity and flash storage. loop_file_path non-empty = "already saved":
    // it gates the deferred save in save_loops_to_preset and is reset on clear().
    int loop_id = -1;
    String loop_file_path = "";

    // State flags
    bool loop_is_playing = false;
    bool is_recording = false;
    bool has_loop = false;
    bool playback_use_clock = true;

    // Completion tracking
    bool note_ons_complete = false;
    bool note_offs_complete = false;
    bool ccs_complete = true;
    bool ats_complete = true;
    bool cc_sweep_complete = false; // hold mode: CC sweep played through once?
    bool at_sweep_complete = false;
    bool max_events_reached = false;

    void reset(bool align_to_clock = true);
    void clear_notes_and_pixels();
    void clear();
    size_t count_events() const;
    void reset_timing();
    // on_or_off: -1 = toggle (Python None), 0/1 explicit. use_midi_clock: -1 = leave as-is.
    void toggle_playstate(int on_or_off = -1, bool align_to_clock = true, int use_midi_clock = -1);
    void toggle_record_state(int on_or_off = -1);
    void add_note(uint8_t midi_note, uint8_t velocity, uint8_t padidx, bool add_or_remove,
                  bool force_add = false, uint8_t midi_channel = 0);
    bool has_events() const;
    void add_cc(uint8_t cc_num, uint8_t cc_value, uint8_t midi_channel = 0);
    void add_aftertouch(uint8_t pressure, uint8_t midi_channel = 0);
    void trim_loaded_ccs();
    void trim_silence();
    // Fills `out`; returns false where Python returned None
    bool get_new_events(LoopEvents &out);
    void create_oneshot_ccs();
    void update_oneshot_notes();
    void quantize_loop();
    void quantize_events();
    String change_loop_mode(bool forward = true); // cycles loop -> oneshot -> hold
    bool needs_oneshot_generation() const;
    void ensure_oneshot_notes();
    void warm_unique_ccs(); // fill cached_unique_ccs if empty (arp reads the cache directly; R2)

private:
    // Recording de-dup caches moved to a shared file-static in looper.cpp (item 6):
    // only one loop records at a time, so per-instance arrays wasted ~62 KB of RAM.

    // True once the finalized-loops total + this recording loop's live events reach the
    // global budget. Single-recorder invariant means `this` is the only uncounted loop.
    bool _global_budget_reached() const;

    // Recording ticks are stored as uint16 (and the .bin header truncates to uint16). Past
    // MAX_TICK_VALUE, events pile up at the clamp and playback is corrupt. Returns true and
    // flags the loop to stop when the current tick has overflowed (item 15).
    bool _tick_overflow_stop(int32_t tick);

    int32_t _get_current_tick() const;
    void _reset_cc_values();
    void _remove_leading_off_notes();
    void _trim_silence_start();
    void _ensure_all_notes_have_offs();
    void _trim_silence_end();
    void _handle_loop_end();
    size_t _process_note_queue(int32_t current_ticks, size_t queue_index,
                               ArrayBasedEventStorage &storage, std::vector<NoteMsg> &out,
                               bool is_note_on);
    size_t _process_cc_queue(int32_t current_ticks, size_t queue_index,
                             ArrayBasedCCStorage &storage, std::vector<CcMsg> &out);
    std::vector<CcMsg> _compute_unique_ccs();
};

void set_next_or_prev_quantization(bool up_or_down = true);
String get_quantization_text();
String get_quantization_display_value();
void set_quantization_percent(bool up_or_down = true);
float get_quantization_percent();
int get_quantization_percent_int();
MidiLoop *make_midi_loop(const char *loop_type = "loop", uint8_t pad_idx = C::DEFAULT_LOOP_PAD_IDX);
