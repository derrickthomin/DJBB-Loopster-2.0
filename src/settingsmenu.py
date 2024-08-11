
from display import display_text_middle
from utils import next_or_previous_index
from settings import settings

settings_page_indicies = settings.SETTINGS_MENU_OPTION_INDICIES
settings_menu_idx = 0

settings_options = [
    ("Startup Menu", ["1", "2", "3", "4", "5", "6", "7"]),
    ("Trim Silence", ["start", "end", "none", "both"]),
    ("Quantize Amt", ["none","1/4", "1/8", "1/16", "1/32", "1/64"]),
    ("Quantize Loop", ["On", "Off"]),
    ("Quantize Percent", ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]),
    ("LED Brightness", ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]),
    ("Arp Type", ["Up", "Down", "UpDown", "DownUp", "Random", "Peepee"]),
    ("Loop Type", ["chordloop", "chord"]),
    ("Encoder Steps", ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]),
    ("Arp Polyphonic", ["On", "Off"]),
]

def get_settings_display_text():
    """
    Returns the display text for the settings menu based on the current index.
    """
    global settings_menu_idx

    title, options = settings_options[settings_menu_idx]
    selected_option = options[settings_page_indicies[settings_menu_idx]]
    display_text = f"{title}: {selected_option}"

    return display_text

def setting_menu_fn_press_function():
    """
    Function to handle the function button being pressed in the settings menu.
    """
    global settings_menu_idx

    settings_menu_idx = next_or_previous_index(settings_menu_idx, len(settings_options), True, True)
    display_text_middle(get_settings_display_text())

def next_quantization_amt(upOrDown = True):
    """
    Move the selected quantization index in the given direction.
    
    Args:
        direction (int): The direction to move the selected quantization index. 
                         Positive values move forward, negative values move backward.
    """
    global settings_page_indicies

    settings_page_indicies[2] = next_or_previous_index(settings_page_indicies[2], len(settings_options[2][1]), upOrDown, True)
    settings.QUANTIZE_AMT = settings_options[2][1][settings_page_indicies[2]]



def setting_menu_encoder_change_function(upOrDown = True):
    """
    Function to handle the encoder being turned in the settings menu.

    Args:
        encoder_delta (int): The amount the encoder was turned.
    """
    global settings_page_indicies

    _, options = settings_options[settings_menu_idx]

    settings_page_indicies[settings_menu_idx] = next_or_previous_index(settings_page_indicies[settings_menu_idx], len(options), upOrDown, True)
    selected_option = options[settings_page_indicies[settings_menu_idx]]
    display_text_middle(get_settings_display_text())
    
    # Startup menu
    if settings_menu_idx == 0:
        settings.STARTUP_MENU_IDX = int(selected_option) - 1

    # Trim silence
    if settings_menu_idx == 1:
        settings.TRIM_SILENCE = selected_option

    # Quantize
    if settings_menu_idx == 2:
        settings.QUANTIZE_AMT = selected_option
        print(settings.QUANTIZE_AMT)

    # Quantize Loop
    if settings_menu_idx == 3:
        settings.QUANTIZE_LOOP = selected_option

    # Quantize Percent
    if settings_menu_idx == 4:
        settings.QUANTIZE_STRENGTH = int(selected_option)

    # Pixel brightness - requires a reload
    if settings_menu_idx == 5:
        settings.PIXEL_BRIGHTNESS = int(selected_option) / 100

    # Arp Type
    if settings_menu_idx == 6:
        settings.ARPPEGIATOR_TYPE = selected_option

    # Loop Type
    if settings_menu_idx == 7:
        settings.CHORDMODE_DEFAULT_LOOPTYPE = selected_option
