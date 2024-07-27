import json
import time
from settings import settings
from debug import DEBUG_MODE
from display import display_notification, display_text_middle
import supervisor
from midi import save_midi_settings

PRESET_NAMES = ["DEFAULT", "PRESET_1", "PRESET_2", "PRESET_3", "PRESET_4", "PRESET_5"]
# PRESETS_JSON_FILE = "presets.json"

selected_preset_name = settings.get_startup_preset()
selected_preset_idx = int(PRESET_NAMES.index(selected_preset_name))

def load_preset():

    preset_name = PRESET_NAMES[selected_preset_idx]
    if DEBUG_MODE:
        print(f"Loading preset: {preset_name}")
    print(f"Loading preset: {preset_name}") #DJT delete
    if preset_name.upper() not in PRESET_NAMES:
        print(f"Invalid preset name: {preset_name}")
        return
    
    settings.load_preset(preset_name)
    print(f"Loaded preset: {preset_name}") #DJT delete
    supervisor.reload()

def save_preset():

    save_midi_settings()
    preset_name = PRESET_NAMES[selected_preset_idx]
    if preset_name.upper() not in PRESET_NAMES:
        print(f"Invalid preset name: {preset_name}")
        return
    try:
        settings.save_preset(preset_name)
        display_notification(f"Saved {preset_name}")
        time.sleep(1)
    except Exception as e:
        print(f"Error saving preset {preset_name}: {e}")
        display_notification(f"Er. {e}")


def next_or_previous_preset(direction):
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

    selected_preset_idx += direction
    if selected_preset_idx < 0:
        selected_preset_idx = len(PRESET_NAMES) - 1
    elif selected_preset_idx >= len(PRESET_NAMES):
        selected_preset_idx = 0

    display_text_middle(get_preset_display_text())

def get_preset_display_text():
    """
    Returns the display text for the selected preset.

    Returns:
        str: The display text for the selected preset.
    """
    return f"Preset: {PRESET_NAMES[selected_preset_idx]}"

