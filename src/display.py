from settings import settings
import constants
import board
import busio
import adafruit_ssd1306
import time
import neopixel
from debug import debug



# PINS / SETUP
i2c = busio.I2C(constants.SCL, constants.SDA, frequency=400_000)
display = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)

# NEOPIXEL SETUP
pixels = neopixel.NeoPixel(board.GP9, 18, brightness=settings.PIXEL_BRIGHTNESS)

# DJT - move me. DJBB CUP
pixels_djbb_cup = neopixel.NeoPixel(board.GP15,16,brightness = 0.8)

NOTE_COLOR = constants.ORANGE

# TRACKING VARIABLES
display_needs_update_flag = True  # If true, show the display
notification_text_title = None
notification_ontime = 0
current_top_text = None
prev_top_text = None
display_notification_FPS_timer = 0
display_notification_most_recent = ""
pixel_blink_timer = 0
pixels_blink_state = [False] * 18
pixel_status = [False] * 18
pixels_default_color = [constants.BLACK] * 18  # Usually black, unlss feature is overriding


# Sets global display_needs_update_flag 
def display_flag_for_update(yesOrNo = True):
    global display_needs_update_flag
    display_needs_update_flag = yesOrNo

def display_text_top(text, notification=False):
    """
    Display text on the top part of the screen.

    Args:
        text (str): Text to display.
        notification (bool, optional): Indicates if it's a notification. Defaults to False.
    """
    bkg_color = 0   # blank, pixels off
    txt_color = 1   # Pixels on
    display.fill_rect(0, 0, constants.WIDTH, constants.TOP_HEIGHT, bkg_color)

    # Set up special border for notification text
    if notification:
        linepad_x = 0
        display.fill_rect(0 + linepad_x, constants.TOP_HEIGHT - 1, constants.WIDTH - (2 * linepad_x), 1, 1) 
    display.text(text, 0 + constants.PADDING, 0 + constants.PADDING, txt_color)  
    display_flag_for_update()

def display_text_middle(text):
    """
    Display text in the middle part of the screen.

    Args:
        text (str or list): Text or list of text lines to display.
    """
    debug.performance_timer("display_text_middle")
    bkg_color = 0   # blank, pixels off
    txt_color = 1   # Pixels on
    if not isinstance(text, list):
        text = [text]
    display.fill_rect(0, constants.MIDDLE_Y_START, constants.WIDTH, constants.MIDDLE_HEIGHT, bkg_color)

    if len(text) > 0:
        line_num = 0
        for text_line in text:
            display.text(text_line, 0 + constants.TEXT_PAD, constants.MIDDLE_Y_START + (line_num * constants.LINEHEIGHT), txt_color)
            line_num = line_num + 1
        display_flag_for_update()
    debug.performance_timer("display_text_middle")
def display_text_bottom(text):
    """
    Display text on the bottom part of the screen.

    Args:
        text (str): Text to display.
    """
    bkg_color = 0   # blank, pixels off
    txt_color = 1   # Pixels on
    display.fill_rect(0, constants.BOTTOM_Y_START, constants.WIDTH, constants.HEIGHT, bkg_color)  
    display.text(text, 0, constants.BOTTOM_Y_START, txt_color)  
    display_flag_for_update()

def toggle_select_button_icon(onOrOff=False):
    """
    Toggle the select button icon on the screen.

    Args:
        onOrOff (bool, optional): Indicates whether to turn the icon on or off. Defaults to False.
    """
    if settings.PERFORMANCE_MODE:
        return
    
    startx = 30  # Px from the left of the screen
    starty = constants.BOTTOM_Y_START
    icon_width = 35
    icon_height = 18
    pad = 2
    display.fill_rect(startx - pad, starty - pad, icon_width, icon_height, 0)  
    if onOrOff: 
        display.text(constants.SEL_ICON_TXT, startx, starty, 1)
    display_flag_for_update()

def display_line_bottom():
    """
    Display a line at the bottom of the screen.
    """
    display.fill_rect(0, constants.BOTTOM_LINE_Y_START, constants.WIDTH, 1, 1)
    display_flag_for_update()

def toggle_recording_icon(onOrOff=False):
    """
    Toggle the recording icon on the screen.

    Args:
        onOrOff (bool, optional): Indicates whether to turn the icon on or off. Defaults to False.
    """
    if settings.PERFORMANCE_MODE:
        return
    height = 10
    width = 18
    starty = constants.HEIGHT - height

    if onOrOff is True:
        display.fill_rect(0, starty, width, height, 1)
        display.text(constants.RECORDING_ICON, 0, starty, 0)

    if onOrOff is False:
        display.fill_rect(0, starty, width, height, 0)

def toggle_play_icon(onOrOff=False):
    """
    Toggle the play icon on the screen.

    Args:
        onOrOff (bool, optional): Indicates whether to turn the icon on or off. Defaults to False.
    """
    if settings.PERFORMANCE_MODE:
        return
    height = 10
    width = 18
    starty = constants.HEIGHT - 23

    if onOrOff is True:
        display.fill_rect(0, starty, width, height, 0)
        display.text(constants.PLAY_ICON, 0, starty, 1)

    if onOrOff is False:
        display.fill_rect(0, starty, width, height, 0)

