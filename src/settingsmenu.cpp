#include "settingsmenu.h"
#include "display.h"
#include "utils.h"
#include "settings.h"
#include "clock.h"
#include "midi.h"
#include "pixels.h"
#include <vector>

namespace settingsmenu {

int settings_menu_idx = 0;
int midi_settings_page_index = 0;

static void (*_oneshot_refresh)() = nullptr;
void set_oneshot_refresh_hook(void (*fn)()) { _oneshot_refresh = fn; }

struct Page {
    const char *title;
    std::vector<String> options;
};

static std::vector<Page> settings_pages;
static std::vector<Page> midi_settings_pages;

static std::vector<String> make_range(int start, int end) { // [start, end)
    std::vector<String> out;
    for (int i = start; i < end; i++) {
        out.push_back(String(i));
    }
    return out;
}

// ---- current-settings-value -> display string, per page (Python special_cases) ----

static String settings_value_display(int idx) {
    switch (idx) {
    case 0: return settings.trim_silence_mode;
    case 1: return settings.quantize_time;
    case 2: return settings.quantize_loop;
    case 3: return String((int)(roundf(settings.quantize_strength / 10.0f) * 10)); // round(x, -1)
    case 4: return settings.quantize_cc ? "True" : "False";
    case 5: return String((int)(settings.led_brightness * 100));
    case 6: return settings.arpeggiator_type;
    case 7: return settings.loop_type;
    case 8: return settings.arp_is_polyphonic ? "True" : "False";
    case 9: return settings.arpeggiator_length;
    case 10: return settings.notes_all_at_once ? "True" : "False";
    case 11: return settings.cc_reset_mode;
    default: return "";
    }
}

static String midi_value_display(int idx) {
    switch (idx) {
    case 0: return settings.midi_sync ? "True" : "False";
    case 1: return String(settings.default_bpm);
    case 2: return settings.midi_type;
    case 3: return String(settings.midi_channel_out + 1); // 1-indexed
    case 4: return settings.midi_channel_in == -1 ? String("ALL") : String(settings.midi_channel_in + 1);
    case 5: return String(settings.default_velocity);
    case 6: return settings.midi_usb_io;
    case 7: return settings.midi_aux_io;
    case 8: return String(settings.cc_resolution);
    case 9: return settings.record_cc ? "True" : "False";
    case 10: return settings.clock_source;
    case 11: return settings.passthru_mode;
    default: return "";
    }
}

// ---- apply selected option -> settings field, per page ----

static void apply_settings_option(int idx, const String &opt) {
    switch (idx) {
    case 0: settings.trim_silence_mode = opt; break;
    case 1: settings.quantize_time = opt; break;
    case 2: settings.quantize_loop = opt; break;
    case 3: settings.quantize_strength = opt.toInt(); break;
    case 4: settings.quantize_cc = (opt == "True"); break;
    case 5:
        settings.led_brightness = opt.toInt() / 100.0f;
        // Apply live — previously only boot-time main.cpp read this (R5). setBrightness
        // runs on core 0 while core 1 may be mid-show(): accepted torn-frame rule.
        pixels.apply_brightness();
        break;
    case 6: settings.arpeggiator_type = opt; break;
    case 7: settings.loop_type = opt; break;
    case 8: settings.arp_is_polyphonic = (opt == "True"); break;
    case 9: settings.arpeggiator_length = opt; break;
    case 10:
        settings.notes_all_at_once = (opt == "True");
        // Generate oneshot notes for existing oneshot loops when turned on
        if (settings.notes_all_at_once && _oneshot_refresh) {
            _oneshot_refresh();
        }
        break;
    case 11: settings.cc_reset_mode = opt; break;
    default: break;
    }
    settings.mark_dirty();
}

static void apply_midi_option(int idx, const String &opt) {
    switch (idx) {
    case 0: settings.midi_sync = (opt == "True"); break;
    case 1:
        settings.default_bpm = opt.toInt();
        if (!settings.midi_sync) {
            clock_.set_bpm(settings.default_bpm);
        }
        break;
    case 2: settings.midi_type = opt; break;
    case 3:
        // Dedup cache entries sent under the old out channel don't apply to the new
        // channel's receiver — drop them so the first CC after a switch isn't skipped (R10).
        if (settings.midi_channel_out != opt.toInt() - 1) {
            midi.clear_cc_cache();
        }
        settings.midi_channel_out = opt.toInt() - 1;
        break;
    case 4:
        if (opt == "ALL") {
            settings.midi_channel_in = -1;
        } else {
            settings.midi_channel_in = opt.toInt() - 1;
        }
        break;
    case 5:
        // Re-seed pads BEFORE updating default_velocity: check_default=true
        // compares against the OLD default (Python ran set_all first too).
        midi.set_all_midi_velocities(opt.toInt());
        settings.default_velocity = opt.toInt();
        break;
    case 6: settings.midi_usb_io = opt; break;
    case 7: settings.midi_aux_io = opt; break;
    case 8: settings.cc_resolution = opt.toInt(); break;
    case 9: settings.record_cc = (opt == "True"); break;
    case 10: settings.clock_source = opt; break;
    case 11: settings.passthru_mode = opt; break;
    default: break;
    }
    settings.mark_dirty();
}

// ---- table construction + index validation (Python module-level code) ----

static void validate_indices(const std::vector<Page> &pages, int *indices,
                             String (*value_display)(int)) {
    for (size_t idx = 0; idx < pages.size(); idx++) {
        const std::vector<String> &options = pages[idx].options;
        String current = value_display((int)idx);
        int stored = indices[idx];
        if (stored < 0 || stored >= (int)options.size() || options[stored] != current) {
            bool found = false;
            for (size_t i = 0; i < options.size(); i++) {
                if (options[i] == current) {
                    indices[idx] = (int)i;
                    found = true;
                    break;
                }
            }
            // Garbage string setting (web/hand-edited preset) + bad stored index: without
            // this the OOB index survives and get_settings_display_text() reads past the
            // options vector (R7).
            if (!found) {
                indices[idx] = 0;
            }
        }
    }
}

void init() {
    settings_pages = {
        {"trim silence", {"start", "end", "none", "both"}},
        {"quantize amt", {"none", "1/4", "1/8", "1/16", "1/32", "1/64"}},
        {"quantize loop", {"none", "1", "1/2", "1/4", "1/8"}},
        {"quantize %", {"0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"}},
        {"quantize cc?", {"True", "False"}},
        {"led intensity", {"0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"}},
        {"arp", {"up", "down", "random", "rand oct up", "rand oct dn", "rnd st up", "rnd st dn"}},
        {"loop type", {"loop", "oneshot", "hold"}},
        {"arp polyph", {"True", "False"}},
        {"arp length", {"1/64", "1/32", "1/16", "1/8", "1/4", "1/2", "1"}},
        {"inst oneshot", {"True", "False"}},
        {"CC Snapback", {"none", "hold", "all"}},
    };

    midi_settings_pages = {
        {"MIDI In Sync", {"True", "False"}},
        {"BPM", make_range(60, 200)},
        {"MIDI Type", {"USB", "AUX", "ALL"}},
        {"MIDI Ch Out", make_range(1, 17)},
        {"MIDI Ch In", {}}, // filled below: ALL + 1-16
        {"Def Vel", make_range(1, 128)},
        {"midi usb i/o", {"both", "in", "out"}},
        {"midi DIN i/o", {"both", "in", "out"}},
        {"CC Resolution", {"1", "2", "5", "8", "16", "32", "64"}},
        {"Record CC", {"True", "False"}},
        {"Clock Source", {"USB", "AUX"}},
        {"Pass Through", {"off", "aux", "usb", "all"}},
    };
    midi_settings_pages[4].options.push_back("ALL");
    for (int i = 1; i <= 16; i++) {
        midi_settings_pages[4].options.push_back(String(i));
    }

    validate_indices(settings_pages, settings.settings_menu_option_indices, settings_value_display);
    validate_indices(midi_settings_pages, settings.midi_settings_page_indices, midi_value_display);
}

// ---- display + navigation ----

String get_settings_display_text() {
    const Page &p = settings_pages[settings_menu_idx];
    return String(p.title) + ": " + p.options[settings.settings_menu_option_indices[settings_menu_idx]];
}

String get_midi_settings_display_text() {
    const Page &p = midi_settings_pages[midi_settings_page_index];
    return String(p.title) + ": " + p.options[settings.midi_settings_page_indices[midi_settings_page_index]];
}

void settings_menu_setup() {
    display.show_page_indicator(settings_menu_idx + 1, settings_pages.size());
}

void midi_settings_menu_setup() {
    display.show_page_indicator(midi_settings_page_index + 1, midi_settings_pages.size());
}

void settings_menu_fn_press_function(bool up_or_down, const char *action_type) {
    if (!strcmp(action_type, "press")) {
        return;
    }
    settings_menu_idx = next_or_previous_index(settings_menu_idx, settings_pages.size(), up_or_down, true);
    display.show_text_middle(get_settings_display_text());
    display.show_page_indicator(settings_menu_idx + 1, settings_pages.size());
}

void midi_settings_menu_fn_press_function(bool up_or_down, const char *action_type) {
    if (!strcmp(action_type, "press")) {
        return;
    }
    midi_settings_page_index = next_or_previous_index(midi_settings_page_index, midi_settings_pages.size(), up_or_down, true);
    display.show_text_middle(get_midi_settings_display_text());
    display.show_page_indicator(midi_settings_page_index + 1, midi_settings_pages.size());
}

void settings_menu_fn_btn_encoder_chg_function(bool up_or_down) {
    settings_menu_fn_press_function(up_or_down, "release");
}

void midi_settings_menu_fn_btn_encoder_chg_function(bool up_or_down) {
    midi_settings_menu_fn_press_function(up_or_down, "release");
}

// ---- pad channel assignment ----

static String _get_pad_channel_display_text(int channel_value) {
    if (channel_value == C::PAD_CH_AS_RECORDED) {
        return "Pad Ch: As Rec";
    }
    if (channel_value == C::PAD_CH_GLOBAL) {
        return "Pad Ch: Global";
    }
    if (channel_value >= 0 && channel_value <= 15) {
        return "Pad Ch: " + String(channel_value + 1);
    }
    return "Pad Ch: ???";
}

// Order (no wrap): As Recorded (-1) -> Global (-2) -> 1-16 (0-15)
static int _next_pad_channel(int current, bool up_or_down) {
    if (up_or_down) {
        if (current == C::PAD_CH_AS_RECORDED) return C::PAD_CH_GLOBAL;
        if (current == C::PAD_CH_GLOBAL) return 0;
        if (current < 15) return current + 1;
        return 15;
    }
    if (current == C::PAD_CH_AS_RECORDED) return C::PAD_CH_AS_RECORDED;
    if (current == C::PAD_CH_GLOBAL) return C::PAD_CH_AS_RECORDED;
    if (current == 0) return C::PAD_CH_GLOBAL;
    return current - 1;
}

void midi_settings_pad_held_function(int first_pad_held_idx, const bool *button_states, int encoder_delta) {
    if (first_pad_held_idx >= 0) {
        int current_setting = settings.midi_channel_pad_mapping[first_pad_held_idx];
        midi.current_assignment_channel = current_setting;
        display.show_notification(_get_pad_channel_display_text(current_setting));
    }

    if (encoder_delta == 0) {
        return;
    }

    int current = (midi.current_assignment_channel == -999) ? C::PAD_CH_AS_RECORDED
                                                            : midi.current_assignment_channel;
    int new_pad_channel = _next_pad_channel(current, encoder_delta > 0);
    midi.current_assignment_channel = new_pad_channel;
    display.show_notification(_get_pad_channel_display_text(new_pad_channel));

    for (uint8_t pad_idx = 0; pad_idx < C::NUM_PADS; pad_idx++) {
        if (button_states[pad_idx]) {
            midi.set_midi_channel_for_pad(pad_idx, (int8_t)new_pad_channel);
            pixels.flash_pixel(pad_idx, 0.2f);
        }
    }
}

// ---- option cycling ----

String next_setting_option(int setting_idx, bool up_or_down) {
    const std::vector<String> &options = settings_pages[setting_idx].options;
    settings.settings_menu_option_indices[setting_idx] = next_or_previous_index(
        settings.settings_menu_option_indices[setting_idx], options.size(), up_or_down, true);
    String new_value = options[settings.settings_menu_option_indices[setting_idx]];
    apply_settings_option(setting_idx, new_value);
    return new_value;
}

String set_next_or_prev_quantization_time(bool up_or_down) {
    return next_setting_option(1, up_or_down);
}

String set_next_arp_type(bool up_or_down) {
    return next_setting_option(6, up_or_down);
}

String set_next_arp_length(bool up_or_down) {
    return next_setting_option(9, up_or_down);
}

String get_arp_type_text() {
    return settings.arpeggiator_type;
}

String get_arp_len_text() {
    return settings.arpeggiator_length;
}

void generic_settings_fn_hold_function_dots(bool trigger_on_release) {
    if (!trigger_on_release) {
        display.display_right_dot(false);
        display.display_left_dot(true);
    } else {
        display.display_left_dot(false);
        display.display_right_dot(true);
    }
}

void settings_menu_encoder_change_function(bool up_or_down) {
    const std::vector<String> &options = settings_pages[settings_menu_idx].options;
    settings.settings_menu_option_indices[settings_menu_idx] = next_or_previous_index(
        settings.settings_menu_option_indices[settings_menu_idx], options.size(), up_or_down, true);
    String selected = options[settings.settings_menu_option_indices[settings_menu_idx]];
    display.show_text_middle(get_settings_display_text());
    display.show_page_indicator(settings_menu_idx + 1, settings_pages.size());
    apply_settings_option(settings_menu_idx, selected);
}

void midi_settings_menu_encoder_change_function(bool up_or_down) {
    const std::vector<String> &options = midi_settings_pages[midi_settings_page_index].options;
    settings.midi_settings_page_indices[midi_settings_page_index] = next_or_previous_index(
        settings.midi_settings_page_indices[midi_settings_page_index], options.size(), up_or_down, true);
    String selected = options[settings.midi_settings_page_indices[midi_settings_page_index]];
    display.show_text_middle(get_midi_settings_display_text());
    display.show_page_indicator(midi_settings_page_index + 1, midi_settings_pages.size());
    apply_midi_option(midi_settings_page_index, selected);
}

} // namespace settingsmenu
