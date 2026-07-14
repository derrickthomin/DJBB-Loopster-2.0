// Port of src/settings.py — device settings + preset persistence (presets.json).
// JSON key names MUST stay byte-identical to the Python attribute names: presets.json
// is shared with the web config UI and existing user presets.
//
// Couplings the Python resolved with imports-at-save-time (loopmanager, loop_storage,
// display) are runtime-registered callbacks here to avoid include cycles; loopmanager
// and loop_storage register themselves during their init.
#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include <vector>
#include "constants.h"

class Settings {
public:
    Settings();

    // --- Core (names match presets.json keys) ---
    int midibank_idx = 3;
    int midi_channel_out = 0;
    int midi_channel_in = -1; // -1 = ALL channels
    uint8_t default_velocity = 120;
    uint16_t default_bpm = 120;
    uint8_t midi_notes_default[C::NUM_PADS];
    String midi_type = "USB";
    String midi_usb_io = "both";
    String midi_aux_io = "both";
    int scale_idx = 0;
    int rootnote_idx = 0;
    int scalenotes_idx = 2;
    String play_mode = "loop";
    bool midi_sync = false;
    String passthru_mode = "off"; // "off", "aux", "usb", "all"
    bool record_cc = true;
    String clock_source = "USB";
    bool notes_all_at_once = false;
    int midi_settings_page_indices[13] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0};
    int settings_menu_option_indices[13] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1};
    int8_t midi_channel_pad_mapping[C::NUM_PADS]; // PAD_CH_AS_RECORDED default

    // --- Loop mode settings ---
    String loop_type = "loop";
    String arpeggiator_type = "up";
    String arpeggiator_length = "1/8";
    bool arp_is_polyphonic = true;
    // loops_to_load: serialized "loops" object from the loaded preset; loopmanager
    // parses it during initialize(). Empty string = nothing to load.
    String loops_to_load_json = "";
    int next_loop_id = 1; // persisted at presets.json root, not per-preset
    // Set by loop_storage::init() from the /loops dir scan (max existing file id + 1);
    // load_preset never lets next_loop_id fall below it, so a regressed presets.json
    // can't re-issue an id that would overwrite a loop file still on disk.
    int loop_id_floor = 1;

    // --- Quantizer ---
    String quantize_time = "none";
    int quantize_strength = 100;
    String quantize_loop = "none";
    String trim_silence_mode = "start";
    int cc_resolution = 1;
    bool quantize_cc = false;
    // (midi_channel_current, midi_channel_mode, cc_stream_to_flash removed 2026-07-07:
    // write-only legacy fields nothing read; old presets' keys are ignored on load)
    String cc_reset_mode = "hold";   // "none", "hold", "all"

    // --- Display ---
    float led_brightness = 0.3f;

    // --- Accelerometer CC mapping ---
    int accel_left_tilt_cc = C::ACCEL_LEFT_TILT_CC;
    int accel_right_tilt_cc = C::ACCEL_RIGHT_TILT_CC;
    int accel_backward_tilt_cc = C::ACCEL_BACKWARD_TILT_CC;

    // --- State tracking (runtime, stripped on preset write by web UI too) ---
    // Unsaved-changes flag (never persisted): set by every preset-affecting edit,
    // cleared on save and at end of boot. Shown as "*" on the Play title's preset
    // name (2026-07-12 UI review). Coarse by design — no per-field diffing.
    bool dirty = false;
    void mark_dirty() { dirty = true; }
    bool velocity_mapped = false;
    // Python mutated C.VELOCITY_MODE_ENABLED at runtime; constants are immutable in
    // C++, so the runtime flag lives here instead.
    bool velocity_mode_enabled = C::VELOCITY_MODE_ENABLED;

    // --- Preset persistence ---
    int get_next_loop_id() { return next_loop_id++; }
    String get_startup_preset();
    std::vector<String> get_preset_names_list(); // sorted, with "*NEW*" appended
    bool load_preset(const String &preset_name); // false = read failed / preset not found (no reboot)
    bool save_preset_to_file(const String &preset_name); // false = refused (preset cap reached)
#ifdef LOOPSTER_TEST_HOOKS
    // Test-only (TEST_DELETE_PRESET): lets the harness clean up scratch presets.
    // Refuses reserved keys and the current startup preset. The web UI's
    // DELETE_PRESET lives in serial_config.cpp with per-cause error codes;
    // this simpler bool version stays out of release builds.
    bool delete_preset(const String &preset_name);
#endif
    void load_startup_preset();
    void cleanup_orphan_loops();

    void set_play_mode(const String &mode) { play_mode = mode; dirty = true; }
    const String &get_play_mode() const { return play_mode; }

    // Registered by loopmanager: adds "loops" metadata to the preset being saved and
    // performs the deferred flash save of recorded loops.
    using SaveLoopsFn = void (*)(JsonObject &preset_settings);
    void set_save_loops_callback(SaveLoopsFn fn) { _save_loops = fn; }
    // Registered by loop_storage: deletes loop files not in the given id list.
    using CleanupOrphansFn = int (*)(const std::vector<int> &valid_ids);
    void set_cleanup_orphans_callback(CleanupOrphansFn fn) { _cleanup_orphans = fn; }

private:
    void _sanitize_accel_cc_settings();
    void _validate_loaded_fields(); // clamp every preset field to a legal range (item 5)
    std::vector<int> _collect_loop_ids(const JsonDocument &doc);
    void _apply_preset_json(JsonObjectConst preset);
    void _write_fields_to_json(JsonObject out);

    SaveLoopsFn _save_loops = nullptr;
    CleanupOrphansFn _cleanup_orphans = nullptr;
};

extern Settings settings;
