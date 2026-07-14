// Port of src/constants.py — same names, same grouping, for side-by-side diffing.
// Time values: Python used float seconds; here everything is uint32_t milliseconds
// (suffix _MS replaces _S) per the conversion rules in .claude/library-map.md.
#pragma once
#include <Arduino.h>

namespace C {

// ------ CORE ------ //
constexpr uint8_t NUM_PADS = 16;
constexpr bool VELOCITY_MODE_ENABLED = false; // or auto-enabled by preset
constexpr uint8_t NUM_PIXELS = 18;
constexpr uint8_t FN_LED_IDX = 16;
constexpr uint8_t ENC_LED_IDX = 17;

// ------ MENU INDICES ------ //
constexpr uint8_t MENU_PLAY = 0;
constexpr uint8_t MENU_MIDI = 2;

// ------ PIN SETUP ------ //

// Display I2C pins (GP18/19 = I2C1 -> Wire1)
constexpr uint8_t PIN_SCL = 19;
constexpr uint8_t PIN_SDA = 18;

// Pad matrix (keypad.KeyMatrix equivalent; columns_to_anodes=True)
constexpr uint8_t PAD_ROW_PINS[4] = {4, 3, 2, 1};
constexpr uint8_t PAD_COL_PINS[4] = {5, 6, 7, 8};

// Encoder pins
constexpr uint8_t PIN_FN_BTN = 10;
constexpr uint8_t PIN_ENCODER_BTN = 11;
constexpr uint8_t PIN_ENCODER_CLK = 12;
constexpr uint8_t PIN_ENCODER_DT = 13;

// MIDI pins (GP16/17 = UART0 -> Serial1) and settings
constexpr uint8_t PIN_UART_MIDI_TX = 16;
constexpr uint8_t PIN_UART_MIDI_RX = 17;

// NeoPixel data pin (main strip)
constexpr uint8_t PIN_PIXELS = 15;

// Pad channel mode values (for midi_channel_pad_mapping)
// -1 = As Recorded (use per-note stored channel during playback, global for live)
// -2 = Global (always use current midi_channel_out dynamically)
// 0-15 = specific channel override
constexpr int8_t PAD_CH_AS_RECORDED = -1;
constexpr int8_t PAD_CH_GLOBAL = -2;

// Event limits — in C++ these are static buffer sizes, not fragmentation workarounds
constexpr uint16_t LOOP_NOTES_LIMIT = 512;   // 512 note-ons = ~256 actual notes
// Per-loop CC (and aftertouch) event cap. 1024 is generous for real control sources —
// knobs/faders/pedals rarely exceed a few hundred stored events (only changes past
// cc_resolution are kept). At ~5.4 KB per maxed loop it lets ~14 pads hold dense CC loops
// before the recording heap floor bites (2048 allowed only ~8). Raise toward 2048 if you
// need to capture >~10 s of continuous accelerometer motion in a single loop.
constexpr uint16_t CC_EVENTS_LIMIT = 1024;
// Global RAM budget (item 1): a REAL guard, not the old 99999 (~500 KB, unreachable).
// Each event is ~5 B in RAM; 20,000 events ≈ 100 KB, comfortable on the 264 KB RP2040
// after items 6/7 freed headroom. Enforced live while recording (add_note/add_cc/
// add_aftertouch, counting the recording loop against the finalized total) and on preset
// load (file headers give exact counts before reading, so an over-budget pad is skipped).
// A failed allocation on this platform = panic, so the rule is: refuse before allocating.
constexpr uint32_t TOTAL_LOOP_EVENTS_LIMIT = 20000;
// Secondary guard: coarse free-heap floor checked only at checkpoints (before a loop-file
// load, before opening a JsonDocument to save). Covers bounded JSON/String spikes the event
// budget doesn't. free != contiguous, so this is a tripwire against exhaustion, not a budget.
constexpr uint32_t HEAP_FLOOR_BYTES = 32 * 1024;
// Higher floor for STARTING a new recording. On-device stress testing (2026-07-05) showed
// each fully-maxed loop costs ~10.85 KB and the heap panics from fragmentation around ~55 KB
// free — while getFreeHeap() still reports it as free (free != contiguous). Because a
// single recording's growth is bounded by the per-loop caps (~11-23 KB), refusing to START
// a recording below this floor keeps the heap out of the fragmentation panic zone entirely,
// so an over-full instrument shows "Low Memory" instead of a panic + watchdog reboot.
constexpr uint32_t RECORDING_HEAP_FLOOR_BYTES = 72 * 1024;
// Recording vectors grow in fixed chunks instead of doubling, so a large loop never needs a
// transient 2x-size block mid-set (fragmentation containment; item 1).
constexpr size_t EVENT_RESERVE_CHUNK = 256;

// Default velocities for single note mode
constexpr uint8_t DEFAULT_SINGLENOTE_MODE_VELOCITIES[16] = {
    8, 15, 22, 29, 36, 43, 50, 57, 64, 71, 78, 85, 92, 99, 106, 127
};

// ------ SCREEN CONFIGURATION ------ //
constexpr int16_t SCREEN_W = 128;
constexpr int16_t SCREEN_H = 64;

// Screen sections
constexpr int16_t TOP_HEIGHT = 16;
constexpr int16_t MIDDLE_Y_START = 24;
constexpr int16_t MIDDLE_HEIGHT = 28;
constexpr int16_t BOTTOM_LINE_Y_START = 53;

// Text settings
constexpr int16_t LINEHEIGHT = 8;
constexpr int16_t TEXT_PAD = 7;
constexpr int16_t NAV_MSG_WIDTH = 38;
constexpr int16_t NAV_ICON_X_START = 90;
constexpr int16_t PADDING = 4;

// Bottom status strip (rows 54-63), left to right:
//   [transport icons 0-29][mode glyph 34-43][BPM(+EXT) 48-89][nav/lock badge 90-127]
constexpr int16_t BOTTOM_LEFT_X_START = 0;
constexpr int16_t BOTTOM_LEFT_Y_START = BOTTOM_LINE_Y_START + 1;      // = 54
constexpr int16_t BOTTOM_LEFT_WIDTH = 30;                             // transport icons (play + rec)
constexpr int16_t BOTTOM_LEFT_HEIGHT = SCREEN_H - BOTTOM_LEFT_Y_START; // = 10
constexpr int16_t MODE_GLYPH_X_START = 34;  // inverted A/V box; loop mode draws nothing
constexpr int16_t MODE_GLYPH_WIDTH = 10;
constexpr int16_t BPM_X_START = 48;         // note glyph + "120" + 8px sync glyph (max 39 px)
constexpr int16_t BPM_WIDTH = 42;
constexpr int16_t BPM_GLYPH_W = 10;         // 8px quarter-note glyph + 2px gap before the number

// ------ COLORS ------ //
struct Rgb {
    uint8_t r, g, b;
};

constexpr bool operator==(const Rgb &a, const Rgb &b) {
    return a.r == b.r && a.g == b.g && a.b == b.b;
}
constexpr bool operator!=(const Rgb &a, const Rgb &b) {
    return !(a == b);
}

// Basic colors
constexpr Rgb RED = {255, 0, 0};
constexpr Rgb GREEN = {0, 245, 0};
constexpr Rgb BLUE = {0, 0, 255};
constexpr Rgb WHITE = {255, 255, 255};
constexpr Rgb BLACK = {0, 0, 0};

// Additional colors
constexpr Rgb YELLOW = {255, 255, 0};
constexpr Rgb ORANGE = {255, 165, 0};
constexpr Rgb DARK_CYAN = {0, 50, 50};
constexpr Rgb LIGHT_BLUE = {173, 216, 230};
constexpr Rgb PURPLE = {180, 0, 255};

// Visual feedback colors
constexpr Rgb OFF_COLOR = {0, 0, 0};
constexpr Rgb CC_COLOR = BLUE;
constexpr Rgb PASSTHRU_COLOR = {0, 128, 128};

// ------ NEOPIXEL SETTINGS ------ //
constexpr uint8_t PAD_TO_PIXEL_IDX_MAP[18] = {13, 14, 15, 16, 9, 10, 11, 12, 5, 6, 7, 8, 1, 2, 3, 4, 0, 17};
constexpr uint32_t PIXEL_BLINK_TIME_MS = 250;
constexpr uint32_t PIXEL_UPDATE_INTERVAL_MS = 16; // ~60 fps fixed (core 1 owns show(); no load backoff — Item 3)
constexpr Rgb FN_BUTTON_COLOR = ORANGE;
constexpr Rgb PIXEL_LOOP_PLAYING_COLOR = GREEN;
constexpr Rgb NOTE_COLOR = ORANGE;
constexpr Rgb NAV_MODE_COLOR = LIGHT_BLUE;
// Purple, not red: red is reserved for "recording" on this device (pads + panic flash).
constexpr Rgb ENCODER_LOCK_COLOR = PURPLE;
constexpr uint16_t BKG_COLOR = 0; // SSD1306 framebuffer colors
constexpr uint16_t TXT_COLOR = 1;
constexpr uint32_t DISPLAY_PUSH_MIN_INTERVAL_MS = 50; // core-1 OLED push cap (~20 fps; one push is ~25 ms of I2C)
constexpr Rgb LOOP_COLOR = {20, 0, 20};
constexpr Rgb PAD_HELD_COLOR = DARK_CYAN;

// ------ ASSORTED SETTINGS ------ //
constexpr uint32_t NAV_BUTTONS_POLL_MS = 20;
constexpr uint32_t BUTTON_HOLD_THRESH_MS = 350;
constexpr uint32_t ENCODER_HOLD_THRESH_MS = 300;
constexpr uint32_t FN_HOLD_THRESH_MS = 100;
constexpr uint32_t NOTIFICATION_METERING_THRESH_MS = 33; // Item 5: core 1 already caps pushes at 50 ms, so this no longer gates; ~30 fps top-line
constexpr uint32_t DBL_PRESS_THRESH_MS = 400;
constexpr uint32_t NOTIFICATION_THRESH_MS = 1500;
// PANIC chord: FN + encoder both held this long -> stop all loops + all-notes-off.
// Well past the hold thresholds (100/300 ms) so context-hold gestures and slow
// bank-chord taps can never trip it accidentally (user call 2026-07-12: 2 s).
constexpr uint32_t PANIC_HOLD_MS = 2000;
// Max stored user presets (item 18). Boot loads the whole presets.json into a JsonDocument
// twice; unbounded preset growth eventually OOMs at boot. Creating a new preset past this cap
// is refused (on-device *NEW* save + web SET_PRESET); overwriting an existing one is fine.
constexpr int MAX_PRESETS = 16;
constexpr const char *PRESETS_FILEPATH = "/presets.json";
// Atomic-write staging file: writers serialize to here, then remove(real)+rename(tmp->real).
// Boot-side recovery renames a stranded tmp into place if power died between those two steps.
constexpr const char *PRESETS_TMP_FILEPATH = "/presets_tmp.json";
constexpr uint8_t PAD_OFFSET_AMOUNT = 4;
constexpr uint8_t DEFAULT_LOOP_PAD_IDX = 255;
constexpr uint32_t CC_ONLY_LOOP_LENGTH_MS = 500;
constexpr uint32_t MS_PER_SECOND = 1000;
constexpr uint8_t VELOCITY_CHANGE_DISPLAY_THRESH = 5;

// ============================================================================
// ============================= COLM USER ADDONS =============================
// ============================================================================

// ------ FEATURE FLAGS ------ //
constexpr bool USING_FOOT_PEDALS = true;
constexpr bool USING_GLOVE_BUTTONS = true;
constexpr bool USING_ACCELEROMETER = true;

// ------ ACCELEROMETER SETTINGS ------ //
// GPIO pins for accelerometer I2C (GP20/21 = I2C0 -> Wire; separate from display I2C)
constexpr uint8_t PIN_ACCEL_I2C_SCL = 21;
constexpr uint8_t PIN_ACCEL_I2C_SDA = 20;

// Accelerometer tilt-based CC numbers
constexpr uint8_t ACCEL_LEFT_TILT_CC = 1;      // modulation wheel
constexpr uint8_t ACCEL_RIGHT_TILT_CC = 74;    // filter cutoff
constexpr uint8_t ACCEL_BACKWARD_TILT_CC = 7;  // volume

// Accelerometer processing settings
// EWMA smoothing: prev = factor*new + (1-factor)*prev  (1 = no smoothing).
// Item 4: sample rate raised 20 Hz -> 100 Hz. At a fixed factor, 5x faster
// sampling shortens the real-time filter constant ~5x, letting more single-sample
// jitter through. Dropping factor 0.8 -> 0.5 keeps the filter well-damped
// (time-constant ~14 ms vs the old ~31 ms) — snappier AND smoother, since 5x
// oversampling rejects spikes better. CC flooding is bounded by the value-change
// gate below (emits per integer step of motion, not per sample) + midi.cpp dedupe.
constexpr float ACCEL_SMOOTH_FACTOR = 0.5f;
constexpr uint32_t ACCEL_UPDATE_INTERVAL_MS = 10; // 100 Hz; MPU read is one burst on I2C0 (separate from display bus)

// Accelerometer switch/enable pin (A3 = GP29)
constexpr uint8_t PIN_ACCEL_ENABLE = 29;

// Accelerometer tilt settings
constexpr float ACCEL_DEADZONE_DEGREES = 10.0f;
constexpr float ACCEL_MAX_TILT_DEGREES = 90.0f;

// Accelerometer arpeggiator control settings
constexpr float ACCEL_ARP_MAX_TILT_DEGREES = 90.0f;
constexpr uint32_t ACCEL_ARP_MIN_INTERVAL_MS = 50;
constexpr uint32_t ACCEL_ARP_MAX_INTERVAL_MS = 1000;

// ------ GLOVE BUTTON SETTINGS ------ //
constexpr uint8_t PIN_GLOVE_LEFT = 23;
constexpr uint8_t PIN_GLOVE_RIGHT = 24;
constexpr uint32_t GLOVE_DEBOUNCE_TIME_MS = 20;

// ------ PEDAL SETTINGS ------ //
constexpr uint8_t PIN_PEDAL_1 = 9;
constexpr uint8_t PIN_PEDAL_2 = 0;
constexpr uint8_t PIN_PEDAL_3 = 26; // A0, used as digital
constexpr uint8_t PIN_PEDAL_4 = 27; // A1, used as digital
constexpr uint8_t PIN_PEDAL_5 = 22;
constexpr uint8_t PIN_PEDAL_NEOPIXEL = 14;
constexpr uint8_t PEDAL_COUNT = 5;
constexpr float PEDAL_BRIGHTNESS = 1.0f;

// ------ ACCELEROMETER CALIBRATION SETTINGS ------ //
constexpr uint32_t ACCEL_CALIBRATION_NEUTRAL_TIME_MS = 3000;
constexpr uint32_t ACCEL_CALIBRATION_MOVEMENT_TIME_MS = 20000;
constexpr uint32_t ACCEL_CALIBRATION_DISPLAY_UPDATE_MS = 3000;
constexpr uint32_t ACCEL_DOUBLE_TOGGLE_WINDOW_MS = 1000;

// Accelerometer adaptive mode settings
constexpr uint32_t ACCEL_MODE_HOLD_DURATION_MS = 1500;
constexpr uint8_t ACCEL_STABLE_MODE_THRESHOLD = 4;
constexpr uint8_t ACCEL_CHANGING_MODE_THRESHOLD = 1;
constexpr uint8_t ACCEL_STABILITY_BUFFER_SIZE = 3;
constexpr uint8_t ACCEL_MAX_STABILITY_VARIATION = 4;

} // namespace C
