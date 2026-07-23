// Port of src/loopmanager.py — loop recording/playback/pad assignment manager.
// Python's `loops[idx] == ""` empty-slot idiom -> nullptr. recording_pad None -> -1.
// Because flash streaming is dropped, load_loops_binary() reads CC/AT events fully
// into RAM (Python set lazy cache paths instead).
// Also implements the settings save-loops callback (Python settings.py imported
// loop_manager at save time) and registers the pedals/settingsmenu hooks.
#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include "constants.h"
#include "looper.h"

class LoopManager {
public:
    MidiLoop *loops[C::NUM_PADS] = {nullptr};
    bool play_queue[C::NUM_PADS] = {false}; // play these when MIDI start received
    bool any_loop_playing = false;
    int recording_pad = -1; // -1 = none
    bool is_recording = false;
    bool recording_is_armed = false; // armed to record when transport starts or note played
    uint32_t total_events_count = 0;

    void add_remove_loop(uint8_t pad_idx);
    void check_event_limits();
    void handle_fn_press(const char *action_type = "press");
    void change_loop_mode(uint8_t button_idx, bool forward = true);
    void display_loop_mode(uint8_t idx);
    void toggle_loop_playstate(uint8_t idx, bool force_play = false, bool force_stop = false);
    void start_armed_recording();
    void process_loop_on_queue();
    void stop_all_loops();
    void silence_all_for_lock(); // unconditional stop + note-off on every loop (web-lock entry)
    void initialize(); // loads loops from settings.loops_to_load_json + registers hooks
    void load_loops_binary(JsonObjectConst loops_metadata);
    void update_pad_pixels();
    void finalize_loop_load(uint8_t pad_idx);
    void handle_midi_sync_change();

    // settings save-preset callback: writes "loops" metadata + deferred flash save
    void save_loops_to_preset(JsonObject &preset_settings);

private:
    void _create_new_loop(uint8_t pad_idx);
    void _remove_loop(uint8_t pad_idx);
    void _stop_single_loop(uint8_t idx, MidiLoop *loop_obj);
    // on_or_off: -1 = toggle. use_midi_clock: -1 = leave as-is.
    void _play_loop(uint8_t idx, int on_or_off = -1, bool align_to_clock = true, int use_midi_clock = -1);
};

extern LoopManager loop_manager;
