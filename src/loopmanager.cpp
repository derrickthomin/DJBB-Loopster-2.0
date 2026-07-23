#include "loopmanager.h"
#include <LittleFS.h>
#include "display.h"
#include "pixels.h"
#include "pedals.h"
#include "settings.h"
#include "settingsmenu.h"
#include "clock.h"
#include "loop_storage.h"
#include "midi.h"
#include "ticks.h"
#include "profiling.h"

LoopManager loop_manager;

// ---- hooks registered with other modules ----

static void _settings_save_loops(JsonObject &preset_settings) {
    loop_manager.save_loops_to_preset(preset_settings);
}

static PadLoopState _pedals_loop_state(uint8_t pad_idx) {
    if (pad_idx >= C::NUM_PADS || loop_manager.loops[pad_idx] == nullptr) {
        return PadLoopState::None;
    }
    return loop_manager.loops[pad_idx]->loop_is_playing ? PadLoopState::Playing : PadLoopState::HasLoop;
}

static void _oneshot_refresh() {
    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        if (loop_manager.loops[i] && loop_manager.loops[i]->loop_type == "oneshot") {
            loop_manager.loops[i]->ensure_oneshot_notes();
        }
    }
}

// ---- LoopManager ----

void LoopManager::add_remove_loop(uint8_t pad_idx) {
    settings.mark_dirty(); // loops are preset content
    // Add
    if (loops[pad_idx] == nullptr && recording_pad == -1) {
        _create_new_loop(pad_idx);
    }
    // Switch recording pad
    else if (loops[pad_idx] == nullptr && recording_pad != -1 && recording_pad != pad_idx) {
        MidiLoop *current_loop = loops[recording_pad];
        if (!current_loop->has_events()) {
            _remove_loop(recording_pad);
        } else {
            // Finalize BEFORE counting: trim_silence() both removes leading note-offs and
            // synthesizes missing ones, so counting first drifts the global budget (R3;
            // handle_fn_press has the correct order).
            current_loop->toggle_record_state(0);
            total_events_count += current_loop->count_events();
            pixels.set_blink(recording_pad, false);
        }
        _create_new_loop(pad_idx);
    }
    // Remove
    else if (recording_pad == pad_idx || !is_recording) {
        _remove_loop(pad_idx);
    }
}

void LoopManager::_create_new_loop(uint8_t pad_idx) {
    // If we bail before a loop is created, clear recording ownership (item 12). In the
    // switch-recording branch of add_remove_loop the previous loop was already finalized and
    // recording_pad still points at it; leaving that stale means a later FN press re-runs the
    // full stop path on an already-finalized loop (double quantize, wasted loop_id).
    if (total_events_count >= C::TOTAL_LOOP_EVENTS_LIMIT) {
        display.show_notification("Max Events Reached");
        recording_pad = -1;
        is_recording = false;
        recording_is_armed = false;
        return;
    }
    // Secondary guard (item 1): refuse a new recording if free heap is already below the
    // recording floor. Sized (72 KB) from on-device data so that even a maxed loop's growth
    // can't drop the heap into the ~55 KB fragmentation-panic zone — an over-full instrument
    // shows "Low Memory" instead of panicking (and relying on the watchdog to recover).
    if (rp2040.getFreeHeap() < C::RECORDING_HEAP_FLOOR_BYTES) {
        display.show_notification("Low Memory");
        recording_pad = -1;
        is_recording = false;
        recording_is_armed = false;
        return;
    }

    loops[pad_idx] = make_midi_loop(settings.loop_type.c_str(), pad_idx);
    recording_pad = pad_idx;
    is_recording = true;

    pixels.set_default_color(pad_idx, C::LOOP_COLOR, true);

    // Arm recording if midi sync enabled but clock not playing
    if (settings.midi_sync && !clock_.is_playing) {
        recording_is_armed = true;
        pixels.set_blink(pad_idx, true, C::RED); // blinking red = armed/waiting
    } else {
        recording_is_armed = false;
        loops[pad_idx]->toggle_record_state();
        // Solid red for active recording
        pixels.set_blink(pad_idx, false);
        pixels.set_default_color(pad_idx, C::RED, true);
        pixels.set_color(pad_idx, C::RED);
    }
}

