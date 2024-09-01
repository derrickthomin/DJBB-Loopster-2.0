
from display import display_text_middle, display_left_dot, display_right_dot
from utils import next_or_previous_index
from settings import settings as s
from arp import arpeggiator

settings_menu_idx = 0

settings_options = [
    ("startup menu", ["1", "2", "3", "4", "5", "6", "7"]),
    ("trim silence", ["start", "end", "none", "both"]),
    ("quantize amt", ["none","1/4", "1/8", "1/16", "1/32", "1/64"]),
    ("quantize loop", ["on", "off"]),
    ("quantize percent", ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]),
    ("led brightness", ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]),
    ("arp type", ["up", "down","random", "rand oct up", "rand oct dn","randstartup","randstartdown"]),
    ("loop type", ["chordloop", "chord"]),
    ("encoder steps", ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]),
    ("arp polyphonic", ["on", "off"]),
    ("arp length", ["1/64", "1/32", "1/16", "1/8", "1/4", "1/2", "1"]),
]

def validate_settings_menu_indicies():
    print(f"old settings: {s.SETTINGS_MENU_OPTION_INDICIES}")
    for idx, (title, options) in enumerate(settings_options):
        selected_option = options[s.SETTINGS_MENU_OPTION_INDICIES[idx]]
        if idx == 0:
            if s.STARTUP_MENU_IDX != int(selected_option) - 1:
                try:
                    s.SETTINGS_MENU_OPTION_INDICIES[idx] = options.index(str(s.STARTUP_MENU_IDX + 1))
                except ValueError:
                    print(f"Error: Could not find index for {s.STARTUP_MENU_IDX + 1} in {options} ({title})")

        elif idx == 1:
            if s.TRIM_SILENCE_MODE != selected_option:
                try:
                    s.SETTINGS_MENU_OPTION_INDICIES[idx] = options.index(s.TRIM_SILENCE_MODE)
                except ValueError:
                    print(f"Error: Could not find index for {s.TRIM_SILENCE_MODE} in {options} ({title})")

        elif idx == 2:
            if s.QUANTIZE_AMT != selected_option:
                try:
                    s.SETTINGS_MENU_OPTION_INDICIES[idx] = options.index(s.QUANTIZE_AMT)
                except ValueError:
                    print(f"Error: Could not find index for {s.QUANTIZE_AMT} in {options} ({title})")
        elif idx == 3:
            if s.QUANTIZE_LOOP != selected_option:
                try:
                    s.SETTINGS_MENU_OPTION_INDICIES[idx] = options.index(s.QUANTIZE_LOOP)
                except ValueError:
                    print(f"Error: Could not find index for {s.QUANTIZE_LOOP} in {options} ({title})")
        elif idx == 4:
            if s.QUANTIZE_STRENGTH != int(selected_option):
                try:
                    s.SETTINGS_MENU_OPTION_INDICIES[idx] = options.index(str(s.QUANTIZE_STRENGTH))
                except ValueError:
                    print(f"Error: Could not find index for {s.QUANTIZE_STRENGTH} in {options} ({title})")
        elif idx == 5:
            if s.PIXEL_BRIGHTNESS != int(selected_option) / 100:
                try:
                    s.SETTINGS_MENU_OPTION_INDICIES[idx] = options.index(str(int(s.PIXEL_BRIGHTNESS * 100)))
                except ValueError:
                    print(f"Error: Could not find index for {s.PIXEL_BRIGHTNESS} in {options} ({title})")
        elif idx == 6:
            if s.ARPPEGIATOR_TYPE != selected_option:
                try:
                    s.SETTINGS_MENU_OPTION_INDICIES[idx] = options.index(s.ARPPEGIATOR_TYPE)
                except ValueError:
                    print(f"Error: Could not find index for {s.ARPPEGIATOR_TYPE} in {options} ({title})")
        elif idx == 7:
            if s.CHORDMODE_LOOPTYPE != selected_option:
                try:
                    s.SETTINGS_MENU_OPTION_INDICIES[idx] = options.index(s.CHORDMODE_LOOPTYPE)
                except ValueError:
                    print(f"Error: Could not find index for {s.CHORDMODE_LOOPTYPE} in {options} ({title})")
        elif idx == 8:
            if s.ENCODER_STEPS != int(selected_option):
                try:
                    s.SETTINGS_MENU_OPTION_INDICIES[idx] = options.index(str(s.ENCODER_STEPS))
                except ValueError:
                    print(f"Error: Could not find index for {s.ENCODER_STEPS} in {options} ({title})")
        elif idx == 9:
            if s.POLYPHONIC_ARP != selected_option:
                try:
                    s.SETTINGS_MENU_OPTION_INDICIES[idx] = options.index(s.POLYPHONIC_ARP)
                except ValueError:
                    print(f"Error: Could not find index for {s.POLYPHONIC_ARP} in {options} ({title})")
        elif idx == 10:
            if s.ARP_LENGTH != selected_option:
                try:
                    s.SETTINGS_MENU_OPTION_INDICIES[idx] = options.index(s.ARP_LENGTH)
                except ValueError:
                    print(f"Error: Could not find index for {s.ARP_LENGTH} in {options} ({title})")
        print(f"new settings: {s.SETTINGS_MENU_OPTION_INDICIES}")

