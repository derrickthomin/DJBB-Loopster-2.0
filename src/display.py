import time
import board
import busio
import neopixel
from settings import settings
import constants
import adafruit_ssd1306
from debug import debug
from globalstates import global_states


# Display Setup
i2c = busio.I2C(constants.SCL, constants.SDA, frequency=400_000)
display = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)

# Neopixel Setup
all_pixels = neopixel.NeoPixel(board.GP9, 18, brightness=settings.led_pixel_brightness) # V1
# all_pixels = neopixel.NeoPixel(board.GP15, 18, brightness=settings.led_pixel_brightness) #V2

# Dots
dot_start_positions = [(0, 25), (0, 42), (120, 42), (125, 25)]
DOT_WIDTH = 3
DOT_HEIGHT = 3

# TRACKING VARIABLES
display_needs_update = True  # If true, show the display
notification_text_title = None
notification_on_time = 0
current_top_text = None
previous_top_text = None
display_notification_FPS_timer = 0
display_notification_most_recent = ""
pixel_blink_timer = 0
pixel_blink_states = [False] * 18
pixel_status = [False] * 18
pixels_blink_colors = [constants.RED] * 18
pixels_default_colors = [constants.BLACK] * 18  # Usually black, unlss feature is overriding
dot_states = [False] * 4
velocity_map_colors = []*16

def display_set_update_flag(yesOrNo=True, immediate=False):
    """
    Sets the display update flag.

    Args:
        yesOrNo (bool, optional): Flag indicating whether the display needs to be updated. Defaults to True.
        immediate (bool, optional): Flag indicating whether the display update should happen immediately. Defaults to False.
    Returns:
        None
    """
    global display_needs_update

    if immediate:
        display_needs_update = False
        display.show()
        return
    
    display_needs_update = yesOrNo

def display_text_top(text, notification=False):
    """
    Display text on the top part of the screen. If it's a notification, the text will be displayed only temporarily.

    Args:
        text (str): Text to display.
        notification (bool, optional): Indicates if it's a notification. Defaults to False.
    """
    display.fill_rect(0, 0, constants.SCREEN_W, constants.TOP_HEIGHT, constants.BKG_COLOR)

    if notification:
        linepad_x = 0
        display.fill_rect(0 + linepad_x, constants.TOP_HEIGHT - 1, constants.SCREEN_W - (2 * linepad_x), 1, 1) 

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
        display.fill_rect(dot_start_positions[i][0], dot_start_positions[i][1], DOT_WIDTH, DOT_HEIGHT, 0)
        dot_states[i] = False

    dot_states[selection_pos] = on_or_off

    if on_or_off:
        display.fill_rect(dot_start_positions[selection_pos][0], dot_start_positions[selection_pos][1], DOT_WIDTH, DOT_HEIGHT, 1)

    display_set_update_flag()

def turn_off_all_dots():
    """
    Turns off all the dots on the display.

    Returns:
        None
    """
    for i in range(4):
        display.fill_rect(dot_start_positions[i][0], dot_start_positions[i][1], DOT_WIDTH, DOT_HEIGHT, 0)
        dot_states[i] = False

    # Also clear all pixels on left side and right side of screen. TEXT_PAD is the width
    display.fill_rect(0, constants.MIDDLE_Y_START, constants.TEXT_PAD, constants.MIDDLE_HEIGHT, 0)
    display.fill_rect(constants.SCREEN_W - constants.TEXT_PAD, constants.MIDDLE_Y_START, constants.TEXT_PAD, constants.MIDDLE_HEIGHT, 0)
    display_set_update_flag()

def toggle_fn_button_icon(on_or_off=False):
    """
    Toggle the fn button icon on the screen.

    Args:
        on_or_off (bool, optional): Indicates whether to turn the icon on or off. Defaults to False.

    Returns:
        None
    """
    if settings.performance_mode or constants.LOOPSTER_VERSION == 2: # Dont need this in V2.. LED is on the button
        return
    
    start_x = constants.FN_BTN_ICON_X_START
    start_y = constants.BOTTOM_Y_START
    icon_width = 32
    icon_height = 18
    pad = 2
    display.fill_rect(start_x - pad, start_y - pad, icon_width, icon_height, 0)  
    if on_or_off: 
        display.text(constants.SEL_ICON_TXT, start_x, start_y, 1)
    display_set_update_flag()


