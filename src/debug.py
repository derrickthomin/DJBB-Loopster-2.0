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
        # Global counter for tracking total MIDI events across all loops
        self.total_midi_events = 0

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

    def increment_midi_event_counter(self):
        """Increment the global MIDI event counter and log the total"""
        self.total_midi_events += 1
        if self.total_midi_events % 10 == 0:  # Log every 10 events to reduce console spam
            self.add_debug_line("Total MIDI Events", self.total_midi_events)
            print(f"Total MIDI Events across all loops: {self.total_midi_events}")


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

def print_debug(message, debug_obj=debug):
    """Print debug message with minimal formatting"""
    if debug_obj.DEBUG_MODE:
        print(f"D: {message}")

if __name__ == "__main__":
    # Performance test - storing 1000 ints vs floats vs array.array
    import random
    from utils import free_memory, show_memory

    print("Performance Test", "Starting...")
    free_memory()
    show_memory()
    
    # Test with standard Python lists
    integers = [random.randint(0, 1000000) for _ in range(1000)]
    print("INT LIST")
    show_memory()
    free_memory()
    
    floats = [random.uniform(0.0, 1000000.0) for _ in range(1000)]
    print("FLOAT LIST")
    show_memory()
    free_memory()
    
    # Test with array.array - more memory efficient for numeric data
    # 'f' is the typecode for float
    float_array = array.array('f', [random.uniform(0.0, 1000000.0) for _ in range(1000)])
    print("FLOAT ARRAY")
    show_memory()
    free_memory()
    
    # Test with integer array
    # 'i' is the typecode for signed int
    int_array = array.array('i', [random.randint(0, 1000000) for _ in range(1000)])
    print("INT ARRAY")
    show_memory()
    
    # Clean up to free memory
    del integers
    del floats
    del float_array
    del int_array
    free_memory()
    print("After cleanup")
    show_memory()
    
    # Memory usage test - comparing different data structures for storing note timing data
    import gc
    
    # Test parameters
    NUM_NOTES = 500  # Typical number of notes in a loop
    
    print("==== MEMORY USAGE TEST FOR NOTE TIMING DATA STRUCTURES ====")
    free_memory()
    show_memory("Starting memory")
    
    # Baseline - nothing allocated yet
    gc.collect()
    baseline = gc.mem_free()
    
    # 1. Regular Python lists of tuples (current implementation)
    # Format: (note, velocity, time, padidx, ticks)
    notes_on_list = []
    notes_off_list = []
    for i in range(NUM_NOTES):
        # Simulate typical note values
        note = random.randint(36, 96)  # MIDI note range
        velocity = random.randint(1, 127)  # MIDI velocity
        time_s = random.uniform(0, 60.0)  # Time in seconds (0-60 second loop)
        padidx = random.randint(0, 15)  # Pad index
        ticks = int(time_s * 24)  # Convert to MIDI ticks (24 per quarter note)
        
        notes_on_list.append((note, velocity, time_s, padidx, ticks))
        # Note off happens a bit later
        notes_off_list.append((note, 0, time_s + random.uniform(0.1, 1.0), padidx, ticks + random.randint(1, 24)))
    
    gc.collect()
    list_tuples_mem = baseline - gc.mem_free()
    print(f"1. Lists of tuples ({NUM_NOTES} notes): {list_tuples_mem} bytes ({list_tuples_mem/NUM_NOTES:.2f} bytes/note)")
    show_memory()
    
    # Clear previous data
    del notes_on_list
    del notes_off_list
    gc.collect()
    
    # 2. Lists of smaller tuples with minimal data (int-only)
    # Format: (note, time_ms) - storing time in milliseconds as integer
    notes_on_minimal = []
    notes_off_minimal = []
    for i in range(NUM_NOTES):
        note = random.randint(36, 96)
        time_ms = int(random.uniform(0, 60.0) * 1000)  # Time in milliseconds
        
        notes_on_minimal.append((note, time_ms))
        notes_off_minimal.append((note, time_ms + random.randint(100, 1000)))
    
    gc.collect()
    minimal_tuples_mem = baseline - gc.mem_free()
    print(f"2. Lists of minimal tuples ({NUM_NOTES} notes): {minimal_tuples_mem} bytes ({minimal_tuples_mem/NUM_NOTES:.2f} bytes/note)")
    show_memory()
    
    # Clear previous data
    del notes_on_minimal
    del notes_off_minimal
    gc.collect()
    
    # 3. Separate arrays for each attribute (columnar storage)
    notes = array.array('B', [random.randint(36, 96) for _ in range(NUM_NOTES)])  # 'B' for unsigned char (0-255)
    velocities = array.array('B', [random.randint(1, 127) for _ in range(NUM_NOTES)])
    times_ms = array.array('I', [int(random.uniform(0, 60.0) * 1000) for _ in range(NUM_NOTES)])  # 'I' for unsigned int
    pad_indices = array.array('B', [random.randint(0, 15) for _ in range(NUM_NOTES)])
    
    gc.collect()
    columnar_mem = baseline - gc.mem_free()
    print(f"3. Separate arrays (columnar storage) ({NUM_NOTES} notes): {columnar_mem} bytes ({columnar_mem/NUM_NOTES:.2f} bytes/note)")
    show_memory()
    
    # Clear previous data
    del notes
    del velocities
    del times_ms
    del pad_indices
    gc.collect()
    
    # 4. Byte-packed tuples with bit manipulation
    # Pack note (7 bits), velocity (7 bits), pad (4 bits) into 3 bytes
    # Time stored separately in ms
    packed_data = []
    packed_times = []
    
    for i in range(NUM_NOTES):
        note = random.randint(36, 96) & 0x7F  # 7 bits
        velocity = random.randint(1, 127) & 0x7F  # 7 bits
        padidx = random.randint(0, 15) & 0x0F  # 4 bits
        time_ms = int(random.uniform(0, 60.0) * 1000)
        
        # Pack data: First byte is note, second is velocity, third has pad in lower 4 bits
        byte1 = note
        byte2 = velocity
        byte3 = padidx
        
        packed_data.append((byte1, byte2, byte3))
        packed_times.append(time_ms)
    
    gc.collect()
    packed_mem = baseline - gc.mem_free()
    print(f"4. Byte-packed tuples ({NUM_NOTES} notes): {packed_mem} bytes ({packed_mem/NUM_NOTES:.2f} bytes/note)")
    show_memory()
    
    # Clear previous data
    del packed_data
    del packed_times
    gc.collect()
    
    # 5. Class with __slots__ (memory optimized objects)
    class NoteEventSlots:
        __slots__ = ('note', 'time_ms')
        
        def __init__(self, note, time_ms):
            self.note = note
            self.time_ms = time_ms
    
    notes_on_slots = [NoteEventSlots(random.randint(36, 96), int(random.uniform(0, 60.0) * 1000)) for _ in range(NUM_NOTES)]
    notes_off_slots = [NoteEventSlots(random.randint(36, 96), int(random.uniform(0, 60.0) * 1000)) for _ in range(NUM_NOTES)]
    
    gc.collect()
    slots_mem = baseline - gc.mem_free()
    print(f"5. Class with __slots__ ({NUM_NOTES} notes): {slots_mem} bytes ({slots_mem/NUM_NOTES:.2f} bytes/note)")
    show_memory()
    
    # Clear previous data
    del notes_on_slots
    del notes_off_slots
    gc.collect()
    
    # 6. Using bytearray for compact storage (most complex but potentially most efficient)
    # Each note event is 7 bytes: 1 byte note, 1 byte velocity, 1 byte padidx, 4 bytes time (ms)
    bytes_per_event = 7
    note_events_bytearray = bytearray(NUM_NOTES * bytes_per_event)
    
    for i in range(NUM_NOTES):
        offset = i * bytes_per_event
        note = random.randint(36, 96)
        velocity = random.randint(1, 127)
        padidx = random.randint(0, 15)
        time_ms = int(random.uniform(0, 60.0) * 1000)
        
        note_events_bytearray[offset] = note
        note_events_bytearray[offset + 1] = velocity
        note_events_bytearray[offset + 2] = padidx
        
        # Store time_ms as 4 bytes (little-endian)
        note_events_bytearray[offset + 3] = time_ms & 0xFF
        note_events_bytearray[offset + 4] = (time_ms >> 8) & 0xFF
        note_events_bytearray[offset + 5] = (time_ms >> 16) & 0xFF
        note_events_bytearray[offset + 6] = (time_ms >> 24) & 0xFF
    
    gc.collect()
    bytearray_mem = baseline - gc.mem_free()
    print(f"6. Bytearray ({NUM_NOTES} notes): {bytearray_mem} bytes ({bytearray_mem/NUM_NOTES:.2f} bytes/note)")
    show_memory()
    
    # Clean up
    del note_events_bytearray
    gc.collect()
    
    # Summary
    print("\n==== SUMMARY ====")
    print("Data structure efficiency (bytes per note, lower is better):")
    results = [
        ("Lists of tuples", list_tuples_mem / NUM_NOTES),
        ("Lists of minimal tuples", minimal_tuples_mem / NUM_NOTES),
        ("Separate arrays", columnar_mem / NUM_NOTES),
        ("Byte-packed tuples", packed_mem / NUM_NOTES),
        ("Class with __slots__", slots_mem / NUM_NOTES),
        ("Bytearray", bytearray_mem / NUM_NOTES)
    ]
    
    # Sort by memory efficiency
    results.sort(key=lambda x: x[1])
    
    for idx, (name, bytes_per_note) in enumerate(results):
        print(f"{idx+1}. {name}: {bytes_per_note:.2f} bytes per note")
    
    print("\nMemory after cleanup:")
    gc.collect()
    show_memory()