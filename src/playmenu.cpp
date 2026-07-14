#include "playmenu.h"
#include "constants.h"
#include "loopmanager.h"
#include "display.h"
#include "looper.h"
#include "midi.h"
#include "settings.h"
#include "settingsmenu.h"

namespace playmenu {

// Toggle play modes: velocity -> encoder -> loop (-> velocity if enabled).
void double_click_fn_button() {
    String play_mode = settings.get_play_mode();
    if (play_mode == "velocity") {
        play_mode = "encoder";
        display_arp_info(true);
    } else if (play_mode == "encoder") {
        play_mode = "loop";
        display_arp_info(false);
        display_quantization_info(true);
        loop_manager.update_pad_pixels();
    } else if (play_mode == "loop") {
        display_quantization_info(false); // clear loop display first
        if (settings.velocity_mode_enabled) { // C.VELOCITY_MODE_ENABLED (runtime flag)
            play_mode = "velocity";
        } else {
            play_mode = "encoder";
            display_arp_info(true);
        }
    }

    settings.set_play_mode(play_mode);
    display.update_playmode_icon(play_mode.c_str());
}

void pad_held_function(int first_pad_held_idx, const bool *button_states, int encoder_delta) {
    String play_mode = settings.get_play_mode();
    if (play_mode == "encoder") { // special case — see inputs.cpp
        return;
    }

    // No pads were held before this one in this session
    if (first_pad_held_idx >= 0) {
        if (play_mode == "velocity") {
            uint8_t velocity = midi.get_velocity_by_idx(first_pad_held_idx);
            midi.update_global_velocity(velocity);
            display.show_notification("velocity: " + String(velocity));
            return;
        }
    }

    // Pad is held AND encoder was turned
    if (abs(encoder_delta) > 0 && button_states != nullptr) {
        bool any_pressed = false;
        for (uint8_t i = 0; i < C::NUM_PADS; i++) {
            if (button_states[i]) {
                any_pressed = true;
                break;
            }
        }
        if (!any_pressed) {
            return;
        }

        if (play_mode == "velocity") {
            int current_velocity = midi.get_current_assignment_velocity();
            int new_velocity = max(0, min(127, current_velocity + encoder_delta));

            if (new_velocity != current_velocity) {
                midi.update_global_velocity((uint8_t)new_velocity);
                for (uint8_t pad_idx = 0; pad_idx < C::NUM_PADS; pad_idx++) {
                    if (button_states[pad_idx]) {
                        midi.set_midi_velocity_by_idx(pad_idx, (uint8_t)new_velocity);
                    }
                }
                if (new_velocity % C::VELOCITY_CHANGE_DISPLAY_THRESH == 0 || new_velocity == 1 || new_velocity == 127) {
                    display.show_notification("velocity: " + String(new_velocity));
                }
            }
        } else if (play_mode == "loop") {
            for (uint8_t pad_idx = 0; pad_idx < C::NUM_PADS; pad_idx++) {
                if (button_states[pad_idx]) {
                    loop_manager.change_loop_mode(pad_idx, encoder_delta > 0);
                }
            }
        }
    }
}

void change_and_display_midi_bank(bool up_or_down, bool display_text) {
    midi.change_bank(up_or_down);
    int scale_bank = midi.get_scale_bank_idx();
    if (display_text) {
        int idx = (scale_bank == 0) ? midi.get_midi_bank_idx() : midi.get_scale_notes_idx();
        String offset_suffix = midi.get_pad_offset_suffix();
        // Clear 36px wide (enough for "10 +++" = 6 chars)
        display.show_text_middle(String(idx) + offset_suffix, true, 38 + C::PADDING, 36);
        display.display_dot(0, true);
    }
}

void display_bank_offset() {
    int scale_bank = midi.get_scale_bank_idx();
    int idx = (scale_bank == 0) ? midi.get_midi_bank_idx() : midi.get_scale_notes_idx();
    String offset_suffix = midi.get_pad_offset_suffix();
    display.show_text_middle(String(idx) + offset_suffix, true, 38 + C::PADDING, 36);
}

void fn_button_held_function(bool trigger_on_release) {
    String pm = settings.get_play_mode();
    if (pm != "loop" && pm != "encoder") {
        return;
    }
    if (!trigger_on_release) {
        display.display_dot(1, true);
    } else {
        display.display_dot(1, false);
        display.display_dot(0, true);
    }
}

std::vector<String> get_playmenu_display_text() {
    std::vector<String> text;
    String offset_suffix = midi.get_pad_offset_suffix();
    if (midi.get_scale_bank_idx() == 0) {
        text.push_back("Bank: " + String(midi.get_midi_bank_idx()) + offset_suffix);
    } else {
        text.push_back("Bank: " + String(midi.get_scale_notes_idx()) + offset_suffix);
    }

    display.display_dot(0, true);
    display.update_playmode_icon(settings.get_play_mode().c_str());
    return text;
}

void play_menu_setup() {
    // Draw bottom-line info after show_text_middle has cleared the area
    if (settings.get_play_mode() == "loop") {
        display_quantization_info(true);
    } else if (settings.get_play_mode() == "encoder") {
        display_arp_info();
    }
}

void fn_button_held_and_encoder_turned_function(bool encoder_delta) {
    String pm = settings.get_play_mode();
    if (pm != "loop" && pm != "encoder") {
        return;
    }
    if (pm == "loop") {
        set_next_or_prev_quantization(encoder_delta);
        display.show_text_bottom(get_quantization_display_value(), true, 35, 36);
    }
    if (pm == "encoder") {
        String arp_direction = settingsmenu::set_next_arp_type(encoder_delta);
        display.show_text_bottom(arp_direction, true, C::TEXT_PAD, 80);
    }
}

void encoder_button_press_and_turn_function(bool encoder_delta) {
    String pm = settings.get_play_mode();
    if (pm != "loop" && pm != "encoder") {
        return;
    }

    display.display_dot(2, true);

    if (pm == "loop") {
        set_quantization_percent(encoder_delta);
        display.show_text_bottom(String(get_quantization_percent_int()) + "%", true, 91, 25);
    }
    if (pm == "encoder") {
        String arp_length = settingsmenu::set_next_arp_length(encoder_delta);
        display.show_text_bottom(arp_length, true, 90, 30);
    }
}

void display_quantization_info(bool on_or_off) {
    if (on_or_off) {
        display.show_text_bottom(get_quantization_text(), true, 0, 40);
        display.show_text_bottom(String(get_quantization_percent_int()) + "%", true, 91, 25);
    } else {
        display.show_text_bottom("");
    }
}

void display_arp_info(bool on_or_off) {
    if (on_or_off) {
        display.show_text_bottom(settingsmenu::get_arp_type_text(), true, 0, 60);
        display.show_text_bottom(settingsmenu::get_arp_len_text(), true, 91, 25);
    } else {
        display.show_text_bottom("");
    }
}

void encoder_button_held_function(bool released) {
    String pm = settings.get_play_mode();
    if (pm != "loop" && pm != "encoder") {
        return;
    }
    if (!released) {
        display.display_dot(2, true);
    } else {
        display.display_dot(2, false);
        display.display_dot(0, true);
    }
}

} // namespace playmenu
