// Port of src/settingsmenu.py — settings + MIDI-settings menu pages.
// Python's heterogeneous option lists (str/int/bool/range) become display-string
// lists; typed conversion happens in the per-page apply logic, preserving the
// exact display text ("True"/"False", "per note", 1-indexed channels, "ALL").
#pragma once
#include <Arduino.h>

namespace settingsmenu {

extern int settings_menu_idx;
extern int midi_settings_page_index;

void init(); // builds option tables + validates indices (Python module-level code)

String get_settings_display_text();
String get_midi_settings_display_text();
void settings_menu_setup();
void midi_settings_menu_setup();
void settings_menu_fn_press_function(bool up_or_down = true, const char *action_type = "press");
void midi_settings_menu_fn_press_function(bool up_or_down = true, const char *action_type = "press");
void settings_menu_fn_btn_encoder_chg_function(bool up_or_down = true);
void midi_settings_menu_fn_btn_encoder_chg_function(bool up_or_down = true);
void midi_settings_pad_held_function(int first_pad_held_idx, const bool *button_states, int encoder_delta);
String next_setting_option(int setting_idx, bool up_or_down = true);
String set_next_or_prev_quantization_time(bool up_or_down = true);
String set_next_arp_type(bool up_or_down = true);
String set_next_arp_length(bool up_or_down = true);
String get_arp_type_text();
String get_arp_len_text();
void generic_settings_fn_hold_function_dots(bool trigger_on_release = false);
void settings_menu_encoder_change_function(bool up_or_down = true);
void midi_settings_menu_encoder_change_function(bool up_or_down = true);

// Hook for the notes_all_at_once change (Python late-imported loop_manager);
// loopmanager registers a function that ensures oneshot notes on all oneshot loops.
void set_oneshot_refresh_hook(void (*fn)());

} // namespace settingsmenu
