#include "clock.h"
#include "ticks.h"
#include "settings.h"
#include "serial_config.h" // cdc_log (Q1 bounded prints)

Clock clock_;

Clock::Clock() {
    last_tick_time = 0; // millis() not valid in static-init; harmless (Python used boot time)
    set_bpm(bpm_current);
}

void Clock::set_bpm(float bpm) {
    float quarter = 60.0f / bpm;
    bpm_current = bpm;
    seconds_per_tick = 60.0f / (bpm_current * TICKS_PER_QUARTER_NOTE);
    quarternote_duration = quarter;
    halfnote_duration = quarter * 2;
    wholenote_duration = quarter * 4;
    eighthnote_duration = quarter / 2;
    sixteenthnote_duration = quarter / 4;
}

void Clock::update_clock() {
    uint32_t timenow = ticks::ticks_ms();
    last_tick_time = timenow;

    if (first_tick_pending) {
        // Downbeat tick: counter stays 0 so midi_ticks_elapsed == song tick from here on
        // (see clock.h). BPM window restarts here so the first beat measurement
        // spans exactly 24 tick intervals instead of 25. new_tick stays clear too: a loop
        // resumed at Start is already AT position 0 == this downbeat, so advancing playback
        // here made the entire first pass play one tick early (hw-observed: ~19 ms @ 130,
        // self-corrected only at the first wrap re-snap).
        first_tick_pending = false;
        bpm_window_start_time = timenow;
        bpm_window_ticks = 0;
        return;
    }
    new_tick = true;
    midi_ticks_elapsed++;

    // Quarter-note measurement window (was whole-note in the Python port). The 96-tick
    // window + double-confirm was sized for CircuitPython main-loop stalls; with ms
    // timestamps only the window endpoints matter, so one beat (±2-4 ms endpoint jitter
    // over ~500 ms @ 120) resolves integer BPM within the ±1 deadband. Latch worst case
    // drops from ~3 whole notes to 3 beats. Confirmation + deadband kept: consecutive
    // windows share the boundary timestamp, so a jitter spike skews them in opposite
    // directions and can never confirm. Window ticks are counted explicitly (not
    // midi_ticks_elapsed % 24) so an SPP+Continue resume mid-beat can't produce a
    // short first window and a bogus over-read.
    if (++bpm_window_ticks >= TICKS_PER_QUARTER_NOTE) {
        bpm_window_ticks = 0;
        float beat_time = ticks::ticks_diff(timenow, bpm_window_start_time) / MILLISECONDS_TO_SECONDS;
        bpm_window_start_time = timenow;

        int new_bpm = 0;
        if (beat_time > 0) {
            new_bpm = (int)roundf(60.0f / beat_time);
        }

        if (new_bpm != (int)bpm_current && new_bpm > 0) {
            // Ignore ±1 BPM fluctuations (measurement noise from timing jitter)
            if (abs(new_bpm - (int)bpm_current) <= 1) {
                pending_bpm = -1;
            } else if (new_bpm == pending_bpm) {
                set_bpm((float)new_bpm);
                pending_bpm = -1;
            } else {
                // First time seeing this value, wait for confirmation
                pending_bpm = new_bpm;
            }
        } else {
            // Current BPM is stable, clear any pending
            pending_bpm = -1;
        }
    }
}

int32_t Clock::seconds_to_ticks(float seconds, float bpm) const {
    float spt = (bpm > 0) ? 60.0f / (bpm * TICKS_PER_QUARTER_NOTE) : seconds_per_tick;
    return (int32_t)roundf(seconds / spt);
}

float Clock::ticks_to_seconds(int32_t t, float bpm) const {
    float spt = (bpm > 0) ? 60.0f / (bpm * TICKS_PER_QUARTER_NOTE) : seconds_per_tick;
    return t * spt;
}

float Clock::get_note_duration_seconds(const char *note_type) const {
    if (!strcmp(note_type, "whole") || !strcmp(note_type, "1")) return wholenote_duration;
    if (!strcmp(note_type, "half") || !strcmp(note_type, "1/2")) return halfnote_duration;
    if (!strcmp(note_type, "quarter") || !strcmp(note_type, "1/4")) return quarternote_duration;
    if (!strcmp(note_type, "eighth") || !strcmp(note_type, "1/8")) return eighthnote_duration;
    if (!strcmp(note_type, "sixteenth") || !strcmp(note_type, "1/16")) return sixteenthnote_duration;
    if (!strcmp(note_type, "thirtysecond") || !strcmp(note_type, "1/32")) return sixteenthnote_duration / 2;
    if (!strcmp(note_type, "sixtyfourth") || !strcmp(note_type, "1/64")) return sixteenthnote_duration / 4;
    return quarternote_duration;
}

void Clock::start_clock() {
    is_playing = true;
    reset_midi_tick_count();
    first_tick_pending = true; // next 0xF8 is the downbeat — don't count it (see clock.h)
    bpm_window_start_time = ticks::ticks_ms(); // fresh timing reference
    bpm_window_ticks = 0;
    pending_bpm = -1;
    // Deliberately no new_tick here (removed with the downbeat fix): this synthetic tick
    // pushed resumed loops to position 1 while the song was still at tick 0 — the other
    // half of the first-pass-early skew. Tick-0 events don't need it; get_new_events
    // fires `tick <= current` even without an increment.
}

void Clock::continue_clock() {
    is_playing = true;
    // The clock bundled with Continue IS the resume-point tick (see first_tick_pending in
    // clock.h) — the counter already holds that position (via SPP, or the stop-point count),
    // so counting it would put the grid one tick early.
    first_tick_pending = true;
    bpm_window_start_time = ticks::ticks_ms(); // fresh timing reference for BPM
    bpm_window_ticks = 0;
    pending_bpm = -1;
    // Don't reset midi_ticks_elapsed — SPP (sent by Live right before Continue) pins it;
    // without SPP it resumes from the stop-point count
}

void Clock::stop_clock() {
    is_playing = false;
    // Don't reset midi_ticks_elapsed — needed for recording finalization
    // when Stop arrives before toggle_record_state() computes total_midi_ticks
}