def toggle_menu_navmode_icon(onOrOff):
    """
    Toggle the navigation mode icon on the screen.

    Args:
        onOrOff (bool): Indicates whether to turn the icon on or off.

    """
    if onOrOff is True:
        display.fill_rect(constants.NAV_ICON_X_START, constants.HEIGHT - constants.LINEHEIGHT - 2, constants.NAV_MSG_WIDTH, 10, 1)
        display.text(constants.NAV_MODE_TXT, constants.NAV_ICON_X_START + 4, constants.HEIGHT - constants.LINEHEIGHT,0)
        display_flag_for_update()

    elif onOrOff is False:
        display.fill_rect(constants.NAV_ICON_X_START, constants.HEIGHT - constants.LINEHEIGHT - 2, constants.NAV_MSG_WIDTH, 10, 0)  
        display_flag_for_update()

def check_show_display():
    global disp_timing_compensation
    """
    Check and show the display if it needs an update.
    """
    if display_needs_update_flag:
        debug.performance_timer("display update")
        display.show()
        display_flag_for_update(False)
        debug.performance_timer("display update")
    
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
    global current_top_text
    global display_notification_most_recent
    global display_notification_FPS_timer

    if not msg:
        return
    
    if (time.monotonic() - display_notification_FPS_timer) > constants.DISPLAY_NOTIFICATION_METERING_THRESH:
        notification_text_title = msg

        if notification_ontime > 0:
            prev_top_text = current_top_text

        current_top_text = msg
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
    global current_top_text

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
    display_text_top("DJBB MIDI LOOPSTER", False)
    display_text_middle(f"Loading {settings.get_startup_preset()}...")
    display.show()
    time.sleep(1.5)
#
display_startup_screen()
display.fill(0)
display_line_bottom()
display.show()


# ------- NEOPIXEL --------
# Map pixels to buttons
pixels_mapped = [13,14,15,16,
                9,10,11,12,
                5,6,7,8,
                1,2,3,4]

def get_pixel(index):
    return pixels_mapped[index]

def pixel_note_on(pad_idx):
    """
    Turn on a pixel when a note is played.

    Args:
        pad_idx (int): Index of the pad to turn on.
    """
    debug.performance_timer("pixel_note_on")
    pixels[get_pixel(pad_idx)] = NOTE_COLOR
    pixels_djbb_cup[pad_idx] = NOTE_COLOR
    debug.performance_timer("pixel_note_on")

def pixel_note_off(pad_idx):
    """
    Turn off a pixel when a note is released.

    Args:
        pad_idx (int): Index of the pad to turn off.
    """
    debug.performance_timer("pixel_note_off")
    pixels[get_pixel(pad_idx)] = get_default_color(pad_idx)
    pixels_djbb_cup[pad_idx] = constants.BLACK
    debug.performance_timer("pixel_note_off")

def pixel_fn_button_on(color=constants.BLUE):
    """
    Turn on a pixel when the function button is pressed.

    Args:
        pad_idx (int): Index of the pad to turn on.
    """
    pixels[0] = color

def pixel_fn_button_off():
    """
    Turn off a pixel when the function button is released.

    Args:
        pad_idx (int): Index of the pad to turn off.
    """
    pixels[0] = (0, 0, 0)

def pixel_encoder_button_on():
    """
    Turn on a pixel when the encoder button is pressed.

    Args:
        pad_idx (int): Index of the pad to turn on.
    """
    pixels[17] = (0, 0, 255)

def pixel_encoder_button_off():
    """
    Turn off a pixel when the encoder button is released.

    Args:
        pad_idx (int): Index of the pad to turn off.
    """
    pixels[17] = (0, 0, 0)

# False will immediatly turn off pixel as well as setting flag
def set_blink_pixel(pad_idx, onOrOff = True):
    global pixel_blink_timer
    global pixels_blink_state
    global pixel_status
    
    if onOrOff == False:
        pixels_blink_state[pad_idx]=False
        pixels[get_pixel(pad_idx)] = get_default_color(pad_idx)
        return
    else:
        pixels_blink_state[pad_idx]=True
    
def blink_pixels():
    global pixel_blink_timer
    global pixels_blink_state
    global pixel_status

    if True in pixels_blink_state and time.monotonic() - pixel_blink_timer > constants.PIXEL_BLINK_TIME:
        for i in range(16):
            if pixels_blink_state[i]:
                pixel_status[i] = not pixel_status[i]
                
                if pixel_status[i]:
                    pixels[get_pixel(i)] = constants.RED
                else:
                    pixels[get_pixel(i)] =constants.BLACK

        pixel_blink_timer = time.monotonic()

def get_default_color(pad_idx):
    return pixels_default_color[pad_idx]

def set_default_color(pad_idx, color):
    global pixels_default_color
    pixels_default_color[pad_idx] = color

