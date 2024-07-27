import time
from settings import settings
from utils import next_or_previous_index
from debug import DEBUG_MODE
from display import display_notification, display_text_middle
import supervisor
from midi import save_midi_settings

selected_preset_name = settings.get_startup_preset()
PRESET_NAMES_LIST = settings.get_preset_names()
selected_preset_idx = int(PRESET_NAMES_LIST.index(selected_preset_name))

def load_preset():
    """
    Loads a preset based on the selected preset index.

    The function retrieves the preset name from the `PRESET_NAMES_LIST` using the `selected_preset_idx`.
    If the preset name is not found in the list, an error message is printed and the function returns.
    Otherwise, the `settings.load_preset` function is called with the preset name, and the `supervisor.reload` function is called.
    """

    preset_name = PRESET_NAMES_LIST[selected_preset_idx]
    if preset_name.upper() not in PRESET_NAMES_LIST:
        print(f"Invalid preset name: {preset_name}")
        return
    
    settings.load_preset(preset_name)
    supervisor.reload()

def save_preset():
    """
    Saves the current preset settings.

    This function saves the MIDI settings and the current preset name.
    If the preset name is "*NEW*", it displays a notification for creating a new preset,
    waits for 1 second, and reloads the supervisor.
    Otherwise, it displays a notification for saving the preset name and waits for 1 second.

    If an exception occurs during the saving process, it prints an error message and displays
    an error notification.

    :return: None
    """
    save_midi_settings()
    preset_name = PRESET_NAMES_LIST[selected_preset_idx]

    try:
        settings.save_preset(preset_name)
        if preset_name == "*NEW*":
            display_notification("created new preset")
            time.sleep(1)
            supervisor.reload()
        else:
            display_notification(f"Saved {preset_name}")
        time.sleep(1)
    except Exception as e:
        print(f"Error saving preset {preset_name}: {e}")
        display_notification(f"Er. {e}")


def next_or_previous_preset(upOrDown=True):
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

    selected_preset_idx = next_or_previous_index(selected_preset_idx, len(PRESET_NAMES_LIST), upOrDown)
    display_text_middle(get_preset_display_text())
 

def get_preset_display_text():
    """
    Returns the display text for the selected preset.

    Returns:
        str: The display text for the selected preset.
    """
    return f"Preset: {PRESET_NAMES_LIST[selected_preset_idx]}"