def display_line_bottom():
    """
    Display a line at the bottom of the screen.
    """
    display.fill_rect(0, constants.BOTTOM_LINE_Y_START, constants.SCREEN_W, 1, 1)
    display_set_update_flag()

def toggle_recording_icon(on_or_off=False):
    """
    Toggle the recording icon on the screen.

    Args:
        on_or_off (bool, optional): Indicates whether to turn the icon on or off. Defaults to False.
    """
    if settings.performance_mode:
        return

    height = 10
    width = 18
    start_y = constants.SCREEN_H - height

    if on_or_off is True:
        display.fill_rect(0, start_y, width, height, 1)
        display.text(constants.RECORDING_ICON, 0, start_y, 0)
        display_set_update_flag()

    if on_or_off is False:
        display.fill_rect(0, start_y, width, height, 0)
        display_set_update_flag()

def display_text_bottom(text, value_only=False, start_x=-1, text_width_px=10):
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
    
    if value_only and start_x > 0:
        display.fill_rect(start_x, bottom_y_start, char_width, char_height, constants.BKG_COLOR)
        display.text(text, start_x, bottom_y_start, constants.TXT_COLOR)

    else:
        display.fill_rect(0, bottom_y_start, constants.SCREEN_W, char_height, constants.BKG_COLOR)   
        display.text(text, 0 + constants.TEXT_PAD, bottom_y_start, constants.TXT_COLOR)
            
    display_set_update_flag()

def toggle_play_icon(on_or_off=False):
    """
    Toggle the play icon on the screen.

    Args:
        on_or_off (bool, optional): Indicates whether to turn the icon on or off. Defaults to False.
    """
    if settings.performance_mode:
        return

    height = 10
    width = 18
    start_y = constants.SCREEN_H - 23

    if on_or_off is True:
        display.fill_rect(0, start_y, width, height, 0)
        display.text(constants.PLAY_ICON, 0, start_y, 1)

    if on_or_off is False:
        display.fill_rect(0, start_y, width, height, 0)

def toggle_menu_navmode_icon(on_or_off):
    """
    Toggle the navigation mode icon on the screen.

    Args:
        on_or_off (bool): Indicates whether to turn the icon on or off.

    Returns:
        None
    """
    if on_or_off is True:
        display.fill_rect(constants.NAV_ICON_X_START, constants.SCREEN_H - constants.LINEHEIGHT - 2, constants.NAV_MSG_WIDTH, 10, 1)
        display.text(constants.NAV_MODE_TXT, constants.NAV_ICON_X_START + 4, constants.SCREEN_H - constants.LINEHEIGHT, 0)
        display_set_update_flag()
        pixel_set_encoder_button_on()

    elif on_or_off is False:
        display.fill_rect(constants.NAV_ICON_X_START, constants.SCREEN_H - constants.LINEHEIGHT - 2, constants.NAV_MSG_WIDTH, 10, 0)
        display_set_update_flag()
        pixel_set_encoder_button_off()

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
        display.fill_rect(constants.NAV_ICON_X_START, constants.SCREEN_H - constants.LINEHEIGHT - 2, constants.NAV_MSG_WIDTH, 10, 1)
        display.text(constants.ENCODER_LOCK_TXT, constants.NAV_ICON_X_START + 4, constants.SCREEN_H - constants.LINEHEIGHT, 0)
        display_set_update_flag()
        pixel_set_encoder_button_on(constants.ENCODER_LOCK_COLOR)

    elif on_or_off is False:
        display.fill_rect(constants.NAV_ICON_X_START, constants.SCREEN_H - constants.LINEHEIGHT - 2, constants.NAV_MSG_WIDTH, 10, 0)
        display_set_update_flag()
        if nav_mode_on:
            pixel_set_encoder_button_on(constants.NAV_MODE_COLOR)
            toggle_menu_navmode_icon(True)
        else:
            pixel_set_encoder_button_off()

