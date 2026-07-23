// Port of src/code.py (main loop).
//
// boot.py difference: CircuitPython exposed the FAT drive on FN-held boot. The
// filesystem is now LittleFS (2026-07-06: FatFS's flash-translation layer cost a
// flat ~2 s per file op — see .claude/CHANGELOG.md), which hosts cannot mount, so
// USB drive mode is gone entirely; all preset/loop access goes through the web
// config UI's serial protocol (serial_config.cpp), which works in normal mode.
//
// The 270 MHz overclock is intentionally gone (stock clock outruns CircuitPython).
#include <Arduino.h>
#include <Adafruit_TinyUSB.h>
#include <LittleFS.h>

#include "constants.h"
#include "ticks.h"
#include "settings.h"
#include "settingsmenu.h"
#include "midiscales.h"
#include "buttons.h"
#include "clock.h"
#include "pixels.h"
#include "pedals.h"
#include "display.h"
#include "presets.h"
#include "midi.h"
#include "looper.h"
#include "loop_storage.h"
#include "loopmanager.h"
#include "arp.h"
#include "inputs.h"
#include "menus.h"
#include "playmenu.h"
#include "serial_config.h"
#include "test_hooks.h"
#include "useraddons.h"
#include "profiling.h"

#if PRESET_LOAD_PROFILE
PresetLoadTiming g_preset_timing; // Item 3 measurement; remove with profiling.h
#endif

// ---------------- core 1: display + pixel offload ----------------
//
// Core 0 never blocks on the ~25 ms SSD1306 I2C push or the NeoPixel show; it
// only writes the framebuffer/color buffers and sets volatile dirty flags.
// Core 1 owns every hardware push once offload_to_core1() flips the ownership
// flags (end of setup()).
//
// Signaling is plain volatile flags, deliberately NOT rp2040.fifo: the
// inter-core FIFO is what arduino-pico's flash-write lockout (idleOtherCore)
// uses, and LittleFS preset saves rely on it to park this loop automatically
// during flash_range_erase/program.
//
// Shared-buffer rule: single-buffered framebuffer + flag. Core 0 may write the
// framebuffer while core 1 is mid-push — worst case is one torn frame,
// corrected within DISPLAY_PUSH_MIN_INTERVAL_MS. Same deal for pixel colors.

static volatile bool core1_active = false;

static void offload_to_core1() {
    display_manager.core1_owns_display = true;
    pixels.core1_owns_pixels = true;
    core1_active = true; // set last — core 1 gates on this before touching hardware
}

void setup1() {
    // Intentionally empty: display/pixel init happens in setup() on core 0;
    // loop1 waits for core1_active before touching either bus.
}

void loop1() {
    if (!core1_active) {
        delay(1);
        return;
    }

    display_manager.core1_push(); // OLED, only when dirty, ~20 fps cap

    static uint32_t pixel_prev = 0;
    uint32_t now = ticks::ticks_ms();
    if (ticks::ticks_diff(now, pixel_prev) > (int32_t)pixels.update_interval_ms) {
        pixels.update(); // flash expiry + strip.show when dirty (+ pedal pixels)
        if (C::USING_FOOT_PEDALS) {
            pedals.show_pedal_pixels(); // pedal-only changes (self-guarded on its flag)
        }
        pixel_prev = now;
    }
}

// ---------------- code.py: state ----------------

static uint32_t polling_time_prev = 0;
static uint32_t clear_notifications_time_prev = 0;
static bool prev_midi_sync_state = false;
static bool prev_serial_locked = false;
static LoopEvents loop_events; // reused buffer for loop playback events

// -------------------- MIDI event handlers --------------------

static void record_midi_event(uint8_t note_val, uint8_t velocity, uint8_t padidx, bool is_on, uint8_t midi_channel = 0) {
    if (loop_manager.is_recording && !loop_manager.recording_is_armed) {
        loop_manager.loops[loop_manager.recording_pad]->add_note(note_val, velocity, padidx, is_on, false, midi_channel);
    }
}

// Record incoming MIDI note messages to active loop.
static void record_note_midi_messages(const std::vector<NoteMsg> &messages, bool is_note_on) {
    for (const NoteMsg &msg : messages) {
        uint8_t padidx = msg.padidx;
        uint8_t midi_channel = (msg.channel >= 0) ? (uint8_t)msg.channel : 0;
        if (loop_manager.is_recording) {
            padidx = (uint8_t)loop_manager.recording_pad;
        }
        record_midi_event(msg.note, msg.velocity, padidx, is_note_on, midi_channel);
    }
}

