#include "test_hooks.h"

#ifdef LOOPSTER_TEST_HOOKS

#include <ArduinoJson.h>
#include <LittleFS.h>
#include "loopmanager.h"
#include "settings.h"
#include "clock.h"
#include "ticks.h"
#include "inputs.h"
#include "menus.h"
#include "fw_version.h"
#include "midi.h"
#include "arp.h"

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

    // TEST_ARP_CONFIG|<poly 1/0>[|<length>] — e.g. TEST_ARP_CONFIG|0|1/8
    if (cmd.startsWith("TEST_ARP_CONFIG|")) {
        String rest = cmd.substring(16);
        int sep = rest.indexOf('|');
        String poly = (sep < 0) ? rest : rest.substring(0, sep);
        settings.arp_is_polyphonic = poly.toInt() != 0;
        if (sep >= 0) {
            settings.arpeggiator_length = rest.substring(sep + 1);
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
        if (!settings.save_preset_to_file(name)) {
            return _err("Save refused (preset cap reached?)", "save_failed");
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

    return _err("Unknown TEST command", "unknown_command");
}

void after_response() {
    if (!s_reboot_pending) {
        return;
    }
    Serial.flush();
    delay(100); // let the host read the ack before USB drops
    if (s_pending_preset.length()) {
        settings.load_preset(s_pending_preset);
    }
    rp2040.reboot();
}

} // namespace test_hooks

#endif // LOOPSTER_TEST_HOOKS
