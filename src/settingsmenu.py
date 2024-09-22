from display import display_text_middle, display_left_dot, display_right_dot
from utils import next_or_previous_index
from settings import settings as s
from arp import arpeggiator
from clock import clock
from midi import set_all_midi_velocities, change_midi_channel

# Initialize settings menu index
settings_menu_idx = 0
midi_settings_page_index = 0

# Define settings options and their mappings
settings_pages = [
    ("startup menu", [1, 2, 3, 4, 5, 6, 7]),
    ("trim silence", ["start", "end", "none", "both"]),
    ("quantize amt", ["none", "1/4", "1/8", "1/16", "1/32", "1/64"]),
    ("quantize loop", ["none", "1", "1/2", "1/4", "1/8"]), 
    ("quantize %", [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
    ("led brightness", [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
    ("arp type", ["up", "down", "random", "rand oct up", "rand oct dn", "randstartup", "randstartdown"]),
    ("loop type", ["chordloop", "chord"]),
    ("encoder steps", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
    ("arp polyphonic", [True, False]),
    ("arp length", ["1/64", "1/32", "1/16", "1/8", "1/4", "1/2", "1"]),
]

settings_mapping = {
    0: ("startup_menu_idx", int),
    1: ("trim_silence_mode", str),
    2: ("quantize_time", str),
    3: ("quantize_loop", str),
    4: ("quantize_strength", int),
    5: ("led_pixel_brightness", float),
    6: ("arpeggiator_type", str), 
    7: ("chordmode_looptype", str),
    8: ("encoder_steps_per_arpnote", int),
    9: ("arp_is_polyphonic", bool),
    10: ("arpeggiator_length", str),
}

midi_settings_pages = [
    ("MIDI In Sync", [True, False]),
    ("BPM",  [int(i) for i in range(60, 200)]),
    ("MIDI Type",  ["USB", "AUX", "ALL"]),
    ("MIDI Ch Out",  [int(i) for i in range(1, 17)]),
    ("MIDI Ch In",  [int(i) for i in range(1, 17)]),
    ("Def Vel", [int(i) for i in range(1, 127)])
]

midi_settings_mapping = {
    0: ("midi_sync", bool),
    1: ("default_bpm", int),
    2: ("midi_type", str),
    3: ("midi_channel_out", int),
    4: ("midi_channel_in", int),
    5: ("default_velocity", int),
}

def validate_indices(settings_pages, settings_mapping, indices, settings_object, special_cases=None):
    """
    Validates and updates the indices to match the current settings.

    Args:
        settings_pages (list): List of settings pages.
        settings_mapping (list): List of settings mappings.
        indices (list): List of indices to update.
        settings_object (object): The settings object to validate against.
        special_cases (dict, optional): Special cases for attribute conversion.
    """
    for idx, (title, options) in enumerate(settings_pages):
        attr_name, attr_type = settings_mapping[idx]
        current_value = getattr(settings_object, attr_name)
        selected_option = options[indices[idx]]

        # Convert the current value to the appropriate format for comparison
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
                print(f"Error: Could not find index for {current_value} in {options} ({title})")

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

    Returns:
        str: The display text for the selected setting.
    """
    title, options = settings_pages[settings_menu_idx]
    selected_option = options[s.settings_menu_option_indices[settings_menu_idx]]
    return f"{title}: {selected_option}"

def get_midi_settings_display_text():
    """
    Returns the display text for the currently selected MIDI setting.

    Returns:
        str: The display text for the selected MIDI setting.
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
    display_text_middle(get_settings_display_text())

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
    display_text_middle(get_midi_settings_display_text())

def settings_menu_fn_btn_encoder_chg_function(up_or_down=True):
    """
    Handles the encoder change function for the settings menu.

    Args:
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.
    """
    settings_menu_fn_press_function(up_or_down, action_type="release")

def midi_settings_menu_fn_btn_encoder_chg_function(up_or_down=True):
    """
    Handles the encoder change function for the MIDI settings menu.

    Args:
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.
    """
    midi_settings_menu_fn_press_function(up_or_down, action_type="release")

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

    if setting_idx == 6:
        arpeggiator.set_arp_type(s.arpeggiator_type)
    elif setting_idx == 10:
        arpeggiator.set_arp_length(s.arpeggiator_length)

    return new_value

def next_midi_setting_option(setting_idx, up_or_down=True):
    """
    Changes the selected option for a given MIDI setting.

    Args:
        setting_idx (int): The index of the MIDI setting to change.
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.

    Returns:
        str: The new value of the MIDI setting.
    """
    s.midi_settings_page_indices[setting_idx] = next_or_previous_index(
        s.midi_settings_page_indices[setting_idx], len(midi_settings_pages[setting_idx][2]), up_or_down, True
    )
    new_value = midi_settings_pages[setting_idx][2][s.midi_settings_page_indices[setting_idx]]

    attr_name, attr_type = midi_settings_mapping[setting_idx]
    if attr_type == int:
        setattr(s, attr_name, int(new_value))
    else:
        setattr(s, attr_name, new_value)

    return new_value

def set_next_or_prev_quantization_time(up_or_down=True):
    """
    Changes the quantization amount setting.

    Args:
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.

    Returns:
        str: The new value of the quantization amount setting.
    """
    return next_setting_option(2, up_or_down)

def set_next_arp_type(up_or_down=True):
    """
    Changes the arpeggiator type setting.

    Args:
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.

    Returns:
        str: The new value of the arpeggiator type setting.
    """
    return next_setting_option(6, up_or_down)

def set_next_arp_length(up_or_down=True):
    """
    Changes the arpeggiator length setting.

    Args:
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.

    Returns:
        str: The new value of the arpeggiator length setting.
    """
    return next_setting_option(10, up_or_down)

def get_arp_type_text():
    """
    Returns the current arpeggiator type.

    Returns:
        str: The current arpeggiator type.
    """
    return s.arpeggiator_type

def get_arp_len_text():
    """
    Returns the current arpeggiator length.

    Returns:
        str: The current arpeggiator length.
    """
    return s.arpeggiator_length

def generic_settings_fn_hold_function_dots(trigger_on_release=False):
    """
    Handles the hold function for the settings menu with dot display.

    Args:
        trigger_on_release (bool, optional): Whether to trigger on release. Default is False.
    """
    if not trigger_on_release:
        display_right_dot(False)
        display_left_dot(True)
    else:
        display_left_dot(False)
        display_right_dot(True)

def settings_menu_encoder_change_function(up_or_down=True):
    """
    Handles the encoder change function for the settings menu.

    Args:
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.
    """
    _, options = settings_pages[settings_menu_idx]

    s.settings_menu_option_indices[settings_menu_idx] = next_or_previous_index(
        s.settings_menu_option_indices[settings_menu_idx], len(options), up_or_down, True
    )
    selected_option = options[s.settings_menu_option_indices[settings_menu_idx]]
    display_text_middle(get_settings_display_text())

    attr_name, attr_type = settings_mapping[settings_menu_idx]
    if attr_type == int:
        setattr(s, attr_name, int(selected_option))
    elif attr_type == float:
        setattr(s, attr_name, int(selected_option) / 100)
    else:
        setattr(s, attr_name, selected_option)

    if settings_menu_idx == 6:
        arpeggiator.set_arp_type(s.arpeggiator_type)
    elif settings_menu_idx == 10:
        arpeggiator.set_arp_length(s.arpeggiator_length)
    elif settings_menu_idx == 0:
        s.startup_menu_idx = int(selected_option) - 1
        print(f"Startup menu index: {s.startup_menu_idx}")


def midi_settings_menu_encoder_change_function(up_or_down=True):
    """
    Handles the encoder change function for the settings menu.

    Args:
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.
    """
    _, options = midi_settings_pages[midi_settings_page_index]

    s.midi_settings_page_indices[midi_settings_page_index] = next_or_previous_index(
        s.midi_settings_page_indices[midi_settings_page_index], len(options), up_or_down, True
    )
    selected_option = options[s.midi_settings_page_indices[midi_settings_page_index]]
    display_text_middle(get_midi_settings_display_text())

    if midi_settings_page_index == 5:
        set_all_midi_velocities(selected_option)

    attr_name, attr_type = midi_settings_mapping[midi_settings_page_index]
    if attr_type == int:
        setattr(s, attr_name, int(selected_option))
    elif attr_type == float:
        setattr(s, attr_name, int(selected_option) / 100)
    elif attr_type == bool:
        setattr(s, attr_name, bool(selected_option))
    else:
        setattr(s, attr_name, selected_option)

    # 1 - default bpm
    if midi_settings_page_index == 1:
        s.default_bpm = selected_option
        if not s.midi_sync:
            clock.update_all_timings(60 / int(s.default_bpm))

    if midi_settings_page_index == 3:
        change_midi_channel(int(selected_option), "out", selected_option-1)
    
    if midi_settings_page_index == 4:
        change_midi_channel(int(selected_option), "in", selected_option-1)