// Record incoming MIDI CC messages to active loop.
static void record_cc_messages(const std::vector<CcMsg> &message_data) {
    if (!loop_manager.is_recording) {
        return;
    }
    for (const CcMsg &msg : message_data) {
        if (msg.cc == 123 && msg.value == 0 && settings.midi_sync) {
            loop_manager.handle_fn_press(); // special case: CC 123 (All Notes Off)
        }
        if (loop_manager.is_recording && !loop_manager.recording_is_armed) {
            loop_manager.loops[loop_manager.recording_pad]->add_cc(msg.cc, msg.value, (uint8_t)max((int8_t)0, msg.channel));
        }
    }
}

// Record incoming channel pressure (aftertouch) messages to active loop.
static void record_aftertouch_messages(const std::vector<AtMsg> &message_data) {
    if (!loop_manager.is_recording) {
        return;
    }
    for (const AtMsg &msg : message_data) {
        if (loop_manager.is_recording && !loop_manager.recording_is_armed) {
            loop_manager.loops[loop_manager.recording_pad]->add_aftertouch(msg.pressure, (uint8_t)max((int8_t)0, msg.channel));
        }
    }
}

// -------------------- Event processing --------------------

// Send MIDI notes, update pixels, optionally record. playback_pad_idx >= 0 for
// loop playback channel routing.
static void process_notes(const std::vector<NoteMsg> &notes, bool is_on, bool record = true, int playback_pad_idx = -1) {
    for (const NoteMsg &note : notes) {
        int output_channel;
        if (playback_pad_idx >= 0) {
            output_channel = midi.get_midi_channel_for_pad(playback_pad_idx, note.channel);
        } else {
            output_channel = midi.get_midi_channel_for_pad(note.padidx, note.channel);
        }

        if (is_on) {
            midi.send_note_on(note.note, note.velocity, output_channel);
            pixels.set_note_on(note.padidx, note.velocity);
            useraddons::handle_new_notes_on(note.note, note.velocity, note.padidx, output_channel);
        } else {
            midi.send_note_off(note.note, output_channel);
            pixels.set_note_off(note.padidx);
            useraddons::handle_new_notes_off(note.note, note.velocity, note.padidx, output_channel);
        }
        if (record) {
            uint8_t midi_channel = (note.channel >= 0 && note.channel <= 15)
                                       ? (uint8_t)note.channel
                                       : (uint8_t)settings.midi_channel_out;
            record_midi_event(note.note, note.velocity, note.padidx, is_on, midi_channel);
        }
    }
}

// Send MIDI CCs, update pixels, optionally record. loop_type "oneshot" shortens flash.
static void process_cc_events(const std::vector<CcMsg> &cc_events, bool record = true,
                              uint8_t loop_pad_idx = C::DEFAULT_LOOP_PAD_IDX,
                              const char *loop_type = nullptr) {
    bool is_oneshot_mode = loop_type && !strcmp(loop_type, "oneshot");

    for (const CcMsg &cc_event : cc_events) {
        int output_channel = midi.get_midi_channel_for_pad(
            loop_pad_idx == C::DEFAULT_LOOP_PAD_IDX ? -1 : loop_pad_idx, cc_event.channel);

        midi.send_cc(cc_event.cc, cc_event.value, output_channel);
        useraddons::handle_new_cc(cc_event.cc, cc_event.value, output_channel);

        if (loop_pad_idx != C::DEFAULT_LOOP_PAD_IDX) {
            pixels.flash_pixel(loop_pad_idx, is_oneshot_mode ? 0.1f : 0.2f, C::CC_COLOR);
        } else {
            pixels.flash_pixel(C::ENC_LED_IDX, is_oneshot_mode ? 0.1f : 0.2f, C::CC_COLOR);
        }

        if (record && loop_manager.is_recording) {
            loop_manager.loops[loop_manager.recording_pad]->add_cc(
                cc_event.cc, cc_event.value, (uint8_t)max((int8_t)0, cc_event.channel));
        }
    }
}