def update_playmode_icon(playmode):
    """
    Update the playmode icon on the screen.

    Args:
        playmode (str): The playmode to display.

    Returns:
        None
    """
    if settings.performance_mode:
        return
    
    y = constants.SCREEN_H - 8
    display_text = ""

    display.fill_rect(constants.PLAYMODE_ICON_X_START, y, 25, 25, 0)
    if playmode == "chord":
        display_text = constants.CHD_MODE_ICON
    elif playmode == "velocity":
        display_text = constants.VEL_MODE_ICON
    elif playmode == "encoder":
        display_text = constants.ENC_MODE_ICON

    display.text(display_text, constants.PLAYMODE_ICON_X_START, y, 1)
    display_set_update_flag()

def check_show_display():
    """
    Checks if the display needs to be updated and shows it if necessary.
    """
    if display_needs_update:
        display.show()
        display_set_update_flag(False)
    
def display_notification(msg=None):
    """
    Display a temporary notification banner at the top of the screen.

    Args:
        msg (str): Notification message to display.
    """

    if settings.performance_mode:
        return

    global notification_text_title
    global notification_on_time
    global previous_top_text
    global current_top_text
    global display_notification_most_recent
    global display_notification_FPS_timer

    if not msg:
        return

    if (time.monotonic() - display_notification_FPS_timer) > constants.DISPLAY_NOTIFICATION_METERING_THRESH:
        notification_text_title = msg

        if notification_on_time > 0:
            previous_top_text = current_top_text

        current_top_text = msg
        display_text_top(msg, True)

        notification_on_time = time.monotonic()

        display_notification_FPS_timer = time.monotonic()

def display_clear_notifications(replace_text=None):
    """
    Check and clear notifications from the top bar if necessary.

    Args:
        replace_text (str, optional): Text to replace the notification with. Defaults to None.
    """
    global notification_text_title
    global notification_on_time
    global previous_top_text
    global current_top_text

    if notification_text_title is None or replace_text is None:
        return

    if notification_text_title == replace_text:
        return

    if time.monotonic() - notification_on_time > constants.NOTIFICATION_THRESH_S:
        notification_on_time = -1
        notification_text_title = None
        display_text_top(replace_text)

def display_startup_screen():
    """
    Display the startup screen.
    """
    display.fill(0)
    display_line_bottom()
    display_text_top("DJBB MIDI LOOPSTER", notification=False)
    display_text_middle(f"Loading {settings.get_startup_preset()}...")
    display.show()
    time.sleep(0.8)

# -------------------- NEOPIXEL -------------------------

# Map pixels to buttons
pixels_mapped = [13,14,15,16,
                9,10,11,12,
                5,6,7,8,
                1,2,3,4,0,17]

def get_pixel(index):
    """
    Retrieves the pixel value at the specified index.

    Args:
        index (int): The index of the pixel to retrieve.

    Returns:
        int: The pixel value at the specified index.
    """
    return pixels_mapped[index]

def pixel_set_note_on(pad_idx, velocity=120):
    """
    Turn on a pixel when a note is played.

    Args:
        pad_idx (int): Index of the pad to turn on.
    """

    color=scale_brightness(constants.NOTE_COLOR, velocity/127)
    all_pixels[get_pixel(pad_idx)] = color


def pixel_set_note_off(pad_idx):
    """
    Turn off a pixel when a note is released.

    Args:
        pad_idx (int): Index of the pad to turn off.
    """

    if global_states.velocity_mapped is True:
        all_pixels[get_pixel(pad_idx)] = pixels_get_velocity_map_color(pad_idx)
    else:
        all_pixels[get_pixel(pad_idx)] = get_default_color(pad_idx)


def pixel_set_fn_button_on(color=constants.BLUE):
    """
    Turn on a pixel when the function button is pressed.

    Args:
        pad_idx (int): Index of the pad to turn on.
    """
    all_pixels[0] = color

