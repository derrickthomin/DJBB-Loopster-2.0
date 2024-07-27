from settings import settings
import board
import busio
import adafruit_ssd1306
import time
import neopixel

disp_timing_compensation = 0

# PINS / SETUP
SCL_PIN = board.GP19
SDA_PIN = board.GP18
i2c = busio.I2C(SCL_PIN, SDA_PIN, frequency=400_000)
display = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)

# NEOPIXEL SETUP
pixels = neopixel.NeoPixel(board.GP9, 18, brightness=settings.PIXEL_BRIGHTNESS)

# DJT - move me. DJBB CUP
pixels_djbb_cup = neopixel.NeoPixel(board.GP15,16,brightness = 0.8)

# Constants for colors
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
PINK = (255, 105, 180)
YELLOW = (255, 255, 0)
PURPLE = (128, 0, 128)
ORANGE = (255, 165, 0)
LIGHT_PURPLE = (221, 160, 221)
CYAN = (0, 255, 255)
LIGHT_BLUE = (173, 216, 230)
LIGHT_GREEN = (144, 238, 144)
LIGHT_YELLOW = (255, 255, 224)
LIGHT_ORANGE = (255, 204, 153)

COLORS = [YELLOW, YELLOW, YELLOW, YELLOW, YELLOW,
          YELLOW, YELLOW, YELLOW, YELLOW,
          YELLOW, YELLOW, YELLOW, YELLOW,
          YELLOW, YELLOW, YELLOW, YELLOW, YELLOW]

NOTE_COLOR = ORANGE

# SCREEN CONSTANTS
WIDTH = 128
HEIGHT = 64
TOP_HEIGHT = 16
MIDDLE_Y_START = HEIGHT // 3 + 3
MIDDLE_HEIGHT = 28
BOTTOM_Y_START = 56
BOTTOM_LINE_Y_START = MIDDLE_Y_START + MIDDLE_HEIGHT + 1
LINEHEIGHT = 8
CHARS_PER_LINE = 20
TEXT_PAD = 4
SEL_ICON_TXT = "[fn]"
SEL_ICON_X_START = 30  # Where to display icon when select button is being held
NOTIFICATION_ICON_TXT = "[!]"
LOOP_ON_ICON = "∞"
RECORDING_ICON = "(r)"
PLAY_ICON = "|>"
NAV_MODE_TXT = "N A V"
NAV_MSG_WIDTH = 38
NAV_ICON_X_START = WIDTH - NAV_MSG_WIDTH
NAV_ICON_Y_START = 100
REC_ICON_X_START = 0
REC_ICON_Y_START = HEIGHT - 20

# TRACKING VARIABLES
display_needs_update_flag = True  # If true, show the display
notification_text_title = None
notification_ontime = 0
current_top_text = None
prev_top_text = None
display_notification_FPS_timer = 0
display_notification_most_recent = ""
pixel_blink_timer = 0
PIXEL_BLINK_TIME = 0.4
pixels_blink_state = [False] * 18
pixel_status = [False] * 18
pixels_default_color = [BLACK] * 18  # Usually black, unlss feature is overriding


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
    PADDING = 4     # px
    display.fill_rect(0, 0, WIDTH, TOP_HEIGHT, bkg_color)

    # Set up special border for notification text
    if notification:
        linepad_x = 0
        display.fill_rect(0 + linepad_x, TOP_HEIGHT - 1, WIDTH - (2 * linepad_x), 1, 1) 
    display.text(text, 0 + PADDING, 0 + PADDING, txt_color)  
    display_flag_for_update()

def display_text_middle(text):
    """
    Display text in the middle part of the screen.

    Args:
        text (str or list): Text or list of text lines to display.
    """
    bkg_color = 0   # blank, pixels off
    txt_color = 1   # Pixels on
    if not isinstance(text, list):
        text = [text]
    display.fill_rect(0, MIDDLE_Y_START, WIDTH, MIDDLE_HEIGHT, bkg_color)

    if len(text) > 0:
        line_num = 0
        for text_line in text:
            display.text(text_line, 0 + TEXT_PAD, MIDDLE_Y_START + (line_num * LINEHEIGHT), txt_color)
            line_num = line_num + 1
        display_flag_for_update()
    else:
        print("WARNING: No Text Array Passed in")