void LoopManager::_remove_loop(uint8_t pad_idx) {
    if (loops[pad_idx] != nullptr) {
        uint32_t removed = loops[pad_idx]->count_events();
        total_events_count = (total_events_count >= removed) ? total_events_count - removed : 0;
        loops[pad_idx]->clear();
        delete loops[pad_idx];
        loops[pad_idx] = nullptr;
    }
    recording_pad = -1;
    play_queue[pad_idx] = false;
    is_recording = false;
    recording_is_armed = false;
    pixels.set_default_color(pad_idx);
    pixels.set_blink(pad_idx, false);
}

void LoopManager::check_event_limits() {
    if (recording_pad == -1) {
        return;
    }
    if (loops[recording_pad] == nullptr) { // invariant insurance (R9b)
        recording_pad = -1;
        is_recording = false;
        recording_is_armed = false;
        return;
    }
    if (loops[recording_pad]->max_events_reached) {
        handle_fn_press();
    }
}

void LoopManager::handle_fn_press(const char *action_type) {
    if (!strcmp(action_type, "press") && is_recording) {
        if (recording_pad < 0 || loops[recording_pad] == nullptr) { // invariant insurance (R9b)
            recording_pad = -1;
            is_recording = false;
            recording_is_armed = false;
            return;
        }
        int pad_idx = recording_pad;
        MidiLoop *current_loop = loops[pad_idx];
        recording_is_armed = false;
        current_loop->toggle_record_state(0);
        pixels.set_blink(pad_idx, false);

        // Remove empty loop
        if (!current_loop->has_events()) {
            _remove_loop(pad_idx);
            return;
        }

        total_events_count += current_loop->count_events();

        // Hold mode: start in stopped state
        if (current_loop->loop_type == "hold") {
            current_loop->toggle_playstate(0);
            pixels.set_blink(pad_idx, false);
            pixels.set_color(pad_idx, C::LOOP_COLOR);
            pixels.set_default_color(pad_idx, C::LOOP_COLOR, true);
            recording_pad = -1;
            is_recording = false;
            return;
        }

        if (settings.midi_sync) {
            play_queue[pad_idx] = true;
            if (clock_.is_playing) {
                current_loop->toggle_playstate(1);
                pixels.set_color(pad_idx, C::PIXEL_LOOP_PLAYING_COLOR);
                pixels.set_default_color(pad_idx, C::PIXEL_LOOP_PLAYING_COLOR, true);
            } else {
                pixels.set_blink(pad_idx, true, C::PIXEL_LOOP_PLAYING_COLOR);
            }
        } else {
            if (!current_loop->loop_is_playing) {
                current_loop->toggle_playstate(1);
            }
            pixels.set_color(pad_idx, C::PIXEL_LOOP_PLAYING_COLOR);
            pixels.set_default_color(pad_idx, C::PIXEL_LOOP_PLAYING_COLOR, true);
        }

        recording_pad = -1;
        is_recording = false;
    }
}

void LoopManager::change_loop_mode(uint8_t button_idx, bool forward) {
    if (loops[button_idx] != nullptr) {
        settings.mark_dirty();
        String loop_type = loops[button_idx]->change_loop_mode(forward);
        loops[button_idx]->clear_notes_and_pixels();
        loops[button_idx]->toggle_playstate(0);
        play_queue[button_idx] = false;
        pixels.set_blink(button_idx, false);
        display_loop_mode(button_idx);
        if (loop_type != settings.loop_type) {
            settings.loop_type = loop_type;
        }
    }
}

void LoopManager::display_loop_mode(uint8_t idx) {
    if (loops[idx] != nullptr) {
        // 1-indexed pad number, matching the corrupt/skip messages
        display.show_notification("Pad " + String(idx + 1) + " Loop: " + loops[idx]->loop_type);
    }
}

