import board

# ------ LOOPSTER VERSION ------ #
LOOPSTER_VERSION = 2
NUM_PADS = 16
NUM_PIXELS = 18
FN_LED_IDX = 16
ENC_LED_IDX = 17

# ------ MENU INDICES ------ #
MENU_PLAY = 0
MENU_SCALE = 1
MENU_MIDI = 2
MENU_SETTINGS = 3
MENU_LOAD = 4
MENU_SAVE = 5

# ------ PIN SETUP ------ #

# Display I2C Pins
SCL = board.GP19
SDA = board.GP18

# Encoder Pins
FN_BTN = board.GP10
ENCODER_BTN = board.GP11
ENCODER_CLK = board.GP12
ENCODER_DT = board.GP13

# MIDI Pins and Settings
UART_MIDI_TX = board.GP16
UART_MIDI_RX = board.GP17

# Event limits - Power-of-2 boundaries to prevent fragmentation-causing array resizes
# Smaller limits = smaller arrays = less fragmentation = more loops possible
LOOP_NOTES_LIMIT = 512              # 512 note-ons = ~256 actual notes, plenty for music
CC_EVENTS_LIMIT = 1024              # Most real CC usage doesn't need more  
CC_RAM_LIMIT = 250                  # Max CCs when flash streaming disabled
TOTAL_LOOP_EVENTS_LIMIT = 99999     # High for stress testing - doesn't affect fragmentation          

# Memory management
MEMORY_LOW_THRESHOLD = 25000        # Trigger aggressive GC below this (bytes free)
MEMORY_CRITICAL_THRESHOLD = 10000   # Stop recording if below this

# Default velocities for single note mode
DEFAULT_SINGLENOTE_MODE_VELOCITIES = [
    8, 15, 22, 29, 36, 43, 50, 57, 64, 71, 78, 85, 92, 99, 106, 127
]

# ------ SCREEN CONFIGURATION ------ #
SCREEN_W = 128
SCREEN_H = 64

# Screen Sections
TOP_HEIGHT = 16
MIDDLE_Y_START = 24
MIDDLE_HEIGHT = 28
BOTTOM_Y_START = 56
BOTTOM_LINE_Y_START = 53

# Text Settings
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
LOOP_MODE_ICON = "(LOOP)"
VEL_MODE_ICON = "(VEL)"
ENC_MODE_ICON = "(ARP)"
PLAYMODE_ICON_X_START = 50
NAV_MSG_WIDTH = 38
NAV_ICON_X_START = 90
NAV_ICON_Y_START = 100
REC_ICON_X_START = 0
REC_ICON_Y_START = 44
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
CYAN = (0, 255, 255)
DARK_CYAN = (0, 50, 50)
LIGHT_BLUE = (173, 216, 230)
AMBER = (255, 50, 0)

# Visual Feedback Colors
OFF_COLOR = (0, 0, 0)
ENCODER_COLOR = (64, 64, 64)
CC_COLOR = BLUE
PASSTHRU_COLOR = (0, 128, 128)

# ------ NEOPIXEL SETTINGS ------ #
PAD_TO_PIXEL_IDX_MAP = [13, 14, 15, 16, 9, 10, 11, 12, 5, 6, 7, 8, 1, 2, 3, 4, 0, 17]
PIXEL_BLINK_TIME = 0.25
FN_BUTTON_COLOR = ORANGE
PIXEL_LOOP_PLAYING_COLOR = GREEN
NOTE_COLOR = ORANGE
NAV_MODE_COLOR = LIGHT_BLUE
ENCODER_LOCK_COLOR = RED
BKG_COLOR = 0
TXT_COLOR = 1
LOOP_COLOR = (20, 0, 20)
PAD_HELD_COLOR = DARK_CYAN


# ------ ARPEGGIATOR SETTINGS ------ #
VALID_ARP_LENGTHS = ["1", "1/2", "1/4", "1/8", "1/16", "1/32", "1/64"]

# ------ ASSORTED SETTINGS ------ #
NAV_BUTTONS_POLL_S = 0.02
BUTTON_HOLD_THRESH_S = 0.35
ENCODER_HOLD_THRESH_S = 0.3
FN_HOLD_THRESH_S = 0.1
NOTIFICATION_METERING_THRESH = 0.08
DBL_PRESS_THRESH_S = 0.4
NOTIFICATION_THRESH_S = 0.5
PRESETS_FILEPATH = "presets.json"
MIN_TIME_BETWEEN_EVENTS = 0.03
PAD_OFFSET_AMOUNT = 4
DEFAULT_LOOP_PAD_IDX = 255
CC_ONLY_LOOP_LENGTH_SECONDS = 0.5
MS_PER_SECOND = 1000
VELOCITY_CHANGE_DISPLAY_THRESH = 5
MEMORY_CLEANUP_INTERVAL = 50

