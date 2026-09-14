#include "presets.h"
#include "settings.h"
#include "utils.h"
#include "display.h"
#include "menus.h"
#include "loopmanager.h"
#include "arp.h"
#include "midi.h"

static const char *NEW_PRESET = "*NEW*";

// Armed by the first FN press when saving over an EXISTING preset; the second
// press confirms. Anything else (encoder turn, encoder click / nav toggle,
// menu re-entry) cancels via cancel_pending_preset_overwrite().
static bool overwrite_pending = false;

static void _redraw_save_menu_text() {
    String lines[3];
    get_preset_display_text(lines, true);
    display.show_text_middle(lines, 3);
}

void cancel_pending_preset_overwrite() {
    if (!overwrite_pending) return;
    overwrite_pending = false;
    // Arming is only possible while the Save Preset menu is current, but guard so
    // a stray cancel can never draw preset lines over another menu's content.
    if (Menu::current_menu && Menu::current_menu->menu_title == "Save Preset") {
        _redraw_save_menu_text();
    }
}

std::vector<String> PRESET_NAMES_LIST;
int selected_preset_idx = 0;
String CURRENT_PRESET_NAME = "";

void presets_init() {
    String selected_preset_name = settings.get_startup_preset();
    PRESET_NAMES_LIST = settings.get_preset_names_list();

    // Fall back to first real preset if startup preset not found or list is empty
    bool found = false;
    for (const String &p : PRESET_NAMES_LIST) {
        if (p == selected_preset_name) {
            found = true;
            break;
        }
    }
    if (!found) {
        String first_real = "";
        for (const String &p : PRESET_NAMES_LIST) {
            if (p != NEW_PRESET) {
                first_real = p;
                break;
            }
        }
        if (first_real.length()) {
            selected_preset_name = first_real;
        } else if (!PRESET_NAMES_LIST.empty()) {
            selected_preset_name = PRESET_NAMES_LIST[0];
        } else {
            selected_preset_name = "DEFAULT";
            PRESET_NAMES_LIST = {"DEFAULT", NEW_PRESET};
        }
    }

    selected_preset_idx = 0;
    for (size_t i = 0; i < PRESET_NAMES_LIST.size(); i++) {
        if (PRESET_NAMES_LIST[i] == selected_preset_name) {
            selected_preset_idx = (int)i;
            break;
        }
    }

    // The resolved startup preset IS the loaded one — cache it for the Play title.
    CURRENT_PRESET_NAME = selected_preset_name;
}

// Load selected preset and reload system.
void load_preset(const char *action_type) {
    if (!strcmp(action_type, "release")) {
        return; // prevents double load
    }

    String preset_name = PRESET_NAMES_LIST[selected_preset_idx];
    if (preset_name == NEW_PRESET) {
        // *NEW* is a save target, not a loadable preset — never reboot into it (item 19).
        display.show_notification("Nothing to load");
        return;
    }
    // Only reboot if the preset actually loaded. A missing/corrupt preset used to reboot
    // pointlessly mid-set (and with the atomic-write fix could reboot into a wiped state).
    if (settings.load_preset(preset_name)) {
        // Silence only once the load succeeded — a failed load must keep the set running.
        // (load_preset has already applied the NEW preset's channel routing to RAM, so a
        // Global/fixed-mapped loop's offs resolve through that mapping; the all-channels
        // blast inside silence_for_reboot covers the corner where the two presets differ.)
        silence_for_reboot();
        rp2040.reboot();
    } else {
        display.show_notification("Load failed");
    }
}

void silence_for_reboot() {
    // Mirrors Inputs::_do_panic minus the display/pixel feedback: stop + note-off every
    // loop (each on its resolved output channel), clear the play queue, abandon any
    // in-progress recording, flush the arp's ringing notes, then blast CC64=0 + CC123 +
    // CC120 on all 16 channels for live/held notes.
    loop_manager.silence_all_for_lock();
    for (const NoteMsg &off : arpeggiator.flush_playing_notes()) {
        midi.send_note_off(off.note, off.channel);
    }
    arpeggiator.clear_arp_notes();
    midi.all_notes_off_all_channels();
    // Let the MIDI TX drain before the reboot drops the buses: the 48-CC blast alone is
    // ~46 ms at 31250 baud on the DIN side, and delay() services the TinyUSB task so the
    // USB MIDI packets go out too (arduino-pico delay.cpp).
    delay(60);
}