// Send channel pressure (aftertouch) events during playback.
static void process_aftertouch_events(const std::vector<CcMsg> &at_events, uint8_t loop_pad_idx = C::DEFAULT_LOOP_PAD_IDX) {
    for (const CcMsg &at_event : at_events) {
        // Storage uses (cc=0, pressure, channel) for compat with CC format
        int output_channel = midi.get_midi_channel_for_pad(
            loop_pad_idx == C::DEFAULT_LOOP_PAD_IDX ? -1 : loop_pad_idx, at_event.channel);
        midi.send_aftertouch(at_event.value, output_channel);

        if (loop_pad_idx != C::DEFAULT_LOOP_PAD_IDX) {
            pixels.flash_pixel(loop_pad_idx, 0.2f, C::CC_COLOR);
        } else {
            pixels.flash_pixel(C::ENC_LED_IDX, 0.2f, C::CC_COLOR);
        }
    }
}

// Bottom status strip, polled from the slow block rather than hooked at the
// mutation sites (loop toggles, record arm/start, sync/BPM changes come from
// menus, pads, MIDI AND the web UI) — one poll catches every path. Redraws only
// on state change.
//
// Set when the WEB CONFIG full-screen takeover ends: the panel was blanked, so
// the change-detection caches below no longer match what's on screen.
static bool status_strip_stale = false;

// Transport icons: play triangle when any loop is playing, rec circle when
// recording (blinking at the pixel-blink cadence while armed). Derived fresh
// each poll: any_loop_playing is a stop-all optimization flag that can go stale
// when the last loop is individually toggled off, so don't trust it for display.
static void update_status_strip() {
    static int8_t drawn_transport = -1;
    static int drawn_bpm = -1;
    static int8_t drawn_ext = -1;
    static int8_t drawn_pulse = 1; // draw_bpm() leaves the glyph solid
    if (status_strip_stale) {
        status_strip_stale = false;
        drawn_transport = -1;
        drawn_bpm = -1; // forces draw_bpm(), which also redraws the pulse glyph
    }

    bool any_playing = false;
    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        if (loop_manager.loops[i] && loop_manager.loops[i]->loop_is_playing) {
            any_playing = true;
            break;
        }
    }
    bool armed = loop_manager.recording_is_armed;
    bool recording = loop_manager.is_recording && !armed;
    bool armed_blink_on = armed && ((ticks::ticks_ms() / C::PIXEL_BLINK_TIME_MS) & 1);

    int8_t transport = (any_playing ? 1 : 0) | (recording ? 2 : 0) | (armed_blink_on ? 4 : 0);
    if (transport != drawn_transport) {
        display.draw_transport_icons(any_playing, recording, armed_blink_on);
        drawn_transport = transport;
    }

    // BPM + "EXT" while slaved to external MIDI clock (bpm_current tracks the
    // measured tempo in that case).
    int bpm = (int)roundf(clock_.bpm_current);
    int8_t ext = settings.midi_sync ? 1 : 0;
    if (bpm != drawn_bpm || ext != drawn_ext) {
        display.draw_bpm(bpm, ext != 0);
        drawn_bpm = bpm;
        drawn_ext = ext;
        drawn_pulse = 1;
    }

    // Beat blink on the note glyph while RECORDING only — a metronome to play
    // against: glyph pops on at each beat, blanks between, solid again the
    // moment recording ends. Synced: phase comes from the tick counter, so the
    // blink sits on the master's beat grid. Unsynced: wall clock anchored at
    // the record-start edge, so the first blink coincides with the take
    // starting. 25% duty.
    static uint32_t rec_anchor = 0;
    static bool prev_recording = false;
    uint32_t now = ticks::ticks_ms();
    if (recording && !prev_recording) {
        rec_anchor = now;
    }
    prev_recording = recording;

    int8_t pulse = 1; // solid when not recording
    if (recording) {
        if (settings.midi_sync && clock_.is_playing) {
            pulse = (clock_.midi_ticks_elapsed % Clock::TICKS_PER_QUARTER_NOTE) < 6 ? 1 : 0;
        } else {
            uint32_t quarter_ms = (uint32_t)(clock_.quarternote_duration * 1000.0f);
            if (quarter_ms > 0) {
                pulse = ((now - rec_anchor) % quarter_ms) < (quarter_ms >> 2) ? 1 : 0;
            }
        }
    }
    if (pulse != drawn_pulse) {
        display.draw_bpm_pulse(pulse != 0);
        drawn_pulse = pulse;
    }
}

