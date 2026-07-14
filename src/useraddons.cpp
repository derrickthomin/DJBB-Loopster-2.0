// Port of src/useraddons.py + src/mpu6050_minimal.py — Colm's addons:
// glove buttons (pedal bank switching), MPU6050 tilt->CC with double-toggle
// calibration, accelerometer-driven arp timing. Motor feedback hooks are no-ops
// (they were in the Python too). Accel I2C: GP20/21 = I2C0 = Wire.
// CC tuples carried channel None -> CcMsg.channel = -1 (global out channel).
#include "useraddons.h"
#include <Wire.h>
#include "constants.h"
#include "pedals.h"
#include "display.h"
#include "settings.h"
#include "menus.h"
#include "midi.h"
#include "ticks.h"

namespace useraddons {

// ---------------- MPU6050 minimal driver ----------------

class MPU6050 {
public:
    bool begin(TwoWire &wire, uint8_t address = 0x68) {
        _wire = &wire;
        _addr = address;
        // Wake up the sensor (clear sleep bit in PWR_MGMT_1)
        _wire->beginTransmission(_addr);
        _wire->write(0x6B);
        _wire->write(0x00);
        return _wire->endTransmission() == 0;
    }

    // Returns false on read error; fills m/s^2 values
    bool acceleration(float &x, float &y, float &z) {
        _wire->beginTransmission(_addr);
        _wire->write(0x3B); // ACCEL_XOUT_H
        if (_wire->endTransmission(false) != 0) {
            return false;
        }
        if (_wire->requestFrom((int)_addr, 6) != 6) {
            return false;
        }
        uint8_t buf[6];
        for (uint8_t i = 0; i < 6; i++) {
            buf[i] = _wire->read();
        }
        int16_t raw_x = (buf[0] << 8) | buf[1];
        int16_t raw_y = (buf[2] << 8) | buf[3];
        int16_t raw_z = (buf[4] << 8) | buf[5];
        const float scale = 9.80665f / 16384.0f; // ±2g, 16384 LSB/g
        x = raw_x * scale;
        y = raw_y * scale;
        z = raw_z * scale;
        return true;
    }

private:
    TwoWire *_wire = nullptr;
    uint8_t _addr = 0x68;
};

// ---------------- Glove buttons ----------------

static bool glove_left_prev = true;
static bool glove_right_prev = true;
static uint32_t last_press_time = 0;
static uint32_t glove_left_last_release_time = 0;
static uint32_t glove_right_last_release_time = 0;
static const uint32_t MIN_OFF_TIME_MS = 100; // prevent fabric contact bounce

static void check_glove_buttons() {
    uint32_t current_time = ticks::ticks_ms();
    bool glove_left_current = digitalRead(C::PIN_GLOVE_LEFT) == HIGH;
    bool glove_right_current = digitalRead(C::PIN_GLOVE_RIGHT) == HIGH;

    // Track releases (pressed -> not pressed)
    if (!glove_left_prev && glove_left_current) {
        glove_left_last_release_time = current_time;
    }
    if (!glove_right_prev && glove_right_current) {
        glove_right_last_release_time = current_time;
    }

    // Presses need both debounce time AND minimum off time
    if (current_time - last_press_time >= C::GLOVE_DEBOUNCE_TIME_MS) {
        if (glove_left_prev && !glove_left_current &&
            current_time - glove_left_last_release_time >= MIN_OFF_TIME_MS) {
            int new_bank = min(pedals.current_bank + 1, 2);
            if (new_bank != pedals.current_bank) {
                pedals.set_pedal_bank(new_bank);
            }
            last_press_time = current_time;
        }
        if (glove_right_prev && !glove_right_current &&
            current_time - glove_right_last_release_time >= MIN_OFF_TIME_MS) {
            int new_bank = max(pedals.current_bank - 1, 0);
            if (new_bank != pedals.current_bank) {
                pedals.set_pedal_bank(new_bank);
            }
            last_press_time = current_time;
        }
    }

    glove_left_prev = glove_left_current;
    glove_right_prev = glove_right_current;
}

// ---------------- Accelerometer controller ----------------

class AccelerometerController {
public:
    void begin() {
        pinMode(C::PIN_ACCEL_ENABLE, INPUT_PULLUP);

        Wire.setSDA(C::PIN_ACCEL_I2C_SDA);
        Wire.setSCL(C::PIN_ACCEL_I2C_SCL);
        Wire.begin();
        // Q5: the framework default is a 25 ms timeout with reset_with_timeout=false —
        // a wedged sensor (cable flex, ESD; this is a body-worn addon) then costs up to
        // ~50 ms of bus timeout EVERY 10 ms poll, forever. With reset the bus gets a
        // recovery attempt after each timeout instead of staying stuck.
        Wire.setTimeout(25, true);
        has_accelerometer = mpu.begin(Wire);
        if (!has_accelerometer) {
            Serial.println("Error initializing accelerometer");
        }
    }

