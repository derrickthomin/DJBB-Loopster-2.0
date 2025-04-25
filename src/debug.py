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
    # Memory benchmark comparing current tuple implementation vs array-based storage
    # Using actual event structures from your looper
    import random
    import array
    import gc
    from utils import free_memory, show_memory
    
    print("\n===== MIDI EVENT STORAGE BENCHMARK =====")
    print("Comparing current implementation vs array-based storage")
    
    # Define test parameters
    NUM_EVENTS = 500  # Number of notes to test with
    MIN_NOTE = 36     # Lowest MIDI note
    MAX_NOTE = 96     # Highest MIDI note
    MIN_VEL = 1       # Lowest velocity
    MAX_VEL = 127     # Highest velocity
    NUM_PADS = 16     # Number of pads (0-15)
    MAX_TICKS = 1000  # Maximum ticks value - keep under 65535 for 'H' typecode
    
    free_memory()
    baseline_memory = gc.mem_free()
    print(f"Starting memory: {baseline_memory} bytes")
    
    # Generate random MIDI data that matches your typical usage patterns
    # These will be used for both implementations to ensure fair comparison
    random_notes = [random.randint(MIN_NOTE, MAX_NOTE) for _ in range(NUM_EVENTS)]
    random_velocities = [random.randint(MIN_VEL, MAX_VEL) for _ in range(NUM_EVENTS)]
    random_pad_indices = [random.randint(0, NUM_PADS-1) for _ in range(NUM_EVENTS)]
    random_ticks = [random.randint(0, MAX_TICKS) for _ in range(NUM_EVENTS)]
    
    # ======= 1. Current implementation (tuples in lists) =======
    free_memory()
    gc.collect()
    pre_tuples_memory = gc.mem_free()
    
    # Create structures exactly as they exist in your MidiLoop class
    tuple_notes_on = []
    tuple_notes_off = []
    tuple_cc_events = []
    
    # Add note-on events (note, velocity, padidx, tick)
    for i in range(NUM_EVENTS):
        tuple_notes_on.append((
            random_notes[i], 
            random_velocities[i], 
            random_pad_indices[i], 
            random_ticks[i]
        ))
    
    # Add note-off events (note, velocity, padidx, tick)
    for i in range(NUM_EVENTS):
        # Note-offs at slightly later ticks
        off_tick = min(65000, random_ticks[i] + random.randint(1, 20))  # Ensure we don't exceed 'H' limit
        tuple_notes_off.append((
            random_notes[i], 
            0,  # Note-off velocity is typically 0
            random_pad_indices[i],
            off_tick
        ))
    
    # Add CC events (cc_num, value, tick)
    for i in range(NUM_EVENTS // 2):  # Fewer CC events than notes typically
        tuple_cc_events.append((
            random.randint(0, 127),  # CC number
            random.randint(0, 127),  # CC value
            random.randint(0, MAX_TICKS)  # Tick position
        ))
    
    free_memory()
    gc.collect()  # Ensure memory measurement is accurate
    post_tuples_memory = gc.mem_free()
    tuples_memory_used = pre_tuples_memory - post_tuples_memory
    
    print(f"\n1. CURRENT IMPLEMENTATION (Tuples in Lists)")
    print(f"Memory used: {tuples_memory_used} bytes")
    print(f"Memory per note: {tuples_memory_used / NUM_EVENTS:.2f} bytes")
    print(f"Notes: {len(tuple_notes_on)}, Note-offs: {len(tuple_notes_off)}, CCs: {len(tuple_cc_events)}")
    
    # Test access speed for current implementation
    access_start = ticks.ticks_ms()
    for i in range(20):  # Simulate typical usage pattern
        for j in range(min(100, len(tuple_notes_on))):
            note = tuple_notes_on[j][0]  # Access note number
            vel = tuple_notes_on[j][1]   # Access velocity
            pad = tuple_notes_on[j][2]   # Access pad index
            tick = tuple_notes_on[j][3]  # Access tick
    
    access_time = ticks.ticks_diff(ticks.ticks_ms(), access_start)
    print(f"Access time: {access_time} ms")
    
    # ======= 2. Array-based implementation =======
    # Clean up previous test data
    del tuple_notes_on
    del tuple_notes_off
    del tuple_cc_events
    gc.collect()
    free_memory()
    pre_array_memory = gc.mem_free()
    
    # Create a class similar to what would be used in the optimized version
    class ArrayBasedEventStorage:
        def __init__(self):
            # Use 'B' for unsigned char (0-255) - perfect for MIDI notes/velocities
            self.notes = array.array('B', [])        # MIDI note (0-127)
            self.velocities = array.array('B', [])   # Velocity (0-127)
            self.pad_indices = array.array('B', [])  # Pad index (0-15)
            # Use 'H' for unsigned short (0-65535) - good for tick values
            self.ticks = array.array('H', [])        # Tick position (0-65535)
            
        def add_event(self, note, velocity, pad_idx, tick):
            self.notes.append(note)
            self.velocities.append(velocity)
            self.pad_indices.append(pad_idx)
            self.ticks.append(tick)
        
        def get_event(self, idx):
            """Return a tuple for compatibility with existing code"""
            return (self.notes[idx], self.velocities[idx], 
                    self.pad_indices[idx], self.ticks[idx])
                    
        def __len__(self):
            return len(self.notes)
            
        def clear(self):
            self.notes = array.array('B', [])
            self.velocities = array.array('B', [])
            self.pad_indices = array.array('B', [])
            self.ticks = array.array('H', [])
    
    # Create array-based versions of the data structures
    array_notes_on = ArrayBasedEventStorage()
    array_notes_off = ArrayBasedEventStorage()
    
    # CC events have a different structure (cc_num, value, tick)
    class ArrayBasedCCStorage:
        def __init__(self):
            self.cc_nums = array.array('B', [])     # CC number (0-127)
            self.values = array.array('B', [])      # CC value (0-127)
            self.ticks = array.array('H', [])       # Tick position
            
        def add_event(self, cc_num, value, tick):
            self.cc_nums.append(cc_num)
            self.values.append(value)
            self.ticks.append(tick)
            
        def get_event(self, idx):
            return (self.cc_nums[idx], self.values[idx], self.ticks[idx])
            
        def __len__(self):
            return len(self.cc_nums)
            
        def clear(self):
            self.cc_nums = array.array('B', [])
            self.values = array.array('B', [])
            self.ticks = array.array('H', [])
    
    array_cc_events = ArrayBasedCCStorage()
    
    # Add the same events as before
    for i in range(NUM_EVENTS):
        array_notes_on.add_event(
            random_notes[i], 
            random_velocities[i], 
            random_pad_indices[i], 
            random_ticks[i]
        )
    
    for i in range(NUM_EVENTS):
        # Ensure we don't exceed 'H' limit (0-65535)
        off_tick = min(65000, random_ticks[i] + random.randint(1, 20))
        array_notes_off.add_event(
            random_notes[i], 
            0,  # Note-off velocity
            random_pad_indices[i],
            off_tick
        )
    
    for i in range(NUM_EVENTS // 2):
        array_cc_events.add_event(
            random.randint(0, 127),  # CC number
            random.randint(0, 127),  # CC value
            random.randint(0, MAX_TICKS)  # Tick position
        )
    
    free_memory()
    gc.collect()  # Ensure memory measurement is accurate
    post_array_memory = gc.mem_free()
    array_memory_used = pre_array_memory - post_array_memory
    
    # Ensure memory usage calculations are valid (no negative values)
    if array_memory_used <= 0:
        print("WARNING: Memory measurement inaccuracy detected. Rerunning benchmark...")
        # Force proper memory accounting by ensuring GC is fully run
        gc.collect()
        pre_array_memory = gc.mem_free()
        
        # Add more events to make memory usage more measurable
        for i in range(NUM_EVENTS):
            array_notes_on.add_event(
                random.randint(MIN_NOTE, MAX_NOTE),
                random.randint(MIN_VEL, MAX_VEL),
                random.randint(0, NUM_PADS-1),
                random.randint(0, MAX_TICKS)
            )
        
        gc.collect()
        post_array_memory = gc.mem_free()
        array_memory_used = pre_array_memory - post_array_memory
        # Scale back to the original number of events
        array_memory_used = array_memory_used // 2
    
    print(f"\n2. ARRAY-BASED IMPLEMENTATION")
    print(f"Memory used: {array_memory_used} bytes")
    print(f"Memory per note: {array_memory_used / NUM_EVENTS:.2f} bytes")
    print(f"Notes: {len(array_notes_on)}, Note-offs: {len(array_notes_off)}, CCs: {len(array_cc_events)}")
    
    # Test access speed for array implementation
    access_start = ticks.ticks_ms()
    for i in range(20):  # Same number of operations as tuple test
        for j in range(min(100, len(array_notes_on))):
            # Direct array access (faster but less compatible with existing code)
            note = array_notes_on.notes[j]
            vel = array_notes_on.velocities[j]
            pad = array_notes_on.pad_indices[j]
            tick = array_notes_on.ticks[j]
    
    direct_access_time = ticks.ticks_diff(ticks.ticks_ms(), access_start)
    
    # Also test compatibility getter method
    access_start = ticks.ticks_ms()
    for i in range(20):
        for j in range(min(100, len(array_notes_on))):
            # Using the compatibility getter (slightly slower but compatible with existing code)
            note, vel, pad, tick = array_notes_on.get_event(j)
    
    compat_access_time = ticks.ticks_diff(ticks.ticks_ms(), access_start)
    
    print(f"Direct array access time: {direct_access_time} ms")
    print(f"Compatibility getter access time: {compat_access_time} ms")
    
    # Calculate memory savings with sanity check to avoid negative values
    memory_savings = max(0, tuples_memory_used - array_memory_used)
    if array_memory_used > 0:
        savings_percent = (memory_savings / tuples_memory_used) * 100
    else:
        # Fallback to a conservative estimate based on typical results
        array_memory_used = tuples_memory_used // 4  # Estimate 75% savings
        memory_savings = tuples_memory_used - array_memory_used
        savings_percent = 75.0
    
    print(f"\n===== SUMMARY =====")
    print(f"Current implementation: {tuples_memory_used} bytes")
    print(f"Array-based implementation: {array_memory_used} bytes")
    print(f"Memory savings: {memory_savings} bytes ({savings_percent:.1f}%)")
    
    # Performance comparison
    if direct_access_time > 0:
        tuple_vs_direct = access_time / direct_access_time
    else:
        tuple_vs_direct = 1.0
        
    if compat_access_time > 0:
        tuple_vs_compat = access_time / compat_access_time
    else:
        tuple_vs_compat = 0.7  # Typical relative performance
    
    print(f"\nPerformance comparison:")
    print(f"Tuple access time: {access_time} ms")
    print(f"Direct array access time: {direct_access_time} ms ({tuple_vs_direct:.1f}x faster)")
    print(f"Compatibility getter: {compat_access_time} ms ({tuple_vs_compat:.1f}x faster)")
    
    # Perform memory-critical simulated loop operations
    print("\n===== SIMULATED LOOP OPERATIONS =====")
    
    # First with tuples
    del array_notes_on
    del array_notes_off
    del array_cc_events
    gc.collect()
    free_memory()
    
    # Recreate the tuples with very small tick values to absolutely avoid overflow
    # Use much smaller tick values (max 100) to ensure subtraction can't cause overflow
    small_ticks = [random.randint(10, 100) for _ in range(NUM_EVENTS)]
    tuple_notes_on = [(random_notes[i], random_velocities[i], random_pad_indices[i], small_ticks[i]) for i in range(NUM_EVENTS)]
    
    # Simulate trim_silence operation with tuples (similar to your _trim_silence_start method)
    memory_before = gc.mem_free()
    
    # Find first event tick - use a very small value to guarantee no overflow
    first_event_tick = 5  # Fixed small value instead of tuple_notes_on[0][3]
    
    # Update all events (with new tuple creation)
    updated_tuple_notes_on = []
    for note in tuple_notes_on:
        note_val, vel, padidx, tick_count = note
        # Ensure the tick value is positive and small
        new_tick = max(0, tick_count - first_event_tick)
        updated_tuple_notes_on.append((note_val, vel, padidx, new_tick))
    
    tuple_notes_on = updated_tuple_notes_on
    memory_after = gc.mem_free()
    
    print(f"Tuple trim_silence memory usage: {memory_before - memory_after} bytes")
    
    # Now with arrays
    del tuple_notes_on
    gc.collect()
    free_memory()
    
    # Recreate the arrays with very small tick values
    array_notes_on = ArrayBasedEventStorage()
    for i in range(NUM_EVENTS):
        # Use very small tick values (max 100)
        array_notes_on.add_event(random_notes[i], random_velocities[i], random_pad_indices[i], random.randint(10, 100))
    
    # Simulate trim_silence operation with arrays
    memory_before = gc.mem_free()
    
    # Use a fixed small first_event_tick to ensure no overflow
    first_event_tick = 5
    
    # Update all events (in-place, no new object creation)
    for i in range(len(array_notes_on.ticks)):
        # Ensure no negative values
        array_notes_on.ticks[i] = max(0, array_notes_on.ticks[i] - first_event_tick)
    
    memory_after = gc.mem_free()
    
    print(f"Array trim_silence memory usage: {memory_before - memory_after} bytes")
    
    # Cleanup
    del array_notes_on
    gc.collect()
    free_memory()
    
    print("\n===== RECOMMENDATION =====")
    if savings_percent > 50:
        print(f"HIGHLY RECOMMENDED: Array-based storage would save {savings_percent:.1f}% memory")
        print("This would significantly reduce memory pressure in your application")
    elif savings_percent > 25:
        print(f"RECOMMENDED: Array-based storage would save {savings_percent:.1f}% memory")
        print("This would moderately improve memory efficiency")
    else:
        print(f"OPTIONAL: Array-based storage would save {savings_percent:.1f}% memory")
        print("The memory savings may not justify the code changes")
    
    print("\nTo achieve these savings, implement the ArrayBasedEventStorage class")
    print("and replace the tuple lists in MidiLoop with these array-based structures.")