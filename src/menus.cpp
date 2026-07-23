#include "menus.h"
#include "display.h"
#include "presets.h"
#include "playmenu.h"
#include "settingsmenu.h"
#include "loopmanager.h"
#include "midi.h"
#include "settings.h"
#include "utils.h"
#include "ticks.h"

// Menu position for the nav badge ("2/6") — shown only while nav mode is active,
// so the top row never spends width on numbering (2026-07-12 UI review).
static String _nav_position_label() {
    return String(Menu::current_idx + 1) + "/" + String(Menu::num_menus);
}

std::vector<Menu *> Menu::menus;
int Menu::current_idx = 0;
int Menu::num_menus = 0;
Menu *Menu::current_menu = nullptr;
bool Menu::is_nav_mode = false;
bool Menu::is_locked = false;

Menu::Menu(const char *title, MenuActions acts)
    : menu_title(title), actions(acts) {
    menu_number = Menu::num_menus + 1;
    Menu::num_menus++;
    Menu::menus.push_back(this);
}

void Menu::next_or_prev_menu(bool up_or_down, int jump_to_index) {
    int prev_idx = current_idx;
    if (jump_to_index >= 0) {
        current_idx = jump_to_index;
    } else {
        current_idx = next_or_previous_index(current_idx, num_menus, up_or_down, false);

        // At the first/last menu (no loop-around) a further detent leaves
        // current_idx unchanged. Skip the redraw: re-rendering an identical
        // screen on every detent causes the visible flicker/glitch at the menu
        // boundaries. (Explicit jump_to_index always renders, to allow a forced
        // refresh of the current menu.)
        if (current_idx == prev_idx) {
            return;
        }
    }
    current_menu = menus[current_idx];

    // Render title + full content immediately on every detent. The old deferred
    // render (settle_nav / _nav_pending, a 120 ms scroll-settle wait) existed
    // because a full frame render+push stuttered the encoder in CircuitPython.
    // Post core-1 offload the ~25 ms I2C push is off the hot path and building
    // the framebuffer is ~free, so there's nothing left to defer.
    ::display.show_text_top(get_current_title_text());
    _render_full_current_menu();

    // Keep the nav badge's "2/6" current while scrolling through menus
    if (is_nav_mode) {
        ::display.toggle_navmode_icon(true, _nav_position_label());
    }
}

void Menu::_render_full_current_menu() {
    ::display.turn_off_all_dots();
    current_menu->display();
    current_menu->setup();
}

void Menu::toggle_nav_mode() {
    cancel_pending_preset_overwrite(); // encoder click while a save-confirm is armed = cancel
    is_nav_mode = !is_nav_mode;
    ::display.toggle_navmode_icon(is_nav_mode, _nav_position_label());
    _heal_title_after_nav_off();
}

void Menu::toggle_nav_mode(bool on_or_off) {
    cancel_pending_preset_overwrite();
    is_nav_mode = on_or_off;
    ::display.toggle_navmode_icon(is_nav_mode, _nav_position_label());
    _heal_title_after_nav_off();
}

// The top-right badge may have overdrawn the title's tail; redraw it once the
// badge is gone (unless a notification currently owns the top line).
void Menu::_heal_title_after_nav_off() {
    if (!is_nav_mode && ::display.notification_text.length() == 0) {
        ::display.show_text_top(get_current_title_text());
    }
}

void Menu::toggle_lock_mode() {
    is_locked = !is_locked;
    ::display.toggle_lock_icon(is_locked, is_nav_mode);
}

void Menu::toggle_lock_mode(bool on_or_off) {
    is_locked = on_or_off;
    ::display.toggle_lock_icon(is_locked, is_nav_mode);
}

void Menu::clear_notifications() {
    ::display.clear_notifications(get_current_title_text());
}

void Menu::initialize() {
    current_menu = menus[current_idx];
    current_menu->display();
    current_menu->setup();
    ::display.show_text_top(get_current_title_text());
}

String Menu::get_current_title_text() {
    // No "n) " prefix — position lives in the nav badge while navigating.
    String title = current_menu->menu_title;
    // Play screen only: append the loaded preset name (e.g. "Play - MYPRESET").
    // Deliberately NO unsaved-changes star here — recording anything makes the
    // preset dirty, so it would sit there permanently; the star lives in the
    // Save Preset menu instead (2026-07-13 user call). menu_number 1 is the Play
    // menu (first one created in menus_init).
    if (current_menu->menu_number == 1 && CURRENT_PRESET_NAME.length()) {
        title += " - " + CURRENT_PRESET_NAME;
    }
    return title;
}

void Menu::display() {
    std::vector<String> display_text;
    if (actions.primary_display_function) {
        display_text = actions.primary_display_function();
    }
    if (display_text.empty()) {
        display_text.push_back("");
    }
    ::display.show_text_middle(display_text.data(), (uint8_t)display_text.size());
}

void Menu::setup() {
    if (actions.setup_function) {
        actions.setup_function();
    }
}

