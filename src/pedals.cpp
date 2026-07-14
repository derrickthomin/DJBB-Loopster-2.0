#include "pedals.h"
#include "pixels.h"
#include "serial_config.h" // cdc_log (Q1 bounded prints)

Pedals pedals;

const uint8_t Pedals::_pedal_pins[C::PEDAL_COUNT] = {
    C::PIN_PEDAL_1, C::PIN_PEDAL_2, C::PIN_PEDAL_3, C::PIN_PEDAL_4, C::PIN_PEDAL_5
};

Pedals::Pedals()
    : _pixels(C::PEDAL_COUNT, C::PIN_PEDAL_NEOPIXEL, NEO_GRB + NEO_KHZ800) {}

void Pedals::begin() {
    _pixels.begin();
    _pixels.setBrightness((uint8_t)(C::PEDAL_BRIGHTNESS * 255));
    _pixels.clear();
    for (uint8_t i = 0; i < C::PEDAL_COUNT; i++) {
        pinMode(_pedal_pins[i], INPUT_PULLUP);
    }
}

void Pedals::_push_event(uint8_t key, bool pressed) {
    if (_q_count >= sizeof(_queue) / sizeof(_queue[0])) {
        return; // queue full; drop (Python list could grow unbounded — bounded here)
    }
    _queue[(_q_head + _q_count) % (sizeof(_queue) / sizeof(_queue[0]))] = {key, pressed};
    _q_count++;
}

bool Pedals::get_event(PedalEvent &out) {
    if (_q_count == 0) {
        return false;
    }
    out = _queue[_q_head];
    _q_head = (_q_head + 1) % (sizeof(_queue) / sizeof(_queue[0]));
    _q_count--;
    return true;
}

void Pedals::update() {
    for (uint8_t i = 0; i < C::PEDAL_COUNT; i++) {
        pedal_buttons[i].set_current_value(digitalRead(_pedal_pins[i]) == HIGH);

        bool prev_state = pedal_buttons[i].state;
        pedal_buttons[i].update_all();

        if (!prev_state && pedal_buttons[i].state) { // new press
            _push_event((uint8_t)pedal_buttons[i].pad_idx, true);
        } else if (prev_state && !pedal_buttons[i].state) { // new release
            _push_event((uint8_t)pedal_buttons[i].pad_idx, false);
        }
    }
}

void Pedals::show_pedal_pixels() {
    if (pixels_need_update) {
        pixels_need_update = false; // clear first: a concurrent core-0 write re-dirties
        _pixels.show();
    }
}

void Pedals::set_pixel_on(uint8_t loopster_pad_idx, C::Rgb color) {
    int idx = get_pedal_pixel_index(loopster_pad_idx);
    if (idx >= 0) {
        _pixels.setPixelColor(idx, color.r, color.g, color.b);
        pixels_need_update = true;
    }
}

void Pedals::set_pixel_off(uint8_t loopster_pad_idx) {
    int idx = get_pedal_pixel_index(loopster_pad_idx);
    if (idx >= 0) {
        _pixels.setPixelColor(idx, 0);
        pixels_need_update = true;
    }
}

void Pedals::reset_pedals() {
    for (uint8_t i = 0; i < C::PEDAL_COUNT; i++) {
        pedal_buttons[i].reset_actions();
    }
}

void Pedals::set_pedal_bank(int bank_idx) {
    if (bank_idx < 0 || bank_idx > 2) {
        return;
    }
    current_bank = bank_idx;
    bank_offset = bank_idx * 5;
    for (uint8_t i = 0; i < C::PEDAL_COUNT; i++) {
        pedal_buttons[i].pad_idx = bank_offset + i;
    }
    _update_pixels_for_current_bank();
    cdc_log("Switched to pedal bank %d (pads %d-%d)\n", bank_idx, bank_offset, bank_offset + 4);
}

int Pedals::get_pedal_pixel_index(uint8_t loopster_pad_idx) const {
    if (loopster_pad_idx >= bank_offset && loopster_pad_idx < bank_offset + 5) {
        return loopster_pad_idx - bank_offset;
    }
    return -1; // this pad doesn't correspond to any pedal
}

void Pedals::_update_pixels_for_current_bank() {
    if (!_loop_state) {
        return; // loopmanager not initialized yet
    }
    for (uint8_t i = 0; i < 5; i++) {
        uint8_t pad = bank_offset + i;
        switch (_loop_state(pad)) {
        case PadLoopState::Playing:
            _pixels.setPixelColor(i, C::PIXEL_LOOP_PLAYING_COLOR.r, C::PIXEL_LOOP_PLAYING_COLOR.g, C::PIXEL_LOOP_PLAYING_COLOR.b);
            break;
        case PadLoopState::HasLoop:
            _pixels.setPixelColor(i, C::LOOP_COLOR.r, C::LOOP_COLOR.g, C::LOOP_COLOR.b);
            break;
        default:
            _pixels.setPixelColor(i, 0);
            break;
        }
    }
    pixels_need_update = true;
}

void update_pedal_pixels() {
    if (pixels.core1_owns_pixels) {
        return; // core 1 shows pedal pixels from loop1; a core-0 show would race it
    }
    if (pedals.pixels_need_update) {
        pedals.show_pedal_pixels();
    }
}
