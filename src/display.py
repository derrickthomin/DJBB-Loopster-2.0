import time
import board
import busio
import neopixel
from settings import settings
import constants
import adafruit_ssd1306
from debug import debug


# PINS / SETUP
i2c = busio.I2C(constants.SCL, constants.SDA, frequency=400_000)
display = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)

# NEOPIXEL SETUP
all_pixels = neopixel.NeoPixel(board.GP9, 18, brightness=settings.PIXEL_BRIGHTNESS)

# DJT - move me. DJBB CUP
pixels_djbb_cup = neopixel.NeoPixel(board.GP15,16,brightness = 0.8)

# Dots
dot_start_positions = [(0, 25), (0, 42), (120, 42), (125, 25)]
dot_width = 3
dot_height = 3

# TRACKING VARIABLES
display_update_flag = True  # If true, show the display
notification_text_title = None
notification_ontime = 0
current_top_display_text = None
prev_top_text = None
display_notification_FPS_timer = 0
display_notification_most_recent = ""
pixel_blink_timer = 0
pixel_blink_states = [False] * 18
pixel_status = [False] * 18
pixel_blink_colors = [constants.RED] * 18
pixels_default_color = [constants.BLACK] * 18  # Usually black, unlss feature is overriding
dot_states = [False] * 4


# Sets global display_update_flag 
def display_set_update_flag(yesOrNo=True, immediate=False):
    """
    Sets the display update flag.

    Args:
        yesOrNo (bool, optional): Flag indicating whether the display needs to be updated. Defaults to True.
        immediate (bool, optional): Flag indicating whether the display update should happen immediately. Defaults to False.
    Returns:
        None
    """
    global display_update_flag

    if immediate:
        display_update_flag = False
        display.show()
        return
    
    display_update_flag = yesOrNo

def display_text_top(text, notification=False):
    """
    Display text on the top part of the screen.

    Args:
        text (str): Text to display.
        notification (bool, optional): Indicates if it's a notification. Defaults to False.
    """
    display.fill_rect(0, 0, constants.WIDTH, constants.TOP_HEIGHT, constants.BKG_COLOR)

    # Set up special border for notification text
    if notification:
        linepad_x = 0
        display.fill_rect(0 + linepad_x, constants.TOP_HEIGHT - 1, constants.WIDTH - (2 * linepad_x), 1, 1) 

    display.text(text, 0 + constants.PADDING, 0 + constants.PADDING, constants.TXT_COLOR)  
    display_set_update_flag()

def display_text_middle(text, value_only=False, value_start_x=-1):
    """
    Display text in the middle part of the screen.

    Args:
        text (str or list): Text or list of text lines to display.
        value_only (bool, optional): Indicates if only a value should be displayed. Defaults to False.
        value_start_x (int, optional): The starting x position for the value. Defaults to -1.

    Returns:
        None
    """
    char_height = 8
    char_width = 6

    debug.performance_timer("display_text_middle")

    if value_only and isinstance(text, list):
        print("ERROR: display_text_middle - value_only is True, but text is a list")
        return

    if not isinstance(text, list):
        text = [text]
    
    if value_only and value_start_x > 0:
        display.fill_rect(value_start_x, constants.MIDDLE_Y_START, char_width, char_height, constants.BKG_COLOR)
        display.text(text[0], value_start_x, constants.MIDDLE_Y_START, constants.TXT_COLOR)

    else:
        display.fill_rect(constants.TEXT_PAD, constants.MIDDLE_Y_START, 116, constants.MIDDLE_HEIGHT, constants.BKG_COLOR)
        if len(text) > 0:
            line_num = 0
            for text_line in text:
                display.text(text_line, constants.TEXT_PAD, constants.MIDDLE_Y_START + (line_num * constants.LINEHEIGHT), constants.TXT_COLOR)
                line_num += 1

    display_set_update_flag()
    debug.performance_timer("display_text_middle")