void LoopManager::toggle_loop_playstate(uint8_t idx, bool force_play, bool force_stop) {
    if (is_recording || loops[idx] == nullptr) { // press is for a note if recording
        return;
    }

    if (force_play) {
        if (settings.midi_sync) {
            if (clock_.is_playing) {
                play_queue[idx] = true;
                _play_loop(idx, -1, true, 1);
            } else {
                _play_loop(idx, -1, false, 0);
            }
            pixels.set_blink(idx, false);
            pixels.set_color(idx, C::PIXEL_LOOP_PLAYING_COLOR);
            pixels.set_default_color(idx, C::PIXEL_LOOP_PLAYING_COLOR, true);
            return;
        }
        loops[idx]->toggle_playstate(1);
        play_queue[idx] = true;
        any_loop_playing = true; // direct start bypasses _play_loop's flag upkeep
        pixels.set_blink(idx, false);
        pixels.set_color(idx, C::PIXEL_LOOP_PLAYING_COLOR);
        pixels.set_default_color(idx, C::PIXEL_LOOP_PLAYING_COLOR, true);
        return;
    }

    if (force_stop) {
        loops[idx]->toggle_playstate(0);
        play_queue[idx] = false;
        pixels.set_blink(idx, false);
        pixels.set_color(idx, C::LOOP_COLOR);
        pixels.set_default_color(idx, C::LOOP_COLOR, true);
        return;
    }

    if (settings.midi_sync) {
        if (loops[idx]->loop_type == "oneshot") {
            bool is_clock_playing = clock_.is_playing;

            if (play_queue[idx]) {
                if (is_clock_playing) {
                    loops[idx]->toggle_playstate(0);
                    loops[idx]->toggle_playstate(1);
                    pixels.set_blink(idx, false);
                    pixels.set_color(idx, C::PIXEL_LOOP_PLAYING_COLOR);
                    pixels.set_default_color(idx, C::PIXEL_LOOP_PLAYING_COLOR, true);
                } else {
                    play_queue[idx] = false;
                    pixels.set_blink(idx, false);
                    pixels.set_color(idx, C::LOOP_COLOR);
                    pixels.set_default_color(idx, C::LOOP_COLOR, true);
                }
            } else {
                play_queue[idx] = true;
                if (is_clock_playing) {
                    loops[idx]->toggle_playstate(1);
                    pixels.set_blink(idx, false);
                    pixels.set_color(idx, C::PIXEL_LOOP_PLAYING_COLOR);
                    pixels.set_default_color(idx, C::PIXEL_LOOP_PLAYING_COLOR, true);
                } else {
                    pixels.set_blink(idx, true, C::PIXEL_LOOP_PLAYING_COLOR);
                }
            }
        } else {
            play_queue[idx] = !play_queue[idx];
            pixels.set_blink(idx, play_queue[idx], C::PIXEL_LOOP_PLAYING_COLOR);
        }

        if (clock_.is_playing) {
            _play_loop(idx);
        }
    } else {
        _play_loop(idx);
    }
}

void LoopManager::start_armed_recording() {
    if (!recording_is_armed || recording_pad == -1) {
        return;
    }
    recording_is_armed = false;
    loops[recording_pad]->toggle_record_state();
    // Solid red for active recording
    pixels.set_blink(recording_pad, false);
    pixels.set_default_color(recording_pad, C::RED, true);
    pixels.set_color(recording_pad, C::RED);
}

void LoopManager::process_loop_on_queue() {
    if (recording_is_armed) {
        start_armed_recording();
    }
    if (clock_.is_playing && !any_loop_playing) {
        any_loop_playing = true;
        for (uint8_t idx = 0; idx < C::NUM_PADS; idx++) {
            if (play_queue[idx]) {
                _play_loop(idx, -1, false, 1);
            }
        }
    }
}

void LoopManager::stop_all_loops() {
    // Skip if nothing is playing or transport already running (Stop only)
    if (!any_loop_playing || clock_.is_playing) {
        return;
    }
    any_loop_playing = false;
    midi.clear_cc_cache(); // fresh start for CC duplicate suppression
    for (uint8_t idx = 0; idx < C::NUM_PADS; idx++) {
        if (loops[idx]) {
            _stop_single_loop(idx, loops[idx]);
        }
    }
}