// ------------- Set up each menu (Python module-level construction) ----------- //

void menus_init() {
    MenuActions play_actions;
    play_actions.primary_display_function = playmenu::get_playmenu_display_text;
    play_actions.setup_function = playmenu::play_menu_setup;
    play_actions.encoder_change_function = [](bool up) { playmenu::change_and_display_midi_bank(up); };
    play_actions.pad_held_function = playmenu::pad_held_function;
    play_actions.fn_button_press_function = [](const char *a) { loop_manager.handle_fn_press(a); };
    play_actions.fn_button_dbl_press_function = playmenu::double_click_fn_button;
    play_actions.fn_button_held_function = playmenu::fn_button_held_function;
    play_actions.encoder_button_press_and_turn_function = playmenu::encoder_button_press_and_turn_function;
    play_actions.fn_button_held_and_encoder_change_function = playmenu::fn_button_held_and_encoder_turned_function;
    play_actions.encoder_button_held_function = playmenu::encoder_button_held_function;
    new Menu("Play", play_actions);

    MenuActions scale_actions;
    scale_actions.primary_display_function = []() {
        String lines[3];
        midi.get_current_scale_display_text(lines);
        return std::vector<String>{lines[0], lines[1], lines[2]};
    };
    scale_actions.setup_function = []() { midi.scale_setup_function(); };
    scale_actions.encoder_change_function = [](bool up) { midi.next_or_prev_scale(up); };
    scale_actions.fn_button_press_function = [](const char *a) { midi.scale_fn_press_function(a); };
    scale_actions.fn_button_dbl_press_function = []() { midi.next_or_prev_root(); };
    scale_actions.fn_button_held_function = [](bool rel) { midi.scale_fn_held_function(rel); };
    scale_actions.fn_button_held_and_encoder_change_function = [](bool up) { midi.next_or_prev_root(up); };
    new Menu("Scale Select", scale_actions);

    MenuActions midi_actions;
    midi_actions.primary_display_function = []() {
        return std::vector<String>{settingsmenu::get_midi_settings_display_text()};
    };
    midi_actions.setup_function = settingsmenu::midi_settings_menu_setup;
    midi_actions.pad_held_function = settingsmenu::midi_settings_pad_held_function;
    midi_actions.encoder_change_function = [](bool up) { settingsmenu::midi_settings_menu_encoder_change_function(up); };
    midi_actions.fn_button_press_function = [](const char *a) { settingsmenu::midi_settings_menu_fn_press_function(true, a); };
    midi_actions.fn_button_dbl_press_function = []() { settingsmenu::midi_settings_menu_fn_press_function(); };
    midi_actions.fn_button_held_function = settingsmenu::generic_settings_fn_hold_function_dots;
    midi_actions.fn_button_held_and_encoder_change_function = [](bool up) { settingsmenu::midi_settings_menu_fn_btn_encoder_chg_function(up); };
    new Menu("MIDI Settings", midi_actions);

    MenuActions settings_actions;
    settings_actions.primary_display_function = []() {
        return std::vector<String>{settingsmenu::get_settings_display_text()};
    };
    settings_actions.setup_function = settingsmenu::settings_menu_setup;
    settings_actions.encoder_change_function = [](bool up) { settingsmenu::settings_menu_encoder_change_function(up); };
    settings_actions.fn_button_press_function = [](const char *a) { settingsmenu::settings_menu_fn_press_function(true, a); };
    settings_actions.fn_button_dbl_press_function = []() { settingsmenu::settings_menu_fn_press_function(); };
    settings_actions.fn_button_held_function = settingsmenu::generic_settings_fn_hold_function_dots;
    settings_actions.fn_button_held_and_encoder_change_function = [](bool up) { settingsmenu::settings_menu_fn_btn_encoder_chg_function(up); };
    new Menu("Other Settings", settings_actions);

    MenuActions load_actions;
    load_actions.primary_display_function = []() {
        String lines[3];
        get_preset_display_text(lines);
        return std::vector<String>{lines[0], lines[1], lines[2]};
    };
    load_actions.encoder_change_function = [](bool up) { load_next_or_previous_preset(up); };
    load_actions.fn_button_press_function = [](const char *a) { load_preset(a); };
    load_actions.setup_function = load_preset_setup;
    new Menu("Load Preset", load_actions);

    MenuActions save_actions;
    save_actions.primary_display_function = []() {
        String lines[3];
        get_preset_display_text(lines, true); // dirty star + overwrite-confirm arrow
        return std::vector<String>{lines[0], lines[1], lines[2]};
    };
    save_actions.setup_function = cancel_pending_preset_overwrite; // entering the menu never shows a stale arm
    save_actions.encoder_change_function = [](bool up) { select_next_or_previous_preset(up); };
    save_actions.fn_button_press_function = [](const char *a) { save_preset_to_file(a); };
    new Menu("Save Preset", save_actions);
}
