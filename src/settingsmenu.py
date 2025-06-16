from display import display
from utils import next_or_previous_index
from settings import settings as s
from clock import clock
from midi import midi
from pixels import pixels
import constants as C

settings_menu_idx = 0
midi_settings_page_index = 0

# Define settings options and their mappings
settings_pages = [
    ("startup menu", [1, 2, 3, 4, 5, 6]),
    ("trim silence", ["start", "end", "none", "both"]),
    ("quantize amt", ["none", "1/4", "1/8", "1/16", "1/32", "1/64"]),
    ("quantize loop", ["none", "1", "0.5", "0.25"]), 
    ("quantize %", [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
    ("quantize cc?", [True, False]),
    ("led intensity", [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
    ("arp", ["up", "down", "random", "rand oct up", "rand oct dn", "rnd st up", "rnd st dn"]),
    ("loop type", ["loop", "oneshot"]),
    ("encoder steps", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
    ("arp polyph", [True, False]),
    ("arp length", ["1/64", "1/32", "1/16", "1/8", "1/4", "1/2", "1"]),
    ("inst oneshot", [True, False]),
]

settings_mapping = {
    0: ("startup_menu_idx", int),
    1: ("trim_silence_mode", str),
    2: ("quantize_time", str),
    3: ("quantize_loop", str),
    4: ("quantize_strength", int),
    5: ("quantize_cc", bool),
    6: ("led_brightness", float),
    7: ("arpeggiator_type", str), 
    8: ("chordmode_looptype", str),
    9: ("encoder_steps_per_arpnote", int),
    10: ("arp_is_polyphonic", bool),
    11: ("arpeggiator_length", str),
    12: ("notes_all_at_once", bool),
}

midi_settings_pages = [
    ("MIDI In Sync", [True, False]),
    ("BPM",  [int(i) for i in range(60, 200)]),
    ("MIDI Type",  ["USB", "AUX", "ALL"]),
    ("MIDI Ch Out",  [int(i) for i in range(1, 17)]),
    ("MIDI Ch In",  [int(i) for i in range(1, 17)]),
    ("Def Vel", [int(i) for i in range(1, 127)]),
    ("midi usb i/o", ["both", "in", "out"]),
    ("midi DIN i/o", ["both", "in", "out"]),
    ("CC Resolution", [1, 2, 5, 8, 16, 32, 64]),
    ("Record CC", [True, False]),
    ("Clock Source", ["AUTO","USB","AUX"]),
    ("MIDI Passthru", [True, False]),
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
    11:("midi_passthru", bool),
}

def validate_indices(settings_pgs, settings_map, indices, settings_object, special_cases=None):
    """
    Validates and updates the indices to match the current settings.

    Args:
        settings_pgs (list): List of settings pages.
        settings_map (list): List of settings mappings.
        indices (list): List of indices to update.
        settings_object (object): The settings object to validate against.
        special_cases (dict, optional): Special cases for attribute conversion.
    """
    for idx, (title, options) in enumerate(settings_pgs):
        attr_name, attr_type = settings_map[idx]
        current_value = getattr(settings_object, attr_name)
        selected_option = options[indices[idx]]

        if attr_type == int:
            current_value = int(current_value)
            if special_cases and attr_name in special_cases:
                current_value = special_cases[attr_name](current_value)

        elif attr_type == float:
            current_value = int(current_value * 100)  # Convert to percentage for comparison

        elif attr_type == bool:
            current_value = bool(current_value)

        if selected_option != current_value:
            try:
                indices[idx] = options.index(current_value)
            except ValueError:
                print(f"[ERROR] Could not find index for {current_value} in {options} ({title})")

def validate_settings_menu_indices():
    """
    Validates and updates the settings menu indices to match the current settings.
    """

    settings_special_cases = {
        "quantize_strength": lambda x: round(x, -1),
        "startup_menu_idx": lambda x: x + 1  # Convert to 1-indexed
    }

    midi_special_cases = {
        "midi_channel_out": lambda x: x + 1,  # Convert to 1-indexed
        "midi_channel_in": lambda x: x + 1,  # Convert to 1-indexed
    }

    validate_indices(settings_pages, settings_mapping, s.settings_menu_option_indices, s, settings_special_cases)
    validate_indices(midi_settings_pages, midi_settings_mapping, s.midi_settings_page_indices, s, midi_special_cases)

validate_settings_menu_indices()

def get_settings_display_text():
    """
    Returns the display text for the currently selected setting.
    """
    title, options = settings_pages[settings_menu_idx]
    selected_option = options[s.settings_menu_option_indices[settings_menu_idx]]
    return f"{title}: {selected_option}"

def get_midi_settings_display_text():
    """
    Returns the display text for the currently selected MIDI setting.
    """
    title, options = midi_settings_pages[midi_settings_page_index]
    selected_option = options[s.midi_settings_page_indices[midi_settings_page_index]]
    return f"{title}: {selected_option}"

def settings_menu_fn_press_function(up_or_down=True, action_type="press"):
    """
    Handles the press function for the settings menu.

    Args:
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.
        action_type (str, optional): The type of action. Default is "press".
    """
    if action_type == "press":
        return
    
    global settings_menu_idx
    settings_menu_idx = next_or_previous_index(settings_menu_idx, len(settings_pages), up_or_down, True)
    display.show_text_middle(get_settings_display_text())

def midi_settings_menu_fn_press_function(up_or_down=True, action_type="press"):
    """
    Handles the press function for the MIDI settings menu.

    Args:
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.
        action_type (str, optional): The type of action. Default is "press".
    """
    if action_type == "press":
        return
    
    global midi_settings_page_index
    midi_settings_page_index = next_or_previous_index(midi_settings_page_index, len(midi_settings_pages), up_or_down, True)
    display.show_text_middle(get_midi_settings_display_text())

def settings_menu_fn_btn_encoder_chg_function(up_or_down=True):
    """
    Handles the encoder change function for the settings menu.
    """
    settings_menu_fn_press_function(up_or_down, action_type="release")

def midi_settings_menu_fn_btn_encoder_chg_function(up_or_down=True):
    """
    Handles the encoder change function for the MIDI settings menu.
    """
    midi_settings_menu_fn_press_function(up_or_down, action_type="release")

def midi_settings_pad_held_function(first_pad_held_idx, button_states_array, encoder_delta):
    """
    Handles the MIDI settings when a pad is held down.
    Args:
        first_pad_held_idx (int): The index of the first pad held down.
        button_states_array (list): The array of button states.
        encoder_delta (int): The delta value from the encoder.
    """
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
    """
    Changes the selected option for a given setting.

    Args:
        setting_idx (int): The index of the setting to change.
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.

    Returns:
        str: The new value of the setting.
    """
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
    """
    Changes the quantization amount setting and returns it.
    """
    return next_setting_option(2, up_or_down)

def set_next_arp_type(up_or_down=True):
    """
    Changes the arpeggiator type setting and returns it.
    """
    return next_setting_option(7, up_or_down)

def set_next_arp_length(up_or_down=True):
    """
    Changes the arpeggiator length setting and returns it.
    """
    return next_setting_option(11, up_or_down)

def get_arp_type_text():
    """
    Returns the current arpeggiator type as a string.
    """
    return s.arpeggiator_type

def get_arp_len_text():
    """
    Returns the current arpeggiator length.
    """
    return str(s.arpeggiator_length)

def generic_settings_fn_hold_function_dots(trigger_on_release=False):
    """
    Handles the hold function for the settings menu with dot display.
    """
    if not trigger_on_release:
        display.display_right_dot(False)
        display.display_left_dot(True)
    else:
        display.display_left_dot(False)
        display.display_right_dot(True)

def settings_menu_encoder_change_function(up_or_down=True):
    """
    Handles the encoder change function for the settings menu.
    """
    _, options = settings_pages[settings_menu_idx]

    s.settings_menu_option_indices[settings_menu_idx] = next_or_previous_index(
        s.settings_menu_option_indices[settings_menu_idx], len(options), up_or_down, True
    )
    selected_option = options[s.settings_menu_option_indices[settings_menu_idx]]
    display.show_text_middle(get_settings_display_text())

    attr_name, attr_type = settings_mapping[settings_menu_idx]
    if attr_type == int:
        setattr(s, attr_name, int(selected_option))
    elif attr_type == float:
        setattr(s, attr_name, int(selected_option) / 100)
    else:
        setattr(s, attr_name, selected_option)

    if settings_menu_idx == 0:
        s.startup_menu_idx = int(selected_option) - 1

def midi_settings_menu_encoder_change_function(up_or_down=True):
    """
    Handles the encoder change function for the settings menu.
    """
    _, options = midi_settings_pages[midi_settings_page_index]

    s.midi_settings_page_indices[midi_settings_page_index] = next_or_previous_index(
        s.midi_settings_page_indices[midi_settings_page_index], len(options), up_or_down, True
    )
    selected_option = options[s.midi_settings_page_indices[midi_settings_page_index]]
    display.show_text_middle(get_midi_settings_display_text())

    if midi_settings_page_index == 5:
        midi.set_all_midi_velocities(selected_option)

    attr_name, attr_type = midi_settings_mapping[midi_settings_page_index]
    if attr_type == int:
        setattr(s, attr_name, int(selected_option))
    elif attr_type == float:
        setattr(s, attr_name, int(selected_option) / 100)
    elif attr_type == bool:
        setattr(s, attr_name, bool(selected_option))
    else:
        setattr(s, attr_name, selected_option)

    if midi_settings_page_index == 1:
        s.default_bpm = selected_option
        if not s.midi_sync:
            clock.set_bpm(int(s.default_bpm))

    if midi_settings_page_index == 3:
        midi.change_midi_channel(int(selected_option), "out", selected_option-1)
    
    if midi_settings_page_index == 4:
        midi.change_midi_channel(int(selected_option), "in", selected_option-1)
