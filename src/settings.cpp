#include "settings.h"
#include <LittleFS.h>
#include <algorithm>
#include "midiscales.h" // NUM_SCALES / NUM_ROOTS / MAX_BANKS bounds for field validation
#include "profiling.h"
#include "serial_config.h" // cdc_log (Q1 bounded prints)

Settings settings;

static bool read_presets_file(JsonDocument &doc) {
    File f = LittleFS.open(C::PRESETS_FILEPATH, "r");
    if (!f) {
        return false;
    }
    DeserializationError err = deserializeJson(doc, f);
    f.close();
    rp2040.wdt_reset(); // cheap insurance around flash ops; no-op before wdt_begin
    return !err;
}

static bool write_presets_file(const JsonDocument &doc) {
    // Serialize to a RAM buffer first, then write it in ONE bulk call —
    // serializeJson(doc, file) would stream a byte at a time.
    //
    // ATOMIC (item 2): write to a tmp file, then remove(real)+rename(tmp->real).
    // A direct "w" open truncates presets.json in place, so power loss mid-write
    // leaves a corrupt/empty presets.json — which on next boot makes orphan
    // cleanup delete EVERY loop file. LittleFS commits each of these ops
    // atomically (copy-on-write), so the tmp+rename dance plus the boot-side
    // recovery below covers every power-cut point.
    String out;
    serializeJson(doc, out);

    // 2026-07-06: on LittleFS this whole function is ~tens of ms (it was ~6 s on
    // FatFS, whose FTL rewrote ~63 KB of metadata per file op — see CHANGELOG).
    // Keep the wdt feeds anyway; callers run inside one loop() pass under the
    // 8.3 s watchdog and flash erases can still stack up on a full partition.
    rp2040.wdt_reset();
    File f = LittleFS.open(C::PRESETS_TMP_FILEPATH, "w");
    if (!f) {
        return false;
    }
    size_t written = f.write((const uint8_t *)out.c_str(), out.length());
    f.close();
    rp2040.wdt_reset();
    if (written != out.length()) {
        LittleFS.remove(C::PRESETS_TMP_FILEPATH); // don't leave a truncated tmp to be "recovered"
        return false;
    }
    LittleFS.remove(C::PRESETS_FILEPATH);
    rp2040.wdt_reset();
    return LittleFS.rename(C::PRESETS_TMP_FILEPATH, C::PRESETS_FILEPATH);
}

// Boot-side recovery: if power died between remove(real) and rename(tmp->real),
// presets.json is gone but a complete presets_tmp.json remains. Promote it before
// the first read so we don't boot into a wiped state (and wipe all loop files).
static void recover_interrupted_presets_write() {
    if (!LittleFS.exists(C::PRESETS_FILEPATH) && LittleFS.exists(C::PRESETS_TMP_FILEPATH)) {
        LittleFS.rename(C::PRESETS_TMP_FILEPATH, C::PRESETS_FILEPATH);
    }
}

Settings::Settings() {
    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        midi_notes_default[i] = 36 + i;
        midi_channel_pad_mapping[i] = C::PAD_CH_AS_RECORDED;
    }
}

void Settings::_sanitize_accel_cc_settings() {
    if (accel_left_tilt_cc < 0 || accel_left_tilt_cc > 127) {
        accel_left_tilt_cc = C::ACCEL_LEFT_TILT_CC;
    }
    if (accel_right_tilt_cc < 0 || accel_right_tilt_cc > 127) {
        accel_right_tilt_cc = C::ACCEL_RIGHT_TILT_CC;
    }
    if (accel_backward_tilt_cc < 0 || accel_backward_tilt_cc > 127) {
        accel_backward_tilt_cc = C::ACCEL_BACKWARD_TILT_CC;
    }
}

