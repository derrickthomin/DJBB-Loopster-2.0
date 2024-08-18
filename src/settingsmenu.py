
from display import display_text_middle
from utils import next_or_previous_index
from settings import settings
from arp import arpeggiator

settings_page_indicies = settings.SETTINGS_MENU_OPTION_INDICIES
settings_menu_idx = 0

settings_options = [
    ("startup menu", ["1", "2", "3", "4", "5", "6", "7"]),
    ("trim silence", ["start", "end", "none", "both"]),
    ("quantize amt", ["none","1/4", "1/8", "1/16", "1/32", "1/64"]),
    ("quantize loop", ["on", "off"]),
    ("quantize percent", ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]),
    ("led brightness", ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]),
    ("arp type", ["up", "down","random", "randomoctaveup", "randomoctavedown","randstartup","randstartdown"]),
    ("loop type", ["chordloop", "chord"]),
    ("encoder steps", ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]),
    ("arp polyphonic", ["on", "off"]),
    ("arp length", ["1/64", "1/32", "1/16", "1/8", "1/4", "1/2", "1"]),
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
        settings.TRIM_SILENCE_MODE = selected_option

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
        settings.CHORDMODE_LOOPTYPE = selected_option

    # Encoder Steps
    if settings_menu_idx == 8:
        settings.ENCODER_STEPS = int(selected_option)

    # Arp Polyphonic
    if settings_menu_idx == 9:
        settings.POLYPHONIC_ARP = selected_option

    # Arp Length
    if settings_menu_idx == 10:
        settings.ARP_LENGTH = selected_option
        arpeggiator.set_arp_length(selected_option)
