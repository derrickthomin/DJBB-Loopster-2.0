// Port of src/playmenu.py — play menu screen + bank/velocity/loop-mode actions.
#pragma once
#include <Arduino.h>
#include <vector>

namespace playmenu {

void double_click_fn_button();
void pad_held_function(int first_pad_held_idx, const bool *button_states, int encoder_delta);
void change_and_display_midi_bank(bool up_or_down = true, bool display_text = true);
void display_bank_offset();
void fn_button_held_function(bool trigger_on_release = false);
std::vector<String> get_playmenu_display_text();
void play_menu_setup();
void fn_button_held_and_encoder_turned_function(bool encoder_delta);
void encoder_button_press_and_turn_function(bool encoder_delta);
void display_quantization_info(bool on_or_off = true);
void display_arp_info(bool on_or_off = true);
void encoder_button_held_function(bool released = false);

} // namespace playmenu