static void process_loop_notes() {
    if (settings.midi_sync != prev_midi_sync_state) { // sync state just changed: stop all loops
        loop_manager.handle_midi_sync_change();
        prev_midi_sync_state = settings.midi_sync;
        return;
    }

    if (settings.midi_sync && clock_.is_playing) {
        loop_manager.process_loop_on_queue();
    }

    // CC coalescing: collect all CCs from all loops, keep only last value per CC#/channel
    struct Coalesced {
        uint8_t cc;
        int8_t channel;
        uint8_t value;
        uint8_t pad_idx;
        bool oneshot;
    };
    // Static + clear() (retains capacity) instead of a fresh vector each call: this runs every
    // loop iteration on core 0 only, so reusing the buffer removes per-iteration realloc churn
    // and heap fragmentation on the tick path (Tier 3 Item 4).
    static std::vector<Coalesced> cc_coalesce;
    cc_coalesce.clear();

    for (uint8_t idx = 0; idx < C::NUM_PADS; idx++) {
        MidiLoop *loop = loop_manager.loops[idx];
        if (loop == nullptr || !loop->loop_is_playing) {
            continue;
        }
        if (settings.midi_sync && loop->playback_use_clock && !loop_manager.play_queue[idx]) {
            continue;
        }

        bool is_oneshot = (loop->loop_type == "oneshot");
        if (loop->get_new_events(loop_events)) {
            // Notes: process immediately (timing-critical). Offs before ons so a
            // coincident same-pitch off (legato repeat) can't cancel the new note-on.
            process_notes(loop_events.notes_off, false, false, idx);
            process_notes(loop_events.notes_on, true, false, idx);

            // CCs: coalesce (last value wins)
            for (const CcMsg &cc_event : loop_events.cc) {
                bool updated = false;
                for (Coalesced &c : cc_coalesce) {
                    if (c.cc == cc_event.cc && c.channel == cc_event.channel) {
                        c.value = cc_event.value;
                        c.pad_idx = idx;
                        c.oneshot = is_oneshot;
                        updated = true;
                        break;
                    }
                }
                if (!updated) {
                    cc_coalesce.push_back({cc_event.cc, cc_event.channel, cc_event.value, idx, is_oneshot});
                }
            }

            // Aftertouch: process immediately (less common, timing matters)
            process_aftertouch_events(loop_events.at, idx);
        }
    }

    // Send coalesced CCs: one send per unique CC#/channel
    for (const Coalesced &c : cc_coalesce) {
        midi.send_cc(c.cc, c.value, c.channel);
        pixels.flash_pixel(c.pad_idx, c.oneshot ? 0.1f : 0.2f, C::CC_COLOR);
    }
}

// ---------------------------- Setup -------------------------------

// True when the previous boot ended in a hardware-watchdog timeout (item 4). Read once at
// the very top of setup(), before anything can touch the reset registers. getResetReason()
// returns WDT_RESET only for a genuine timeout (watchdog_enable path); our own intentional
// rp2040.reboot() reports SOFT_RESET, so preset-load/save reboots never false-flag as crashes.
static bool g_watchdog_recovered = false;

