from display import display
from utils import next_or_previous_index
from settings import settings as s
from clock import clock
from midi import midi
from pixels import pixels
import constants as C

settings_menu_idx = 0
midi_settings_page_index = 0

def _find_index(options, value):
    """Find index of value in list or range. Handles range() which lacks .index() method."""
    if isinstance(options, range):
        if value in options:
            return value - options.start
        raise ValueError(f"{value} is not in range")
    return options.index(value)

# Define settings options and their mappings
settings_pages = [
    ("trim silence", ["start", "end", "none", "both"]),
    ("quantize amt", ["none", "1/4", "1/8", "1/16", "1/32", "1/64"]),
    ("quantize loop", ["none", "1", "1/2", "1/4", "1/8"]), 
    ("quantize %", [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
    ("quantize cc?", [True, False]),
    ("led intensity", [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
    ("arp", ["up", "down", "random", "rand oct up", "rand oct dn", "rnd st up", "rnd st dn"]),
    ("loop type", ["loop", "oneshot", "hold"]),
    ("arp polyph", [True, False]),
    ("arp length", ["1/64", "1/32", "1/16", "1/8", "1/4", "1/2", "1"]),
    ("inst oneshot", [True, False]),
    ("CC to Flash", [False, True]),
    ("CC Snapback", ["none", "hold", "all"]),
]

settings_mapping = {
    0: ("trim_silence_mode", str),
    1: ("quantize_time", str),
    2: ("quantize_loop", str),
    3: ("quantize_strength", int),
    4: ("quantize_cc", bool),
    5: ("led_brightness", float),
    6: ("arpeggiator_type", str), 
    7: ("loop_type", str),
    8: ("arp_is_polyphonic", bool),
    9: ("arpeggiator_length", str),
    10: ("notes_all_at_once", bool),
    11: ("cc_stream_to_flash", bool),
    12: ("cc_reset_mode", str),
}

# Memory optimization: Use range() instead of list comprehensions
# range() objects are ~48 bytes vs ~1KB for full lists
midi_settings_pages = [
    ("MIDI In Sync", [True, False]),
    ("BPM", range(60, 200)),                    # Was: [int(i) for i in range(60, 200)] ~1.1KB
    ("MIDI Type",  ["USB", "AUX", "ALL"]),
    ("MIDI Ch Out", range(1, 17)),              # Was: [int(i) for i in range(1, 17)] ~130 bytes
    ("MIDI Ch In",  ["ALL"] + list(range(1, 17))),  # Keep list - mixed types (string + ints)
    ("Def Vel", range(1, 128)),                 # Was: [int(i) for i in range(1, 127)] ~1KB (fixed to 128 for 1-127)
    ("midi usb i/o", ["both", "in", "out"]),
    ("midi DIN i/o", ["both", "in", "out"]),
    ("CC Resolution", [1, 2, 5, 8, 16, 32, 64]),
    ("Record CC", [True, False]),
    ("Clock Source", ["USB", "AUX"]),
    ("Pass Through", ["off", "aux", "usb", "all"]),
    ("Ch Mode", ["per note", "per pad"]),
]

midi_settings_mapping = {
    0: ("midi_sync", bool),
    1: ("default_bpm", int),
    2: ("midi_type", str),
    3: ("midi_channel_out", int),
    4: ("midi_channel_in", int),
    5: ("default_velocity", int),
    6: ("midi_usb_io", str),
    7: ("midi_aux_io", str),
    8: ("cc_resolution", int),
    9: ("record_cc", bool),
    10:("clock_source", str),
    11:("passthru_mode", str),
    12:("midi_channel_mode", str),
}

def validate_indices(settings_pgs, settings_map, indices, settings_object, special_cases=None):
    """Update indices to match current settings values."""
    expected_len = len(settings_pgs)
    # Fix length mismatch: truncate if too long, extend with 0s if too short
    while len(indices) > expected_len:
        indices.pop()
    while len(indices) < expected_len:
        indices.append(0)
    
    for idx, (title, options) in enumerate(settings_pgs):
        attr_name, attr_type = settings_map[idx]
        current_value = getattr(settings_object, attr_name)
        selected_option = options[indices[idx]]

        if special_cases and attr_name in special_cases:
            current_value = special_cases[attr_name](current_value)
        elif attr_type == int:
            current_value = int(current_value)
        elif attr_type == float:
            current_value = int(current_value * 100)  # Convert to percentage for comparison
        elif attr_type == bool:
            current_value = bool(current_value)

        if selected_option != current_value:
            try:
                indices[idx] = _find_index(options, current_value)
            except ValueError:
                if s.debug:
                    print(f"[ERROR] Could not find index for {current_value} in {options} ({title})")

def validate_settings_menu_indices():
    settings_special_cases = {
        "quantize_strength": lambda x: round(x, -1)
    }

    midi_special_cases = {
        "midi_channel_out": lambda x: x + 1,  # Convert to 1-indexed
        "midi_channel_in": lambda x: "ALL" if x == -1 else x + 1,  # Convert -1 to ALL, others to 1-indexed
        "midi_channel_mode": lambda x: x.replace("_", " "),  # Display without underscores
    }

    validate_indices(settings_pages, settings_mapping, s.settings_menu_option_indices, s, settings_special_cases)
    validate_indices(midi_settings_pages, midi_settings_mapping, s.midi_settings_page_indices, s, midi_special_cases)

validate_settings_menu_indices()

def get_settings_display_text():
    title, options = settings_pages[settings_menu_idx]
    selected_option = options[s.settings_menu_option_indices[settings_menu_idx]]
    return f"{title}: {selected_option}"

def get_midi_settings_display_text():
    title, options = midi_settings_pages[midi_settings_page_index]
    selected_option = options[s.midi_settings_page_indices[midi_settings_page_index]]
    return f"{title}: {selected_option}"

def settings_menu_setup():
    """Setup function called when entering settings menu."""
    display.show_page_indicator(settings_menu_idx + 1, len(settings_pages))

def midi_settings_menu_setup():
    """Setup function called when entering MIDI settings menu."""
    display.show_page_indicator(midi_settings_page_index + 1, len(midi_settings_pages))

def settings_menu_fn_press_function(up_or_down=True, action_type="press"):
    if action_type == "press":
        return
    
    global settings_menu_idx
    settings_menu_idx = next_or_previous_index(settings_menu_idx, len(settings_pages), up_or_down, True)
    display.show_text_middle(get_settings_display_text())
    display.show_page_indicator(settings_menu_idx + 1, len(settings_pages))

def midi_settings_menu_fn_press_function(up_or_down=True, action_type="press"):
    if action_type == "press":
        return
    
    global midi_settings_page_index
    midi_settings_page_index = next_or_previous_index(midi_settings_page_index, len(midi_settings_pages), up_or_down, True)
    display.show_text_middle(get_midi_settings_display_text())
    display.show_page_indicator(midi_settings_page_index + 1, len(midi_settings_pages))

def settings_menu_fn_btn_encoder_chg_function(up_or_down=True):
    settings_menu_fn_press_function(up_or_down, action_type="release")

def midi_settings_menu_fn_btn_encoder_chg_function(up_or_down=True):
    midi_settings_menu_fn_press_function(up_or_down, action_type="release")

def midi_settings_pad_held_function(first_pad_held_idx, button_states_array, encoder_delta):
    """Assign MIDI channels to held pads via encoder."""
    if first_pad_held_idx >= 0:
        if s.midi_channel_pad_mapping[first_pad_held_idx] is None:
            display.show_notification("No Channel Assigned")
            return
        else:
            midi.current_assignment_channel = s.midi_channel_pad_mapping[first_pad_held_idx]
            display.show_notification(f"Pad Channel: {midi.current_assignment_channel+1}")

    if encoder_delta == 0:
        return

    if midi.current_assignment_channel is None:
        new_pad_channel = s.midi_channel_out
    else:
        new_pad_channel = next_or_previous_index(midi.current_assignment_channel, 16, encoder_delta > 0, False)
    midi.current_assignment_channel = new_pad_channel
    display.show_notification(f"Pad Channel: {new_pad_channel+1}")

    for pad_idx in range(C.NUM_PADS):
        if button_states_array[pad_idx] is True:
            midi.set_midi_channel_for_pad(pad_idx, new_pad_channel)
            pixels.flash_pixel(pad_idx, 0.2)

def next_setting_option(setting_idx, up_or_down=True):
    s.settings_menu_option_indices[setting_idx] = next_or_previous_index(
        s.settings_menu_option_indices[setting_idx], len(settings_pages[setting_idx][1]), up_or_down, True
    )
    new_value = settings_pages[setting_idx][1][s.settings_menu_option_indices[setting_idx]]

    attr_name, attr_type = settings_mapping[setting_idx]
    if attr_type == int:
        setattr(s, attr_name, int(new_value))
    elif attr_type == float:
        setattr(s, attr_name, int(new_value) / 100)
    else:
        setattr(s, attr_name, new_value)

    return new_value

def set_next_or_prev_quantization_time(up_or_down=True):
    return next_setting_option(1, up_or_down)

def set_next_arp_type(up_or_down=True):
    return next_setting_option(6, up_or_down)

def set_next_arp_length(up_or_down=True):
    return next_setting_option(9, up_or_down)

def get_arp_type_text():
    return s.arpeggiator_type

def get_arp_len_text():
    return str(s.arpeggiator_length)

def generic_settings_fn_hold_function_dots(trigger_on_release=False):
    if not trigger_on_release:
        display.display_right_dot(False)
        display.display_left_dot(True)
    else:
        display.display_left_dot(False)
        display.display_right_dot(True)

def settings_menu_encoder_change_function(up_or_down=True):
    _, options = settings_pages[settings_menu_idx]

    s.settings_menu_option_indices[settings_menu_idx] = next_or_previous_index(
        s.settings_menu_option_indices[settings_menu_idx], len(options), up_or_down, True
    )
    selected_option = options[s.settings_menu_option_indices[settings_menu_idx]]
    display.show_text_middle(get_settings_display_text())
    display.show_page_indicator(settings_menu_idx + 1, len(settings_pages))

    attr_name, attr_type = settings_mapping[settings_menu_idx]
    if attr_type == int:
        setattr(s, attr_name, int(selected_option))
    elif attr_type == float:
        setattr(s, attr_name, int(selected_option) / 100)
    else:
        setattr(s, attr_name, selected_option)
    
    # Handle notes_all_at_once setting change - generate oneshot notes for existing oneshot loops
    if attr_name == "notes_all_at_once" and selected_option is True:
        from loopmanager import loop_manager
        for loop in loop_manager.loops:
            if loop != "" and loop.loop_type == "oneshot":
                loop.ensure_oneshot_notes()

def midi_settings_menu_encoder_change_function(up_or_down=True):
    _, options = midi_settings_pages[midi_settings_page_index]

    s.midi_settings_page_indices[midi_settings_page_index] = next_or_previous_index(
        s.midi_settings_page_indices[midi_settings_page_index], len(options), up_or_down, True
    )
    selected_option = options[s.midi_settings_page_indices[midi_settings_page_index]]
    display.show_text_middle(get_midi_settings_display_text())
    display.show_page_indicator(midi_settings_page_index + 1, len(midi_settings_pages))

    if midi_settings_page_index == 5:
        midi.set_all_midi_velocities(selected_option)

    attr_name, attr_type = midi_settings_mapping[midi_settings_page_index]
    if attr_type == int:
        if attr_name == "midi_channel_in":
            # Convert from 1-indexed display (or "ALL") to 0-indexed internal
            if selected_option == "ALL":
                setattr(s, attr_name, -1)
                midi.change_midi_channel(set_channel=-1, in_or_out="in", update_global_channel=False)
            else:
                setattr(s, attr_name, int(selected_option) - 1)
                midi.change_midi_channel(set_channel=int(selected_option) - 1, in_or_out="in", update_global_channel=False)
        elif attr_name == "midi_channel_out":
            # Convert from 1-indexed display to 0-indexed internal
            setattr(s, attr_name, int(selected_option) - 1)
            midi.change_midi_channel(set_channel=int(selected_option) - 1, in_or_out="out", update_global_channel=False)
        else:
            setattr(s, attr_name, int(selected_option))
    elif attr_type == float:
        setattr(s, attr_name, int(selected_option) / 100)
    elif attr_type == bool:
        setattr(s, attr_name, bool(selected_option))
    else:
        # Convert display strings back to internal format (e.g. "per note" -> "per_note")
        if attr_name == "midi_channel_mode":
            setattr(s, attr_name, selected_option.replace(" ", "_"))
        else:
            setattr(s, attr_name, selected_option)

    if midi_settings_page_index == 1:
        s.default_bpm = selected_option
        if not s.midi_sync:
            clock.set_bpm(int(s.default_bpm))