def display_left_dot(on_or_off=True):
    """
    Display the left dot on the screen.

    Args:
        on_or_off (bool): Indicates whether to turn the dot on or off.
    """
    display_selected_dot(0, on_or_off)

def display_right_dot(on_or_off=True):
    """
    Display the right dot on the screen.

    Args:
        on_or_off (bool): Indicates whether to turn the dot on or off.
    """
    display_selected_dot(3, on_or_off)

def display_selected_dot(selection_pos=0, on_or_off=True):
    """
    Displays a selected dot on the display.

    Args:
        selection_pos (str) L, R, LB, RB
        on_or_off (bool): Determines whether the dot should be turned on or off.

    Returns:
        None
    """
    global dot_states

    if selection_pos not in (0, 1, 2, 3, "L", "R", "LB", "RB"):
        print("ERROR: display_selected_dot- invalid selection_pos")
        return
    
    if selection_pos == "L":
        selection_pos = 0
    elif selection_pos == "R":
        selection_pos = 1
    elif selection_pos == "LB":
        selection_pos = 2
    elif selection_pos == "RB":
        selection_pos = 3

    # First turn off all dots
    for i in range(4):
        display.fill_rect(dot_start_positions[i][0], dot_start_positions[i][1], dot_width, dot_height, 0)
        dot_states[i] = False

    dot_states[selection_pos] = on_or_off

    if on_or_off:
        display.fill_rect(dot_start_positions[selection_pos][0], dot_start_positions[selection_pos][1], dot_width, dot_height, 1)

    # Turn on / off new dot
    display.fill_rect(dot_start_positions[selection_pos][0], dot_start_positions[selection_pos][1], dot_width, dot_height, on_or_off)
    # if not dot_states[1] and not dot_states[2]:
    #     display.fill_rect(dot_start_positions[0][0], dot_start_positions[0][1], dot_width, dot_height, 1)
    # else:
    #     display.fill_rect(dot_start_positions[0][0], dot_start_positions[0][1], dot_width, dot_height, 0)
    display_set_update_flag()

def turn_off_all_dots():
    """
    Turns off all the dots on the display.

    Returns:
        None
    """
    for i in range(4):
        display.fill_rect(dot_start_positions[i][0], dot_start_positions[i][1], dot_width, dot_height, 0)
        dot_states[i] = False

    # Also clear all pixels on left side and right side of screen. TEXT_PAD is the width
    display.fill_rect(0, constants.MIDDLE_Y_START, constants.TEXT_PAD, constants.MIDDLE_HEIGHT, 0)
    display.fill_rect(constants.WIDTH - constants.TEXT_PAD, constants.MIDDLE_Y_START, constants.TEXT_PAD, constants.MIDDLE_HEIGHT, 0)
    display_set_update_flag()

def toggle_select_button_icon(on_or_off=False):
    """
    Toggle the select button icon on the screen.

    Args:
        on_or_off (bool, optional): Indicates whether to turn the icon on or off. Defaults to False.

    Returns:
        None
    """
    if settings.PERFORMANCE_MODE:
        return
    
    startx = 30  # Px from the left of the screen
    starty = constants.BOTTOM_Y_START
    icon_width = 35
    icon_height = 18
    pad = 2
    display.fill_rect(startx - pad, starty - pad, icon_width, icon_height, 0)  
    if on_or_off: 
        display.text(constants.SEL_ICON_TXT, startx, starty, 1)
    display_set_update_flag()


def display_line_bottom():
    """
    Display a line at the bottom of the screen.
    """
    display.fill_rect(0, constants.BOTTOM_LINE_Y_START, constants.WIDTH, 1, 1)
    display_set_update_flag()

def toggle_recording_icon(on_or_off=False):
    """
    Toggle the recording icon on the screen.

    Args:
        on_or_off (bool, optional): Indicates whether to turn the icon on or off. Defaults to False.
    """
    if settings.PERFORMANCE_MODE:
        return
    height = 10
    width = 18
    starty = constants.HEIGHT - height

    if on_or_off is True:
        display.fill_rect(0, starty, width, height, 1)
        display.text(constants.RECORDING_ICON, 0, starty, 0)

    if on_or_off is False:
        display.fill_rect(0, starty, width, height, 0)

