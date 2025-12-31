import time
import adafruit_ticks as ticks
from settings import settings
from utils import free_memory

DEBUG_INTERVAL_S = 1.5  # Interval to print debug info (seconds)

class Debug():
    """Debug utility for memory and performance monitoring."""
    def __init__(self):
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
        """Track MIDI events by type. Logs every 20 events."""
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