void LoopManager::silence_all_for_lock() {
    // Web-config lock seizes the instrument and the main loop stops servicing loops/MIDI, so
    // any playing loop would freeze mid-bar with its notes hung. Unlike stop_all_loops(), there
    // is no transport guard here — stop playback + note-off EVERY loop and clear the play queue
    // so nothing auto-resumes. clear_notes_and_pixels() emits the note-offs on each loop's
    // resolved output channel; the caller follows with an all-channels blast for live/held
    // notes. Any in-progress recording is just abandoned (state cleared) rather than finalized —
    // running toggle_record_state(0) on already-finalized loops would re-quantize them and burn
    // loop IDs. (item 8)
    is_recording = false;
    recording_is_armed = false;
    recording_pad = -1;
    for (uint8_t idx = 0; idx < C::NUM_PADS; idx++) {
        if (loops[idx]) {
            loops[idx]->toggle_playstate(0);
            loops[idx]->clear_notes_and_pixels();
            play_queue[idx] = false;
            pixels.set_blink(idx, false);
            pixels.set_default_color(idx, C::LOOP_COLOR, true);
        }
    }
    any_loop_playing = false;
}

void LoopManager::_stop_single_loop(uint8_t idx, MidiLoop *loop_obj) {
    if (play_queue[idx] && loop_obj->loop_is_playing) {
        pixels.set_blink(idx, true, C::PIXEL_LOOP_PLAYING_COLOR);
    } else {
        play_queue[idx] = false;
    }
    loop_obj->toggle_playstate(0);
    loop_obj->clear_notes_and_pixels();
    pixels.set_default_color(idx, C::LOOP_COLOR, true);
}

void LoopManager::_play_loop(uint8_t idx, int on_or_off, bool align_to_clock, int use_midi_clock) {
    if (loops[idx] == nullptr) {
        return;
    }

    if (loops[idx]->loop_type == "loop") {
        bool previous_state = loops[idx]->loop_is_playing;
        loops[idx]->toggle_playstate(on_or_off, align_to_clock, use_midi_clock);

        if (previous_state && !loops[idx]->loop_is_playing) { // now off
            loops[idx]->clear_notes_and_pixels();
            pixels.set_default_color(idx, C::LOOP_COLOR, true);
        } else if (!previous_state && loops[idx]->loop_is_playing) { // now on
            loops[idx]->clear_notes_and_pixels();
            pixels.set_default_color(idx, C::PIXEL_LOOP_PLAYING_COLOR, true);
            pixels.set_color(idx, C::PIXEL_LOOP_PLAYING_COLOR);
        }
    } else {
        loops[idx]->toggle_playstate(1, align_to_clock, use_midi_clock);
    }

    pixels.set_blink(idx, false);

    // stop_all_loops() early-outs on !any_loop_playing, and process_loop_on_queue() only
    // maintains the flag while a MIDI clock is rolling — playback started here with
    // midi_sync off (or a stopped clock) must set it too, or stop-all becomes a no-op.
    if (loops[idx]->loop_is_playing) {
        any_loop_playing = true;
    }
}

void LoopManager::initialize() {
    // Register cross-module hooks (Python resolved these with late imports)
    settings.set_save_loops_callback(_settings_save_loops);
    pedals.set_loop_state_provider(_pedals_loop_state);
    settingsmenu::set_oneshot_refresh_hook(_oneshot_refresh);
    // Give looper the finalized-loops event total so it can enforce the global RAM budget
    // live while recording (item 1). recording_pad's loop is excluded until finalized, so
    // total_events_count is exactly "all loops except the one currently recording".
    midiloop_register_events_base([]() -> uint32_t { return loop_manager.total_events_count; });

    total_events_count = 0;

    if (settings.loops_to_load_json.length() > 0) {
        JsonDocument doc;
        PROF_START(t_json);
        bool parsed_ok = !deserializeJson(doc, settings.loops_to_load_json);
        PROF_ADD(json_parse_us, t_json);
        if (parsed_ok) {
            PROF_START(t_bin);
            load_loops_binary(doc.as<JsonObjectConst>());
            PROF_ADD(load_binary_us, t_bin);
        }
    }

    recording_pad = -1;
    is_recording = false;
}