std::vector<int> Settings::_collect_loop_ids(const JsonDocument &doc) {
    std::vector<int> ids;
    for (JsonPairConst kv : doc.as<JsonObjectConst>()) {
        const char *name = kv.key().c_str();
        if (strcmp(name, "STARTUP_PRESET") == 0 || strcmp(name, "next_loop_id") == 0) {
            continue;
        }
        JsonObjectConst preset = kv.value().as<JsonObjectConst>();
        if (preset.isNull()) {
            continue;
        }
        JsonObjectConst loops = preset["loops"].as<JsonObjectConst>();
        if (loops.isNull()) {
            continue;
        }
        for (JsonPairConst loop_kv : loops) {
            JsonObjectConst meta = loop_kv.value().as<JsonObjectConst>();
            if (!meta.isNull() && meta["loop_id"].is<int>()) {
                ids.push_back(meta["loop_id"].as<int>());
            }
        }
    }
    return ids;
}

void Settings::cleanup_orphan_loops() {
    if (!_cleanup_orphans) {
        return; // loop_storage not initialized yet
    }
    JsonDocument doc;
    bool parsed = read_presets_file(doc);
    if (!parsed && LittleFS.exists(C::PRESETS_FILEPATH)) {
        // presets.json is present but unreadable/corrupt. Do NOT fall through to
        // "no valid ids -> delete every loop file" — that would turn a transient
        // parse failure into permanent, unrecoverable loss of all recorded loops
        // (item 2). A genuinely missing file (fresh device) still cleans up.
        return;
    }
    std::vector<int> valid_ids = _collect_loop_ids(doc); // empty doc -> deletes ALL orphans (safe: no presets reference loops)
    _cleanup_orphans(valid_ids);
}

String Settings::get_startup_preset() {
    JsonDocument doc;
    if (read_presets_file(doc) && doc["STARTUP_PRESET"].is<const char *>()) {
        return doc["STARTUP_PRESET"].as<const char *>();
    }
    return "DEFAULT";
}

std::vector<String> Settings::get_preset_names_list() {
    std::vector<String> names;
    JsonDocument doc;
    if (!read_presets_file(doc)) {
        return names;
    }
    for (JsonPairConst kv : doc.as<JsonObjectConst>()) {
        const char *name = kv.key().c_str();
        if (strcmp(name, "STARTUP_PRESET") != 0 && strcmp(name, "next_loop_id") != 0) {
            names.push_back(String(name));
        }
    }
    std::sort(names.begin(), names.end(), [](const String &a, const String &b) {
        return strcmp(a.c_str(), b.c_str()) < 0;
    });
    names.push_back("*NEW*");
    return names;
}