def display_text_bottom(text, value_only=False, value_start_x=-1, text_width_px=10):
    """
    Display text in the bottom part of the screen.

    Args:
        text (str or list): Text or list of text lines to display.
        value_only (bool, optional): Indicates if only a value should be displayed. Defaults to False.
        value_start_x (int, optional): The starting x position for the value. Defaults to -1.
        text_width_px (int, optional): The width of each character in pixels. Defaults to 10.
    """
    char_height = 8
    char_width = text_width_px
    bottom_y_start = 40

    if value_only and not isinstance(text, str):
        print("ERROR: must be string")
        return
    
    if value_only and value_start_x > 0:
        display.fill_rect(value_start_x, bottom_y_start, char_width, char_height, constants.BKG_COLOR)
        display.text(text, value_start_x, bottom_y_start, constants.TXT_COLOR)

    else:
        display.fill_rect(0, bottom_y_start, constants.WIDTH, char_height, constants.BKG_COLOR)   
        display.text(text, 0 + constants.TEXT_PAD, bottom_y_start, constants.TXT_COLOR)
            
    display_set_update_flag()

def toggle_play_icon(on_or_off=False):
    """
    Toggle the play icon on the screen.

    Args:
        on_or_off (bool, optional): Indicates whether to turn the icon on or off. Defaults to False.
    """
    if settings.PERFORMANCE_MODE:
        return

    height = 10
    width = 18
    starty = constants.HEIGHT - 23

    if on_or_off is True:
        display.fill_rect(0, starty, width, height, 0)
        display.text(constants.PLAY_ICON, 0, starty, 1)

    if on_or_off is False:
        display.fill_rect(0, starty, width, height, 0)

def toggle_menu_navmode_icon(on_or_off):
    """
    Toggle the navigation mode icon on the screen.

    Args:
        on_or_off (bool): Indicates whether to turn the icon on or off.

    Returns:
        None
    """
    if on_or_off is True:
        display.fill_rect(constants.NAV_ICON_X_START, constants.HEIGHT - constants.LINEHEIGHT - 2, constants.NAV_MSG_WIDTH, 10, 1)
        display.text(constants.NAV_MODE_TXT, constants.NAV_ICON_X_START + 4, constants.HEIGHT - constants.LINEHEIGHT, 0)
        display_set_update_flag()
        pixel_encoder_button_on()

    elif on_or_off is False:
        display.fill_rect(constants.NAV_ICON_X_START, constants.HEIGHT - constants.LINEHEIGHT - 2, constants.NAV_MSG_WIDTH, 10, 0)
        display_set_update_flag()
        pixel_encoder_button_off()

def toggle_menu_lock_icon(on_or_off, nav_mode_on=False):
    """
    Toggle the lock icon on the screen.

    Args:
        on_or_off (bool): Indicates whether to turn the icon on or off.
        nav_mode_on (bool, optional): Indicates whether the navigation mode is on. Defaults to False.

    Returns:
        None
    """
    if on_or_off is True:
        display.fill_rect(constants.NAV_ICON_X_START, constants.HEIGHT - constants.LINEHEIGHT - 2, constants.NAV_MSG_WIDTH, 10, 1)
        display.text(constants.ENCODER_LOCK_TXT, constants.NAV_ICON_X_START + 4, constants.HEIGHT - constants.LINEHEIGHT, 0)
        display_set_update_flag()
        pixel_encoder_button_on(constants.ENCODER_LOCK_COLOR)

    elif on_or_off is False:
        display.fill_rect(constants.NAV_ICON_X_START, constants.HEIGHT - constants.LINEHEIGHT - 2, constants.NAV_MSG_WIDTH, 10, 0)
        display_set_update_flag()
        if nav_mode_on:
            pixel_encoder_button_on(constants.NAV_MODE_COLOR)
            toggle_menu_navmode_icon(True)
        else:
            pixel_encoder_button_off()

