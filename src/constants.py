import board

# ------ LOOPSTER VERSION ------ #
LOOPSTER_VERSION = 2                    # 1 or 2 for now
NUM_PADS = 16                           # Number of pads in the grid

# ------ PIN SETUP ------ #

# Display I2C Pins
SCL = board.GP19
SDA = board.GP18

# Encoder Pins
fn_btn = board.GP10
ENCODER_BTN = board.GP11
ENCODER_CLK = board.GP12
ENCODER_DT = board.GP13

# MIDI Pins and Settings
UART_MIDI_TX = board.GP16
UART_MIDI_RX = board.GP17
LOOP_NOTES_LIMIT = 500
CC_EVENTS_LIMIT = 1500
TOTAL_LOOP_EVENTS_LIMIT = 5000     # Maximum total events across all chord loops          

# Default velocities for single note mode
DEFAULT_SINGLENOTE_MODE_VELOCITIES = [
    8, 15, 22, 29, 36, 43, 50, 57, 64, 71, 78, 85, 92, 99, 106, 127
]

# ------ SCREEN CONFIGURATION ------ #

# Screen Dimensions
SCREEN_W = 128
SCREEN_H = 64

# Screen Sections
TOP_HEIGHT = 16
MIDDLE_Y_START = SCREEN_H // 3 + 3
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
NAV_ICON_X_START = SCREEN_W - NAV_MSG_WIDTH
NAV_ICON_Y_START = 100
REC_ICON_X_START = 0
REC_ICON_Y_START = SCREEN_H - 20
PADDING = 4

# ------ COLORS ------ #

# Basic Colors
RED = (255, 0, 0)
GREEN = (0, 245, 0)
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
LIGHT_CYAN = (224, 255, 255)
DARK_CYAN = (0, 50, 50)
LIGHT_BLUE = (173, 216, 230)
LIGHT_GREEN = (144, 238, 144)
LIGHT_YELLOW = (255, 255, 224)
LIGHT_ORANGE = (255, 204, 153)
DARK_ORANGE = (255, 100, 0)

# Visual Feedback Colors
OFF_COLOR = (0, 0, 0)
ENCODER_COLOR = (64, 64, 64)
CC_COLOR = (64, 0, 64)                  # Purple
PASSTHRU_COLOR = (0, 128, 128)          # Teal for MIDI passthrough

# ------ NEOPIXEL SETTINGS ------ #
PAD_TO_PIXEL_IDX_MAP = [13, 14, 15, 16, 9, 10, 11, 12, 5, 6, 7, 8, 1, 2, 3, 4, 0, 17]
PIXEL_BLINK_TIME = 0.25                 # Time interval for pixel blink
FN_BUTTON_COLOR = ORANGE
PIXEL_LOOP_PLAYING_COLOR = GREEN
NOTE_COLOR = ORANGE
NAV_MODE_COLOR = LIGHT_BLUE
ENCODER_LOCK_COLOR = RED
BKG_COLOR = 0                           # Background color, all pixels off
TXT_COLOR = 1                           # Text color, pixels on
CHORD_COLOR = (20, 0, 20)
PAD_HELD_COLOR = DARK_CYAN
CC_COLOR = BLUE


# ------ ARPEGGIATOR SETTINGS ------ #
VALID_ARP_LENGTHS = ["1", "1/2", "1/4", "1/8", "1/16", "1/32", "1/64"]

# ------ ASSORTED SETTINGS ------ #
NAV_BUTTONS_POLL_S = 0.02               # Polling interval for navigation buttons
BUTTON_HOLD_THRESH_S = 0.35             # Threshold for button hold
ENCODER_HOLD_THRESH_S = 0.3             # Threshold for encoder hold
FN_HOLD_THRESH_S = 0.1                  # Threshold for function button hold
show_notification_METERING_THRESH = 0.08 # Threshold for display notification metering
DBL_PRESS_THRESH_S = 0.4                # Threshold for double press
NOTIFICATION_THRESH_S = 0.5             # Threshold for notifications
PRESETS_FILEPATH = "presets.json"       # Filepath for presets
MIN_TIME_BETWEEN_EVENTS = 0.03          # Minimum time between events
PAD_OFFSET_AMOUNT = 4                   # How many notes to scroll up or down
DEFAULT_CHORDPAD_IDX = 255              # Default chord pad index
CC_ONLY_LOOP_LENGTH_SECONDS = 0.5       # Default length for CC-only loops
MS_PER_SECOND = 1000
VELOCITY_CHANGE_DISPLAY_THRESH = 5
MEMORY_CLEANUP_INTERVAL = 50