validate_settings_menu_indicies()
def get_settings_display_text():
    """
    Returns the display text for the settings menu based on the current index.
    """
    global settings_menu_idx

    title, options = settings_options[settings_menu_idx]
    selected_option = options[s.SETTINGS_MENU_OPTION_INDICIES[settings_menu_idx]]
    display_text = f"{title}: {selected_option}"

    return display_text

def setting_menu_fn_press_function(upOrDown = True, action_type = "press"):
    """
    Function to handle the function button being pressed in the settings menu.
    """
    global settings_menu_idx

    if action_type == "press":
        return
    
    settings_menu_idx = next_or_previous_index(settings_menu_idx, len(settings_options), upOrDown, True)
    display_text_middle(get_settings_display_text())

def settings_menu_fn_btn_encoder_chg_function(upOrDown = True):
    """
    Function to handle the encoder being turned in the settings menu.
    
    Args:
        encoder_delta (int): The amount the encoder was turned.
    """
    setting_menu_fn_press_function(upOrDown, action_type="release")

def next_quantization_amt(upOrDown = True):
    """
    Move the selected quantization index in the given direction.
    
    Args:
        direction (int): The direction to move the selected quantization index. 
                         Positive values move forward, negative values move backward.
    """

    s.SETTINGS_MENU_OPTION_INDICIES[2] = next_or_previous_index(s.SETTINGS_MENU_OPTION_INDICIES[2], len(settings_options[2][1]), upOrDown, True)
    s.QUANTIZE_AMT = settings_options[2][1][s.SETTINGS_MENU_OPTION_INDICIES[2]]
    return s.QUANTIZE_AMT

def next_arp_type(upOrDown = True):
    """
    Move the selected arp type index in the given direction.
    
    Args:
        direction (int): The direction to move the selected arp type index. 
                         Positive values move forward, negative values move backward.
    """

    s.SETTINGS_MENU_OPTION_INDICIES[6] = next_or_previous_index(s.SETTINGS_MENU_OPTION_INDICIES[6], len(settings_options[6][1]), upOrDown, True)
    s.ARPPEGIATOR_TYPE = settings_options[6][1][s.SETTINGS_MENU_OPTION_INDICIES[6]]
    arpeggiator.set_arp_type(s.ARPPEGIATOR_TYPE)
    return s.ARPPEGIATOR_TYPE

def next_arp_length(upOrDown = True):
    """
    Move the selected arp length index in the given direction.
    
    Args:
        direction (int): The direction to move the selected arp length index. 
                         Positive values move forward, negative values move backward.
    """

    s.SETTINGS_MENU_OPTION_INDICIES[10] = next_or_previous_index(s.SETTINGS_MENU_OPTION_INDICIES[10], len(settings_options[10][1]), upOrDown, True)
    s.ARP_LENGTH = settings_options[10][1][s.SETTINGS_MENU_OPTION_INDICIES[10]]
    arpeggiator.set_arp_length(s.ARP_LENGTH)
    return s.ARP_LENGTH

def get_arp_type_text():
    """
    Returns the display text for the arp type based on the current index.
    """
    return f"{s.ARPPEGIATOR_TYPE}"

def get_arp_len_text():
    """
    Returns the display text for the arp length based on the current index.
    """
    return f"{s.ARP_LENGTH}"

def generic_settings_fn_hold_function_dots(trigger_on_release = False):

    if not trigger_on_release:
        display_right_dot(False)
        display_left_dot(True)
    else:
        display_left_dot(False)
        display_right_dot(True)

def setting_menu_encoder_change_function(upOrDown = True):
    """
    Function to handle the encoder being turned in the settings menu.

    Args:
        encoder_delta (int): The amount the encoder was turned.
    """

    _, options = settings_options[settings_menu_idx]

    s.SETTINGS_MENU_OPTION_INDICIES[settings_menu_idx] = next_or_previous_index(s.SETTINGS_MENU_OPTION_INDICIES[settings_menu_idx], len(options), upOrDown, True)
    selected_option = options[s.SETTINGS_MENU_OPTION_INDICIES[settings_menu_idx]]
    display_text_middle(get_settings_display_text())
    
    # Startup menu
    if settings_menu_idx == 0:
        s.STARTUP_MENU_IDX = int(selected_option) - 1

    # Trim silence
    if settings_menu_idx == 1:
        s.TRIM_SILENCE_MODE = selected_option

    # Quantize
    if settings_menu_idx == 2:
        s.QUANTIZE_AMT = selected_option
        print(s.QUANTIZE_AMT)

    # Quantize Loop
    if settings_menu_idx == 3:
        s.QUANTIZE_LOOP = selected_option

    # Quantize Percent
    if settings_menu_idx == 4:
        s.QUANTIZE_STRENGTH = int(selected_option)

    # Pixel brightness - requires a reload
    if settings_menu_idx == 5:
        s.PIXEL_BRIGHTNESS = int(selected_option) / 100

    # Arp Type
    if settings_menu_idx == 6:
        s.ARPPEGIATOR_TYPE = selected_option

    # Loop Type
    if settings_menu_idx == 7:
        s.CHORDMODE_LOOPTYPE = selected_option

    # Encoder Steps
    if settings_menu_idx == 8:
        s.ENCODER_STEPS = int(selected_option)

    # Arp Polyphonic
    if settings_menu_idx == 9:
        s.POLYPHONIC_ARP = selected_option

    # Arp Length
    if settings_menu_idx == 10:
        s.ARP_LENGTH = selected_option
        arpeggiator.set_arp_length(selected_option)
