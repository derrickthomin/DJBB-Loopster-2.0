import time
from settings import settings
from utils import next_or_previous_index
from display import display_notification, display_text_middle
import supervisor
from debug import print_debug

selected_preset_name = settings.get_startup_preset() 
PRESET_NAMES_LIST = settings.get_preset_names_list()
selected_preset_idx = int(PRESET_NAMES_LIST.index(selected_preset_name))

def load_preset(action_type = "press"):
    """
    Loads a preset based on the selected preset index.

    The function retrieves the preset name from the `PRESET_NAMES_LIST` using the `selected_preset_idx`.
    If the preset name is not found in the list, an error message is printed and the function returns.
    Otherwise, the `settings.load_preset` function is called with the preset name, and the `supervisor.reload` function is called.
    """

    if action_type == "release":
        return

    preset_name = PRESET_NAMES_LIST[selected_preset_idx]
    if preset_name.upper() not in PRESET_NAMES_LIST:
        print_debug(f"Invalid preset name: {preset_name}")
        return
    
    settings.load_preset(preset_name)
    supervisor.reload()

# This just makes sure that *NEW* is not selected when moving to the load preset menu
def load_preset_setup():
    """
    Sets up the load preset menu.

    This function ensures that the selected preset index is not set to the "*NEW*" preset.
    If the selected preset index is set to "*NEW*", the index is moved to the next preset.
    """
    global selected_preset_idx

    if PRESET_NAMES_LIST[selected_preset_idx] == "*NEW*":
        selected_preset_idx = next_or_previous_index(selected_preset_idx, len(PRESET_NAMES_LIST), True)
    display_text_middle(get_preset_display_text())

def save_preset_to_file(action_type = "press"):
    """
    Saves the current preset settings.

    This function saves the MIDI settings and the current preset name.
    If the preset name is "*NEW*", a new preset is created.

    :return: None
    """
    if action_type == "release":
        return
    
    preset_name = PRESET_NAMES_LIST[selected_preset_idx]

    try:
        settings.save_preset_to_file(preset_name)
        if preset_name == "*NEW*":
            display_notification("created new preset")
            time.sleep(1)
            supervisor.reload()
        else:
            display_notification(f"Saved {preset_name}")

    except Exception as e:
        print(f"Error saving preset {preset_name}: {e}")


def select_next_or_previous_preset(up_or_down=True):
    """
    Move the selected preset index in the given direction. Must
    call load_preset() to apply the changes.

    Args:
        direction (int): The direction to move the selected preset index. 
                         Positive values move forward, negative values move backward.

    Returns:
        None
    """
    global selected_preset_idx

    selected_preset_idx = next_or_previous_index(selected_preset_idx, len(PRESET_NAMES_LIST), up_or_down)
    display_text_middle(get_preset_display_text())

def load_next_or_previous_preset(up_or_down=True):
    """
    Move the selected preset index in the given direction. Must
    call load_preset() to apply the changes.

    Args:
        direction (int): The direction to move the selected preset index. 
                         Positive values move forward, negative values move backward.

    Returns:
        None
    """
    global selected_preset_idx

    selected_preset_idx = next_or_previous_index(selected_preset_idx, len(PRESET_NAMES_LIST), up_or_down)
    if PRESET_NAMES_LIST[selected_preset_idx] == "*NEW*":
        selected_preset_idx = next_or_previous_index(selected_preset_idx, len(PRESET_NAMES_LIST), up_or_down)
    display_text_middle(get_preset_display_text())
 

def get_preset_display_text():
    """
    Returns the display text for the selected preset.

    Returns:
        str: The display text for the selected preset.
    """
    return [f"Preset: {PRESET_NAMES_LIST[selected_preset_idx]}", "", "<--- enter"]
