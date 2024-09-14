from display import display_text_middle, display_left_dot, display_right_dot
from utils import next_or_previous_index
from settings import settings as s
from arp import arpeggiator
from clock import clock

# Initialize settings menu index
settings_menu_idx = 0
midi_settings_page_index = 0

# Define settings options and their mappings
settings_pages = [
    ("startup menu", ["1", "2", "3", "4", "5", "6", "7"]),
    ("trim silence", ["start", "end", "none", "both"]),
    ("quantize amt", ["none", "1/4", "1/8", "1/16", "1/32", "1/64"]),
    ("quantize loop", ["none", "1", "1/2", "1/4", "1/8"]), 
    ("quantize percent", ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]),
    ("led brightness", ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]),
    ("arp type", ["up", "down", "random", "rand oct up", "rand oct dn", "randstartup", "randstartdown"]),
    ("loop type", ["chordloop", "chord"]),
    ("encoder steps", ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]),
    ("arp polyphonic", ["True", "False"]),
    ("arp length", ["1/64", "1/32", "1/16", "1/8", "1/4", "1/2", "1"]),
]

settings_mapping = {
    0: ("STARTUP_MENU_IDX", int),
    1: ("TRIM_SILENCE_MODE", str),
    2: ("quantize_amt", str),
    3: ("QUANTIZE_LOOP", str),
    4: ("QUANTIZE_STRENGTH", int),
    5: ("PIXEL_BRIGHTNESS", float),
    6: ("ARPPEGIATOR_TYPE", str),
    7: ("CHORDMODE_LOOPTYPE", str),
    8: ("ENCODER_STEPS", int),
    9: ("POLYPHONIC_ARP", bool),
    10: ("ARP_LENGTH", str),
}

midi_settings_pages = [
    ("MIDI In Sync", ["True", "False"]),
    ("BPM",  [int(i) for i in range(60, 200)]),
    ("MIDI Type",  ["USB", "AUX", "All"]),
    ("MIDI Ch",  [int(i) for i in range(1, 17)]),
    ("Def Vel", [int(i) for i in range(1, 127)])
]

