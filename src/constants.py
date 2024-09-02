import board

# ------ Loopster Version ------ #
LOOPSTER_VERSION = 2  # 1 or 2 for now

# ------ PIN SETUP ------ #

# Display I2C Pins
SCL = board.GP19
SDA = board.GP18

# Encoder Pins
SELECT_BTN = board.GP10
ENCODER_BTN = board.GP11
ENCODER_CLK = board.GP12
ENCODER_DT = board.GP13

# MIDI Pins and Settings
UART_MIDI_TX = board.GP16
UART_MIDI_RX = board.GP17
MIDI_NOTES_LIMIT = 500  # Max MIDI notes limit, fails at ~129 without memory clean

# Default velocities for single note mode
DEFAULT_SINGLENOTE_MODE_VELOCITIES = [
    8, 15, 22, 29, 36, 43, 50, 57, 64, 71, 78, 85, 92, 99, 106, 127
]

# ------ SCREEN CONFIGURATION ------ #

# Screen Dimensions
WIDTH = 128
HEIGHT = 64

# Screen Sections
TOP_HEIGHT = 16
MIDDLE_Y_START = HEIGHT // 3 + 3
MIDDLE_HEIGHT = 28
BOTTOM_Y_START = 56
BOTTOM_LINE_Y_START = MIDDLE_Y_START + MIDDLE_HEIGHT + 1

# Text and Icon Settings
LINEHEIGHT = 8
CHARS_PER_LINE = 20
TEXT_PAD = 7
SEL_ICON_TXT = "[fn]"
FN_BTN_ICON_X_START = 20
NOTIFICATION_ICON_TXT = "[!]"
RECORDING_ICON = "(r)"
PLAY_ICON = "|>"
NAV_MODE_TXT = "N A V"
ENCODER_LOCK_TXT = "!LCK!"
CHD_MODE_ICON = "(CHD)"
VEL_MODE_ICON = "(VEL)"
ENC_MODE_ICON = "(ARP)"
PLAYMODE_ICON_X_START = 50
NAV_MSG_WIDTH = 38
NAV_ICON_X_START = WIDTH - NAV_MSG_WIDTH
NAV_ICON_Y_START = 100
REC_ICON_X_START = 0
REC_ICON_Y_START = HEIGHT - 20
PADDING = 4

# ------ COLORS ------ #

# Basic Colors
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# Additional Colors
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

# ------ NEOPIXEL SETTINGS ------ #

PIXEL_BLINK_TIME = 0.25  # Time interval for pixel blink
FN_BUTTON_COLOR = ORANGE
PIXEL_LOOP_PLAYING_COLOR = GREEN
NOTE_COLOR = ORANGE
NAV_MODE_COLOR = LIGHT_BLUE
ENCODER_LOCK_COLOR = RED
BKG_COLOR = 0  # Background color, all pixels off
TXT_COLOR = 1  # Text color, pixels on
CHORD_COLOR = (20, 0, 20)

# ------ ASSORTED SETTINGS ------ #

NAV_BUTTONS_POLL_S = 0.02  # Polling interval for navigation buttons
BUTTON_HOLD_THRESH_S = 0.4  # Threshold for button hold
DISPLAY_NOTIFICATION_METERING_THRESH = 0.08  # Threshold for display notification metering
DBL_PRESS_THRESH_S = 0.4  # Threshold for double press
NOTIFICATION_THRESH_S = 0.5  # Threshold for notifications
PRESETS_FILEPATH = "presets.json"  # Filepath for presets
