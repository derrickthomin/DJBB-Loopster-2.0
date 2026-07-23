#include "pixels.h"
#include "settings.h"
#include "pedals.h"
#include "ticks.h"

DisplayPixels pixels;

DisplayPixels::DisplayPixels()
    : _strip(C::NUM_PIXELS, C::PIN_PIXELS, NEO_GRB + NEO_KHZ800) {}

void DisplayPixels::begin() {
    _strip.begin();
    _strip.setBrightness((uint8_t)(settings.led_brightness * 255));
    _strip.clear();
    _strip.show();
}

void DisplayPixels::apply_brightness() {
    _strip.setBrightness((uint8_t)(settings.led_brightness * 255));
    set_needs_update(); // repush existing colors at the new brightness
}

void DisplayPixels::_write(uint8_t pixel_idx, C::Rgb color) {
    _shadow[pixel_idx] = color;
    _strip.setPixelColor(pixel_idx, color.r, color.g, color.b);
}

void DisplayPixels::set_note_on(uint8_t pad_idx, uint8_t velocity) {
    C::Rgb color = _scale_brightness(C::NOTE_COLOR, velocity / 127.0f);
    _write(_get_pixel(pad_idx), color);
    if (C::USING_FOOT_PEDALS) {
        pedals.set_pixel_on(pad_idx, color);
    }
    set_needs_update();
}

void DisplayPixels::set_note_off(uint8_t pad_idx) {
    set_needs_update();
    C::Rgb color;
    if (settings.velocity_mapped) {
        color = _get_velocity_map_color(pad_idx);
    } else {
        color = get_default_color(pad_idx);
    }
    _write(_get_pixel(pad_idx), color);
    if (C::USING_FOOT_PEDALS) {
        pedals.set_pixel_on(pad_idx, color);
    }
}

void DisplayPixels::set_fn_button_on(C::Rgb color) {
    if (_shadow[0] != color) { // pixel 0 = FN LED (PAD_TO_PIXEL_IDX_MAP[16])
        _write(0, color);
        set_needs_update();
    }
}

void DisplayPixels::set_fn_button_off() {
    if (_shadow[0] != C::BLACK) {
        _write(0, C::BLACK);
        set_needs_update();
    }
}

void DisplayPixels::encoder_button_on(C::Rgb color) {
    if (_shadow[C::ENC_LED_IDX] != color) {
        _write(C::ENC_LED_IDX, color);
        set_needs_update();
    }
}

void DisplayPixels::encoder_button_off() {
    if (_shadow[C::ENC_LED_IDX] != C::BLACK) {
        _write(C::ENC_LED_IDX, C::BLACK);
        set_needs_update();
    }
}

void DisplayPixels::set_blink(uint8_t pad_idx, bool on_or_off, C::Rgb color) {
    set_needs_update();
    uint8_t pixel_idx = (pad_idx < C::ENC_LED_IDX) ? _get_pixel(pad_idx) : pad_idx;

    if (!on_or_off) {
        _pixel_states[pad_idx] &= ~0x01;
        _write(pixel_idx, get_default_color(pad_idx));
        _blink_colors[pad_idx] = C::RED; // reset to Python's .get() default
    } else {
        _pixel_states[pad_idx] |= 0x01;
        _blink_colors[pad_idx] = color;
        // Immediately sync to current global phase so all blinks are in sync
        _write(pixel_idx, blink_phase ? color : C::BLACK);
    }
}

void DisplayPixels::set_color(uint8_t pad_idx, C::Rgb color) {
    set_needs_update();
    _write(_get_pixel(pad_idx), color);
    if (C::USING_FOOT_PEDALS) {
        pedals.set_pixel_on(pad_idx, color);
    }
}

void DisplayPixels::process_blinks(bool force_update, uint32_t blink_time_ms) {
    uint32_t now = ticks::ticks_ms();

    bool has_blinking = false;
    for (uint8_t i = 0; i < C::NUM_PIXELS; i++) {
        if (_pixel_states[i] & 0x01) {
            has_blinking = true;
            break;
        }
    }

    if (has_blinking && (uint32_t)(now - _pixel_blink_timer) > blink_time_ms) {
        blink_phase = !blink_phase; // toggle global phase (all blinks stay in sync)

        for (uint8_t i = 0; i < C::NUM_PIXELS; i++) {
            if (_pixel_states[i] & 0x01) {
                set_needs_update();
                C::Rgb pixel_color = blink_phase ? _blink_colors[i] : C::BLACK;
                _write(_get_pixel(i), pixel_color);
                if (C::USING_FOOT_PEDALS) {
                    pedals.set_pixel_on(i, pixel_color);
                }
            }
        }

        // force_update is only honored single-core (blocking preset load before
        // offload, drive mode). Once core 1 owns the strip it shows within one
        // PIXEL_UPDATE_INTERVAL_MS anyway, and a core-0 show() would race it.
        if (force_update && !core1_owns_pixels) {
            update();
        }
        _pixel_blink_timer = now;
    }
}

C::Rgb DisplayPixels::get_default_color(uint8_t pad_idx) const {
    return _has_default[pad_idx] ? _default_colors[pad_idx] : C::BLACK;
}

