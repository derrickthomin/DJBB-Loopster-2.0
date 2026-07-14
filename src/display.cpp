#include "display.h"
#include <Wire.h>
#include "settings.h"
#include "pixels.h"
#include "ticks.h"

DisplayManager display_manager;
Display display;

static Adafruit_SSD1306 _display(C::SCREEN_W, C::SCREEN_H, &Wire1, /*reset=*/-1);

// False if the SSD1306 framebuffer alloc / panel init failed. Adafruit_GFX draws
// (and .display()) deref a null buffer, so we skip all pushes when not ready (item 25).
static bool _display_ready = false;

static const int16_t DOT_START_POSITIONS[4][2] = {{0, 25}, {0, 42}, {120, 42}, {125, 25}};
static const int16_t DOT_WIDTH = 3;
static const int16_t DOT_HEIGHT = 3;

// Page indicator, aligned with middle text line 3 (same as scale screen numbers)
static const int16_t PAGE_INDICATOR_X = C::TEXT_PAD;                          // = 7
static const int16_t PAGE_INDICATOR_Y = C::MIDDLE_Y_START + (2 * C::LINEHEIGHT); // = 40

void DisplayManager::check_show_display() {
    if (core1_owns_display) {
        display_needs_update = true; // core 1 pushes on its next pass (<50 ms)
        return;
    }
    if (!_display_ready) {
        return;
    }
    _display.display();
    display_needs_update = false;
}

void DisplayManager::core1_push() {
    static uint32_t last_push_ms = 0;
    if (!_display_ready || !display_needs_update) {
        return;
    }
    uint32_t now = ticks::ticks_ms();
    if (ticks::ticks_diff(now, last_push_ms) < (int32_t)C::DISPLAY_PUSH_MIN_INTERVAL_MS) {
        return;
    }
    // Clear BEFORE pushing: a core-0 framebuffer write during the ~25 ms push
    // re-dirties the flag and gets picked up next pass (no lost frames; worst
    // case is one torn frame, corrected within 50 ms).
    display_needs_update = false;
    _display.display();
    last_push_ms = now;
}

Adafruit_SSD1306 &Display::raw() {
    return _display;
}

void Display::begin() {
    Wire1.setSDA(C::PIN_SDA);
    Wire1.setSCL(C::PIN_SCL);
    Wire1.setClock(400000);
    // begin() returns false if the ~1 KB framebuffer malloc or panel init fails.
    // Retry a few times, then give up gracefully — drawing into a null buffer
    // would hard-fault, so leave _display_ready false and skip all draws/pushes.
    for (int attempt = 0; attempt < 3 && !_display_ready; attempt++) {
        _display_ready = _display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
    }
    if (!_display_ready) {
        Serial.println("[ERROR] SSD1306 init failed; running headless");
        return;
    }
    _display.clearDisplay();
    _display.setTextSize(1);
    _display.setTextWrap(false);
}

// framebuf.text() equivalent: transparent-background single-line text.
// Every method below that touches _display early-returns when !_display_ready:
// Adafruit_SSD1306 never null-checks its framebuffer, so any draw after a failed
// begin() is a hard fault. Headless operation must stay alive (item R6).
void Display::_text(const String &s, int16_t x, int16_t y, uint16_t color) {
    if (!_display_ready) return;
    _display.setTextColor(color == C::BKG_COLOR ? SSD1306_BLACK : SSD1306_WHITE);
    _display.setCursor(x, y);
    _display.print(s);
}

void Display::_set_update_flag(bool yes_or_no, bool immediate) {
    if (immediate) {
        display_manager.check_show_display(); // direct push pre-offload; dirty flag once core 1 owns it
        return;
    }
    display_manager.display_needs_update = yes_or_no;
}

// Nav badge ("2/6") lives in the top-right corner with the rest of the menu
// info; the bottom strip is reserved for functional state (transport/BPM/lock).
// Remembered here so every top-row redraw (titles AND notifications) can
// re-stamp it — show_text_top clears the full top row.
static bool _nav_badge_on = false;
static String _nav_label = "-/-";

void Display::_draw_nav_badge() {
    int16_t w = (int16_t)_nav_label.length() * 6 + 6;
    int16_t x = C::SCREEN_W - w;
    _display.fillRect(x, 0, w, 12, 1);
    _text(_nav_label, x + 3, 2, 0);
}

void Display::show_text_top(const String &text, bool notification, bool force_refresh) {
    if (!_display_ready) return; // R6
    _display.fillRect(0, 0, C::SCREEN_W, C::TOP_HEIGHT, C::BKG_COLOR);

    if (notification) {
        _display.fillRect(0, C::TOP_HEIGHT - 1, C::SCREEN_W, 1, 1);
    }

    _text(text, C::PADDING, C::PADDING, C::TXT_COLOR);
    if (_nav_badge_on) {
        _draw_nav_badge(); // drawn last so a long title can't sit on top of it
    }
    _set_update_flag(true, force_refresh);
}