def pixel_set_fn_button_off():
    """
    Turn off a pixel when the function button is released.

    Args:
        pad_idx (int): Index of the pad to turn off.
    """
    all_pixels[0] = (0, 0, 0)

def pixel_set_encoder_button_on(color=constants.NAV_MODE_COLOR):
    """
    Turn on a pixel when the encoder button is pressed.

    Args:
        pad_idx (int): Index of the pad to turn on.
    """
    all_pixels[17] = color

def pixel_set_encoder_button_off():
    """
    Turn off a pixel when the encoder button is released.

    Args:
        pad_idx (int): Index of the pad to turn off.
    """
    all_pixels[17] = (0, 0, 0)

def set_blink_pixel(pad_idx, on_or_off=True, color=constants.RED):
    """
    Sets the blink state of a pixel on or off.

    Args:
        pad_idx (int): The index of the pixel pad.
        on_or_off (bool, optional): The state to set the blink. Default is True.
        color (str, optional): The color to set for the blinking pixel. Default is RED.

    Returns:
        None
    """
    global pixel_blink_timer
    global pixel_blink_states
    global pixel_status
    global pixels_blink_colors

    def get_pixel_index(pad_idx):
        """Helper function to get the pixel index."""
        return get_pixel(pad_idx) if pad_idx < 16 else pad_idx

    pixel_idx = get_pixel_index(pad_idx)

    if not on_or_off:
        pixel_blink_states[pad_idx] = False
        all_pixels[pixel_idx] = get_default_color(pad_idx)
    else:
        pixel_blink_states[pad_idx] = True
        pixels_blink_colors[pad_idx] = color

def pixel_set_color(pad_idx, color):
    """
    Sets the color of a specific pixel.

    Args:
        pad_idx (int): The index of the pad.
        color (str): The color to set for the pixel.

    Returns:
        None
    """

    all_pixels[get_pixel(pad_idx)] = color

def pixels_process_blinks():
    """
    Blinks the all_pixels based on the current state of `pixel_blink_states`.

    This function toggles the status of the all_pixels that are set to blink. If a pixel is set to blink, its status
    will be toggled between ON and OFF. The status of the all_pixels is updated in the `pixel_status` list, and the
    corresponding LED colors are set accordingly in the `all_pixels` list. The blinking interval is determined by the
    `constants.PIXEL_BLINK_TIME` constant.

    Note: This function assumes that the `pixel_blink_states`, `pixel_status`, and `all_pixels` variables are already
    defined and accessible.

    Returns:
        None
    """
    global pixel_blink_timer
    global pixel_blink_states
    global pixel_status

    current_time = time.monotonic()
    if True in pixel_blink_states and current_time - pixel_blink_timer > constants.PIXEL_BLINK_TIME:
        for i in range(18):
            if pixel_blink_states[i]:
                pixel_status[i] = not pixel_status[i]
                pixel_color = pixels_blink_colors[i] if pixel_status[i] else constants.BLACK
                all_pixels[get_pixel(i)] = pixel_color
        
        pixel_blink_timer = current_time

def get_blink_color(pad_idx):
    """
    Returns the color of the blinking pixel.

    Parameters:
    pad_idx (int): The index of the pad.

    Returns:
    str: The color of the blinking pixel.
    """
    return pixels_blink_colors[pad_idx]

def set_blink_color(pad_idx, color):
    """
    Sets the color of the blinking pixel.

    Parameters:
    pad_idx (int): The index of the pad.
    color (str): The color to set for the blinking pixel.

    Returns:
    None
    """
    global pixels_blink_colors
    
    pixels_blink_colors[pad_idx] = color

def get_default_color(pad_idx):
    """
    Returns the default color for a given pad index.

    Parameters:
    pad_idx (int): The index of the pad.

    Returns:
    str: The default color for the pad.
    """
    return pixels_default_colors[pad_idx]

