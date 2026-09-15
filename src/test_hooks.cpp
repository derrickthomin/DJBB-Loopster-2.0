#include "test_hooks.h"

#ifdef LOOPSTER_TEST_HOOKS

#include <ArduinoJson.h>
#include <LittleFS.h>
#include "loopmanager.h"
#include "settings.h"
#include "presets.h" // silence_for_reboot
#include "clock.h"
#include "ticks.h"
#include "inputs.h"
#include "menus.h"
#include "fw_version.h"
#include "midi.h"
#include "arp.h"
#include "pixels.h"
#include "pedals.h"
#include "serial_config.h"

namespace test_hooks {

// Deferred pre-reboot action ("" = none). Set by handle(), run by after_response().
static String s_pending_preset;
static bool s_reboot_pending = false;

// Main-loop heartbeat (see loop_heartbeat in the header)
static volatile uint32_t s_loop_max_us = 0;
static volatile uint32_t s_loop_iters = 0;
static uint32_t s_loop_prev_us = 0;

void loop_heartbeat() {
    uint32_t now = micros();
    if (s_loop_prev_us != 0) {
        uint32_t dt = now - s_loop_prev_us;
        if (dt > s_loop_max_us) {
            s_loop_max_us = dt;
        }
    }
    s_loop_prev_us = now;
    s_loop_iters++;
}

// CDC diagnostics: how many CMD lines were handled and RSPs written, ever.
// Lets the host tell RX loss (CMD never arrived) from TX loss (RSP vanished).
static uint32_t s_cmds_handled = 0;
static uint32_t s_rsps_sent = 0;

void count_cmd() { s_cmds_handled++; }
void count_rsp() { s_rsps_sent++; }

// R18 instrumentation (see note_rsp_tx in the header)
static uint32_t s_rsp_tx_max_us = 0;
static uint32_t s_tx_bails = 0;
static uint32_t s_hang_phase = 0; // breadcrumb from the boot BEFORE a watchdog reset

void capture_hang_phase(bool wdt_reset) {
    uint32_t crumb = watchdog_hw->scratch[0];
    if (wdt_reset && (crumb & 0xFFFFFF00u) == 0x18BEEF00u) {
        s_hang_phase = crumb & 0xFFu;
    }
    watchdog_hw->scratch[0] = 0; // never re-report a stale crumb
}

void note_rsp_tx(uint32_t us, bool bailed) {
    if (us > s_rsp_tx_max_us) {
        s_rsp_tx_max_us = us;
    }
    if (bailed) {
        s_tx_bails++;
    }
}

static String _json(JsonDocument &d) {
    String out;
    serializeJson(d, out);
    return out;
}

static String _ok() {
    JsonDocument d;
    d["status"] = "ok";
    return _json(d);
}

static String _err(const char *msg, const char *code) {
    JsonDocument d;
    d["error"] = msg;
    d["code"] = code;
    return _json(d);
}

// TEST_STATE[|FULL] — read-only dump. FULL adds the startup preset name, which
// costs a presets.json flash read; the plain form is safe to poll while recording.
static String _state(bool full) {
    JsonDocument d;
    d["status"] = "ok";
    d["built"] = FW_BUILD_DATE; // harness parity with the PING ack (fw-build-date check)
    d["recording"] = loop_manager.is_recording;
    d["recording_pad"] = loop_manager.recording_pad;
    d["armed"] = loop_manager.recording_is_armed;
    d["any_playing"] = loop_manager.any_loop_playing;
    d["clock_playing"] = clock_.is_playing;
    d["clock_ticks"] = clock_.midi_ticks_elapsed; // == master song tick (spec anchor invariant)
    d["tick_pending"] = clock_.first_tick_pending; // downbeat swallow armed (Start/Continue)
    d["bpm"] = clock_.bpm_current;
    d["midi_sync"] = settings.midi_sync;
    d["midi_transport"] = settings.midi_transport;
    d["record_cc"] = settings.record_cc;
    d["channel_out"] = settings.midi_channel_out;
    d["total_events"] = loop_manager.total_events_count;
    d["next_loop_id"] = settings.next_loop_id; // churn test: IDs mustn't burn on remove (item 14)
    d["heap_free"] = rp2040.getFreeHeap();
    d["uptime_ms"] = ticks::ticks_ms();
    d["loop_max_us"] = s_loop_max_us; // worst loop() gap since last TEST_STATE
    d["loop_iters"] = s_loop_iters;
    s_loop_max_us = 0;
    s_loop_iters = 0;
    d["cmds"] = s_cmds_handled; // lifetime counters, never reset
    d["rsps"] = s_rsps_sent;
    d["rsp_tx_max_us"] = s_rsp_tx_max_us; // worst _rsp() CDC TX since last TEST_STATE (R18)
    s_rsp_tx_max_us = 0;
    d["tx_bails"] = s_tx_bails; // lifetime bounded-TX bail-outs (R18)
    d["hang_phase"] = s_hang_phase; // R18_MARK crumb from the pass a prior watchdog reset killed (0 = none)
    d["play_mode"] = settings.get_play_mode();
    d["midi_type"] = settings.midi_type; // string-whitelist validation observable (Q4)
    d["clock_source"] = settings.clock_source;
    d["passthru"] = settings.passthru_mode;
    d["channel_in"] = settings.midi_channel_in;
    d["velocity_mapped"] = settings.velocity_mapped; // single-note velocity map active
    d["web_locked"] = serial_handler.is_locked(); // web-config seize state (PING lock)
    d["menu_idx"] = Menu::current_idx;
    d["pressed"] = inputs.pressed_count;
    d["arp_notes"] = arpeggiator.total_notes; // sourced note count (held pads)
    d["arp_ccs"] = arpeggiator.total_ccs;
    d["bank_idx"] = (settings.scale_idx == 0) ? settings.midibank_idx
                                              : settings.scalenotes_idx;
    if (full) {
        d["preset"] = settings.get_startup_preset();
    }

    JsonArray loops = d["loops"].to<JsonArray>();
    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        MidiLoop *lp = loop_manager.loops[i];
        if (lp == nullptr) {
            continue;
        }
        JsonObject o = loops.add<JsonObject>();
        o["pad"] = i;
        o["type"] = lp->loop_type;
        o["playing"] = lp->loop_is_playing;
        o["queued"] = loop_manager.play_queue[i];
        o["total_ticks"] = lp->total_midi_ticks; // quantize_loop() target (nearest bar/unit)
        o["notes_on"] = lp->notes_on.size();
        o["notes_off"] = lp->notes_off.size();
        o["ccs"] = lp->cc_events.size();
        o["ats"] = lp->aftertouch_events.size();
        o["unique_ccs"] = lp->cached_unique_ccs.size(); // arp CC source (R2)
        o["max_reached"] = lp->max_events_reached;
    }
    return _json(d);
}