void Display::show_text_middle(const String &text, bool value_only, int value_start_x, int clear_width) {
    if (!_display_ready) return; // R6
    const int char_height = 8;
    const int char_width = 6;

    if (value_only && value_start_x > 0) {
        int width = clear_width ? clear_width : max(char_width, (int)text.length() * char_width);
        _display.fillRect(value_start_x, C::MIDDLE_Y_START, width, char_height, C::BKG_COLOR);
        _text(text, value_start_x, C::MIDDLE_Y_START, C::TXT_COLOR);
    } else {
        _display.fillRect(C::TEXT_PAD, C::MIDDLE_Y_START, 116, C::MIDDLE_HEIGHT, C::BKG_COLOR);
        _text(text, C::TEXT_PAD, C::MIDDLE_Y_START, C::TXT_COLOR);
    }
    _set_update_flag();
}

void Display::show_text_middle(const String *lines, uint8_t num_lines) {
    if (!_display_ready) return; // R6
    _display.fillRect(C::TEXT_PAD, C::MIDDLE_Y_START, 116, C::MIDDLE_HEIGHT, C::BKG_COLOR);
    for (uint8_t i = 0; i < num_lines; i++) {
        _text(lines[i], C::TEXT_PAD, C::MIDDLE_Y_START + (i * C::LINEHEIGHT), C::TXT_COLOR);
    }
    _set_update_flag();
}

void Display::show_page_indicator(int current, int total) {
    if (!_display_ready) return; // R6
    char text[12];
    snprintf(text, sizeof(text), "%2d/%d", current, total); // right-aligned numerator
    _display.fillRect(PAGE_INDICATOR_X, PAGE_INDICATOR_Y, 30, 8, C::BKG_COLOR);
    _text(text, PAGE_INDICATOR_X, PAGE_INDICATOR_Y, C::TXT_COLOR);
    _set_update_flag();
}

void Display::display_dot(int selection_pos, bool on_or_off) {
    if (!_display_ready) return; // R6
    if (selection_pos < 0 || selection_pos > 3) {
        return;
    }
    // Early exit if state hasn't changed — avoids expensive I2C display updates
    if (dot_states[selection_pos] == on_or_off) {
        return;
    }

    for (uint8_t i = 0; i < 4; i++) {
        _display.fillRect(DOT_START_POSITIONS[i][0], DOT_START_POSITIONS[i][1], DOT_WIDTH, DOT_HEIGHT, 0);
        dot_states[i] = false;
    }

    dot_states[selection_pos] = on_or_off;
    if (on_or_off) {
        _display.fillRect(DOT_START_POSITIONS[selection_pos][0], DOT_START_POSITIONS[selection_pos][1], DOT_WIDTH, DOT_HEIGHT, 1);
    }
    _set_update_flag();
}

void Display::turn_off_all_dots() {
    if (!_display_ready) return; // R6
    for (uint8_t i = 0; i < 4; i++) {
        _display.fillRect(DOT_START_POSITIONS[i][0], DOT_START_POSITIONS[i][1], DOT_WIDTH, DOT_HEIGHT, 0);
        dot_states[i] = false;
    }
    _display.fillRect(0, C::MIDDLE_Y_START, C::TEXT_PAD, C::MIDDLE_HEIGHT, 0);
    _display.fillRect(C::SCREEN_W - C::TEXT_PAD, C::MIDDLE_Y_START, C::TEXT_PAD, C::MIDDLE_HEIGHT, 0);
    _set_update_flag();
}

void Display::_display_line_bottom() {
    if (!_display_ready) return; // R6
    _display.fillRect(0, C::BOTTOM_LINE_Y_START, C::SCREEN_W, 1, 1);
    _set_update_flag();
}

void Display::show_text_bottom(const String &text, bool value_only, int start_x, int text_width_px) {
    if (!_display_ready) return; // R6
    const int char_height = 8;
    const int bottom_y_start = 40;

    if (value_only && start_x > 0) {
        _display.fillRect(start_x, bottom_y_start, text_width_px, char_height, C::BKG_COLOR);
        _text(text, start_x, bottom_y_start, C::TXT_COLOR);
    } else {
        _display.fillRect(0, bottom_y_start, C::SCREEN_W, char_height, C::BKG_COLOR);
        _text(text, C::TEXT_PAD, bottom_y_start, C::TXT_COLOR);
    }
    _set_update_flag();
}

