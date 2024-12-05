import time
import digitalio
from collections import OrderedDict
from settings import settings
import constants

DEBUG_INTERVAL_S = 1.5  # Interval to print debug info (seconds)

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
        self.DEBUG_MODE = settings.debug


    def check_display_debug(self):
        """
        Display and clear debug information if the interval has passed.
        """
        if not self.DEBUG_MODE:
            return
        
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
        if not title or not data or not self.DEBUG_MODE:
            return

        title = str(title)
        data = str(data)

        if instant:
            print(f"{title} : {data}")
        else:
            self.debug_dict[title] = data
    
    # On 2nd call, it will print the time elapsed since the first call for the same key
    def performance_timer(self, key=""):

        if not self.DEBUG_MODE:
            return
        
        time_now = time.monotonic()

        # Start timer
        if key not in self.debug_timer_dict:
            self.debug_timer_dict[key] = time_now
        
        # End timer
        else:
            elapsed = time_now - self.debug_timer_dict[key]
            self.debug_timer_dict.pop(key, None)  # Remove it for the next use
            ms = round(1000 * elapsed, 1)
            if ms > 25:
                print(f"{key}: {ms} ms !!!!!!!!!!!!!!!!!!!!")
            else:
                print(f"{key}: {ms} ms")

# Create an instance of the Debug class for debugging
debug = Debug()

def print_debug(message, debug_obj=debug):
    """
    Print a debug message if DEBUG_MODE is True.

    Args:
        message (str): Debug message to print.
    """
    if debug_obj.DEBUG_MODE:
        print(f"DEBUG: {message}")
