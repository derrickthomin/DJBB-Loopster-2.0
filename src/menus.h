// Port of src/menus.py — menu navigation + action dispatch.
// Python's actions dict of loosely-typed callables -> MenuActions struct of
// std::function slots; call_function's "does the action exist" return maps to
// checking the std::function's bool conversion.
#pragma once
#include <Arduino.h>
#include <functional>
#include <vector>

struct MenuActions {
    std::function<std::vector<String>()> primary_display_function;
    std::function<void()> setup_function;
    std::function<void(bool)> encoder_change_function;
    // (first_pad_held_idx or -1, button states[16] or nullptr, encoder_delta)
    std::function<void(int, const bool *, int)> pad_held_function;
    std::function<void(const char *)> fn_button_press_function; // action_type
    std::function<void()> fn_button_dbl_press_function;
    std::function<void(bool)> fn_button_held_function; // trigger_on_release
    std::function<void(bool)> encoder_button_press_and_turn_function;
    std::function<void(bool)> fn_button_held_and_encoder_change_function;
    std::function<void(bool)> encoder_button_held_function; // released
};

class Menu {
public:
    static std::vector<Menu *> menus;
    static int current_idx;
    static int num_menus;
    static Menu *current_menu;
    static bool is_nav_mode;
    static bool is_locked;

    int menu_number;
    String menu_title;
    MenuActions actions;

    Menu(const char *title, MenuActions acts);

    static void next_or_prev_menu(bool up_or_down, int jump_to_index = -1);
    static void toggle_nav_mode();             // Python on_or_off=None
    static void toggle_nav_mode(bool on_or_off);
    static void toggle_lock_mode();            // Python on_or_off=None
    static void toggle_lock_mode(bool on_or_off);
    static void clear_notifications();
    static void initialize();
    static String get_current_title_text();

    void display();
    void setup();

private:
    static void _render_full_current_menu();
    static void _heal_title_after_nav_off();
};

// Creates the six menus (Python module-level construction); call once from setup()
// after all modules are initialized.
void menus_init();