// --- Bottom status strip --------------------------------------------------
// Rows 54-63: [transport icons][mode glyph][BPM][nav/lock badge]. Every entry
// point clears its own rect before drawing, so the last writer wins.

void Display::draw_transport_icons(bool any_loop_playing, bool recording, bool armed_blink_on) {
    if (!_display_ready) return; // R6
    const int16_t y = C::BOTTOM_LEFT_Y_START; // 54; band is 10 px tall
    _display.fillRect(C::BOTTOM_LEFT_X_START, y,
                      C::BOTTOM_LEFT_WIDTH, C::BOTTOM_LEFT_HEIGHT, C::BKG_COLOR);

    // Icons sit 2 px below the separator line (rows 56-62, 7 px tall) so they
    // don't crowd it, and align with the strip's text baseline (y 56).
    if (any_loop_playing) { // play triangle, x 2-8
        _display.fillTriangle(2, y + 2, 2, y + 8, 8, y + 5, C::TXT_COLOR);
    }
    if (recording || armed_blink_on) { // rec circle, x 16-22 (armed = caller blinks it)
        _display.fillCircle(19, y + 5, 3, C::TXT_COLOR);
    }
    _set_update_flag();
}

// 8x8 sync glyph: two circular arrows chasing each other clockwise (universal
// "following external clock" symbol). Point-symmetric — top arc runs right into
// a down-pointing head, bottom arc runs left into an up-pointing head.
static const uint8_t SYNC_BMP[8] = {0x3C, 0x42, 0x07, 0x02, 0x40, 0xE0, 0x42, 0x3C};

// 8x8 quarter note: the sheet-music tempo marking ("♩=120") labels the number
// as BPM in 8 px where literal "BPM" text would need 18. Stem up the right
// side, filled head bottom-left.
static const uint8_t NOTE_BMP[8] = {0x04, 0x04, 0x04, 0x04, 0x04, 0x3C, 0x7C, 0x78};

void Display::draw_bpm(int bpm, bool ext_sync) {
    if (!_display_ready) return; // R6
    _display.fillRect(C::BPM_X_START, C::BOTTOM_LEFT_Y_START,
                      C::BPM_WIDTH, C::BOTTOM_LEFT_HEIGHT, C::BKG_COLOR);
    draw_bpm_pulse(true); // solid glyph; the recording beat-blink toggles it
    String text = String(bpm);
    _text(text, C::BPM_X_START + C::BPM_GLYPH_W, C::SCREEN_H - C::LINEHEIGHT, C::TXT_COLOR);
    if (ext_sync) {
        _display.drawBitmap(C::BPM_X_START + C::BPM_GLYPH_W + (int16_t)text.length() * 6 + 3,
                            C::SCREEN_H - C::LINEHEIGHT, SYNC_BMP, 8, 8, C::TXT_COLOR);
    }
    _set_update_flag();
}

// Beat blink while recording: the note glyph appears on the beat and blanks
// between beats (solid when not recording). Redraws only the glyph's 8x8 cell —
// called from the status-strip poll, so it must stay cheap and never touches
// the number or sync glyph.
void Display::draw_bpm_pulse(bool visible) {
    if (!_display_ready) return; // R6
    const int16_t x = C::BPM_X_START;
    const int16_t y = C::SCREEN_H - C::LINEHEIGHT;
    _display.fillRect(x, y, 8, 8, C::BKG_COLOR);
    if (visible) {
        _display.drawBitmap(x, y, NOTE_BMP, 8, 8, C::TXT_COLOR);
    }
    _set_update_flag();
}

void Display::toggle_navmode_icon(bool on_or_off, const String &label) {
    if (label.length()) {
        _nav_label = label;
    }
    _nav_badge_on = on_or_off;
    // Headless (R6): skip framebuffer writes but keep the encoder-pixel side effects
    if (on_or_off) {
        if (_display_ready) {
            _draw_nav_badge();
            _set_update_flag();
        }
        pixels.encoder_button_on();
    } else {
        if (_display_ready) {
            int16_t w = (int16_t)_nav_label.length() * 6 + 6;
            _display.fillRect(C::SCREEN_W - w, 0, w, 12, 0);
            _set_update_flag();
        }
        pixels.encoder_button_off();
    }
}

// 8x8 padlock: shackle over a solid body with a keyhole notch.
static const uint8_t PADLOCK_BMP[8] = {0x3C, 0x42, 0x42, 0xFF, 0xFF, 0xE7, 0xE7, 0xFF};