midi_settings_mapping = {
    0: ("MIDI_SYNC", bool),
    1: ("DEFAULT_BPM", int),
    2: ("MIDI_TYPE", str),
    3: ("MIDI_CHANNEL", int),
    4: ("DEFAULT_VELOCITY", int),
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
            formatted_value = str(current_value)
        elif attr_type == float:
            current_value = int(current_value * 100)  # Convert to percentage for comparison
            formatted_value = str(current_value)
        elif attr_type == bool:
            formatted_value = str(current_value)
        else:
            formatted_value = current_value

        if selected_option != formatted_value:
            try:
                indices[idx] = options.index(formatted_value)
            except ValueError:
                print(f"Error: Could not find index for {formatted_value} in {options} ({title})")

def validate_settings_menu_indices():
    """
    Validates and updates the settings menu indices to match the current settings.
    """
    print(f"Old settings: {s.SETTINGS_MENU_OPTION_indices}")
    print(f"Old midi settings: {s.MIDI_SETTINGS_PAGE_indices}")

    settings_special_cases = {
        "QUANTIZE_STRENGTH": lambda x: round(x, -1),
        "STARTUP_MENU_IDX": lambda x: x + 1  # Convert to 1-indexed
    }

    midi_special_cases = {
        "MIDI_CHANNEL": lambda x: x + 1  # Convert to 1-indexed
    }

    validate_indices(settings_pages, settings_mapping, s.SETTINGS_MENU_OPTION_indices, s, settings_special_cases)
    validate_indices(midi_settings_pages, midi_settings_mapping, s.MIDI_SETTINGS_PAGE_indices, s, midi_special_cases)

    print(f"New settings: {s.SETTINGS_MENU_OPTION_indices}")
    print(f"New midi settings: {s.MIDI_SETTINGS_PAGE_indices}")

validate_settings_menu_indices()

def get_settings_display_text():
    """
    Returns the display text for the currently selected setting.

    Returns:
        str: The display text for the selected setting.
    """
    title, options = settings_pages[settings_menu_idx]
    selected_option = options[s.SETTINGS_MENU_OPTION_indices[settings_menu_idx]]
    return f"{title}: {selected_option}"

def get_midi_settings_display_text():
    """
    Returns the display text for the currently selected MIDI setting.

    Returns:
        str: The display text for the selected MIDI setting.
    """
    title, options = midi_settings_pages[midi_settings_page_index]
    selected_option = options[s.MIDI_SETTINGS_PAGE_indices[midi_settings_page_index]]
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
    s.SETTINGS_MENU_OPTION_indices[setting_idx] = next_or_previous_index(
        s.SETTINGS_MENU_OPTION_indices[setting_idx], len(settings_pages[setting_idx][1]), up_or_down, True
    )
    new_value = settings_pages[setting_idx][1][s.SETTINGS_MENU_OPTION_indices[setting_idx]]

    attr_name, attr_type = settings_mapping[setting_idx]
    if attr_type == int:
        setattr(s, attr_name, int(new_value))
    elif attr_type == float:
        setattr(s, attr_name, int(new_value) / 100)
    else:
        setattr(s, attr_name, new_value)

    if setting_idx == 6:
        arpeggiator.set_arp_type(s.ARPPEGIATOR_TYPE)
    elif setting_idx == 10:
        arpeggiator.set_arp_length(s.ARP_LENGTH)

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
    s.MIDI_SETTINGS_PAGE_indices[setting_idx] = next_or_previous_index(
        s.MIDI_SETTINGS_PAGE_indices[setting_idx], len(midi_settings_pages[setting_idx][2]), up_or_down, True
    )
    new_value = midi_settings_pages[setting_idx][2][s.MIDI_SETTINGS_PAGE_indices[setting_idx]]

    attr_name, attr_type = midi_settings_mapping[setting_idx]
    if attr_type == int:
        setattr(s, attr_name, int(new_value))
    else:
        setattr(s, attr_name, new_value)

    return new_value

def next_quantization_amt(up_or_down=True):
    """
    Changes the quantization amount setting.

    Args:
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.

    Returns:
        str: The new value of the quantization amount setting.
    """
    return next_setting_option(2, up_or_down)

def next_arp_type(up_or_down=True):
    """
    Changes the arpeggiator type setting.

    Args:
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.

    Returns:
        str: The new value of the arpeggiator type setting.
    """
    return next_setting_option(6, up_or_down)

def next_arp_length(up_or_down=True):
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
    return s.ARPPEGIATOR_TYPE

def get_arp_len_text():
    """
    Returns the current arpeggiator length.

    Returns:
        str: The current arpeggiator length.
    """
    return s.ARP_LENGTH

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

    s.SETTINGS_MENU_OPTION_indices[settings_menu_idx] = next_or_previous_index(
        s.SETTINGS_MENU_OPTION_indices[settings_menu_idx], len(options), up_or_down, True
    )
    selected_option = options[s.SETTINGS_MENU_OPTION_indices[settings_menu_idx]]
    display_text_middle(get_settings_display_text())

    attr_name, attr_type = settings_mapping[settings_menu_idx]
    if attr_type == int:
        setattr(s, attr_name, int(selected_option))
    elif attr_type == float:
        setattr(s, attr_name, int(selected_option) / 100)
    else:
        setattr(s, attr_name, selected_option)

    if settings_menu_idx == 6:
        arpeggiator.set_arp_type(s.ARPPEGIATOR_TYPE)
    elif settings_menu_idx == 10:
        arpeggiator.set_arp_length(s.ARP_LENGTH)
    elif settings_menu_idx == 0:
        s.STARTUP_MENU_IDX = int(selected_option) - 1
        print(f"Startup menu index: {s.STARTUP_MENU_IDX}")


def midi_settings_menu_encoder_change_function(up_or_down=True):
    """
    Handles the encoder change function for the settings menu.

    Args:
        up_or_down (bool, optional): True to move forward, False to move backward. Default is True.
    """
    _, options = midi_settings_pages[midi_settings_page_index]

    s.MIDI_SETTINGS_PAGE_indices[midi_settings_page_index] = next_or_previous_index(
        s.MIDI_SETTINGS_PAGE_indices[midi_settings_page_index], len(options), up_or_down, True
    )
    selected_option = options[s.MIDI_SETTINGS_PAGE_indices[midi_settings_page_index]]
    display_text_middle(get_midi_settings_display_text())

    attr_name, attr_type = midi_settings_mapping[midi_settings_page_index]
    if attr_type == int:
        setattr(s, attr_name, int(selected_option))
    elif attr_type == float:
        setattr(s, attr_name, int(selected_option) / 100)
    elif attr_type == bool:
        setattr(s, attr_name, selected_option == "True")
    else:
        setattr(s, attr_name, selected_option)

    # 1 - default bpm
    if midi_settings_page_index == 1:
        s.DEFAULT_BPM = selected_option
        if not s.MIDI_SYNC:
            clock.update_all_timings(60 / int(s.DEFAULT_BPM))
        