// Apply one preset object's keys onto our fields (Python: setattr for matching keys)
void Settings::_apply_preset_json(JsonObjectConst p) {
    if (p["midibank_idx"].is<int>()) midibank_idx = p["midibank_idx"];
    if (p["midi_channel_out"].is<int>()) midi_channel_out = p["midi_channel_out"];
    if (p["midi_channel_in"].is<int>()) midi_channel_in = p["midi_channel_in"];
    if (p["default_velocity"].is<int>()) default_velocity = p["default_velocity"];
    if (p["default_bpm"].is<int>()) default_bpm = p["default_bpm"];
    if (p["midi_notes_default"].is<JsonArrayConst>()) {
        JsonArrayConst arr = p["midi_notes_default"];
        uint8_t i = 0;
        for (JsonVariantConst v : arr) {
            if (i >= C::NUM_PADS) break;
            midi_notes_default[i++] = v.as<uint8_t>();
        }
    }
    if (p["midi_type"].is<const char *>()) midi_type = p["midi_type"].as<const char *>();
    if (p["midi_usb_io"].is<const char *>()) midi_usb_io = p["midi_usb_io"].as<const char *>();
    if (p["midi_aux_io"].is<const char *>()) midi_aux_io = p["midi_aux_io"].as<const char *>();
    if (p["scale_idx"].is<int>()) scale_idx = p["scale_idx"];
    if (p["rootnote_idx"].is<int>()) rootnote_idx = p["rootnote_idx"];
    if (p["scalenotes_idx"].is<int>()) scalenotes_idx = p["scalenotes_idx"];
    if (p["play_mode"].is<const char *>()) play_mode = p["play_mode"].as<const char *>();
    if (p["midi_sync"].is<bool>()) midi_sync = p["midi_sync"];
    if (p["passthru_mode"].is<const char *>()) passthru_mode = p["passthru_mode"].as<const char *>();
    if (p["record_cc"].is<bool>()) record_cc = p["record_cc"];
    if (p["clock_source"].is<const char *>()) clock_source = p["clock_source"].as<const char *>();
    if (p["notes_all_at_once"].is<bool>()) notes_all_at_once = p["notes_all_at_once"];
    if (p["midi_settings_page_indices"].is<JsonArrayConst>()) {
        JsonArrayConst arr = p["midi_settings_page_indices"];
        uint8_t i = 0;
        for (JsonVariantConst v : arr) {
            if (i >= 13) break;
            midi_settings_page_indices[i++] = v.as<int>();
        }
    }
    if (p["settings_menu_option_indices"].is<JsonArrayConst>()) {
        JsonArrayConst arr = p["settings_menu_option_indices"];
        uint8_t i = 0;
        for (JsonVariantConst v : arr) {
            if (i >= 13) break;
            settings_menu_option_indices[i++] = v.as<int>();
        }
    }
    if (p["midi_channel_pad_mapping"].is<JsonArrayConst>()) {
        JsonArrayConst arr = p["midi_channel_pad_mapping"];
        uint8_t i = 0;
        for (JsonVariantConst v : arr) {
            if (i >= C::NUM_PADS) break;
            // Backward compat: old presets used null for "As Recorded"
            midi_channel_pad_mapping[i++] = v.isNull() ? C::PAD_CH_AS_RECORDED : v.as<int8_t>();
        }
    }
    if (p["loop_type"].is<const char *>()) loop_type = p["loop_type"].as<const char *>();
    // Backward compat: old 'chordmode_looptype' key
    else if (p["chordmode_looptype"].is<const char *>()) loop_type = p["chordmode_looptype"].as<const char *>();
    if (p["arpeggiator_type"].is<const char *>()) arpeggiator_type = p["arpeggiator_type"].as<const char *>();
    if (p["arpeggiator_length"].is<const char *>()) arpeggiator_length = p["arpeggiator_length"].as<const char *>();
    if (p["arp_is_polyphonic"].is<bool>()) arp_is_polyphonic = p["arp_is_polyphonic"];
    if (p["quantize_time"].is<const char *>()) quantize_time = p["quantize_time"].as<const char *>();
    if (p["quantize_strength"].is<int>()) quantize_strength = p["quantize_strength"];
    if (p["quantize_loop"].is<const char *>()) quantize_loop = p["quantize_loop"].as<const char *>();
    if (p["trim_silence_mode"].is<const char *>()) trim_silence_mode = p["trim_silence_mode"].as<const char *>();
    if (p["cc_resolution"].is<int>()) cc_resolution = p["cc_resolution"];
    if (p["quantize_cc"].is<bool>()) quantize_cc = p["quantize_cc"];
    if (p["cc_reset_mode"].is<const char *>()) cc_reset_mode = p["cc_reset_mode"].as<const char *>();
    if (p["led_brightness"].is<float>()) led_brightness = p["led_brightness"];
    if (p["accel_left_tilt_cc"].is<int>()) accel_left_tilt_cc = p["accel_left_tilt_cc"];
    if (p["accel_right_tilt_cc"].is<int>()) accel_right_tilt_cc = p["accel_right_tilt_cc"];
    if (p["accel_backward_tilt_cc"].is<int>()) accel_backward_tilt_cc = p["accel_backward_tilt_cc"];
    if (p["velocity_mapped"].is<bool>()) velocity_mapped = p["velocity_mapped"];
    _validate_loaded_fields();
}

// Clamp every field a preset can set to its legal range. The web UI (SET_PRESET) writes
// arbitrary JSON that lands here on the next load; without this, out-of-range indices cause
// OOB array reads and crashes — SCALE_INTERVALS[scale_idx-1], ROOT_NAMES/SCALE_NAMES pointer
// derefs, bank tables, malformed MIDI status bytes. Clamp (don't reject) so a slightly-off
// preset still loads. Runs on EVERY apply, so normal on-device presets are validated too. (item 5)
// Q4 companion to the numeric clamps below: string "enum" fields get no clamping, and a
// misspelled/whitespaced value ("USB ", "usbb") silently disables behavior — a bad
// midi_type makes should_send() AND should_receive() false on both ports: pads light,
// instrument mute, reads as bricked on stage. Match trimmed + case-insensitive, then
// assign the canonical spelling (most consumers compare case-SENSITIVELY, e.g.
// passthru_mode != "off"); anything unrecognized falls back to the default.
static void whitelist_str(String &field, std::initializer_list<const char *> legal,
                          const char *fallback) {
    field.trim();
    for (const char *v : legal) {
        if (field.equalsIgnoreCase(v)) {
            field = v;
            return;
        }
    }
    field = fallback;
}