def pixels_set_default_color(pad_idx, color=""):
    """
    Sets the default color for a specific pad.

    Parameters:
    pad_idx (int): The index of the pad.
    color (str): The color to set for the pad.

    Returns:
    None
    """
    global pixels_default_colors

    if color != "":
        display_color = color

    elif global_states.velocity_mapped is True:
        display_color = pixels_get_velocity_map_color(pad_idx)

    else:
        display_color = constants.BLACK
    
    pixels_default_colors[pad_idx] = display_color
    print(display_color)

def clear_pixels(): # Turn off all pixels. 
    """
    Set all pixels to black.

    Returns:
        None
    """
    for i in range(18):
        all_pixels[i] = constants.BLACK

def interpolate_color(color1, color2, factor):
    """
    Interpolates between two colors.

    Args:
        color1 (tuple): The starting color (R, G, B).
        color2 (tuple): The ending color (R, G, B).
        factor (float): The interpolation factor (0.0 to 1.0).

    Returns:
        tuple: The interpolated color (R, G, B).
    """
    return tuple(int(color1[i] + (color2[i] - color1[i]) * factor) for i in range(3))

def pixels_get_velocity_map_color(pad_idx):
    """
    Returns the color for a given pad index based on the velocity map.

    Args:
        pad_idx (int): The index of the pad to get the color for.

    Returns:
        tuple: The color (R, G, B) for the pad index.
    """
    return velocity_map_colors[pad_idx]

def pixels_generate_velocity_map(global_brightness_factor=0.5):
    """
    Generate a gradient from light green to orange on the neopixels with pad 0 being light green and pad 16 being orange,
    and also transitioning from very dim to bright. Sets the default color for the pixels.

    Args:
        on_or_off (bool): Whether to turn the gradient on or off.
        global_brightness_factor (float): The global factor by which to scale brightness (0.0 to 1.0).

    Returns:
        None
    """

    light_green = (0, 255, 0)
    orange = (255, 165, 0)

    for i in range(16):
        color_factor = i / 15  # Normalizing the index to a range of 0.0 to 1.0 for color interpolation
        brightness_factor = ((i + 1) / 16) * global_brightness_factor  # Normalizing the index to a range of 1/16 to 1.0, then applying global brightness factor

        interpolated_color = interpolate_color(light_green, orange, color_factor)
        final_color = scale_brightness(interpolated_color, brightness_factor)
        velocity_map_colors.append(final_color)

def pixels_display_velocity_map(on_or_off=True):
    """
    Display a gradient from light green to orange on the neopixels with pad 0 being light green and pad 16 being orange,
    and also transitioning from very dim to bright. Sets the default color for the pixels.

    Args:
        on_or_off (bool): Whether to turn the gradient on or off.

    Returns:
        None
    """
    if on_or_off:
        for i in range(16):
            color = velocity_map_colors[i]
            pixels_set_default_color(i, color)
            all_pixels[get_pixel(i)] = color
    else:
        for i in range(16):
            pixels_set_default_color(i, constants.BLACK)
            all_pixels[get_pixel(i)] = constants.BLACK

def scale_brightness(color, brightness_factor):
    """
    Scales the brightness of a color.

    Args:
        color (tuple): The color (R, G, B) to scale brightness for.
        brightness_factor (float): The factor by which to scale brightness (0.0 to 1.0).

    Returns:
        tuple: The color (R, G, B) with scaled brightness.
    """
    return tuple(int(c * brightness_factor) for c in color)

def scale_brightness_by_velocity(pad_idx, velocity):
    """
    Scales the brightness of the default color for a pad index based on the MIDI velocity value.

    Args:
        pad_idx (int): The index of the pad to scale the brightness for.
        velocity (int): The MIDI velocity value (0 to 127).

    Returns:
        None
    """
    brightness_factor = velocity / 127              # Calculate the brightness factor based on the MIDI velocity
    default_color = get_default_color(pad_idx)      # Get the current default color for the pad
    dimmed_color = scale_brightness(default_color, brightness_factor) # Scale the default color's brightness
    pixels_set_default_color(pad_idx, dimmed_color) # Set the dimmed color as the new default color for the pad
    all_pixels[get_pixel(pad_idx)] = dimmed_color   # Update the actual pixel color

pixels_generate_velocity_map()