String handle(const String &cmd) {
    if (cmd == "TEST_STATE") {
        return _state(false);
    }
    if (cmd == "TEST_STATE|FULL") {
        return _state(true);
    }

    if (cmd.startsWith("TEST_RECORD|")) {
        int pad = cmd.substring(12).toInt();
        if (pad < 0 || pad >= C::NUM_PADS) {
            return _err("Bad pad index", "bad_pad");
        }
        // add_remove_loop() on an occupied pad REMOVES the loop — require an
        // empty pad so this command can only ever start a recording.
        if (loop_manager.loops[pad] != nullptr) {
            return _err("Pad already has a loop", "pad_occupied");
        }
        loop_manager.add_remove_loop((uint8_t)pad);
        if (!loop_manager.is_recording) {
            return _err("Recording did not start (event limit?)", "record_failed");
        }
        return _ok();
    }

    if (cmd == "TEST_STOP_RECORD") {
        if (!loop_manager.is_recording) {
            return _err("Not recording", "not_recording");
        }
        loop_manager.handle_fn_press(); // same call as a physical FN press
        return _ok();
    }

    if (cmd.startsWith("TEST_PLAY|") || cmd.startsWith("TEST_STOP|")) {
        bool play = cmd.startsWith("TEST_PLAY|");
        int pad = cmd.substring(10).toInt();
        if (pad < 0 || pad >= C::NUM_PADS || loop_manager.loops[pad] == nullptr) {
            return _err("No loop on pad", "no_loop");
        }
        if (loop_manager.is_recording) {
            return _err("Recording in progress", "recording");
        }
        loop_manager.toggle_loop_playstate((uint8_t)pad, play, !play);
        return _ok();
    }

    if (cmd.startsWith("TEST_TOGGLE|")) {
        // Plain toggle — the same semantics as a user pad press (queues under
        // midi_sync with a stopped clock, unlike TEST_PLAY's force_play).
        int pad = cmd.substring(12).toInt();
        if (pad < 0 || pad >= C::NUM_PADS || loop_manager.loops[pad] == nullptr) {
            return _err("No loop on pad", "no_loop");
        }
        if (loop_manager.is_recording) {
            return _err("Recording in progress", "recording");
        }
        loop_manager.toggle_loop_playstate((uint8_t)pad);
        return _ok();
    }

    if (cmd == "TEST_STOP_ALL") {
        loop_manager.stop_all_loops();
        return _ok();
    }

    if (cmd.startsWith("TEST_CLEAR|")) {
        int pad = cmd.substring(11).toInt();
        if (pad < 0 || pad >= C::NUM_PADS || loop_manager.loops[pad] == nullptr) {
            return _err("No loop on pad", "no_loop");
        }
        if (loop_manager.is_recording && loop_manager.recording_pad != pad) {
            return _err("Recording on another pad", "recording");
        }
        loop_manager.add_remove_loop((uint8_t)pad); // occupied pad -> remove
        return _ok();
    }

    if (cmd == "TEST_CLEAR_ALL") {
        if (loop_manager.is_recording) {
            loop_manager.handle_fn_press(); // finalize (empty loops get removed)
        }
        for (uint8_t i = 0; i < C::NUM_PADS; i++) {
            if (loop_manager.loops[i] != nullptr) {
                loop_manager.add_remove_loop(i);
            }
        }
        return _ok();
    }

    if (cmd.startsWith("TEST_LOOP_TYPE|")) {
        String t = cmd.substring(15);
        if (t != "loop" && t != "oneshot" && t != "hold") {
            return _err("Bad loop type", "bad_type");
        }
        settings.loop_type = t; // applied to loops created from now on
        return _ok();
    }

    if (cmd.startsWith("TEST_MIDI_SYNC|")) {
        bool v = cmd.substring(15).toInt() != 0;
        settings.midi_sync = v;
        loop_manager.handle_midi_sync_change(); // same as the settings-menu toggle
        return _ok();
    }

    if (cmd.startsWith("TEST_TRANSPORT|")) { // on/off — same path as the settings menu
        String v = cmd.substring(15);
        if (v != "on" && v != "off") {
            return _err("Usage: TEST_TRANSPORT|on/off", "bad_args");
        }
        // Message mode must see a real MIDI Start — never inherit the free-run latch
        // (mirrors apply_midi_option case 12).
        if (v == "on" && settings.midi_transport == "off") {
            clock_.stop_clock();
        }
        settings.midi_transport = v;
        return _ok();
    }

    // TEST_PAD|<pad>|<1/0> — virtual pad press/release. Consumed by the next
    // input pass exactly like a pedal event, so it drives the REAL pipeline
    // (encoder-arp add/remove, flush-on-release, play-mode dispatch).
    if (cmd.startsWith("TEST_PAD|")) {
        int sep = cmd.indexOf('|', 9);
        if (sep < 0) {
            return _err("Usage: TEST_PAD|pad|1/0", "bad_args");
        }
        int pad = cmd.substring(9, sep).toInt();
        if (pad < 0 || pad >= C::NUM_PADS) {
            return _err("Bad pad index", "bad_pad");
        }
        inputs.test_inject_pad((uint8_t)pad, cmd.substring(sep + 1).toInt() != 0);
        return _ok();
    }

    // TEST_ENCODER|<delta> — virtual encoder detents (positive = clockwise).
    // Merged with the hardware count on the next slow input pass (20 ms poll).
    if (cmd.startsWith("TEST_ENCODER|")) {
        int delta = cmd.substring(13).toInt();
        if (delta == 0) {
            return _err("Zero delta", "bad_args");
        }
        inputs.test_inject_encoder(delta);
        return _ok();
    }

    // TEST_MENU|<idx> — jump straight to a menu (0=PLAY, 2=MIDI, ...), the same
    // call the FN+pad jump uses.
    if (cmd.startsWith("TEST_MENU|")) {
        int idx = cmd.substring(10).toInt();
        if (idx < 0 || idx >= Menu::num_menus) {
            return _err("Bad menu index", "bad_menu");
        }
        Menu::next_or_prev_menu(true, idx);
        return _ok();
    }

    if (cmd.startsWith("TEST_PLAY_MODE|")) {
        String mode = cmd.substring(15);
        if (mode != "loop" && mode != "encoder" && mode != "velocity") {
            return _err("Bad play mode", "bad_mode");
        }
        settings.set_play_mode(mode);
        // Mirror the device-side toggle (inputs.cpp): encoder mode locks the play
        // menu so bare encoder turns feed the arp instead of the menu action.
        if (Menu::current_idx == C::MENU_PLAY) {
            Menu::toggle_lock_mode(mode == "encoder");
        }
        return _ok();
    }

    // TEST_BANK|<1/0> — bank up/down via the real handler (held-pad note-offs +
    // CC123 all-notes-off; the CC120-127 dedup bypass under test is item R1).
    if (cmd.startsWith("TEST_BANK|")) {
        midi.change_bank(cmd.substring(10).toInt() != 0);
        return _ok();
    }

    // TEST_QUANTIZE|<time>|<strength>[|<loop>] — e.g. TEST_QUANTIZE|1/8|100|none.
    // Applied to recordings finalized from now on (quantize runs at record stop).
    if (cmd.startsWith("TEST_QUANTIZE|")) {
        String rest = cmd.substring(14);
        int sep = rest.indexOf('|');
        if (sep < 0) {
            return _err("Usage: TEST_QUANTIZE|time|strength[|loop]", "bad_args");
        }
        String qtime = rest.substring(0, sep);
        String rest2 = rest.substring(sep + 1);
        int sep2 = rest2.indexOf('|');
        int strength = (sep2 < 0 ? rest2 : rest2.substring(0, sep2)).toInt();
        if (qtime != "none" && qtime != "1" && qtime != "1/2" && qtime != "1/4" &&
            qtime != "1/8" && qtime != "1/16" && qtime != "1/32" && qtime != "1/64") {
            return _err("Bad quantize time", "bad_args");
        }
        settings.quantize_time = qtime;
        settings.quantize_strength = max(0, min(100, strength));
        if (sep2 >= 0) {
            settings.quantize_loop = rest2.substring(sep2 + 1);
        }
        return _ok();
    }

    // TEST_ARP_CONFIG|<poly 1/0>[|<length>[|<type>]] — e.g. TEST_ARP_CONFIG|0|1/8|rand oct up
    if (cmd.startsWith("TEST_ARP_CONFIG|")) {
        String rest = cmd.substring(16);
        int sep = rest.indexOf('|');
        String poly = (sep < 0) ? rest : rest.substring(0, sep);
        settings.arp_is_polyphonic = poly.toInt() != 0;
        if (sep >= 0) {
            String rest2 = rest.substring(sep + 1);
            int sep2 = rest2.indexOf('|');
            settings.arpeggiator_length = (sep2 < 0) ? rest2 : rest2.substring(0, sep2);
            if (sep2 >= 0) {
                String t = rest2.substring(sep2 + 1);
                if (t != "up" && t != "down" && t != "random" && t != "rand oct up" &&
                    t != "rand oct dn" && t != "rnd st up" && t != "rnd st dn") {
                    return _err("Bad arp type", "bad_args");
                }
                settings.arpeggiator_type = t; // same values as the settings menu list
            }
        }
        return _ok();
    }

    if (cmd.startsWith("TEST_LOAD_PRESET|")) {
        String name = cmd.substring(17);
        bool found = false;
        for (const String &p : settings.get_preset_names_list()) {
            if (p == name) {
                found = true;
                break;
            }
        }
        if (!found) {
            return _err("Preset not found", "no_preset");
        }
        // Same path as the preset menu: persist selection, then reboot.
        // Deferred so the RSP reaches the host before the CDC port drops.
        s_pending_preset = name;
        s_reboot_pending = true;
        JsonDocument d;
        d["status"] = "ok";
        d["rebooting"] = true;
        return _json(d);
    }

    if (cmd.startsWith("TEST_SAVE_PRESET|")) {
        // Same path as the device menu save: settings + recorded loops -> flash
        // (loop .bin write, atomic presets.json write, orphan cleanup). Also sets
        // the startup preset to `name`, exactly like a menu save.
        String name = cmd.substring(17);
        if (name.length() == 0) {
            return _err("Empty preset name", "bad_name");
        }
        if (loop_manager.is_recording) {
            return _err("Recording in progress", "recording");
        }
        SaveResult saved = settings.save_preset_to_file(name);
        if (saved == SaveResult::LimitReached) {
            return _err("Save refused (preset cap reached)", "save_failed");
        }
        if (saved == SaveResult::FileUnreadable) {
            // presets.json exists but won't parse (fix 5) — see TEST_CORRUPT_PRESETS_FILE.
            return _err("presets.json unreadable", "file_unreadable");
        }
        return _ok();
    }

    if (cmd.startsWith("TEST_DELETE_PRESET|")) {
        String name = cmd.substring(19);
        if (!settings.delete_preset(name)) {
            return _err("Delete refused (missing, reserved, or startup preset)",
                        "delete_failed");
        }
        return _ok();
    }

    if (cmd == "TEST_WIPE_PRESETS_FILE") {
        // Simulate a factory-fresh unit: no presets.json at all (the state every
        // shipped unit is in until its first on-device save). Lets the suite prove
        // the web-config handshake works out of the box (Aug 2026 customer bug).
        // RAM settings are untouched; the caller restores fixtures afterwards.
        JsonDocument d;
        d["status"] = "ok";
        d["existed"] = LittleFS.remove(C::PRESETS_FILEPATH);
        LittleFS.remove(C::PRESETS_TMP_FILEPATH);
        return _json(d);
    }

    if (cmd.startsWith("TEST_PRESETS_RAW|")) {
        // TEST_PRESETS_RAW|<offset>|<done 0/1>|<base64> — write presets.json BYTE-EXACT from
        // the host, chunked like PUT_LOOP_FILE_CHUNK (offset 0 truncates, later chunks append
        // and must land at the current size). Exists so the compat corpus can put a file on
        // flash exactly as an OLDER firmware left it — SET_PRESET would re-serialize it — and
        // then prove two things across a reboot: the new firmware reads it correctly, and it
        // does NOT rewrite the file unasked (Derrick, 2026-09-14: updates must never touch
        // customer presets unless the user saves). The tmp file goes on the first chunk so
        // boot-side recovery can't promote a stale copy over the fixture. RAM settings are
        // untouched; the harness restores with TEST_WIPE_PRESETS_FILE + SET_PRESET afterwards.
        int p1 = cmd.indexOf('|', 17);
        int p2 = (p1 < 0) ? -1 : cmd.indexOf('|', p1 + 1);
        if (p1 < 0 || p2 < 0) {
            return _err("Bad args", "bad_args");
        }
        int offset = cmd.substring(17, p1).toInt();
        bool done = cmd.substring(p1 + 1, p2).toInt() != 0;
        String b64 = cmd.substring(p2 + 1);
        uint8_t data[512];
        int n = b64.length() ? cfg_base64_decode(b64, data, sizeof(data)) : 0;
        if (n < 0 || offset < 0) {
            return _err("Invalid base64", "invalid_data");
        }
        if (offset == 0) {
            LittleFS.remove(C::PRESETS_TMP_FILEPATH);
        }
        File f = LittleFS.open(C::PRESETS_FILEPATH, offset == 0 ? "w" : "a");
        if (!f) {
            return _err("Could not open presets.json for writing", "fs_error");
        }
        if (offset > 0 && (int)f.size() != offset) {
            f.close();
            return _err("Bad offset", "bad_offset");
        }
        bool wrote = (n == 0) || ((int)f.write(data, n) == n);
        size_t size = f.size();
        f.close();
        rp2040.wdt_reset();
        if (!wrote) {
            return _err("Write failed", "io_error");
        }
        JsonDocument d;
        d["status"] = "ok";
        d["size"] = (int)size;
        d["done"] = done;
        return _json(d);
    }

    if (cmd == "TEST_CORRUPT_PRESETS_FILE") {
        // Overwrite presets.json with truncated JSON so it EXISTS but won't parse — the
        // state a power cut mid-write, a bad backup upload, or a NoMemory parse leaves
        // behind. Exists to prove the save-path refusal (fix 5): TEST_SAVE_PRESET must
        // answer code "file_unreadable" instead of rewriting the file with only the new
        // preset and orphan-sweeping every other preset's loop files. The tmp file goes
        // too, so boot-side recovery can't quietly promote a good copy over the damage.
        // RAM settings are untouched; the harness restores with TEST_WIPE_PRESETS_FILE +
        // SET_PRESET afterwards.
        static const char kTruncated[] = "{\"STARTUP_PRESET\":\"T_MULTI\",";
        LittleFS.remove(C::PRESETS_TMP_FILEPATH);
        File f = LittleFS.open(C::PRESETS_FILEPATH, "w");
        if (!f) {
            return _err("Could not open presets.json for writing", "fs_error");
        }
        size_t n = f.write((const uint8_t *)kTruncated, sizeof(kTruncated) - 1);
        f.close();
        rp2040.wdt_reset();
        JsonDocument d;
        d["status"] = "ok";
        d["bytes"] = (int)n;
        return _json(d);
    }

    if (cmd == "TEST_FS_BENCH") {
        // Per-operation filesystem timings (all values in us). Answers "which file op
        // is slow": create-vs-rewrite-vs-remove-vs-rename, ~presets.json-sized
        // payload. Uses throwaway files in /; cleans up after itself.
        JsonDocument d;
        String payload;
        payload.reserve(4096);
        while (payload.length() < 4096) {
            payload += "0123456789abcdef";
        }
        LittleFS.remove("/bench_a.bin"); // known-clean start
        LittleFS.remove("/bench_t.bin");
        rp2040.wdt_reset();

        uint32_t t = micros();
        { File f = LittleFS.open("/bench_a.bin", "w"); f.write((const uint8_t *)payload.c_str(), payload.length()); f.close(); }
        d["create_4k_us"] = micros() - t; // fresh file: create + data + close
        rp2040.wdt_reset();

        t = micros();
        { File f = LittleFS.open("/bench_a.bin", "w"); f.write((const uint8_t *)payload.c_str(), payload.length()); f.close(); }
        d["rewrite_4k_us"] = micros() - t; // existing file truncated in place
        rp2040.wdt_reset();

        t = micros();
        { File f = LittleFS.open("/bench_t.bin", "w"); f.write((const uint8_t *)payload.c_str(), payload.length()); f.close(); }
        uint32_t t2 = micros();
        d["tmp_create_4k_us"] = t2 - t;
        LittleFS.remove("/bench_a.bin");
        uint32_t t3 = micros();
        d["remove_us"] = t3 - t2;
        LittleFS.rename("/bench_t.bin", "/bench_a.bin");
        d["rename_us"] = micros() - t3; // tmp+remove+rename = the atomic-write pattern
        rp2040.wdt_reset();

        t = micros();
        { File f = LittleFS.open("/bench_s.bin", "w"); f.write((const uint8_t *)"x", 1); f.close(); }
        d["create_1b_us"] = micros() - t; // fixed per-file cost, no data to speak of
        rp2040.wdt_reset();

        t = micros();
        d["remove_missing_us"] = 0;
        LittleFS.remove("/bench_none.bin");
        d["remove_missing_us"] = micros() - t; // failed remove (dir lookup only)

        LittleFS.remove("/bench_s.bin");
        LittleFS.remove("/bench_a.bin");
        rp2040.wdt_reset();
        d["status"] = "ok";
        return _json(d);
    }

    if (cmd == "TEST_REBOOT") {
        s_reboot_pending = true;
        JsonDocument d;
        d["status"] = "ok";
        d["rebooting"] = true;
        return _json(d);
    }

    // TEST_PIXELS — read-only dump of the LOGICAL pixel state machine (shadow color,
    // blink flag + color, flash pending) per pad, plus FN/encoder and the palette
    // constants, so the harness asserts states without hardcoding RGB values.
    // Blinking pads' shadow alternates with blink_phase — assert blink+bc, not c.
    if (cmd == "TEST_PIXELS") {
        JsonDocument d;
        d["status"] = "ok";
        auto hex = [](C::Rgb c) {
            char buf[7];
            snprintf(buf, sizeof(buf), "%02X%02X%02X", c.r, c.g, c.b);
            return String(buf);
        };
        JsonObject pal = d["palette"].to<JsonObject>();
        pal["black"] = hex(C::BLACK);
        pal["recording"] = hex(C::RED); // solid while recording, blinking while armed
        pal["loop"] = hex(C::LOOP_COLOR);
        pal["playing"] = hex(C::PIXEL_LOOP_PLAYING_COLOR);
        JsonArray pads = d["pads"].to<JsonArray>();
        for (uint8_t i = 0; i < C::NUM_PADS; i++) {
            JsonObject o = pads.add<JsonObject>();
            o["c"] = hex(pixels.test_shadow(i));
            o["blink"] = pixels.test_blinking(i);
            o["bc"] = hex(pixels.test_blink_color(i));
            o["flash"] = pixels.test_flash_active(i);
        }
        d["fn"] = hex(pixels.test_shadow(C::FN_LED_IDX));
        d["enc"] = hex(pixels.test_shadow(C::ENC_LED_IDX));
        // Pedal LEDs render loop STATE only (never note/CC activity) — report the state
        // enum the strip was last rendered from, not a color, so the assertion is about
        // the filter itself. Polled every 20 ms, so allow that much settle after a change.
        JsonObject ped = d["pedals"].to<JsonObject>();
        ped["bank"] = pedals.current_bank;
        JsonArray pl = ped["pads"].to<JsonArray>();
        static const char *const kNames[] = {"none", "loop", "playing", "queued", "recording", "armed"};
        for (uint8_t i = 0; i < C::PEDAL_COUNT; i++) {
            JsonObject o = pl.add<JsonObject>();
            o["pad"] = pedals.bank_offset + i;
            o["state"] = kNames[(uint8_t)pedals.test_state(i)];
        }
        return _json(d);
    }

    // TEST_PEDAL_BANK|<0-2> — switch the pedal bank (the glove GPIO can't be driven by the
    // harness). Same entry point the glove buttons use.
    if (cmd.startsWith("TEST_PEDAL_BANK|")) {
        int bank = cmd.substring(16).toInt();
        if (bank < 0 || bank > 2) {
            return _err("Bad bank (0-2)", "bad_args");
        }
        pedals.set_pedal_bank(bank);
        return _ok();
    }

    // TEST_DIN|<hex> — queue raw bytes (e.g. "FAF8F8" or "90 3C 64") for the AUX/DIN
    // input: consumed by the REAL UART running-status parser on the next MIDI drain,
    // so clock arbitration, channel filter and passthru all see a genuine DIN source.
    // Needs an AUX-receivable midi_type (see TEST_MIDI_CFG) for the drain to run.
    if (cmd.startsWith("TEST_DIN|")) {
        String hexstr = cmd.substring(9);
        uint8_t bytes[128];
        size_t n = 0;
        int hi = -1;
        for (size_t i = 0; i < hexstr.length(); i++) {
            char c = hexstr[i];
            if (c == ' ') {
                continue;
            }
            int v = (c >= '0' && c <= '9')   ? c - '0'
                    : (c >= 'A' && c <= 'F') ? c - 'A' + 10
                    : (c >= 'a' && c <= 'f') ? c - 'a' + 10
                                             : -1;
            if (v < 0) {
                return _err("Bad hex", "bad_args");
            }
            if (hi < 0) {
                hi = v;
            } else {
                if (n >= sizeof(bytes)) {
                    return _err("Too many bytes (max 128 per command)", "bad_args");
                }
                bytes[n++] = (uint8_t)((hi << 4) | v);
                hi = -1;
            }
        }
        if (hi >= 0 || n == 0) {
            return _err("Odd or empty hex string", "bad_args");
        }
        size_t queued = midi.test_inject_din(bytes, n);
        if (queued < n) {
            return _err("DIN inject buffer full", "din_overflow");
        }
        JsonDocument d;
        d["status"] = "ok";
        d["queued"] = (int)queued;
        return _json(d);
    }

    // TEST_MIDI_CFG|<midi_type>|<clock_source> — runtime equivalents of the two
    // preset fields the clock tests otherwise need a reboot to change. Both are
    // read live at every use (should_receive / should_accept_clock).
    if (cmd.startsWith("TEST_MIDI_CFG|")) {
        String rest = cmd.substring(14);
        int sep = rest.indexOf('|');
        if (sep < 0) {
            return _err("Usage: TEST_MIDI_CFG|type|clock_source", "bad_args");
        }
        String t = rest.substring(0, sep);
        String cs = rest.substring(sep + 1);
        if (t != "USB" && t != "AUX" && t != "ALL") {
            return _err("Bad midi_type", "bad_args");
        }
        if (cs != "USB" && cs != "AUX") {
            return _err("Bad clock_source", "bad_args");
        }
        settings.midi_type = t;
        settings.clock_source = cs;
        return _ok();
    }

    if (cmd.startsWith("TEST_PASSTHRU|")) { // off/aux/usb/all — read live per drain pass
        String m = cmd.substring(14);
        if (m != "off" && m != "aux" && m != "usb" && m != "all") {
            return _err("Bad passthru mode", "bad_args");
        }
        settings.passthru_mode = m;
        return _ok();
    }

    if (cmd.startsWith("TEST_CHANNEL_IN|")) { // -1 = ALL, 0-15 — the RX channel filter
        int ch = cmd.substring(16).toInt();
        if (ch < -1 || ch > 15) {
            return _err("Bad channel", "bad_args");
        }
        settings.midi_channel_in = ch;
        return _ok();
    }

    if (cmd.startsWith("TEST_RECORD_CC|")) {
        settings.record_cc = cmd.substring(15).toInt() != 0;
        return _ok();
    }

    // TEST_PAD_CHANNEL|<pad>|<ch> — per-pad output channel mapping via the same
    // public API the settings menu calls (-2 global, -1 as-recorded, 0-15 fixed).
    if (cmd.startsWith("TEST_PAD_CHANNEL|")) {
        String rest = cmd.substring(17);
        int sep = rest.indexOf('|');
        if (sep < 0) {
            return _err("Usage: TEST_PAD_CHANNEL|pad|ch", "bad_args");
        }
        int pad = rest.substring(0, sep).toInt();
        int ch = rest.substring(sep + 1).toInt();
        if (pad < 0 || pad >= C::NUM_PADS || ch < C::PAD_CH_GLOBAL || ch > 15) {
            return _err("Bad pad or channel", "bad_args");
        }
        midi.set_midi_channel_for_pad((uint8_t)pad, (int8_t)ch);
        return _ok();
    }

    // TEST_VELOCITY_MODE|<pad> — toggle single-note velocity mapping, delegating to
    // the same handler an FN+pad press runs in velocity play mode.
    if (cmd.startsWith("TEST_VELOCITY_MODE|")) {
        int pad = cmd.substring(19).toInt();
        if (pad < 0 || pad >= C::NUM_PADS) {
            return _err("Bad pad index", "bad_pad");
        }
        inputs.handle_velocity_mode((uint8_t)pad);
        JsonDocument d;
        d["status"] = "ok";
        d["velocity_mapped"] = settings.velocity_mapped;
        return _json(d);
    }

    return _err("Unknown TEST command", "unknown_command");
}

void after_response() {
    if (!s_reboot_pending) {
        return;
    }
    Serial.flush();
    delay(100); // let the host read the ack before USB drops
    // Same pre-reboot silence as the preset menu (fix 2), run BEFORE the preset switch
    // mutates the channel routing so every loop's offs still resolve through the settings
    // its notes went out with — the harness captures these offs across TEST_LOAD_PRESET.
    // (The menu path silences after its load succeeds because a failed load must not stop
    // the set; here the reboot is unconditional, so the order is free.)
    silence_for_reboot();
    if (s_pending_preset.length()) {
        settings.load_preset(s_pending_preset);
    }
    rp2040.reboot();
}

} // namespace test_hooks

#endif // LOOPSTER_TEST_HOOKS