void Settings::_validate_loaded_fields() {
    auto clamp_i = [](int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); };

    // Scale/root/bank indices — the crash-critical ones (int fields keep full JSON value).
    scale_idx      = clamp_i(scale_idx, 0, midiscales::NUM_SCALES - 1);
    rootnote_idx   = clamp_i(rootnote_idx, 0, midiscales::NUM_ROOTS - 1);
    midibank_idx   = clamp_i(midibank_idx, 0, midiscales::MAX_BANKS - 1);
    scalenotes_idx = clamp_i(scalenotes_idx, 0, midiscales::MAX_BANKS - 1);

    // MIDI channels — bad values produce malformed status bytes downstream.
    midi_channel_out = clamp_i(midi_channel_out, 0, 15);
    if (midi_channel_in < -1 || midi_channel_in > 15) midi_channel_in = -1; // -1 = ALL

    // Per-pad note numbers + per-pad channel mapping (sentinel values kept).
    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        if (midi_notes_default[i] > 127) midi_notes_default[i] = 127;
        int8_t m = midi_channel_pad_mapping[i];
        if (m != C::PAD_CH_AS_RECORDED && m != C::PAD_CH_GLOBAL && (m < 0 || m > 15)) {
            midi_channel_pad_mapping[i] = C::PAD_CH_AS_RECORDED;
        }
    }

    // Numeric ranges (non-crash, but keep them sane for playback correctness).
    default_velocity  = (uint8_t)clamp_i(default_velocity, 1, 127);
    default_bpm       = (uint16_t)clamp_i(default_bpm, 60, 200); // matches the BPM menu range
    quantize_strength = clamp_i(quantize_strength, 0, 100);
    cc_resolution     = clamp_i(cc_resolution, 0, 127);
    if (led_brightness < 0.0f) led_brightness = 0.0f;
    if (led_brightness > 1.0f) led_brightness = 1.0f;

    // String "enum" fields (Q4). Legal sets are the menu option tables in
    // settingsmenu.cpp init() (+ play_mode's playmenu values); defaults are the
    // field initializers in settings.h. Keep all three in sync.
    whitelist_str(midi_type, {"USB", "AUX", "ALL"}, "USB");
    whitelist_str(midi_usb_io, {"both", "in", "out"}, "both");
    whitelist_str(midi_aux_io, {"both", "in", "out"}, "both");
    whitelist_str(play_mode, {"loop", "velocity", "encoder"}, "loop");
    whitelist_str(passthru_mode, {"off", "aux", "usb", "all"}, "off");
    whitelist_str(clock_source, {"USB", "AUX"}, "USB");
    whitelist_str(loop_type, {"loop", "oneshot", "hold"}, "loop");
    whitelist_str(arpeggiator_type,
                  {"up", "down", "random", "rand oct up", "rand oct dn", "rnd st up", "rnd st dn"},
                  "up");
    whitelist_str(arpeggiator_length, {"1/64", "1/32", "1/16", "1/8", "1/4", "1/2", "1"}, "1/8");
    whitelist_str(quantize_time, {"none", "1/4", "1/8", "1/16", "1/32", "1/64"}, "none");
    whitelist_str(quantize_loop, {"none", "1", "1/2", "1/4", "1/8"}, "none");
    whitelist_str(trim_silence_mode, {"start", "end", "none", "both"}, "start");
    whitelist_str(cc_reset_mode, {"none", "hold", "all"}, "hold");

    _sanitize_accel_cc_settings();
}

