// Port of src/pixels.py — NeoPixel manager with blink, flash, and velocity mapping.
// Python dicts (flashing_pixels/default_colors/blink_colors) -> fixed per-pixel arrays.
// A shadow buffer of logical colors preserves Python's exact-compare semantics
// (Adafruit_NeoPixel::getPixelColor is lossy after setBrightness).
// flash_pixel keeps its float-seconds duration API so call sites match the Python.
#pragma once
#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include "constants.h"

class DisplayPixels {
public:
    DisplayPixels();

    void begin(); // hardware init; call from setup()
    // Re-read settings.led_brightness into the strip. begin() runs before the
    // startup preset loads, so main.cpp calls this again after load.
    void apply_brightness();

    volatile bool pixels_need_update = true;
    // Once main.cpp flips this, core 1 owns _strip.show() (via update() in loop1);
    // core 0 only writes colors + sets the dirty flag. Two cores feeding the same
    // PIO state machine concurrently would corrupt the LED stream.
    volatile bool core1_owns_pixels = false;
    bool blink_phase = false; // global on/off phase for all blinks (keeps them in sync)
    uint32_t update_interval_ms = C::PIXEL_UPDATE_INTERVAL_MS; // fixed core-1 show cadence (Item 3: no load backoff)

    void set_note_on(uint8_t pad_idx, uint8_t velocity = 120);
    void set_note_off(uint8_t pad_idx);
    void set_fn_button_on(C::Rgb color = C::BLUE);
    void set_fn_button_off();
    void encoder_button_on(C::Rgb color = C::NAV_MODE_COLOR);
    void encoder_button_off();
    void set_blink(uint8_t pad_idx, bool on_or_off = true, C::Rgb color = C::RED);
    void set_color(uint8_t pad_idx, C::Rgb color);
    void process_blinks(bool force_update = false, uint32_t blink_time_ms = C::PIXEL_BLINK_TIME_MS);
    C::Rgb get_default_color(uint8_t pad_idx) const;
    void set_default_color(uint8_t pad_idx, C::Rgb color = C::BLACK, bool has_color = false);
    void clear_all();
    void flash_pixel(uint8_t pad_idx, float duration_s, C::Rgb color = C::WHITE);
    void update();
    void display_velocity_map(bool on_or_off = true);
    bool get_update_pending_flag() const { return pixels_need_update; }
    void set_needs_update(bool yes_or_no = true) { pixels_need_update = yes_or_no; }
    void indicate_preset_loading(bool is_loading = true);

private:
    Adafruit_NeoPixel _strip;
    C::Rgb _shadow[C::NUM_PIXELS] = {};      // logical colors (exact-compare source of truth)

    // Per-pixel state (replaces Python dicts)
    uint8_t _pixel_states[C::NUM_PIXELS] = {}; // bit 0: blink state
    bool _has_default[C::NUM_PIXELS] = {};
    C::Rgb _default_colors[C::NUM_PIXELS] = {};
    C::Rgb _blink_colors[C::NUM_PIXELS] = {};
    struct Flash {
        // `active` is the publish flag: core 0 fills start_ms/duration_ms/color
        // first and sets active LAST, so core 1's update() never reads a torn entry
        // (item 24). volatile keeps the compiler from reordering/caching the flag.
        volatile bool active = false;
        uint32_t start_ms = 0;
        uint32_t duration_ms = 0;
        C::Rgb color = {};
    };
    Flash _flashing[C::NUM_PIXELS];

    uint32_t _pixel_blink_timer = 0;
    bool _velocity_map_initialized = false;
    C::Rgb _velocity_map_colors[C::NUM_PADS] = {};

    void _write(uint8_t pixel_idx, C::Rgb color); // shadow + hardware
    uint8_t _get_pixel(uint8_t index) const { return C::PAD_TO_PIXEL_IDX_MAP[index]; }
    void _initialize_velocity_map(float global_brightness_factor = 0.5f);
    C::Rgb _get_velocity_map_color(uint8_t pad_idx);
    static C::Rgb _interpolate_color(C::Rgb c1, C::Rgb c2, float factor);
    static C::Rgb _scale_brightness(C::Rgb color, float factor);
};

extern DisplayPixels pixels;
