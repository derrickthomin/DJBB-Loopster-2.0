import time
import adafruit_ticks as ticks
import digitalio
from collections import OrderedDict
from settings import settings
import constants
from utils import free_memory
DEBUG_INTERVAL_S = 1.5  # Interval to print debug info (seconds)
# In debug.py

# In debug.py

class PerformanceTimer:
    """
    Memory-efficient performance timer for constrained environments.

    This implementation avoids dynamic memory allocation by using preallocated
    fixed-size arrays for storing labels and statistics. All statistics reset
    after each printout.
    """

    def __init__(self, max_labels=10):
        """
        Initialize the performance timer with a fixed number of labels.

        :param max_labels: Maximum number of unique sections (labels) to track.
        """
        self.max_labels = max_labels
        
        # Preallocate fixed-size structures
        self.labels = [None] * max_labels  # Label names
        self.start_times = [0] * max_labels  # Start times for active labels
        self.total_times = [0] * max_labels  # Accumulated total times
        self.call_counts = [0] * max_labels  # Number of calls for each label
        self.max_times = [0] * max_labels   # Maximum elapsed time for each label
        self.min_times = [float("inf")] * max_labels  # Minimum elapsed time for each label
        
        self._last_print_time = ticks.ticks_ms()  # Last time the statistics were printed

    def _get_label_index(self, label):
        """
        Find the index of the given label or allocate a new one.

        :param label: The name of the section/label.
        :return: Index of the label in preallocated arrays.
        :raises MemoryError: If the maximum number of labels is exceeded.
        """
        # Check if the label already exists
        for i in range(self.max_labels):
            if self.labels[i] == label:
                return i
        
        # Find the first free slot to allocate this label
        for i in range(self.max_labels):
            if self.labels[i] is None:
                self.labels[i] = label
                return i
        
        # If we reach here, we've exceeded the maximum number of labels
        raise MemoryError("Exceeded the maximum number of performance timer labels")

    def start(self, label):
        """
        Start timing the section identified by 'label'.
        """
        try:
            index = self._get_label_index(label)
            self.start_times[index] = ticks.ticks_ms()
        except MemoryError as e:
            print(f"[PerformanceTimer] {e}")

    def stop(self, label):
        """
        Stop timing the section identified by 'label' and update statistics.
        """
        try:
            index = self._get_label_index(label)
            start_time = self.start_times[index]
            if start_time == 0:
                print(f"[PerformanceTimer] Warning: stop() called for label '{label}' without matching start()")
                return

            # Calculate elapsed time
            end_time = ticks.ticks_ms()
            elapsed = ticks.ticks_diff(end_time, start_time)
            self.start_times[index] = 0  # Reset the start time

            # Update statistics for the label
            self.total_times[index] += elapsed
            self.call_counts[index] += 1
            self.max_times[index] = max(self.max_times[index], elapsed)
            self.min_times[index] = min(self.min_times[index], elapsed)

        except MemoryError as e:
            print(f"[PerformanceTimer] {e}")

    def print_data(self):
        """
        Print the accumulated performance data for all tracked sections.
        Resets all statistics after printing.
        """
        header = f"{'Section':<35} {'Calls':>10} {'Total (ms)':>12} {'Avg (ms)':>12} {'Max (ms)':>12} {'Min (ms)':>12}"
        separator = "-" * len(header)
        print("\n=== Performance Timer Data ===")
        print(header)
        print(separator)

        for i in range(self.max_labels):
            if self.labels[i] is not None and self.call_counts[i] > 0:
                # Calculate and display statistics for each label
                total = self.total_times[i]
                count = self.call_counts[i]
                avg = total / count if count > 0 else 0
                max_time = self.max_times[i]
                min_time = self.min_times[i] if self.min_times[i] != float("inf") else 0
                print(f"{self.labels[i]:<35} {count:>10} {total:>12} {avg:>12.2f} {max_time:>12} {min_time:>12}")

        print(separator)

        # Reset all statistics after printing
        self._reset_statistics()

    def _reset_statistics(self):
        """
        Reset all recorded statistics for the timer.
        This clears totals, counts, and min/max times while keeping labels intact.
        """
        for i in range(self.max_labels):
            self.start_times[i] = 0
            self.total_times[i] = 0
            self.call_counts[i] = 0
            self.max_times[i] = 0
            self.min_times[i] = float("inf")

    def update(self):
        """
        Print performance statistics at regular intervals (default: every second).
        Automatically resets statistics after each printout.
        """
        now = ticks.ticks_ms()
        if ticks.ticks_diff(now, self._last_print_time) >= 1000:
            self.print_data()
            self._last_print_time = now
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


    def display_info(self):
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
    
    #On 2nd call, it will print the time elapsed since the first call for the same key
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
            elif ms > 10:
                print(f"{key}: {ms} ms")

# Create an instance of the Debug class for debugging
debug = Debug()
performance_timer = PerformanceTimer()

# Wrapper function to be used as a decorator for performance timers.
def time_function(func=None, func_name=None):
    """
    Decorator to measure the performance of a function.

    Args:
        func (function, optional): The function to decorate.
        key (str, optional): The key to use for the performance data.

    Returns:
        function: The decorated function.
    """



    if func is None:
        def wrapper_with_key(f):
            return time_function(f, func_name=func_name)
        return wrapper_with_key

    def wrapper(*args, **kwargs):
        if func_name not in debug.debug_timer_dict:
            debug.debug_timer_dict[func_name] = {
                "times": [],
                "max_time": 0,
                "call_count": 0
            }

        start_time = time.monotonic()
        result = func(*args, **kwargs)
        end_time = time.monotonic()
        elapsed_time = end_time - start_time

        # Update the times list, max time, and call count
        debug.debug_timer_dict[func_name]["times"].append(elapsed_time)
        if len(debug.debug_timer_dict[func_name]["times"]) > 100:
            debug.debug_timer_dict[func_name]["times"].pop(0)
        if elapsed_time > debug.debug_timer_dict[func_name]["max_time"]:
            debug.debug_timer_dict[func_name]["max_time"] = elapsed_time
        debug.debug_timer_dict[func_name]["call_count"] += 1

        return result

    return wrapper

def print_performance_data():
    """
    Print the performance data for each function.
    """
    if time.monotonic() - debug.debug_timer > DEBUG_INTERVAL_S:
        print("\nPerformance Data".center(50))
        print("_________".center(50))
        for func_name, data in debug.debug_timer_dict.items():
            avg_time_ms = (sum(data["times"]) / len(data["times"]) * 1000) if data["times"] else 0
            max_time_ms = data["max_time"] * 1000
            call_count = data["call_count"]
            if call_count > 0 and max_time_ms > 2:
                print(f"{func_name:<30}: Avg Time: {avg_time_ms:>8.2f} ms, Max Time: {max_time_ms:>8.2f} ms, Calls: {call_count:>5}")
            # Reset data after printing
            debug.debug_timer_dict[func_name] = {
                "times": [],
                "max_time": 0,
                "call_count": 0
            }
        debug.debug_timer = time.monotonic()
        free_memory()

def print_debug(message, debug_obj=debug):
    """
    Print a debug message if DEBUG_MODE is True.

    Args:
        message (str): Debug message to print.
    """
    if debug_obj.DEBUG_MODE:
        print(f"DEBUG: {message}")
