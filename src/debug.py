import time
import adafruit_ticks as ticks
import digitalio
import array
from settings import settings
from utils import free_memory

DEBUG_INTERVAL_S = 1.5  # Interval to print debug info (seconds)

class Debug():
    """
    Memory-optimized debugging utility.
    """
    def __init__(self):
        """Initialize with minimal memory usage"""
        self.debug_timer = time.monotonic()
        # Use a simple list instead of OrderedDict to reduce memory usage
        self.debug_list = []  # List of (key, value) tuples
        self.debug_timer_dict = {} if settings.debug else None  # Only allocate if debug is on
        self.DEBUG_MODE = settings.debug
        # Separate counters for different MIDI event types
        self.total_midi_events = 0
        self.note_on_events = 0
        self.note_off_events = 0

    def display_info(self):
        """Display debug info with minimal formatting"""
        if not self.DEBUG_MODE or not self.debug_list:
            return
        
        if time.monotonic() - self.debug_timer > DEBUG_INTERVAL_S:
            print("\nDebug")
            print("-----")
            for key, item in self.debug_list:
                print(f"{key}: {item}")
            
            # Clear the list but maintain the same object to avoid allocation
            self.debug_list.clear()
            self.debug_timer = time.monotonic()

    def add_debug_line(self, title, data, instant=False):
        """Add debug line with minimal memory usage"""
        if not self.DEBUG_MODE:
            return

        if instant:
            print(f"{title} : {data}")
        else:
            # Find if the key already exists to update instead of adding
            for i, (key, _) in enumerate(self.debug_list):
                if key == title:
                    self.debug_list[i] = (title, data)
                    return
            # Key doesn't exist, add new entry
            self.debug_list.append((title, data))

    def increment_midi_event_counter(self, event_type="unknown"):
        """Increment the global MIDI event counter and log the total
        
        Args:
            event_type (str): Type of event - "note_on", "note_off", "cc", etc.
        """
        self.total_midi_events += 1
        
        # Track specific event types
        if event_type == "note_on":
            self.note_on_events += 1
        elif event_type == "note_off":
            self.note_off_events += 1
            
        # Log every 20 events to reduce console spam but still be useful
        if self.total_midi_events % 20 == 0:
            self.add_debug_line("Total MIDI Events", self.total_midi_events)
            self.add_debug_line("Note On Events", self.note_on_events)
            self.add_debug_line("Note Off Events", self.note_off_events)
            print(f"MIDI Events - Total: {self.total_midi_events}, On: {self.note_on_events}, Off: {self.note_off_events}")


# Create a single instance to avoid multiple allocations
debug = Debug()

# Simplified decorator to reduce memory usage
def time_function(func=None, func_name=None):
    """Minimal decorator for timing functions"""
    if not debug.DEBUG_MODE:
        # If debug mode is off, return the original function without wrapping
        if func is None:
            return lambda f: f  # Return identity decorator
        return func
        
    if func is None:
        def wrapper_with_key(f):
            return time_function(f, func_name=func_name)
        return wrapper_with_key

    def wrapper(*args, **kwargs):
        start_time = time.monotonic()
        result = func(*args, **kwargs)
        elapsed_time = time.monotonic() - start_time
        
        # Use function name if not specified
        name = func_name or func.__name__
        
        # Simple timing output without storing history
        if elapsed_time > 0.01:  # Only report if more than 10ms
            print(f"PERF: {name}: {elapsed_time*1000:.1f} ms")
            
        return result

    return wrapper

# Global variables for memcheck function
_memcheck_enabled = False
_memcheck_last_time = 0

def memcheck():
    """
    Memory monitoring function that prints current memory usage every 1 second.
    Call this function repeatedly in your main loop to enable continuous monitoring.
    Uses global variables for efficient timing and state management.
    """
    global _memcheck_enabled, _memcheck_last_time
    
    # Enable memcheck on first call
    if not _memcheck_enabled:
        _memcheck_enabled = True
        _memcheck_last_time = time.monotonic()
        print("MEMCHECK: Memory monitoring enabled")
        return
    
    # Check if 1 second has elapsed
    current_time = time.monotonic()
    if current_time - _memcheck_last_time >= 1.0:
        try:
            import gc
            
            # Collect garbage before checking memory
            gc.collect()
            
            # Get memory stats
            free_mem = gc.mem_free()
            alloc_mem = gc.mem_alloc()
            total_mem = free_mem + alloc_mem
            usage_percent = (alloc_mem / total_mem) * 100 if total_mem > 0 else 0
            
            # Print only the percentage with visual separators
            print(f"--------- MEM: {usage_percent:.1f}% ---------")
            
        except ImportError:
            # Fallback if gc module not available
            print("--------- MEM: gc module not available ---------")
        except Exception as e:
            print(f"--------- MEM: Error getting memory info: {e} ---------")
        
        # Update timer
        _memcheck_last_time = current_time

def memcheck_stop():
    """Stop memory monitoring"""
    global _memcheck_enabled
    _memcheck_enabled = False
    print("MEMCHECK: Memory monitoring disabled")

def print_debug(message, debug_obj=debug):
    """Print debug message with minimal formatting"""
    if debug_obj.DEBUG_MODE:
        print(f"D: {message}")