void LoopManager::load_loops_binary(JsonObjectConst loops_metadata) {
    uint32_t last_blink_update = ticks::ticks_ms();

    pixels.indicate_preset_loading(true);
    display.show_notification("Loading Loops...", true);

    for (JsonPairConst kv : loops_metadata) {
        int pad_idx = atoi(kv.key().c_str());
        JsonObjectConst meta = kv.value().as<JsonObjectConst>();
        if (pad_idx < 0 || pad_idx >= C::NUM_PADS || meta.isNull()) {
            continue;
        }
        // Duplicate pad key in malformed JSON: first key wins — assigning again would leak
        // the already-loaded MidiLoop and double-count its events in the budget (R9a).
        if (loops[pad_idx] != nullptr) {
            continue;
        }

        // Loading indicator (pixels blink)
        if (ticks::ticks_ms() - last_blink_update >= 200) {
            pixels.process_blinks(true);
            last_blink_update = ticks::ticks_ms();
        }

        // Skip if no loop_id (stale/invalid metadata). Everything else — type, ticks,
        // bpm — comes from the loop file's header, the single source of truth.
        int loop_id = meta["loop_id"] | -1;
        if (loop_id < 0) {
            continue;
        }

        // One 20-byte header peek gives the budget pre-check (item 1) exact event counts
        // BEFORE reading: an over-budget preset skips the offending pad with a notice
        // instead of loading until an allocation panics. Invalid/missing file (stale
        // metadata, bad magic, truncation) is skipped the same way.
        String loop_path = loop_storage::get_loop_path(loop_id);
        loop_storage::LoopHeaderInfo hdr = loop_storage::load_loop_header(loop_path);
        if (!hdr.valid || hdr.total_events() == 0) {
            // Missing file = stale metadata, skip silently. Present-but-unreadable
            // (bad magic/size) = tell the user now, or the loop just looks vanished.
            if (!hdr.valid && LittleFS.exists(loop_path)) {
                char msg[32];
                snprintf(msg, sizeof(msg), "Pad %d loop corrupt", pad_idx + 1);
                display.show_notification(msg);
            }
            continue;
        }
        // Heap gate scales with the incoming loop (5 bytes/event across the four
        // storages): a fixed floor lets a single 20k-event loop pass at 40 KB free
        // and then panic inside reserve().
        uint32_t incoming_bytes = hdr.total_events() * sizeof(loop_storage::NotesEvent);
        if (total_events_count + hdr.total_events() > C::TOTAL_LOOP_EVENTS_LIMIT ||
            rp2040.getFreeHeap() < C::HEAP_FLOOR_BYTES + incoming_bytes) {
            char msg[32];
            snprintf(msg, sizeof(msg), "Preset too big: pad %d skip", pad_idx + 1);
            display.show_notification(msg);
            continue;
        }

        MidiLoop *loop = make_midi_loop(loop_storage::loop_type_name(hdr.loop_type), (uint8_t)pad_idx);
        loop->loop_id = loop_id;
        loop->total_midi_ticks = hdr.total_ticks;
        loop->recording_bpm = hdr.bpm > 0 ? hdr.bpm : 120.0f;
        // 24 MIDI ticks per quarter note at recording_bpm quarters/minute
        loop->total_time_seconds = hdr.total_ticks / 24.0f / (loop->recording_bpm / 60.0f);

        PROF_START(t_load);
        bool loaded = loop_storage::load_loop_from_flash(loop_path, *loop);
        PROF_ADD(loop_read_us, t_load);
        if (!loaded) {
            delete loop; // corrupt body (CRC/short read) — pad skipped cleanly
            char msg[32];
            snprintf(msg, sizeof(msg), "Pad %d loop corrupt", pad_idx + 1);
            display.show_notification(msg);
            continue;
        }
        loop->loop_file_path = loop_path;

        loop->has_loop = true;
        loops[pad_idx] = loop;
        pixels.set_default_color(pad_idx, C::LOOP_COLOR, true);
        PROF_START(t_fin);
        finalize_loop_load(pad_idx);
        PROF_ADD(finalize_us, t_fin);
        PROF_SET(loops_loaded, g_preset_timing.loops_loaded + 1);
    }

    PROF_SET(total_events, total_events_count);
    pixels.indicate_preset_loading(false);
}