def update_playmode_icon(playmode):
    """
    Update the playmode icon on the screen.

    Args:
        playmode (str): The playmode to display.

    Returns:
        None
    """
    x = constants.WIDTH - 60
    y = constants.HEIGHT - 8
    display_text = ""
    if settings.PERFORMANCE_MODE:
        return

    display.fill_rect(x, y, 20, 20, 0)
    if playmode == "chord":
        display_text = constants.CHD_MODE_ICON
    elif playmode == "velocity":
        display_text = constants.VEL_MODE_ICON
    elif playmode == "encoder":
        display_text = constants.ENC_MODE_ICON

    display.text(display_text, x, y, 1)
    display_set_update_flag()

def check_show_display():
    """
    Checks if the display needs to be updated and shows it if necessary.
    """
    if display_update_flag:
        display.show()
        display_set_update_flag(False)
    
def display_notification(msg=None):
    """
    Display a temporary notification banner at the top of the screen.

    Args:
        msg (str): Notification message to display.
    """

    if settings.PERFORMANCE_MODE:
        return

    global notification_text_title
    global notification_ontime
    global prev_top_text
    global current_top_display_text
    global display_notification_most_recent
    global display_notification_FPS_timer

    if not msg:
        return

    if (time.monotonic() - display_notification_FPS_timer) > constants.DISPLAY_NOTIFICATION_METERING_THRESH:
        notification_text_title = msg

        if notification_ontime > 0:
            prev_top_text = current_top_display_text

        current_top_display_text = msg
        display_text_top(msg, True)

        notification_ontime = time.monotonic()

        display_notification_FPS_timer = time.monotonic()

def display_clear_notifications(replace_text=None):
    """
    Check and clear notifications from the top bar if necessary.

    Args:
        replace_text (str, optional): Text to replace the notification with. Defaults to None.
    """
    global notification_text_title
    global notification_ontime
    global prev_top_text
    global current_top_display_text

    if notification_text_title is None or replace_text is None:
        return
    
    if notification_text_title == replace_text:
        return
    
    if time.monotonic() - notification_ontime > constants.NOTIFICATION_THRESH_S:
        notification_ontime = -1
        notification_text_title = None
        display_text_top(replace_text)

def display_startup_screen():
    """
    Display the startup screen.
    """
    display.fill(0)
    display_text_top("DJBB MIDI LOOPSTER", notification=False)
    display_text_middle(f"Loading {settings.get_startup_preset()}...")
    display.show()
    time.sleep(1.5)
#
display_startup_screen()
display.fill(0)
display_line_bottom()
display.show()

# -------------------- NEOPIXEL -------------------------

# Map pixels to buttons
pixels_mapped = [13,14,15,16,
                9,10,11,12,
                5,6,7,8,
                1,2,3,4]

def get_pixel(index):
    """
    Retrieves the pixel value at the specified index.

    Args:
        index (int): The index of the pixel to retrieve.

    Returns:
        int: The pixel value at the specified index.
    """
    return pixels_mapped[index]

def pixel_note_on(pad_idx):
    """
    Turn on a pixel when a note is played.

    Args:
        pad_idx (int): Index of the pad to turn on.
    """
    debug.performance_timer("pixel_note_on")
    all_pixels[get_pixel(pad_idx)] = constants.NOTE_COLOR
    pixels_djbb_cup[pad_idx] = constants.NOTE_COLOR
    debug.performance_timer("pixel_note_on")

def pixel_note_off(pad_idx):
    """
    Turn off a pixel when a note is released.

    Args:
        pad_idx (int): Index of the pad to turn off.
    """
    debug.performance_timer("pixel_note_off")
    all_pixels[get_pixel(pad_idx)] = get_default_color(pad_idx)
    pixels_djbb_cup[pad_idx] = constants.BLACK
    debug.performance_timer("pixel_note_off")

