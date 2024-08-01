import time
import board
import digitalio
from collections import OrderedDict
from settings import settings
import constants

DEBUG_INTERVAL_S = 1.5  # Interval to print debug info (seconds)


encoder_button = digitalio.DigitalInOut(constants.ENCODER_BTN)
encoder_button.direction = digitalio.Direction.INPUT
encoder_button.pull = digitalio.Pull.UP

if not encoder_button.value:  # Check if encoder button is pressed for debug mode
    DEBUG_MODE = True
    print("***** DEBUG MODE ENABLED *****")
else:
    DEBUG_MODE = settings.DEBUG

encoder_button.deinit()  # Deinitialize encoder button

# # Used in other modules to calculate timing between blocks of code
# def debug_timer(msg = "debug timer: ",start_or_end = True):
#     """
#     Debug timing utility to calculate time between blocks of code.

#     Args:
#         start_or_end (bool, optional): If True, start the timer. If False, end the timer. Defaults to True.

#     Returns:
#         float: Time elapsed in seconds.
#     """
#     global debug_timer_prev

#     if not DEBUG_MODE:
#         return
    
#     if start_or_end:
#         debug_timer_prev = time.monotonic()
#     else:
#         elapsed = time.monotonic() - debug_timer_prev
#         print(f"{msg} {1000 * elapsed:.4f} ms")


def print_debug(message):
    """
    Print a debug message if DEBUG_MODE is True.

    Args:
        message (str): Debug message to print.
    """
    if DEBUG_MODE:
        print(f"DEBUG: {message}")

class Debug():
    """
    Debugging utility for displaying and managing debug information.

    Attributes:
        debug_header (str): Header text for the debug information.
        debug_dict (OrderedDict): Ordered dictionary to store debug data.
        debug_timer (float): Timer for managing debug printing intervals.
    """

    def __init__(self):
        """
        Initialize the Debug class.
        """
        self.debug_header = "Debug".center(50)
        self.debug_dict = OrderedDict()  # Stores everything to print
        self.debug_timer = time.monotonic()
        self.debug_timer_dict = {}

    def check_display_debug(self):
        """
        Display and clear debug information if the interval has passed.
        """
        if time.monotonic() - self.debug_timer > DEBUG_INTERVAL_S:
            # Bail if nothing to display
            if not self.debug_dict:
                return

            print("")
            print(self.debug_header)
            print("_________".center(50))
            for key, item in self.debug_dict.items():
                print(f"{key}:  {item}")
            self.debug_dict = {}
            self.debug_timer = time.monotonic()

    def add_debug_line(self, title, data, instant=False):
        """
        Add a debug line with a title and data.

        Args:
            title (str): Title for the debug data.
            data (str): Debug data to display.
            instant (bool, optional): If True, instantly print the debug line. Defaults to False.
        """
        if not title or not data or not DEBUG_MODE:
            return

        title = str(title)
        data = str(data)

        if instant:
            print(f"{title} : {data}")
        else:
            self.debug_dict[title] = data
    
    # On 2nd call, it will print the time elapsed since the first call for the same key
    def performance_timer(self, key=""):

        time_now = time.monotonic()

        # Start timer
        if key not in self.debug_timer_dict:
            self.debug_timer_dict[key] = time_now
        
        # End timer
        else:
            elapsed = time_now - self.debug_timer_dict[key]
            self.debug_timer_dict.pop(key, None)  # Remove it for the next use
            ms = round(1000 * elapsed, 1)
            print(f"{key}: {ms} ms")

# Create an instance of the Debug class for debugging
debug = Debug()
