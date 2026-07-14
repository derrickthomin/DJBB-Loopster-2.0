// Port of src/presets.py — preset selection/load/save menu actions.
// supervisor.reload() -> rp2040.reboot() (full restart; the C++ equivalent of
// CircuitPython's soft reload, and what the web UI's needs_restart flow expects).
// Module-level init code from Python runs in presets_init(), called from setup()
// after the filesystem is available.
#pragma once
#include <Arduino.h>
#include <vector>

extern std::vector<String> PRESET_NAMES_LIST;
extern int selected_preset_idx;

// The preset that was loaded at boot (STARTUP_PRESET, with fallbacks resolved).
// Cached once in presets_init() so the Play-screen title can show it without a
// per-render flash read. A load reboots the device, so this is re-derived each boot.
extern String CURRENT_PRESET_NAME;

void presets_init();

void load_preset(const char *action_type = "press");
void load_preset_setup(); // called from menus
void save_preset_to_file(const char *action_type = "press");
void select_next_or_previous_preset(bool up_or_down = true);
void load_next_or_previous_preset(bool up_or_down = true);
// for_save_menu = trailing unsaved-changes star on the loaded preset + the
// "overwrite?" arrow line while a save-over-existing confirm is armed.
void get_preset_display_text(String out[3], bool for_save_menu = false);
// Disarm the two-press overwrite confirm (no-op if not armed). Wired into
// Menu::toggle_nav_mode so an encoder click/double-click cancels, and into the
// Save Preset menu's setup so re-entering the menu can never show a stale arm.
void cancel_pending_preset_overwrite();