def pixel_fn_button_on(color=constants.BLUE):
    """
    Turn on a pixel when the function button is pressed.

    Args:
        pad_idx (int): Index of the pad to turn on.
    """
    all_pixels[0] = color

def pixel_fn_button_off():
    """
    Turn off a pixel when the function button is released.

    Args:
        pad_idx (int): Index of the pad to turn off.
    """
    all_pixels[0] = (0, 0, 0)

def pixel_encoder_button_on(color=constants.NAV_MODE_COLOR):
    """
    Turn on a pixel when the encoder button is pressed.

    Args:
        pad_idx (int): Index of the pad to turn on.
    """
    all_pixels[17] = color

def pixel_encoder_button_off():
    """
    Turn off a pixel when the encoder button is released.

    Args:
        pad_idx (int): Index of the pad to turn off.
    """
    all_pixels[17] = (0, 0, 0)

def set_blink_pixel(pad_idx, on_or_off=True, color=False):
    """
    Sets the blink state of a pixel on or off.

    Args:
        pad_idx (int): The index of the pixel pad.
        on_or_off (bool, optional): The state to set the blink. Default is True.
        color (bool, optional): The color to set for the blinking pixel. Default is False.

    Returns:
        None
    """
    global pixel_blink_timer
    global pixel_blink_states
    global pixel_status
    global pixel_blink_colors

    if not on_or_off:
        pixel_blink_states[pad_idx] = False
        all_pixels[get_pixel(pad_idx)] = get_default_color(pad_idx)
        return

    pixel_blink_states[pad_idx] = True

    if color:
        pixel_blink_colors[pad_idx] = color

    
def blink_pixels():
    """
    Blinks the all_pixels based on the current state of `pixel_blink_states`.

    This function toggles the status of the all_pixels that are set to blink. If a pixel is set to blink,
    its status will be toggled between ON and OFF. The status of the all_pixels is updated in the `pixel_status`
    list, and the corresponding LED colors are set accordingly in the `all_pixels` list.

    The blinking interval is determined by the `constants.PIXEL_BLINK_TIME` constant.

    Note: This function assumes that the `pixel_blink_states`, `pixel_status`, and `all_pixels` variables are
    already defined and accessible.

    Returns:
        None
    """
    global pixel_blink_timer
    global pixel_blink_states  # whether or not we want to blink
    global pixel_status        # currently ON

    if True in pixel_blink_states and time.monotonic() - pixel_blink_timer > constants.PIXEL_BLINK_TIME:
        for i in range(16):
            if pixel_blink_states[i]:
                pixel_status[i] = not pixel_status[i]
                if pixel_status[i] == True:
                    all_pixels[get_pixel(i)] = pixel_blink_colors[i]
                else:
                    all_pixels[get_pixel(i)] = constants.BLACK

        pixel_blink_timer = time.monotonic()

def get_blink_color(pad_idx):
    """
    Returns the color of the blinking pixel.

    Parameters:
    pad_idx (int): The index of the pad.

    Returns:
    str: The color of the blinking pixel.
    """
    return pixel_blink_colors[pad_idx]

def set_blink_color(pad_idx, color):
    """
    Sets the color of the blinking pixel.

    Parameters:
    pad_idx (int): The index of the pad.
    color (str): The color to set for the blinking pixel.

    Returns:
    None
    """
    global pixel_blink_colors
    
    pixel_blink_colors[pad_idx] = color

def get_default_color(pad_idx):
    """
    Returns the default color for a given pad index.

    Parameters:
    pad_idx (int): The index of the pad.

    Returns:
    str: The default color for the pad.
    """
    return pixels_default_color[pad_idx]

def set_default_color(pad_idx, color):
    """
    Sets the default color for a specific pad.

    Parameters:
    pad_idx (int): The index of the pad.
    color (str): The color to set for the pad.

    Returns:
    None
    """
    global pixels_default_color
    
    pixels_default_color[pad_idx] = color