    bool is_enabled() {
        return digitalRead(C::PIN_ACCEL_ENABLE) == LOW;
    }

    void update();
    void calibrate();
    bool should_trigger_arp_note();

    std::vector<CcMsg> get_cc_data() {
        std::vector<CcMsg> data = cc_data;
        cc_data.clear();
        return data;
    }

    bool has_valid_calibration_data() const {
        return calibrated && x_max != x_min && y_max != y_min &&
               fabsf(x_max - x_min) > C::ACCEL_DEADZONE_DEGREES * 2 &&
               fabsf(y_max - y_min) > C::ACCEL_DEADZONE_DEGREES * 2;
    }

    bool has_accelerometer = false;

private:
    MPU6050 mpu;

    bool calibrated = false;
    bool previous_enabled_state = false;
    uint32_t last_on_transition_time = 0;

    // Q5: mpu.acceleration() failures were treated as transient skips forever — a
    // wedged bus then degrades every pass until reboot. After this many consecutive
    // failed polls (~100 ms of solid failure at the 10 ms cadence) the accel is taken
    // offline with one notification; the next OFF->ON enable toggle re-probes it.
    static const uint8_t MAX_CONSECUTIVE_READ_FAILURES = 10;
    uint8_t consecutive_read_failures = 0;

    // Non-blocking calibration state machine (item 3). The old calibrate() busy-looped
    // ~25 s with delay() on core 0, freezing MIDI (stuck notes, watchdog trip). Now
    // calibrate() just arms this state machine and update() advances it one step per call.
    enum class CalPhase : uint8_t { Idle, Neutral, Movement, Complete };
    CalPhase cal_phase = CalPhase::Idle;
    uint32_t cal_phase_end_time = 0;
    uint32_t cal_last_display_update = 0;
    uint32_t cal_last_sample_time = 0;
    float cal_temp_xb = 0, cal_temp_yb = 0;

    float prev_left_tilt = 0, prev_right_tilt = 0, prev_backward_tilt = 0, prev_forward_tilt = 0;
    int last_left_cc_val = 0, last_right_cc_val = 0, last_backward_cc_val = 0, last_forward_cc_val = 0;
    uint32_t last_update_time = 0;

    int recent_left_cc[3] = {0}, recent_right_cc[3] = {0}, recent_backward_cc[3] = {0}, recent_forward_cc[3] = {0};
    uint8_t recent_left_n = 0, recent_right_n = 0, recent_backward_n = 0, recent_forward_n = 0;

    bool left_stable_mode = true, right_stable_mode = true, backward_stable_mode = true, forward_stable_mode = true;
    uint32_t left_mode_switch = 0, right_mode_switch = 0, backward_mode_switch = 0, forward_mode_switch = 0;

    float x_baseline = 0, y_baseline = 0;
    float x_max = 90, x_min = -90, y_max = 90, y_min = -90;

    std::vector<CcMsg> cc_data;

    uint32_t arp_last_trigger_time = 0;
    float arp_current_interval_ms = -1; // -1 = None
    float arp_locked_interval_ms = -1;
    bool has_cached_reading = false;
    float cached_x = 0, cached_y = 0, cached_z = 0;