// Serialize all persistable fields (Python: for key in self.__dict__)
void Settings::_write_fields_to_json(JsonObject out) {
    out["midibank_idx"] = midibank_idx;
    out["midi_channel_out"] = midi_channel_out;
    out["midi_channel_in"] = midi_channel_in;
    out["default_velocity"] = default_velocity;
    out["default_bpm"] = default_bpm;
    JsonArray notes = out["midi_notes_default"].to<JsonArray>();
    for (uint8_t i = 0; i < C::NUM_PADS; i++) notes.add(midi_notes_default[i]);
    out["midi_type"] = midi_type;
    out["midi_usb_io"] = midi_usb_io;
    out["midi_aux_io"] = midi_aux_io;
    out["scale_idx"] = scale_idx;
    out["rootnote_idx"] = rootnote_idx;
    out["scalenotes_idx"] = scalenotes_idx;
    out["play_mode"] = play_mode;
    out["midi_sync"] = midi_sync;
    out["passthru_mode"] = passthru_mode;
    out["record_cc"] = record_cc;
    out["clock_source"] = clock_source;
    out["notes_all_at_once"] = notes_all_at_once;
    JsonArray pages = out["midi_settings_page_indices"].to<JsonArray>();
    for (uint8_t i = 0; i < 13; i++) pages.add(midi_settings_page_indices[i]);
    JsonArray opts = out["settings_menu_option_indices"].to<JsonArray>();
    for (uint8_t i = 0; i < 13; i++) opts.add(settings_menu_option_indices[i]);
    JsonArray chmap = out["midi_channel_pad_mapping"].to<JsonArray>();
    for (uint8_t i = 0; i < C::NUM_PADS; i++) chmap.add(midi_channel_pad_mapping[i]);
    out["loop_type"] = loop_type;
    out["arpeggiator_type"] = arpeggiator_type;
    out["arpeggiator_length"] = arpeggiator_length;
    out["arp_is_polyphonic"] = arp_is_polyphonic;
    out["quantize_time"] = quantize_time;
    out["quantize_strength"] = quantize_strength;
    out["quantize_loop"] = quantize_loop;
    out["trim_silence_mode"] = trim_silence_mode;
    out["cc_resolution"] = cc_resolution;
    out["quantize_cc"] = quantize_cc;
    out["cc_reset_mode"] = cc_reset_mode;
    out["led_brightness"] = led_brightness;
    out["accel_left_tilt_cc"] = accel_left_tilt_cc;
    out["accel_right_tilt_cc"] = accel_right_tilt_cc;
    out["accel_backward_tilt_cc"] = accel_backward_tilt_cc;
    out["velocity_mapped"] = velocity_mapped;
    // NOTE: loops_to_load / next_loop_id intentionally excluded (runtime / root-level)
}

bool Settings::load_preset(const String &preset_name) {
    JsonDocument doc;
    PROF_START(t_read);
    bool read_ok = read_presets_file(doc);
    PROF_ADD(read_presets_us, t_read);
    if (!read_ok) {
        return false;
    }
    JsonObjectConst preset = doc[preset_name].as<JsonObjectConst>();
    if (preset.isNull()) {
        return false;
    }

    PROF_START(t_apply);
    _apply_preset_json(preset);

    // Loops metadata for binary loading (includes loop_id per pad)
    loops_to_load_json = "";
    if (!preset["loops"].isNull()) {
        serializeJson(preset["loops"], loops_to_load_json);
    }

    // next_loop_id lives at root level (shared across all presets). Reconcile against
    // the boot-time file scan AND every id referenced in the doc: a stale/reset value
    // (corruption fallback, restored backup upload) must never re-issue an id that an
    // existing file or preset still uses — save_loop_to_flash would overwrite it. Both
    // checks are pure in-RAM passes over data already loaded; no extra flash reads.
    next_loop_id = doc["next_loop_id"] | 1;
    if (next_loop_id < loop_id_floor) {
        next_loop_id = loop_id_floor;
    }
    for (int id : _collect_loop_ids(doc)) {
        if (id >= next_loop_id) {
            next_loop_id = id + 1;
        }
    }

    // Enable velocity mode if preset uses it
    if (play_mode == "velocity") {
        velocity_mode_enabled = true;
    }
    PROF_ADD(apply_us, t_apply);

    // Persist the startup preset, but skip the flash write when it's already
    // correct. On a normal boot, load_startup_preset() re-loads the preset that
    // is *already* STARTUP_PRESET, so this write is pure redundant flash churn.
    // The pre-reboot preset switch (where the value actually changes) still
    // writes. Compare before mutating the doc.
    bool startup_changed = (doc["STARTUP_PRESET"].as<String>() != preset_name);
    if (startup_changed) {
        doc["STARTUP_PRESET"] = preset_name;
        PROF_START(t_write);
        write_presets_file(doc);
        PROF_ADD(write_presets_us, t_write);
    }
    return true;
}

