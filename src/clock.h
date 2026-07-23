// Port of src/clock.py — MIDI clock: ticks, BPM estimation, note durations.
// Durations stay float seconds (matching Python exactly) because looper/arp math
// consumes them as-is; tick timestamps elsewhere are uint32 ms.
#pragma once
#include <Arduino.h>

class Clock {
public:
    static constexpr float MILLISECONDS_TO_SECONDS = 1000.0f;
    static constexpr int TICKS_PER_QUARTER_NOTE = 24;
    static constexpr int TICKS_PER_WHOLE_NOTE = TICKS_PER_QUARTER_NOTE * 4;

    uint32_t midi_ticks_elapsed = 0;
    uint32_t last_tick_time = 0;
    float bpm_current = 120.0f;
    bool is_playing = false;
    uint32_t bpm_window_start_time = 0;
    bool new_tick = false;
    // The first 0xF8 after Start OR Continue marks the resume-point tick itself, not the
    // one after it (hw-verified 2026-07-09 via MIDI Monitor: Live bundles SPP + Continue +
    // the first Clock + the on-grid NoteOn in the same millisecond). Counting that clock
    // anchored every %-24 beat-grid derivation one tick ahead of the master's grid, so
    // quantized material played back consistently early. Set by start_clock() and
    // continue_clock(), consumed (without incrementing or setting new_tick) by the next
    // update_clock(). Deliberately NOT cleared by stop_clock().
    bool first_tick_pending = false;
    int pending_bpm = -1; // BPM waiting for confirmation (filters glitches); -1 = none
    uint8_t bpm_window_ticks = 0; // ticks counted into the current BPM measurement window

    // Set by set_bpm()
    float seconds_per_tick = 0;
    float quarternote_duration = 0;
    float halfnote_duration = 0;
    float wholenote_duration = 0;
    float eighthnote_duration = 0;
    float sixteenthnote_duration = 0;

    Clock();

    void reset_midi_tick_count() { midi_ticks_elapsed = 0; }
    void set_bpm(float bpm);
    void reset_new_tick_flag() { new_tick = false; }

    // Song Position Pointer (0xF2): value is MIDI beats (16ths) = 6 ticks each. Ableton
    // resumes transport with SPP + Continue (it only sends 0xFA from the very top), so this
    // is what pins the counter — and therefore the %-24 beat-grid phase — to the master's
    // actual song position. Without it, Continue inherited a stale count and the grid phase
    // was arbitrary. Ignored while rolling: spec masters only send SPP stopped, and a
    // mid-roll jump would corrupt an active recording's event ticks (Live double-sends SPP
    // around its Stop, so the post-Stop one always lands).
    void set_song_position(uint16_t midi_beats) {
        if (is_playing) {
            return;
        }
        midi_ticks_elapsed = (uint32_t)midi_beats * 6;
    }

    // Update on new MIDI clock tick. Calculates BPM from tick intervals.
    void update_clock();

    // Convert seconds <-> MIDI ticks. bpm <= 0 means "use current BPM".
    int32_t seconds_to_ticks(float seconds, float bpm = 0) const;
    float ticks_to_seconds(int32_t t, float bpm = 0) const;

    // Duration in seconds for note type (e.g., "quarter", "1/4", "whole").
    float get_note_duration_seconds(const char *note_type) const;

    void start_clock();
    void continue_clock(); // resume without resetting tick count (MIDI Continue)
    void stop_clock();
    bool get_playstate() const { return is_playing; }
};

extern Clock clock_;  // trailing underscore: <Arduino.h> already claims ::clock()