void setup() {
    g_watchdog_recovered = (rp2040.getResetReason() == RP2040::WDT_RESET);
#ifdef LOOPSTER_TEST_HOOKS
    test_hooks::capture_hang_phase(g_watchdog_recovered); // R18: read + clear the crumb early
#endif

    pinMode(C::PIN_FN_BTN, INPUT_PULLUP); // FN no longer gates a boot mode; app inputs read it later

    // USB identity + interfaces, before enumeration
    TinyUSBDevice.setManufacturerDescriptor("DJBB");
    TinyUSBDevice.setProductDescriptor("Loopster");
    midi.setup_usb(); // TinyUSB MIDI + Serial1 (UART MIDI)
    Serial.begin(115200);

    // Filesystem (14 MB LittleFS partition; self-formats on very first boot)
    if (!LittleFS.begin()) {
        LittleFS.format();
        LittleFS.begin();
    }

    if (TinyUSBDevice.mounted()) {
        TinyUSBDevice.detach();
        delay(10);
        TinyUSBDevice.attach();
    }

    display.begin();
    pixels.begin();
    pedals.begin();

    // ---- Python import-time module init, in dependency order ----
    loop_storage::init();            // registers orphan cleanup with settings
#if PRESET_LOAD_PROFILE
    g_preset_timing.heap_total = rp2040.getTotalHeap();
    g_preset_timing.heap_free_before = rp2040.getFreeHeap();
#endif
    PROF_START(t_startup);
    settings.load_startup_preset();  // settings.py module init
    PROF_ADD(startup_preset_us, t_startup);
    // Apply the saved BPM to the clock so arp durations / quantize grids use it from
    // boot, not a hardcoded 120 until the BPM menu is touched (item 23; mirrors the
    // settings-menu handler). When midi_sync is on, the clock follows incoming MIDI.
    if (!settings.midi_sync) {
        clock_.set_bpm(settings.default_bpm);
    }
    pixels.apply_brightness();       // begin() ran pre-load; apply preset's led_brightness
    presets_init();                  // presets.py module init
    settingsmenu::init();            // settingsmenu.py module init (validate indices)
    useraddons::init();
    inputs.initialize();
    menus_init();                    // menus.py module-level Menu construction

    // ---- code.py startup sequence ----
    pixels.clear_all();
    midi.setup();
    display.show_startup_screen();
    Menu::initialize();

    PROF_START(t_lm);
    loop_manager.initialize();
    PROF_ADD(lm_initialize_us, t_lm);
    PROF_START(t_pix);
    loop_manager.update_pad_pixels();
    PROF_ADD(update_pixels_us, t_pix);
#if PRESET_LOAD_PROFILE
    g_preset_timing.heap_free_after = rp2040.getFreeHeap();
#endif

    uint32_t now = ticks::ticks_ms();
    polling_time_prev = now;
    clear_notifications_time_prev = now;
    prev_midi_sync_state = settings.midi_sync;

    // Surface a recovered crash to the player (item 4). Shown last so it survives into the
    // first loop iterations; a normal boot shows nothing.
    if (g_watchdog_recovered) {
        display.show_notification("Recovered");
    }

    // Boot-time init paths call the same setters players do (play mode, scale seed,
    // loop load) — none of that is a user edit, so start clean here.
    settings.dirty = false;

    offload_to_core1(); // from here on, all OLED/pixel pushes happen on core 1

    // Arm the hardware watchdog LAST — after first-boot LittleFS.format() and the ~1 s preset
    // load, which can exceed the 8.3 s hardware max. From here, loop() must feed it every
    // pass; any hang (wedged I2C, UART stall, logic loop, OOM abort) self-recovers in ~8 s
    // + boot instead of leaving the instrument dead on stage. Max hardware timeout ≈ 8.3 s.
    rp2040.wdt_begin(8300);
}

// ---------------------------- Main loop -------------------------------