    bool _is_readings_stable(int new_val, int *recent, uint8_t &count);
    bool _update_adaptive_mode(bool stable_now, bool current_stable_mode, uint32_t &mode_switch_time, uint32_t now);
    static int _tilt_cc(float tilt_degrees, float baseline, float limit, bool negative_direction);
    void _show_calibration_phase_1(int seconds_left, float xb, float yb);
    void _show_calibration_phase_2(int seconds_left);
    void _show_calibration_complete();
    void _restore_menu_display();
    void _update_calibration(); // advances the non-blocking calibration state machine
};

static AccelerometerController accelerometer;

bool AccelerometerController::_is_readings_stable(int new_val, int *recent, uint8_t &count) {
    // Sliding buffer of ACCEL_STABILITY_BUFFER_SIZE readings
    if (count < C::ACCEL_STABILITY_BUFFER_SIZE) {
        recent[count++] = new_val;
        return false; // not enough readings yet (matches Python)
    }
    recent[0] = recent[1];
    recent[1] = recent[2];
    recent[2] = new_val;

    int min_val = recent[0], max_val = recent[0];
    for (uint8_t i = 1; i < 3; i++) {
        min_val = min(min_val, recent[i]);
        max_val = max(max_val, recent[i]);
    }
    return (max_val - min_val) <= C::ACCEL_MAX_STABILITY_VARIATION;
}

// Returns new stable-mode flag; updates mode_switch_time
bool AccelerometerController::_update_adaptive_mode(bool stable_now, bool current_stable_mode,
                                                    uint32_t &mode_switch_time, uint32_t now) {
    if (current_stable_mode) {
        mode_switch_time = 0;
        return stable_now;
    }
    if (stable_now) {
        if (mode_switch_time == 0) {
            mode_switch_time = now;
            return false; // CHANGING, start hold timer
        }
        if (now - mode_switch_time >= C::ACCEL_MODE_HOLD_DURATION_MS) {
            mode_switch_time = 0;
            return true; // back to STABLE
        }
        return false; // CHANGING, waiting out hold
    }
    mode_switch_time = 0;
    return false;
}

void AccelerometerController::update() {
    if (!has_accelerometer) {
        // Q5: offline (boot probe failed, or taken offline after consecutive read
        // failures). The next OFF->ON toggle of the enable switch re-probes the sensor
        // — one bounded I2C transaction, user-initiated, so a still-dead bus costs at
        // most one timeout per toggle instead of one per pass.
        bool current_enabled_state = is_enabled();
        if (current_enabled_state && !previous_enabled_state && mpu.begin(Wire)) {
            has_accelerometer = true;
            consecutive_read_failures = 0;
            last_on_transition_time = 0; // don't pair with a stale pre-offline toggle
            display.show_notification("Accel online");
        }
        previous_enabled_state = current_enabled_state;
        return;
    }

    // While calibrating, the state machine owns the accel + display. Advance it one step
    // and skip normal tilt processing AND toggle detection (so we don't re-trigger). (item 3)
    if (cal_phase != CalPhase::Idle) {
        _update_calibration();
        return;
    }

    bool current_enabled_state = is_enabled();

    // OFF->ON transition: double-toggle calibration trigger
    if (current_enabled_state && !previous_enabled_state) {
        uint32_t cal_time = ticks::ticks_ms();
        if (last_on_transition_time > 0 &&
            cal_time - last_on_transition_time <= C::ACCEL_DOUBLE_TOGGLE_WINDOW_MS) {
            calibrate();
            last_on_transition_time = 0;
        } else {
            last_on_transition_time = cal_time;
        }
    }
    previous_enabled_state = current_enabled_state;

    if (!current_enabled_state) {
        return;
    }

    uint32_t current_time = ticks::ticks_ms();
    if (current_time - last_update_time < C::ACCEL_UPDATE_INTERVAL_MS) {
        return;
    }
    last_update_time = current_time;

    float ax, ay, az;
    if (!mpu.acceleration(ax, ay, az)) {
        if (++consecutive_read_failures >= MAX_CONSECUTIVE_READ_FAILURES) {
            has_accelerometer = false; // re-probed on the next enable toggle (Q5)
            consecutive_read_failures = 0;
            has_cached_reading = false; // stop the arp trigger using stale tilt
            display.show_notification("Accel offline");
        }
        return;
    }
    consecutive_read_failures = 0;
    cached_x = ax;
    cached_y = ay;
    cached_z = az;
    has_cached_reading = true;

    float x_tilt_degrees = (ax / 9.8f) * 90;
    float y_tilt_degrees = (ay / 9.8f) * 90;

    int left_tilt = 0, right_tilt = 0, backward_tilt = 0, forward_tilt = 0;

    if (has_valid_calibration_data()) {
        if (x_tilt_degrees < (x_baseline - C::ACCEL_DEADZONE_DEGREES)) {
            float effective = fabsf(x_tilt_degrees - x_baseline) - C::ACCEL_DEADZONE_DEGREES;
            float max_effective = fabsf(x_min - x_baseline) - C::ACCEL_DEADZONE_DEGREES;
            if (max_effective > 0) {
                left_tilt = (int)(1 + min(effective / max_effective, 1.0f) * 126);
            }
        } else if (x_tilt_degrees > (x_baseline + C::ACCEL_DEADZONE_DEGREES)) {
            float effective = x_tilt_degrees - x_baseline - C::ACCEL_DEADZONE_DEGREES;
            float max_effective = x_max - x_baseline - C::ACCEL_DEADZONE_DEGREES;
            if (max_effective > 0) {
                right_tilt = (int)(1 + min(effective / max_effective, 1.0f) * 126);
            }
        }
        if (y_tilt_degrees < (y_baseline - C::ACCEL_DEADZONE_DEGREES)) {
            float effective = fabsf(y_tilt_degrees - y_baseline) - C::ACCEL_DEADZONE_DEGREES;
            float max_effective = fabsf(y_min - y_baseline) - C::ACCEL_DEADZONE_DEGREES;
            if (max_effective > 0) {
                backward_tilt = (int)(1 + min(effective / max_effective, 1.0f) * 126);
            }
        } else if (y_tilt_degrees > (y_baseline + C::ACCEL_DEADZONE_DEGREES)) {
            float effective = y_tilt_degrees - y_baseline - C::ACCEL_DEADZONE_DEGREES;
            float max_effective = y_max - y_baseline - C::ACCEL_DEADZONE_DEGREES;
            if (max_effective > 0) {
                forward_tilt = (int)(1 + min(effective / max_effective, 1.0f) * 126);
            }
        }
    } else {
        // Constants-based fallback (no calibration)
        float max_effective = C::ACCEL_MAX_TILT_DEGREES - C::ACCEL_DEADZONE_DEGREES;
        if (x_tilt_degrees < -C::ACCEL_DEADZONE_DEGREES) {
            float effective = fabsf(x_tilt_degrees) - C::ACCEL_DEADZONE_DEGREES;
            left_tilt = (int)(1 + min(effective / max_effective, 1.0f) * 126);
        } else if (x_tilt_degrees > C::ACCEL_DEADZONE_DEGREES) {
            float effective = x_tilt_degrees - C::ACCEL_DEADZONE_DEGREES;
            right_tilt = (int)(1 + min(effective / max_effective, 1.0f) * 126);
        }
        if (y_tilt_degrees < -C::ACCEL_DEADZONE_DEGREES) {
            float effective = fabsf(y_tilt_degrees) - C::ACCEL_DEADZONE_DEGREES;
            backward_tilt = (int)(1 + min(effective / max_effective, 1.0f) * 126);
        } else if (y_tilt_degrees > C::ACCEL_DEADZONE_DEGREES) {
            float effective = y_tilt_degrees - C::ACCEL_DEADZONE_DEGREES;
            forward_tilt = (int)(1 + min(effective / max_effective, 1.0f) * 126);
        }
    }

    // Smoothing
    prev_left_tilt = (C::ACCEL_SMOOTH_FACTOR * left_tilt) + ((1 - C::ACCEL_SMOOTH_FACTOR) * prev_left_tilt);
    prev_right_tilt = (C::ACCEL_SMOOTH_FACTOR * right_tilt) + ((1 - C::ACCEL_SMOOTH_FACTOR) * prev_right_tilt);
    prev_backward_tilt = (C::ACCEL_SMOOTH_FACTOR * backward_tilt) + ((1 - C::ACCEL_SMOOTH_FACTOR) * prev_backward_tilt);
    prev_forward_tilt = (C::ACCEL_SMOOTH_FACTOR * forward_tilt) + ((1 - C::ACCEL_SMOOTH_FACTOR) * prev_forward_tilt);

    int left_cc_val = (int)prev_left_tilt;
    int right_cc_val = (int)prev_right_tilt;
    int backward_cc_val = (int)prev_backward_tilt;
    int forward_cc_val = (int)prev_forward_tilt;

    cc_data.clear();

    // Left tilt CC
    bool stable = _is_readings_stable(left_cc_val, recent_left_cc, recent_left_n);
    left_stable_mode = _update_adaptive_mode(stable, left_stable_mode, left_mode_switch, current_time);
    int threshold = left_stable_mode ? C::ACCEL_STABLE_MODE_THRESHOLD : C::ACCEL_CHANGING_MODE_THRESHOLD;
    if (abs(left_cc_val - last_left_cc_val) >= threshold) {
        if (left_cc_val > 0) {
            cc_data.push_back({(uint8_t)settings.accel_left_tilt_cc, (uint8_t)left_cc_val, -1});
        }
        last_left_cc_val = left_cc_val;
    }

    // Right tilt CC
    stable = _is_readings_stable(right_cc_val, recent_right_cc, recent_right_n);
    right_stable_mode = _update_adaptive_mode(stable, right_stable_mode, right_mode_switch, current_time);
    threshold = right_stable_mode ? C::ACCEL_STABLE_MODE_THRESHOLD : C::ACCEL_CHANGING_MODE_THRESHOLD;
    if (abs(right_cc_val - last_right_cc_val) >= threshold) {
        if (right_cc_val > 0) {
            cc_data.push_back({(uint8_t)settings.accel_right_tilt_cc, (uint8_t)right_cc_val, -1});
        }
        last_right_cc_val = right_cc_val;
    }

    // Backward tilt CC
    stable = _is_readings_stable(backward_cc_val, recent_backward_cc, recent_backward_n);
    backward_stable_mode = _update_adaptive_mode(stable, backward_stable_mode, backward_mode_switch, current_time);
    threshold = backward_stable_mode ? C::ACCEL_STABLE_MODE_THRESHOLD : C::ACCEL_CHANGING_MODE_THRESHOLD;
    if (abs(backward_cc_val - last_backward_cc_val) >= threshold) {
        if (backward_cc_val > 0) {
            cc_data.push_back({(uint8_t)settings.accel_backward_tilt_cc, (uint8_t)backward_cc_val, -1});
        }
        last_backward_cc_val = backward_cc_val;
    }

    // Forward tilt — arp control only, no CC sent
    stable = _is_readings_stable(forward_cc_val, recent_forward_cc, recent_forward_n);
    forward_stable_mode = _update_adaptive_mode(stable, forward_stable_mode, forward_mode_switch, current_time);
    threshold = forward_stable_mode ? C::ACCEL_STABLE_MODE_THRESHOLD : C::ACCEL_CHANGING_MODE_THRESHOLD;
    if (abs(forward_cc_val - last_forward_cc_val) >= threshold) {
        last_forward_cc_val = forward_cc_val;
    }
}

void AccelerometerController::_show_calibration_phase_1(int seconds_left, float xb, float yb) {
    display.show_text_top("Accel Cal (" + String(seconds_left) + "s)", true);
    String lines[3] = {"Keep device FLAT", "and STEADY",
                       "Base: X=" + String((int)xb) + " Y=" + String((int)yb)};
    display.show_text_middle(lines, 3);
    display.show_text_bottom("Neutralizing...");
    display_manager.check_show_display();
}

void AccelerometerController::_show_calibration_phase_2(int seconds_left) {
    float x_range = fabsf(x_max - x_min);
    display.show_text_top("Accel Cal (" + String(seconds_left) + "s)", true);
    String lines[3] = {"TILT ALL DIRECTIONS",
                       "X: " + String((int)x_min) + " to " + String((int)x_max) + " (" + String((int)x_range) + ")",
                       ""};
    display.show_text_middle(lines, 3);
    float y_range = fabsf(y_max - y_min);
    display.show_text_bottom("Y: " + String((int)y_min) + " to " + String((int)y_max) + " (" + String((int)y_range) + ")");
    display_manager.check_show_display();
}

void AccelerometerController::_show_calibration_complete() {
    display.show_text_top("Cal Complete!", true);
    String lines[3] = {"Final ranges:",
                       "X: " + String((int)fabsf(x_max - x_min)) + " range",
                       "Y: " + String((int)fabsf(y_max - y_min)) + " range"};
    display.show_text_middle(lines, 3);
    display.show_text_bottom("Returning to menu...");
    display_manager.check_show_display();
}

void AccelerometerController::_restore_menu_display() {
    if (Menu::current_menu) {
        Menu::current_menu->display();
        display.show_text_top(Menu::get_current_title_text());
    } else {
        display.show_text_top("DJBB MIDI LOOPSTER");
        display.show_text_middle("Ready");
    }
    display_manager.check_show_display();
}

void AccelerometerController::calibrate() {
    if (!has_accelerometer || cal_phase != CalPhase::Idle) {
        return;
    }
    // Arm the non-blocking state machine instead of busy-looping ~25 s (item 3). Send
    // all-notes-off first so anything sounding when calibration triggers doesn't hang while
    // the player tilts the instrument. Loops keep running (the main loop is no longer blocked),
    // so their own note-offs continue to fire normally.
    midi.clear_all_notes();

    uint32_t now = ticks::ticks_ms();
    cal_phase = CalPhase::Neutral;
    cal_phase_end_time = now + C::ACCEL_CALIBRATION_NEUTRAL_TIME_MS;
    cal_last_display_update = 0;
    cal_last_sample_time = 0;
    cal_temp_xb = 0;
    cal_temp_yb = 0;
}

void AccelerometerController::_update_calibration() {
    uint32_t now = ticks::ticks_ms();
    float ax, ay, az;

    // Phase 1: hold neutral, sampling baseline until the timer expires.
    if (cal_phase == CalPhase::Neutral) {
        if (now < cal_phase_end_time) {
            if (now - cal_last_display_update >= C::ACCEL_CALIBRATION_DISPLAY_UPDATE_MS ||
                cal_last_display_update == 0) {
                int remaining = max(1, (int)((cal_phase_end_time - now) / 1000));
                if (mpu.acceleration(ax, ay, az)) {
                    cal_temp_xb = (ax / 9.8f) * 90;
                    cal_temp_yb = (ay / 9.8f) * 90;
                }
                _show_calibration_phase_1(remaining, cal_temp_xb, cal_temp_yb);
                cal_last_display_update = now;
            }
            return;
        }
        // Capture final neutral baseline; a failed read aborts calibration (as before).
        if (!mpu.acceleration(ax, ay, az)) {
            cal_phase = CalPhase::Idle;
            previous_enabled_state = is_enabled();
            _restore_menu_display();
            return;
        }
        x_baseline = (ax / 9.8f) * 90;
        y_baseline = (ay / 9.8f) * 90;
        x_max = x_min = x_baseline;
        y_max = y_min = y_baseline;
        cal_phase = CalPhase::Movement;
        cal_phase_end_time = now + C::ACCEL_CALIBRATION_MOVEMENT_TIME_MS;
        cal_last_display_update = 0;
        cal_last_sample_time = 0;
        return;
    }

    // Phase 2: collect min/max while the player tilts in all directions.
    if (cal_phase == CalPhase::Movement) {
        if (now < cal_phase_end_time) {
            // Sample at the same ~100 Hz cadence the old delay(10) loop used, so I2C load
            // and the gradual-spike filter behave identically.
            if (now - cal_last_sample_time >= C::ACCEL_UPDATE_INTERVAL_MS) {
                cal_last_sample_time = now;
                if (mpu.acceleration(ax, ay, az)) {
                    float x_degrees = (ax / 9.8f) * 90;
                    float y_degrees = (ay / 9.8f) * 90;
                    // Gradual update filtering — reject impossible values and sudden spikes
                    if (fabsf(x_degrees) <= 90 && fabsf(x_degrees - x_max) <= 10 && x_degrees > x_max) {
                        x_max = x_degrees;
                    }
                    if (fabsf(x_degrees) <= 90 && fabsf(x_degrees - x_min) <= 10 && x_degrees < x_min) {
                        x_min = x_degrees;
                    }
                    if (fabsf(y_degrees) <= 90 && fabsf(y_degrees - y_max) <= 10 && y_degrees > y_max) {
                        y_max = y_degrees;
                    }
                    if (fabsf(y_degrees) <= 90 && fabsf(y_degrees - y_min) <= 10 && y_degrees < y_min) {
                        y_min = y_degrees;
                    }
                }
            }
            if (now - cal_last_display_update >= C::ACCEL_CALIBRATION_DISPLAY_UPDATE_MS ||
                cal_last_display_update == 0) {
                int remaining = max(1, (int)((cal_phase_end_time - now) / 1000));
                _show_calibration_phase_2(remaining);
                cal_last_display_update = now;
            }
            return;
        }
        // Movement done — show the completion screen and hold it briefly.
        _show_calibration_complete();
        calibrated = true;
        cal_phase = CalPhase::Complete;
        cal_phase_end_time = now + 2000; // replaces the old delay(2000)
        return;
    }

    // Phase 3: leave the "Cal Complete!" screen up ~2 s, then return to the menu.
    if (cal_phase == CalPhase::Complete) {
        if (now < cal_phase_end_time) {
            return;
        }
        cal_phase = CalPhase::Idle;
        previous_enabled_state = is_enabled(); // avoid a spurious OFF->ON toggle after cal
        last_on_transition_time = 0;
        _restore_menu_display();
    }
}

bool AccelerometerController::should_trigger_arp_note() {
    if (!has_accelerometer || !has_cached_reading || !is_enabled()) {
        return false;
    }

    // Forward tilt uses positive Y axis specifically
    float tilt_degrees = (cached_y / 9.8f) * 90;
    float tilt_ratio;

    if (has_valid_calibration_data()) {
        if (tilt_degrees <= (y_baseline + C::ACCEL_DEADZONE_DEGREES)) {
            arp_current_interval_ms = -1;
            arp_locked_interval_ms = -1;
            arp_last_trigger_time = 0;
            return false;
        }
        float effective = tilt_degrees - y_baseline - C::ACCEL_DEADZONE_DEGREES;
        float max_effective = y_max - y_baseline - C::ACCEL_DEADZONE_DEGREES;
        if (max_effective <= 0) {
            arp_current_interval_ms = -1;
            arp_locked_interval_ms = -1;
            arp_last_trigger_time = 0;
            return false;
        }
        tilt_ratio = min(effective / max_effective, 1.0f);
    } else {
        if (tilt_degrees < C::ACCEL_DEADZONE_DEGREES) {
            arp_current_interval_ms = -1;
            arp_locked_interval_ms = -1;
            arp_last_trigger_time = 0;
            return false;
        }
        float effective = tilt_degrees - C::ACCEL_DEADZONE_DEGREES;
        float max_effective = C::ACCEL_ARP_MAX_TILT_DEGREES - C::ACCEL_DEADZONE_DEGREES;
        tilt_ratio = min(effective / max_effective, 1.0f);
    }

    float interval_range = C::ACCEL_ARP_MAX_INTERVAL_MS - C::ACCEL_ARP_MIN_INTERVAL_MS;
    arp_current_interval_ms = C::ACCEL_ARP_MAX_INTERVAL_MS - (tilt_ratio * interval_range);

    uint32_t now_ms = ticks::ticks_ms();

    // First time entering tilt zone — start timer but don't play immediately
    if (arp_last_trigger_time == 0) {
        arp_locked_interval_ms = arp_current_interval_ms;
        arp_last_trigger_time = now_ms;
        return false;
    }

    // Locked interval for timing (prevents mid-cycle changes)
    if ((float)(now_ms - arp_last_trigger_time) >= arp_locked_interval_ms) {
        arp_locked_interval_ms = arp_current_interval_ms;
        arp_last_trigger_time = now_ms;
        return true;
    }
    return false;
}

// ---------------- module API ----------------

void init() {
    pinMode(C::PIN_GLOVE_LEFT, INPUT_PULLUP);
    pinMode(C::PIN_GLOVE_RIGHT, INPUT_PULLUP);
    if (C::USING_ACCELEROMETER) {
        accelerometer.begin();
    }
}

void slow() {
    update_pedal_pixels();
}

void check_addons_fast() {
    if (C::USING_GLOVE_BUTTONS) {
        check_glove_buttons();
    }
    if (C::USING_FOOT_PEDALS) {
        pedals.update(); // update pedals and generate fake keypad events
    }
    if (C::USING_ACCELEROMETER) {
        accelerometer.update();
    }
}

std::vector<CcMsg> get_accel_cc_data() {
    return accelerometer.get_cc_data();
}

bool should_trigger_accelerometer_arp() {
    return accelerometer.should_trigger_arp_note();
}

// Motor feedback hooks — no-ops, same as the Python originals
void handle_new_notes_on(uint8_t, uint8_t, uint8_t, int) {}
void handle_new_notes_off(uint8_t, uint8_t, uint8_t, int) {}
void handle_new_cc(uint8_t, uint8_t, int) {}

} // namespace useraddons