void Display::toggle_lock_icon(bool on_or_off, bool nav_mode_on) {
    // Headless (R6): skip framebuffer writes but keep the encoder-pixel side effects
    if (on_or_off) {
        if (_display_ready) {
            _display.fillRect(C::NAV_ICON_X_START, C::SCREEN_H - C::LINEHEIGHT - 2, C::NAV_MSG_WIDTH, 10, 1);
            _display.drawBitmap(C::NAV_ICON_X_START + (C::NAV_MSG_WIDTH - 8) / 2,
                                C::SCREEN_H - C::LINEHEIGHT - 1, PADLOCK_BMP, 8, 8, 0);
            _set_update_flag();
        }
        pixels.encoder_button_on(C::ENCODER_LOCK_COLOR);
    } else {
        if (_display_ready) {
            _display.fillRect(C::NAV_ICON_X_START, C::SCREEN_H - C::LINEHEIGHT - 2, C::NAV_MSG_WIDTH, 10, 0);
            _set_update_flag();
        }
        if (nav_mode_on) {
            pixels.encoder_button_on(C::NAV_MODE_COLOR);
            toggle_navmode_icon(true);
        } else {
            pixels.encoder_button_off();
        }
    }
}

void Display::update_playmode_icon(const char *playmode) {
    if (!_display_ready) return; // R6

    String pm = playmode ? String(playmode) : settings.play_mode;

    // Loop mode is the default state and draws nothing; ARP/VEL get a single
    // inverted-box glyph (2026-07-12 UI review: the old "(LOOP)" text added no
    // information and its slot now holds the BPM readout).
    _display.fillRect(C::MODE_GLYPH_X_START, C::BOTTOM_LEFT_Y_START,
                      C::MODE_GLYPH_WIDTH, C::BOTTOM_LEFT_HEIGHT, C::BKG_COLOR);
    const char *glyph = nullptr;
    if (pm == "encoder") glyph = "A";
    else if (pm == "velocity") glyph = "V";

    if (glyph) {
        _display.fillRect(C::MODE_GLYPH_X_START, C::BOTTOM_LEFT_Y_START,
                          C::MODE_GLYPH_WIDTH, C::BOTTOM_LEFT_HEIGHT, C::TXT_COLOR);
        _text(glyph, C::MODE_GLYPH_X_START + 2, C::SCREEN_H - C::LINEHEIGHT, C::BKG_COLOR);
    }
    _set_update_flag();
}

void Display::show_notification(const String &msg, bool force_display) {
    if (msg.length() == 0) {
        return;
    }

    uint32_t time_now = ticks::ticks_ms();
    if ((uint32_t)(time_now - notification_fps_timer) > C::NOTIFICATION_METERING_THRESH_MS || force_display) {
        notification_text = msg;
        show_text_top(msg, true, force_display);
        notification_on_time = time_now;
        notification_fps_timer = time_now;
    }
}

void Display::clear_notifications(const String &replace_text) {
    if (notification_text.length() == 0 || replace_text.length() == 0) {
        return;
    }
    if (notification_text == replace_text) {
        return;
    }
    if ((uint32_t)(ticks::ticks_ms() - notification_on_time) > C::NOTIFICATION_THRESH_MS) {
        notification_on_time = 0;
        notification_text = "";
        show_text_top(replace_text);
    }
}

void Display::show_fullscreen_message(const String &line1, const String &line2) {
    if (!_display_ready) return; // R6
    _display.clearDisplay();
    // Center the 1-2 line block both ways so the message reads as a modal state,
    // not a menu screen (6 px/char at text size 1).
    uint8_t num_lines = line2.length() ? 2 : 1;
    int16_t y = (C::SCREEN_H - num_lines * C::LINEHEIGHT) / 2;
    int16_t x1 = (C::SCREEN_W - (int16_t)line1.length() * 6) / 2;
    _text(line1, x1 > 0 ? x1 : 0, y, C::TXT_COLOR);
    if (line2.length()) {
        int16_t x2 = (C::SCREEN_W - (int16_t)line2.length() * 6) / 2;
        _text(line2, x2 > 0 ? x2 : 0, y + C::LINEHEIGHT, C::TXT_COLOR);
    }
    // Post-offload path: never push directly (core 1 owns Wire1). Set the dirty flag
    // and let core1_push() send it — callers must delay long enough before rebooting.
    _set_update_flag();
}

// After a full-screen takeover blanked the panel: restore the static bottom-strip
// chrome (divider line + play-mode glyph). Transport/BPM repaint separately via the
// status-strip poll, and Menu::initialize() rebuilds the top + middle bands.
void Display::redraw_bottom_chrome() {
    _display_line_bottom();
    update_playmode_icon();
}

void Display::show_startup_screen() {
    if (!_display_ready) return; // R6: clearDisplay() memsets a null framebuffer when init failed
    _display.clearDisplay();
    _display_line_bottom();
    show_text_top("DJBB MIDI LOOPSTER", false);
    show_text_middle("Loading " + settings.get_startup_preset() + "...");
    _display.display();
    delay(800);
}