void load_preset_setup() {
    // If *NEW* is the ONLY entry (no presets saved yet), don't wrap the skip back onto it
    // forever — show a message instead of trapping the selection on an unloadable slot (item 19).
    bool has_real_preset = false;
    for (const String &p : PRESET_NAMES_LIST) {
        if (p != NEW_PRESET) { has_real_preset = true; break; }
    }
    if (!has_real_preset) {
        display.show_text_middle("No saved presets");
        return;
    }
    if (PRESET_NAMES_LIST[selected_preset_idx] == NEW_PRESET) {
        selected_preset_idx = next_or_previous_index(selected_preset_idx, PRESET_NAMES_LIST.size(), true);
    }
    String lines[3];
    get_preset_display_text(lines);
    display.show_text_middle(lines, 3);
}

// Save current settings to preset file.
void save_preset_to_file(const char *action_type) {
    if (!strcmp(action_type, "release")) {
        return;
    }

    String preset_name = PRESET_NAMES_LIST[selected_preset_idx];

    // Overwriting an EXISTING preset takes two presses: the first arms the confirm
    // (arrow line flips to "overwrite?"), the second saves. *NEW* saves immediately.
    if (preset_name != NEW_PRESET && !overwrite_pending) {
        overwrite_pending = true;
        _redraw_save_menu_text();
        return;
    }
    overwrite_pending = false;

    // Secondary heap guard (item 1): saving builds a whole-presets JsonDocument in RAM.
    // If free heap is already below the floor, refuse rather than risk an allocation panic
    // that would freeze the device AND lose the in-RAM loops. They stay recorded in RAM.
    if (rp2040.getFreeHeap() < C::HEAP_FLOOR_BYTES) {
        display.show_notification("Low Memory - Not Saved");
        _redraw_save_menu_text(); // arrow line back to "enter"
        return;
    }

    SaveResult saved = settings.save_preset_to_file(preset_name);
    if (saved != SaveResult::Ok) {
        // Refused, nothing written — loops stay recorded in RAM. FileUnreadable = presets.json
        // is there but won't parse (fix 5): saving would have rewritten it holding only this
        // preset and then orphan-swept every other preset's loops. Top line is 21 chars max.
        display.show_notification(saved == SaveResult::FileUnreadable ? "Not saved: bad file"
                                                                      : "Preset limit reached"); // item 18
        _redraw_save_menu_text();
        return;
    }
    settings.dirty = false; // saved — clear the unsaved-changes star
    if (preset_name == NEW_PRESET) {
        display.show_notification("created new preset");
        silence_for_reboot(); // loops are on flash now; nothing may ring through the reboot (fix 2)
        delay(1000);
        rp2040.reboot();
    } else {
        display.show_notification("Saved " + preset_name);
        _redraw_save_menu_text(); // star + "overwrite?" both gone now
    }
}

void select_next_or_previous_preset(bool up_or_down) {
    overwrite_pending = false; // changing the save target cancels an armed confirm
    selected_preset_idx = next_or_previous_index(selected_preset_idx, PRESET_NAMES_LIST.size(), up_or_down);
    _redraw_save_menu_text();
}

void load_next_or_previous_preset(bool up_or_down) {
    selected_preset_idx = next_or_previous_index(selected_preset_idx, PRESET_NAMES_LIST.size(), up_or_down);
    if (PRESET_NAMES_LIST[selected_preset_idx] == NEW_PRESET) {
        selected_preset_idx = next_or_previous_index(selected_preset_idx, PRESET_NAMES_LIST.size(), up_or_down);
    }
    String lines[3];
    get_preset_display_text(lines);
    display.show_text_middle(lines, 3);
}

void get_preset_display_text(String out[3], bool for_save_menu) {
    const String &name = PRESET_NAMES_LIST[selected_preset_idx];
    out[0] = "Preset: " + name;
    // Save menu only: trailing star marks the loaded preset as having unsaved
    // changes (the Play title deliberately does NOT show it — it would sit there
    // permanently once anything is recorded; saving is the user's call).
    if (for_save_menu && settings.dirty && name == CURRENT_PRESET_NAME) {
        out[0] += "*";
    }
    out[1] = "";
    out[2] = (for_save_menu && overwrite_pending) ? "<--- overwrite?" : "<--- enter";
}