def display_text_bottom(text):
    """
    Display text on the bottom part of the screen.

    Args:
        text (str): Text to display.
    """
    bkg_color = 0   # blank, pixels off
    txt_color = 1   # Pixels on
    display.fill_rect(0, BOTTOM_Y_START, WIDTH, HEIGHT, bkg_color)  
    display.text(text, 0, BOTTOM_Y_START, txt_color)  
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
    starty = BOTTOM_Y_START
    icon_width = 35
    icon_height = 18
    pad = 2
    display.fill_rect(startx - pad, starty - pad, icon_width, icon_height, 0)  
    if onOrOff: 
        display.text(SEL_ICON_TXT, startx, starty, 1)
    display_flag_for_update()

def display_line_bottom():
    """
    Display a line at the bottom of the screen.
    """
    display.fill_rect(0, BOTTOM_LINE_Y_START, WIDTH, 1, 1)
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
    starty = HEIGHT - height

    if onOrOff is True:
        display.fill_rect(0, starty, width, height, 1)
        display.text(RECORDING_ICON, 0, starty, 0)

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
    starty = HEIGHT - 23

    if onOrOff is True:
        display.fill_rect(0, starty, width, height, 0)
        display.text(PLAY_ICON, 0, starty, 1)

    if onOrOff is False:
        display.fill_rect(0, starty, width, height, 0)

def toggle_menu_navmode_icon(onOrOff):
    """
    Toggle the navigation mode icon on the screen.

    Args:
        onOrOff (bool): Indicates whether to turn the icon on or off.

    """
    if onOrOff is True:
        display.fill_rect(NAV_ICON_X_START, HEIGHT - LINEHEIGHT - 2, NAV_MSG_WIDTH, 10, 1)
        display.text(NAV_MODE_TXT, NAV_ICON_X_START + 4, HEIGHT - LINEHEIGHT,0)
        display_flag_for_update()

    elif onOrOff is False:
        display.fill_rect(NAV_ICON_X_START, HEIGHT - LINEHEIGHT - 2, NAV_MSG_WIDTH, 10, 0)  
        display_flag_for_update()

def check_show_display():
    global disp_timing_compensation
    """
    Check and show the display if it needs an update.
    """
    if display_needs_update_flag:
        disptimer = time.monotonic()
        display.show()
        display_flag_for_update(False)
    
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
    
    if (time.monotonic() - display_notification_FPS_timer) > settings.DISPLAY_NOTIFICATION_METERING_THRESH:
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
    
    if time.monotonic() - notification_ontime > settings.NOTIFICATION_THRESH_S:
        notification_ontime = -1
        notification_text_title = None
        display_text_top(replace_text)

# Initialize the display
display.fill(0)
display_line_bottom()
display.show()


# ------- NEOPIXEL --------
# Map pixels to buttons
pixels_mapped = [13,14,15,16,
                9,10,11,12,
                5,6,7,8,
                1,2,3,4]

pixel_colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
                (255, 0, 255), (0, 255, 255), (255, 255, 255), (0, 0, 0),
                (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
                (255, 0, 255), (0, 255, 255), (255, 255, 255), (0, 0, 0)]

def get_pixel(index):
    return pixels_mapped[index]

def pixel_note_on(pad_idx):
    """
    Turn on a pixel when a note is played.

    Args:
        pad_idx (int): Index of the pad to turn on.
    """
    pixels[get_pixel(pad_idx)] = NOTE_COLOR
    pixels_djbb_cup[pad_idx] = NOTE_COLOR
    print(pad_idx)

def pixel_note_off(pad_idx):
    """
    Turn off a pixel when a note is released.

    Args:
        pad_idx (int): Index of the pad to turn off.
    """
    pixels[get_pixel(pad_idx)] = get_default_color(pad_idx)
    pixels_djbb_cup[pad_idx] = BLACK

def pixel_fn_button_on(color=BLUE):
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

    if True in pixels_blink_state and time.monotonic() - pixel_blink_timer > PIXEL_BLINK_TIME:
        print("WE HERE")
        for i in range(16):
            if pixels_blink_state[i]:
                pixel_status[i] = not pixel_status[i]
                
                if pixel_status[i]:
                    pixels[get_pixel(i)] = RED
                else:
                    pixels[get_pixel(i)] = BLACK

        pixel_blink_timer = time.monotonic()

def get_default_color(pad_idx):
    return pixels_default_color[pad_idx]

def set_default_color(pad_idx, color):
    global pixels_default_color
    pixels_default_color[pad_idx] = color