# ============================================================================
# ============================= COLM USER ADDONS =============================
# ============================================================================

# ------ FEATURE FLAGS ------ #
USING_FOOT_PEDALS = True
USING_GLOVE_BUTTONS = True
USING_ACCELEROMETER = True
USING_MOTOR_FEEDBACK = True

# ------ ACCELEROMETER SETTINGS ------ #
# GPIO pins for accelerometer I2C (separate from display I2C)
ACCEL_I2C_SCL = board.GP21
ACCEL_I2C_SDA = board.GP20

# Accelerometer tilt-based CC numbers
ACCEL_LEFT_TILT_CC = 1          # CC number for left tilt (modulation wheel)
ACCEL_RIGHT_TILT_CC = 74        # CC number for right tilt (filter cutoff)
ACCEL_BACKWARD_TILT_CC = 7      # CC number for backward tilt (volume)
ACCEL_FORWARD_TILT_CC = 11      # CC number for forward tilt (not used - forward controls arpeggiator)

# Accelerometer processing settings
ACCEL_THRESHOLD = 1             # Threshold for CC value changes
ACCEL_SMOOTH_FACTOR = 0.8       # Smoothing factor (0-1) where 1 = no smoothing
ACCEL_UPDATE_INTERVAL = 0.05    # Time in seconds between updates

# Accelerometer switch/enable pin
ACCEL_ENABLE_PIN = board.A3     # GPIO pin for accelerometer enable switch

# Accelerometer tilt settings
ACCEL_DEADZONE_DEGREES = 10     # Deadzone in degrees to prevent accidental triggers
ACCEL_MAX_TILT_DEGREES = 90     # Maximum tilt angle for full CC range

# Accelerometer arpeggiator control settings
ACCEL_ARP_MAX_TILT_DEGREES = 90         # Maximum tilt angle for full speed
ACCEL_ARP_MIN_INTERVAL_MS = 50          # Fastest arp interval (50ms at full tilt)
ACCEL_ARP_MAX_INTERVAL_MS = 1000        # Slowest arp interval (1 second at minimal tilt)
ACCEL_ARP_AXIS = 'Y'                    # Which accelerometer axis to use ('X' or 'Y')

# ------ GLOVE BUTTON SETTINGS ------ #
GLOVE_LEFT_PIN = board.GP23
GLOVE_RIGHT_PIN = board.GP24
GLOVE_DEBOUNCE_TIME = 0.02      # 20ms debounce time

# ------ PEDAL SETTINGS ------ #
PEDAL_1_PIN = board.GP9
PEDAL_2_PIN = board.GP0
PEDAL_3_PIN = board.A0          # Analog pin used as digital
PEDAL_4_PIN = board.A1          # Analog pin used as digital
PEDAL_5_PIN = board.GP22
PEDAL_NEOPIXEL_PIN = board.GP14
PEDAL_COUNT = 5
PEDAL_BRIGHTNESS = 1

# ------ MOTOR SETTINGS ------ #
MOTOR_PWM_PIN = board.GP28      # Motor PWM pin for haptic feedback

# Motor haptic feedback settings
MOTOR_PULSE_DURATION = 0.1              # Default pulse duration in seconds
MOTOR_FREQUENCY = 500                   # PWM frequency for motor
MOTOR_MIN_THRESHOLD = 0.20              # Minimum motor intensity threshold
MOTOR_MAX_THRESHOLD = 0.85              # Maximum motor intensity threshold

# ------ ACCELEROMETER CALIBRATION SETTINGS ------ #
ACCEL_CALIBRATION_NEUTRAL_TIME = 3      # Seconds to hold neutral position
ACCEL_CALIBRATION_MOVEMENT_TIME = 20    # Seconds for movement detection
ACCEL_CALIBRATION_DISPLAY_UPDATE = 3    # Display update interval during calibration
ACCEL_DOUBLE_TOGGLE_WINDOW = 1.0        # Time window for double-toggle calibration trigger

# Accelerometer adaptive mode settings
ACCEL_MODE_HOLD_DURATION = 1.5          # Time to hold mode before switching
ACCEL_STABLE_MODE_THRESHOLD = 4         # CC change threshold in stable mode  
ACCEL_CHANGING_MODE_THRESHOLD = 1       # CC change threshold in changing mode
ACCEL_STABILITY_BUFFER_SIZE = 3         # Number of readings to check for stability
ACCEL_MAX_STABILITY_VARIATION = 4       # Max variation between readings for stability

# Debug settings
ACCEL_DEBUG_ENABLED = False             # Enable accelerometer debug output (disable for production!)