// NOTE: file ops are cheap on LittleFS (2026-07-06 switch; they were ~0.5-2 s
// each on FatFS), but the wdt_reset() feeds below and in loop_storage stay — a
// many-loop save on a fragmented partition still does real erase work. Do NOT
// try rp2040.idleOtherCore() around the save to speed up flash lockouts: it
// conflicts with arduino-pico's internal flash-safe lockout and hard-crashes on
// the first flash write (tested).
bool Settings::save_preset_to_file(const String &requested_name) {
    // This whole function runs inside one loop() pass while the watchdog (8.3 s)
    // is armed. A multi-loop save's flash writes can legitimately exceed that, so
    // feed the dog between stages — each stage is still individually covered.
    JsonDocument doc;
    read_presets_file(doc); // missing/invalid file -> empty doc, same as Python
    rp2040.wdt_reset();

    // Count existing user presets up front (item 18 cap + *NEW* naming).
    int preset_count = 0;
    for (JsonPairConst kv : doc.as<JsonObjectConst>()) {
        const char *name = kv.key().c_str();
        if (strcmp(name, "STARTUP_PRESET") != 0 && strcmp(name, "next_loop_id") != 0) {
            preset_count++;
        }
    }

    String preset_name = requested_name;
    if (preset_name == "*NEW*") {
        // PRESET_<n> can collide if presets were renamed/deleted leaving gaps;
        // bump the suffix until it names an unused preset (item 25).
        int suffix = preset_count;
        preset_name = "PRESET_" + String(suffix);
        while (!doc[preset_name].isNull()) {
            suffix++;
            preset_name = "PRESET_" + String(suffix);
        }
    }

    // Refuse creating a NEW preset beyond the cap; overwriting an existing one is fine (item 18).
    if (doc[preset_name].isNull() && preset_count >= C::MAX_PRESETS) {
        return false;
    }

    JsonObject preset_settings = doc[preset_name].isNull()
                                     ? doc[preset_name].to<JsonObject>()
                                     : doc[preset_name].as<JsonObject>();
    _write_fields_to_json(preset_settings);

    // loopmanager adds "loops" metadata + performs deferred flash save of loop events
    if (_save_loops) {
        _save_loops(preset_settings);
    }
    rp2040.wdt_reset();

    doc["STARTUP_PRESET"] = preset_name;
    doc["next_loop_id"] = next_loop_id; // persist at root level

    write_presets_file(doc);
    rp2040.wdt_reset();

    // Immediately clean up orphaned loop files (e.g., loops deleted from pads)
    cleanup_orphan_loops();
    rp2040.wdt_reset();
    return true;
}

#ifdef LOOPSTER_TEST_HOOKS
bool Settings::delete_preset(const String &preset_name) {
    if (preset_name == "STARTUP_PRESET" || preset_name == "next_loop_id") {
        return false; // reserved root keys, not presets
    }
    JsonDocument doc;
    if (!read_presets_file(doc)) {
        return false;
    }
    if (doc[preset_name].isNull()) {
        return false;
    }
    if (doc["STARTUP_PRESET"].as<String>() == preset_name) {
        return false; // boot path would point at a missing preset
    }
    doc.remove(preset_name);
    if (!write_presets_file(doc)) {
        return false;
    }
    cleanup_orphan_loops(); // reclaim the deleted preset's loop .bin files
    return true;
}
#endif

void Settings::load_startup_preset() {
    // Before any read: promote a stranded tmp file from an interrupted atomic write.
    recover_interrupted_presets_write();
    PROF_START(t_cleanup);
    cleanup_orphan_loops(); // delete files from removed presets
    PROF_ADD(cleanup_us, t_cleanup);
    load_preset(get_startup_preset());
}