void loop() {
    // Feed the watchdog first thing, on EVERY path (incl. the web-lock early return
    // below) so only a genuine hang lets it fire (item 4).
    rp2040.wdt_reset();

#ifdef LOOPSTER_TEST_HOOKS
    test_hooks::loop_heartbeat();
#endif
    R18_MARK(1); // main loop

#if PRESET_LOAD_PROFILE
    // Report boot-side preset-load timings once USB CDC has re-enumerated after
    // the reboot (Serial isn't ready in setup() right after load_preset reboots).
    static bool prof_reported = false;
    if (!prof_reported && (Serial || millis() > 4000)) {
        g_preset_timing.report();
        prof_reported = true;
    }
#endif

    uint32_t timenow = ticks::ticks_ms();
    bool loop_recording = loop_manager.is_recording;

    // 0. Serial config handler — process before anything else
    bool prev_locked = prev_serial_locked;
    serial_handler.update();
    bool locked = serial_handler.is_locked();
    prev_serial_locked = locked;
    if (locked) {
        if (!prev_locked) {
            // Just became locked: black out the whole panel with a centered WEB
            // CONFIG — the instrument is seized, so no live state should show.
            display.show_fullscreen_message("WEB CONFIG");
            // Seizing control: stop loops + kill all notes so nothing hangs mid-bar for the
            // duration of the web session (loop/MIDI processing is skipped below). (item 8)
            loop_manager.silence_all_for_lock();
            midi.all_notes_off_all_channels();
        }
        // Skip all MIDI/input/loop processing while web UI is connected
        // (core 1 keeps the display + pixels refreshed)
        return;
    } else if (prev_locked) {
        // Just unlocked — the takeover blanked the whole panel, so rebuild every
        // band: title + menu content, bottom divider + mode glyph, lock badge,
        // and force the status-strip poll to repaint transport + BPM.
        Menu::initialize();
        display.redraw_bottom_chrome();
        if (Menu::is_locked) {
            display.toggle_lock_icon(true, Menu::is_nav_mode);
        }
        status_strip_stale = true;
    }

    // 1. Process MIDI input & clock updates
    clock_.reset_new_tick_flag();
    // Persistent across passes so the vectors keep their capacity — no per-pass
    // heap churn while MIDI streams (item R14).
    static MidiInResult midi_in;
    midi.process_messages_in(midi_in);

    // 1.1 MIDI passthrough visual feedback
    if (midi.should_passthru_midi()) {
        if (!midi_in.notes_on.empty() || !midi_in.cc_events.empty() || !midi_in.at_events.empty()) {
            pixels.flash_pixel(C::ENC_LED_IDX, 0.2f, C::PASSTHRU_COLOR);
        }
    }

    // 1.2 Incoming MIDI messages — show activity regardless of passthru mode
    if (!midi_in.notes_on.empty()) {
        pixels.flash_pixel(C::ENC_LED_IDX, 0.2f, C::NOTE_COLOR);
        if (loop_recording) {
            record_note_midi_messages(midi_in.notes_on, true);
        }
    }
    if (!midi_in.notes_off.empty() && loop_recording) {
        record_note_midi_messages(midi_in.notes_off, false);
    }
    if (!midi_in.cc_events.empty() && settings.record_cc) {
        pixels.flash_pixel(C::ENC_LED_IDX, 0.2f, C::CC_COLOR);
        if (loop_recording) {
            record_cc_messages(midi_in.cc_events);
        }
    }
    // Aftertouch recording — always enabled (pressure is integral to performance)
    if (!midi_in.at_events.empty()) {
        pixels.flash_pixel(C::ENC_LED_IDX, 0.2f, C::CC_COLOR);
        if (loop_recording) {
            record_aftertouch_messages(midi_in.at_events);
        }
    }

    if (midi_in.transport == Transport::Stop && settings.midi_sync) {
        loop_manager.stop_all_loops();
        // Only stop recording if actively recording, not just armed/waiting
        if (loop_manager.is_recording && !loop_manager.recording_is_armed) {
            loop_manager.handle_fn_press();
        }
    }

    // 2. Process user inputs (unless MIDI start received)
    if (midi_in.transport != Transport::Start) {
        // 2.1 Slow input processing (navigation, display, notifications)
        if (ticks::ticks_diff(timenow, polling_time_prev) > (int32_t)C::NAV_BUTTONS_POLL_MS) {
            inputs.process_inputs_slow();
            // Menus now render fully on every detent (Item 2); the display push
            // happens on core 1 whenever display_needs_update is set.

            if (ticks::ticks_diff(timenow, clear_notifications_time_prev) > 1000) {
                clear_notifications_time_prev = timenow;
                Menu::clear_notifications();
            }

            pixels.process_blinks();
            update_status_strip();
            polling_time_prev = timenow;
            useraddons::slow();
            loop_manager.check_event_limits();
        }

        // 2.2 Fast input processing
        inputs.process_inputs_fast();
        useraddons::check_addons_fast();

        // 2.3 Accelerometer CC data (never recorded — live control only)
        process_cc_events(useraddons::get_accel_cc_data(), false);
    }

    // 4. Process loop notes
    process_loop_notes();

    // 5. Process new notes — only when step 2 ran this iteration. On Start the
    // vectors still hold LAST iteration's notes (cleared inside
    // process_inputs_fast); Python's per-iteration local lists were empty here.
    if (midi_in.transport != Transport::Start &&
        (!inputs.new_notes_on.empty() || !inputs.new_notes_off.empty())) {
        // Offs BEFORE ons (item 9): _play_arp_events queues the previous step's note-off and
        // the new step's note-on together. On a monophonic / single-pad arp (repeated pitch),
        // ons-first sends NoteOn then an immediate NoteOff for the same pitch = a silent,
        // zero-length note. process_loop_notes already orders offs-first for this same reason.
        process_notes(inputs.new_notes_off, false, true);
        process_notes(inputs.new_notes_on, true, true);
    }

    // 6. Visual feedback (OLED push + pixel show) runs on core 1 — see loop1()
}
