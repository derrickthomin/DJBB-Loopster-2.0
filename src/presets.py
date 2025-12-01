import supervisor
from settings import settings
from utils import next_or_previous_index
from display import display
import time

# Constants
NEW_PRESET = "*NEW*"

selected_preset_name = settings.get_startup_preset() 
PRESET_NAMES_LIST = settings.get_preset_names_list()
selected_preset_idx = int(PRESET_NAMES_LIST.index(selected_preset_name))

def load_preset(action_type = "press"):
    """Load selected preset and reload system."""
    # prevents duble load
    if action_type == "release":
        return

    preset_name = PRESET_NAMES_LIST[selected_preset_idx]
    if preset_name not in PRESET_NAMES_LIST:
        display.show_notification("[ERR] Preset Nm")
        return

    settings.load_preset(preset_name)
    supervisor.reload()

def load_preset_setup(): # Called from menus.py
    global selected_preset_idx

    if PRESET_NAMES_LIST[selected_preset_idx] == NEW_PRESET:
        selected_preset_idx = next_or_previous_index(selected_preset_idx, len(PRESET_NAMES_LIST), True)
    display.show_text_middle(get_preset_display_text())

def save_preset_to_file(action_type = "press"):
    """Save current settings to preset file."""
    if action_type == "release":
        return
    
    preset_name = PRESET_NAMES_LIST[selected_preset_idx]

    try:
        settings.save_preset_to_file(preset_name)
        if preset_name == NEW_PRESET:
            display.show_notification("created new preset")
            time.sleep(1)
            supervisor.reload()
        else:
            display.show_notification(f"Saved {preset_name}")

    except Exception as e:
        if settings.debug:
            print(f"[ERROR] saving preset {preset_name}: {e}")


def select_next_or_previous_preset(up_or_down=True):
    global selected_preset_idx

    selected_preset_idx = next_or_previous_index(selected_preset_idx, len(PRESET_NAMES_LIST), up_or_down)
    display.show_text_middle(get_preset_display_text())

def load_next_or_previous_preset(up_or_down=True):
    global selected_preset_idx

    selected_preset_idx = next_or_previous_index(selected_preset_idx, len(PRESET_NAMES_LIST), up_or_down)
    if PRESET_NAMES_LIST[selected_preset_idx] == NEW_PRESET:
        selected_preset_idx = next_or_previous_index(selected_preset_idx, len(PRESET_NAMES_LIST), up_or_down)
    display.show_text_middle(get_preset_display_text())
 

def get_preset_display_text():
    return [f"Preset: {PRESET_NAMES_LIST[selected_preset_idx]}", "", "<--- enter"]
