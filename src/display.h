// Port of src/display.py — SSD1306 content/UI manager + DisplayManager dirty flag.
// Adafruit_GFX's built-in 6x8 font has the same cell size as CircuitPython framebuf's
// font5x8.bin, so all pixel coordinates carry over unchanged.
// I2C: GP18/19 = I2C1 = Wire1 (the bus-mux gotcha; see .claude/library-map.md).
// Python's str-or-list text params -> overloads; notification None -> empty String.
#pragma once
#include <Arduino.h>
#include <Adafruit_SSD1306.h>
#include "constants.h"

// Dirty-flag owner. Single-core at boot; once main.cpp flips core1_owns_display,
// ALL I2C pushes happen on core 1 (loop1 -> core1_push) and core 0 only sets the
// flag. Never call _display.display() from core 0 after that flip — two cores on
// Wire1 concurrently corrupts the bus.
class DisplayManager {
public:
    volatile bool display_needs_update = true;
    volatile bool core1_owns_display = false; // set once, at end of setup()
    void check_show_display();
    void core1_push(); // loop1 only: push if dirty, capped at DISPLAY_PUSH_MIN_INTERVAL_MS
};

extern DisplayManager display_manager;

class Display {
public:
    bool dot_states[4] = {false, false, false, false};
    String notification_text = "";   // "" = none (Python None)
    uint32_t notification_on_time = 0;
    uint32_t notification_fps_timer = 0;

    void begin(); // I2C + panel init; call from setup()

    void show_text_top(const String &text, bool notification = false, bool force_refresh = false);

    // Python show_text_middle(text_or_list, value_only, value_start_x, clear_width)
    void show_text_middle(const String &text, bool value_only = false, int value_start_x = -1, int clear_width = 0);
    void show_text_middle(const String *lines, uint8_t num_lines);

    void show_page_indicator(int current, int total);

    void display_left_dot(bool on_or_off = true) { display_dot(0, on_or_off); }
    void display_right_dot(bool on_or_off = true) { display_dot(3, on_or_off); }
    void display_dot(int selection_pos = 0, bool on_or_off = true);
    void turn_off_all_dots();

    void show_text_bottom(const String &text, bool value_only = false, int start_x = -1, int text_width_px = 10);

    // Transport icons in the bottom-left status area (C::BOTTOM_LEFT_* rect).
    // Clears the whole area first, so the last writer wins. armed_blink_on is the
    // current phase of the armed-recording blink (caller owns the cadence).
    void draw_transport_icons(bool any_loop_playing, bool recording, bool armed_blink_on);

    // BPM readout in the bottom strip: quarter-note glyph + "120", plus the
    // circular-arrows sync glyph when following external MIDI clock.
    void draw_bpm(int bpm, bool ext_sync);

    // Show/hide just the quarter-note glyph — the recording beat blink (glyph
    // appears on the beat, blank between beats). draw_bpm() draws it solid.
    void draw_bpm_pulse(bool visible);

    // Nav badge = menu position ("2/6"), drawn TOP-RIGHT with the other menu info
    // (bottom strip stays functional state). label is cached internally so
    // re-draws (title refresh, lock released while nav active) don't need the
    // caller to resupply it; it may overdraw the end of a long title (user-ok).
    void toggle_navmode_icon(bool on_or_off, const String &label = "");
    void toggle_lock_icon(bool on_or_off, bool nav_mode_on = false);
    void update_playmode_icon(const char *playmode = nullptr);

    void show_notification(const String &msg, bool force_display = false);
    void clear_notifications(const String &replace_text);

    void show_startup_screen();

    // Full-screen takeover message (clears the whole panel, draws 1-2 lines centered
    // both ways). Used for the WEB CONFIG lock screen and right before
    // rebootToBootloader() so the OLED shows "Updating..." instead of freezing on the
    // last UI frame while the new firmware flashes. Writes the framebuffer + sets the
    // dirty flag; core 1 pushes it (give it ~one push cap).
    void show_fullscreen_message(const String &line1, const String &line2 = "");

    // Restore the bottom divider line + play-mode glyph after a takeover ends.
    void redraw_bottom_chrome();

    Adafruit_SSD1306 &raw(); // escape hatch for menus drawing directly

private:
    void _set_update_flag(bool yes_or_no = true, bool immediate = false);
    void _display_line_bottom();
    void _draw_nav_badge(); // inverted "2/6" tab, top-right corner
    void _text(const String &s, int16_t x, int16_t y, uint16_t color);
};

extern Display display;