void LoopManager::update_pad_pixels() {
    for (uint8_t pad_idx = 0; pad_idx < C::NUM_PADS; pad_idx++) {
        MidiLoop *loop = loops[pad_idx];
        if (loop == nullptr) {
            pixels.set_default_color(pad_idx);
            pixels.set_color(pad_idx, C::BLACK);
            continue;
        }
        pixels.set_default_color(pad_idx, C::LOOP_COLOR, true);

        if (loop->loop_is_playing) {
            pixels.set_color(pad_idx, C::PIXEL_LOOP_PLAYING_COLOR);
            pixels.set_default_color(pad_idx, C::PIXEL_LOOP_PLAYING_COLOR, true);
        } else if (play_queue[pad_idx]) {
            pixels.set_blink(pad_idx, true, C::PIXEL_LOOP_PLAYING_COLOR);
        } else {
            pixels.set_default_color(pad_idx, C::LOOP_COLOR, true);
            pixels.set_color(pad_idx, C::LOOP_COLOR);
        }
    }
}

void LoopManager::finalize_loop_load(uint8_t pad_idx) {
    if (loops[pad_idx] == nullptr) {
        return;
    }
    total_events_count += loops[pad_idx]->count_events();
    loops[pad_idx]->create_oneshot_ccs();
    loops[pad_idx]->warm_unique_ccs(); // warm the arp's unique-CC cache; record-stop path does this too (R2)

    // Only generate oneshot notes if needed (otherwise lazy at playback)
    if (loops[pad_idx]->loop_type == "oneshot" && settings.notes_all_at_once) {
        loops[pad_idx]->update_oneshot_notes();
    }

    loops[pad_idx]->trim_loaded_ccs(); // prevents long loop when loaded CCs are all oneshot
}

void LoopManager::handle_midi_sync_change() {
    for (uint8_t idx = 0; idx < C::NUM_PADS; idx++) {
        MidiLoop *loop_obj = loops[idx];
        if (loop_obj != nullptr) {
            if (loop_obj->loop_is_playing) {
                loop_obj->toggle_playstate(0);
                loop_obj->clear_notes_and_pixels();
            }
            play_queue[idx] = false;
            pixels.set_blink(idx, false);
            pixels.set_default_color(idx, C::LOOP_COLOR, true);
            pixels.set_color(idx, C::LOOP_COLOR);
        }
    }
    any_loop_playing = false;
}

void LoopManager::save_loops_to_preset(JsonObject &preset_settings) {
    // Build loops metadata (includes loop_id for each pad)
    JsonObject loops_metadata = preset_settings["loops"].to<JsonObject>();

    display.show_notification("Saving loops...", true);

    for (uint8_t pad_idx = 0; pad_idx < C::NUM_PADS; pad_idx++) {
        MidiLoop *loop = loops[pad_idx];
        if (loop == nullptr || !loop->has_loop) {
            continue;
        }
        rp2040.wdt_reset(); // multi-pad flash saves legitimately exceed the 8.3 s budget

        // Deferred save: write the loop file for loops recorded this session
        if (loop->count_events() > 0 && loop->loop_file_path.length() == 0) {
            String filename = loop_storage::save_loop_to_flash(*loop, loop->loop_id);
            if (filename.length()) {
                loop->loop_file_path = String(loop_storage::LOOPS_DIR) + "/" + filename;
            }
        }

        // Only record the reference once the file actually exists — a dangling loop_id
        // (failed flash save) would read as a silently-empty pad on every future load.
        // The path stays empty on failure, so re-saving the preset retries the write.
        if (loop->loop_file_path.length() == 0) {
            if (loop->count_events() > 0) {
                char msg[32];
                snprintf(msg, sizeof(msg), "Pad %d NOT saved", pad_idx + 1);
                display.show_notification(msg);
            }
            continue;
        }

        // v2: the preset carries only the loop id; type/ticks/bpm live in the loop
        // file's header. Kept an object (not a bare int) so future fields stay cheap.
        JsonObject meta = loops_metadata[String(pad_idx)].to<JsonObject>();
        meta["loop_id"] = loop->loop_id;
    }
}