void DisplayPixels::set_default_color(uint8_t pad_idx, C::Rgb color, bool has_color) {
    set_needs_update();

    C::Rgb display_color;
    if (has_color) {
        display_color = color;
    } else if (settings.velocity_mapped) {
        display_color = _get_velocity_map_color(pad_idx);
    } else {
        display_color = C::BLACK;
    }

    // Only store non-BLACK colors (matches Python's memory-saving del)
    if (display_color == C::BLACK) {
        _has_default[pad_idx] = false;
    } else {
        _has_default[pad_idx] = true;
        _default_colors[pad_idx] = display_color;
    }
}

void DisplayPixels::clear_all() {
    for (uint8_t i = 0; i < C::NUM_PIXELS; i++) {
        _write(i, C::BLACK);
        if (C::USING_FOOT_PEDALS) {
            pedals.set_pixel_on(i, C::BLACK);
        }
        _has_default[i] = false;
        _pixel_states[i] = 0;
        _flashing[i].active = false;
    }
    set_needs_update();
}

void DisplayPixels::flash_pixel(uint8_t pad_idx, float duration_s, C::Rgb color) {
    uint32_t duration_ms = (uint32_t)(duration_s * 1000.0f);
    Flash &f = _flashing[pad_idx];

    if (f.active && f.color == color) {
        // Same color — re-up timer but skip hardware update.
        // Known benign race (R17): core 1's update() can be past its expiry check when we
        // re-up here, so its `active = false` may clobber this re-up. Worst case the flash
        // ends one frame early (~1 frame visual glitch); accepted, not worth a lock.
        f.start_ms = ticks::ticks_ms();
        f.duration_ms = duration_ms;
        return;
    }

    // Fill data fields BEFORE publishing via active=true, so core 1's update()
    // can't observe a half-written entry (item 24).
    f.start_ms = ticks::ticks_ms();
    f.duration_ms = duration_ms;
    f.color = color;
    __asm__ __volatile__("" ::: "memory"); // compiler barrier: no reorder past active
    f.active = true;
    set_color(pad_idx, color);
    set_needs_update();
}

void DisplayPixels::update() {
    uint32_t now = ticks::ticks_ms();

    for (uint8_t pad_idx = 0; pad_idx < C::NUM_PIXELS; pad_idx++) {
        Flash &f = _flashing[pad_idx];
        if (!f.active || (uint32_t)(now - f.start_ms) < f.duration_ms) {
            continue;
        }
        C::Rgb default_color = get_default_color(pad_idx);
        uint8_t pixel_idx = (pad_idx < C::ENC_LED_IDX) ? _get_pixel(pad_idx) : pad_idx;

        // Only update if current hardware color differs from default (prevents
        // races where another code path set the color)
        if (_shadow[pixel_idx] != default_color) {
            set_color(pad_idx, default_color);
        }
        f.active = false;
    }

    if (get_update_pending_flag()) {
        // Clear BEFORE show(): a core-0 color write during the show re-dirties
        // the flag and gets pushed next pass (no lost updates across cores).
        set_needs_update(false);
        _strip.show();
        if (C::USING_FOOT_PEDALS) {
            pedals.show_pedal_pixels();
        }
    }
}

void DisplayPixels::_initialize_velocity_map(float global_brightness_factor) {
    if (_velocity_map_initialized) {
        return;
    }
    C::Rgb orange = {255, 165, 0};
    C::Rgb red = {255, 0, 0};

    for (uint8_t i = 0; i < C::NUM_PADS; i++) {
        float color_factor = i / 15.0f;
        float brightness_factor = ((i + 1) / 16.0f) * global_brightness_factor;
        _velocity_map_colors[i] = _scale_brightness(_interpolate_color(orange, red, color_factor), brightness_factor);
    }
    _velocity_map_initialized = true;
}

void DisplayPixels::display_velocity_map(bool on_or_off) {
    set_needs_update();

    if (on_or_off) {
        _initialize_velocity_map();
        for (uint8_t i = 0; i < C::NUM_PADS; i++) {
            C::Rgb color = _velocity_map_colors[i];
            set_default_color(i, color, true);
            _write(_get_pixel(i), color);
        }
    } else {
        for (uint8_t i = 0; i < C::NUM_PADS; i++) {
            set_default_color(i, C::BLACK, true);
            _write(_get_pixel(i), C::BLACK);
        }
    }
}

C::Rgb DisplayPixels::_get_velocity_map_color(uint8_t pad_idx) {
    _initialize_velocity_map();
    return _velocity_map_colors[pad_idx];
}

C::Rgb DisplayPixels::_interpolate_color(C::Rgb c1, C::Rgb c2, float factor) {
    return {
        (uint8_t)(c1.r + (c2.r - c1.r) * factor),
        (uint8_t)(c1.g + (c2.g - c1.g) * factor),
        (uint8_t)(c1.b + (c2.b - c1.b) * factor),
    };
}

C::Rgb DisplayPixels::_scale_brightness(C::Rgb color, float factor) {
    return {
        (uint8_t)(color.r * factor),
        (uint8_t)(color.g * factor),
        (uint8_t)(color.b * factor),
    };
}

void DisplayPixels::indicate_preset_loading(bool is_loading) {
    if (is_loading) {
        // Fast blink on both FN and encoder buttons during loading
        set_blink(C::FN_LED_IDX, true, C::YELLOW);
        set_blink(C::ENC_LED_IDX, true, C::YELLOW);
    } else {
        set_blink(C::FN_LED_IDX, false);
        set_blink(C::ENC_LED_IDX, false);
        flash_pixel(C::FN_LED_IDX, 0.8f, C::GREEN);
        flash_pixel(C::ENC_LED_IDX, 0.8f, C::GREEN);
    }
}
