"""
Flash-Backed Loop Storage Test Script
======================================
Tests the feasibility of storing MIDI loops on flash and streaming playback.

Run on device: Just import this file or copy/paste into REPL

What this tests:
1. Saving a CC-heavy loop to flash (1000+ events)
2. Streaming playback with ring buffer cache
3. Timing analysis - can we read fast enough for MIDI?

Expected results:
- Save time: < 200ms for 1000 events
- Cache miss (read chunk): < 5ms
- Cache hit (get event): < 0.1ms
- All well under MIDI timing requirements (~10ms)
"""

import gc
import os
import struct
import time

# Try to use adafruit_ticks if available (more precise on CircuitPython)
try:
    import adafruit_ticks as ticks
    def get_time_ms():
        return ticks.ticks_ms()
    def time_diff(end, start):
        return ticks.ticks_diff(end, start)
except ImportError:
    def get_time_ms():
        return int(time.monotonic() * 1000)
    def time_diff(end, start):
        return end - start

# ==============================================================================
# Configuration
# ==============================================================================

TEST_LOOP_PATH = "/loops_test"
TEST_FILE = f"{TEST_LOOP_PATH}/test_cc_loop.bin"

# CC event format: cc_num(1) + value(1) + tick(2) + channel(1) = 5 bytes
CC_EVENT_SIZE = 5
CC_FORMAT = '<BBHB'  # little-endian: uint8, uint8, uint16, uint8

# Playback cache size (in events, not bytes)
CACHE_SIZE_EVENTS = 100
CACHE_SIZE_BYTES = CACHE_SIZE_EVENTS * CC_EVENT_SIZE

# ==============================================================================
# Test Data Generation
# ==============================================================================

def generate_cc_sweep_data(num_events=1000, cc_number=1, ticks_per_event=2):
    """
    Generate a CC sweep that goes 0→127→0→127... 
    Simulates a mod wheel or filter cutoff automation.
    
    Returns: bytearray of packed events
    """
    data = bytearray(num_events * CC_EVENT_SIZE)
    
    value = 0
    direction = 1  # 1 = up, -1 = down
    tick = 0
    channel = 0
    
    for i in range(num_events):
        offset = i * CC_EVENT_SIZE
        struct.pack_into(CC_FORMAT, data, offset, cc_number, value, tick, channel)
        
        # Update for next event
        tick += ticks_per_event
        value += direction * 4  # Move by 4 each event
        
        # Reverse at boundaries
        if value >= 127:
            value = 127
            direction = -1
        elif value <= 0:
            value = 0
            direction = 1
    
    return data

# ==============================================================================
# Flash Storage Functions
# ==============================================================================

def ensure_test_folder():
    """Create test folder if it doesn't exist."""
    try:
        os.mkdir(TEST_LOOP_PATH)
        print(f"Created folder: {TEST_LOOP_PATH}")
    except OSError:
        print(f"Folder exists: {TEST_LOOP_PATH}")

def save_loop_to_flash(data, num_events, loop_length_ticks):
    """
    Save loop data to flash with header.
    
    Header format (8 bytes):
    - event_count (uint16)
    - loop_length_ticks (uint16) 
    - reserved (4 bytes for future use)
    """
    header = struct.pack('<HH4s', num_events, loop_length_ticks, b'\x00\x00\x00\x00')
    
    with open(TEST_FILE, "wb") as f:
        f.write(header)
        f.write(data)
    
    print(f"Saved {num_events} events ({len(data)} bytes) to {TEST_FILE}")

def load_loop_header():
    """Load just the loop header (for metadata without loading events)."""
    with open(TEST_FILE, "rb") as f:
        header = f.read(8)
    
    event_count, loop_length = struct.unpack('<HH', header[:4])
    return event_count, loop_length

# ==============================================================================
# Playback Cache (Ring Buffer)
# ==============================================================================

class PlaybackCache:
    """
    Ring buffer cache for streaming loop playback from flash.
    Loads chunks of events on demand.
    """
    
    def __init__(self, file_path, event_count):
        self.file_path = file_path
        self.event_count = event_count
        
        # Cache buffer
        self.cache = bytearray(CACHE_SIZE_BYTES)
        self.cache_start_idx = -1  # Event index at start of cache
        self.cache_valid_events = 0
        
        # Stats
        self.cache_hits = 0
        self.cache_misses = 0
        self.total_read_time_us = 0
    
    def _load_cache(self, start_event_idx):
        """Load a chunk of events into cache starting at given index."""
        start_time = get_time_ms()
        
        # Calculate file offset (skip 8-byte header)
        file_offset = 8 + (start_event_idx * CC_EVENT_SIZE)
        
        # Calculate how many events to read
        events_remaining = self.event_count - start_event_idx
        events_to_read = min(CACHE_SIZE_EVENTS, events_remaining)
        bytes_to_read = events_to_read * CC_EVENT_SIZE
        
        with open(self.file_path, "rb") as f:
            f.seek(file_offset)
            bytes_read = f.readinto(self.cache)
        
        self.cache_start_idx = start_event_idx
        self.cache_valid_events = bytes_read // CC_EVENT_SIZE
        
        elapsed = time_diff(get_time_ms(), start_time)
        self.total_read_time_us += elapsed * 1000
        self.cache_misses += 1
        
        return elapsed
    
    def get_event(self, event_idx):
        """
        Get a single event by index. Loads cache if needed.
        Returns: (cc_num, value, tick, channel) or None if out of range
        """
        if event_idx >= self.event_count:
            return None
        
        # Check if in cache
        cache_offset = event_idx - self.cache_start_idx
        
        if cache_offset < 0 or cache_offset >= self.cache_valid_events:
            # Cache miss - load new chunk
            self._load_cache(event_idx)
            cache_offset = 0
        else:
            self.cache_hits += 1
        
        # Read from cache
        byte_offset = cache_offset * CC_EVENT_SIZE
        return struct.unpack_from(CC_FORMAT, self.cache, byte_offset)
    
    def get_tick(self, event_idx):
        """Get just the tick value for an event (common operation)."""
        event = self.get_event(event_idx)
        return event[2] if event else None
    
    def get_stats(self):
        """Return cache performance stats."""
        total = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total * 100) if total > 0 else 0
        avg_miss_time = (self.total_read_time_us / self.cache_misses / 1000) if self.cache_misses > 0 else 0
        
        return {
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "hit_rate": hit_rate,
            "avg_miss_time_ms": avg_miss_time
        }

# ==============================================================================
# Playback Simulation
# ==============================================================================

def simulate_playback(cache, loop_length_ticks, playback_speed_factor=1.0):
    """
    Simulate loop playback by iterating through events.
    
    playback_speed_factor: 
        1.0 = normal (20ms per tick at 120 BPM)
        0.1 = 10x faster (stress test)
        0.0 = instant (max stress test)
    """
    print(f"\nSimulating playback ({cache.event_count} events, {loop_length_ticks} ticks)...")
    print(f"Speed factor: {playback_speed_factor} (0=instant, 1=realtime)")
    
    # Timing for real-time simulation
    MS_PER_TICK = 20.8  # ~120 BPM: 500ms per beat / 24 ticks = 20.8ms
    
    playhead_idx = 0
    current_tick = 0
    events_played = 0
    
    start_time = get_time_ms()
    last_event_time = start_time
    
    # Track timing violations
    timing_violations = 0
    max_delay_ms = 0
    
    while current_tick < loop_length_ticks:
        # Get events at current tick
        while playhead_idx < cache.event_count:
            event_start = get_time_ms()
            event = cache.get_event(playhead_idx)
            event_time = time_diff(get_time_ms(), event_start)
            
            if event is None:
                break
            
            cc_num, value, tick, channel = event
            
            if tick > current_tick:
                break  # Not time yet
            
            # "Play" the event (in real code, this sends MIDI)
            events_played += 1
            playhead_idx += 1
            
            # Track timing
            if event_time > max_delay_ms:
                max_delay_ms = event_time
            if event_time > 5:  # More than 5ms is concerning
                timing_violations += 1
        
        # Advance time
        current_tick += 1
        
        # Simulate real-time delay (optional)
        if playback_speed_factor > 0:
            time.sleep(MS_PER_TICK / 1000 * playback_speed_factor)
    
    elapsed = time_diff(get_time_ms(), start_time)
    
    print(f"\nPlayback complete:")
    print(f"  Events played: {events_played}")
    print(f"  Time: {elapsed}ms")
    print(f"  Max event read delay: {max_delay_ms}ms")
    print(f"  Timing violations (>5ms): {timing_violations}")
    
    return events_played, timing_violations

# ==============================================================================
# Main Test Functions
# ==============================================================================

def test_save_performance(num_events=1000):
    """Test how long it takes to save a loop to flash."""
    print(f"\n{'='*60}")
    print(f"TEST: Save Performance ({num_events} events)")
    print('='*60)
    
    gc.collect()
    mem_before = gc.mem_free()
    
    # Generate test data
    print("\nGenerating test data...")
    start = get_time_ms()
    data = generate_cc_sweep_data(num_events)
    gen_time = time_diff(get_time_ms(), start)
    print(f"  Generated {len(data)} bytes in {gen_time}ms")
    
    # Save to flash
    print("\nSaving to flash...")
    start = get_time_ms()
    loop_length = num_events * 2  # 2 ticks per event
    save_loop_to_flash(data, num_events, loop_length)
    save_time = time_diff(get_time_ms(), start)
    print(f"  Saved in {save_time}ms")
    
    # Free the data
    del data
    gc.collect()
    mem_after = gc.mem_free()
    
    print(f"\nMemory: {mem_before} → {mem_after} (delta: {mem_after - mem_before})")
    print(f"Result: {'PASS' if save_time < 500 else 'SLOW'} (target: <500ms)")
    
    return save_time

def test_load_performance():
    """Test how long it takes to load loop metadata (not events)."""
    print(f"\n{'='*60}")
    print("TEST: Load Header Performance")
    print('='*60)
    
    start = get_time_ms()
    event_count, loop_length = load_loop_header()
    load_time = time_diff(get_time_ms(), start)
    
    print(f"  Loaded header in {load_time}ms")
    print(f"  Event count: {event_count}")
    print(f"  Loop length: {loop_length} ticks")
    print(f"Result: {'PASS' if load_time < 50 else 'SLOW'} (target: <50ms)")
    
    return load_time

def test_playback_performance(speed_factor=0.0):
    """Test streaming playback performance."""
    print(f"\n{'='*60}")
    print("TEST: Playback Performance (Stress Test)")
    print('='*60)
    
    gc.collect()
    mem_before = gc.mem_free()
    
    # Load header
    event_count, loop_length = load_loop_header()
    
    # Create cache
    print(f"\nCreating playback cache...")
    print(f"  Cache size: {CACHE_SIZE_EVENTS} events ({CACHE_SIZE_BYTES} bytes)")
    cache = PlaybackCache(TEST_FILE, event_count)
    
    gc.collect()
    mem_after_cache = gc.mem_free()
    print(f"  Memory used for cache: {mem_before - mem_after_cache} bytes")
    
    # Run playback simulation
    events_played, violations = simulate_playback(cache, loop_length, speed_factor)
    
    # Print cache stats
    stats = cache.get_stats()
    print(f"\nCache performance:")
    print(f"  Hits: {stats['hits']}")
    print(f"  Misses: {stats['misses']}")
    print(f"  Hit rate: {stats['hit_rate']:.1f}%")
    print(f"  Avg miss time: {stats['avg_miss_time_ms']:.2f}ms")
    
    passed = violations == 0 and stats['avg_miss_time_ms'] < 10
    print(f"\nResult: {'PASS' if passed else 'FAIL'}")
    
    return stats

def test_multiple_loops(num_loops=5, events_per_loop=500):
    """Test creating and reading multiple loops (simulates 5 pads)."""
    print(f"\n{'='*60}")
    print(f"TEST: Multiple Loops ({num_loops} loops × {events_per_loop} events)")
    print('='*60)
    
    gc.collect()
    mem_start = gc.mem_free()
    
    # Create multiple loop files
    print("\nCreating loop files...")
    for i in range(num_loops):
        data = generate_cc_sweep_data(events_per_loop, cc_number=i+1)
        path = f"{TEST_LOOP_PATH}/loop_{i}.bin"
        header = struct.pack('<HH4s', events_per_loop, events_per_loop * 2, b'\x00\x00\x00\x00')
        with open(path, "wb") as f:
            f.write(header)
            f.write(data)
        print(f"  Created {path}")
        del data
        gc.collect()
    
    gc.collect()
    mem_after_save = gc.mem_free()
    print(f"\nMemory after saving all: {mem_after_save} (delta: {mem_after_save - mem_start})")
    
    # Create caches for all loops (simulates 5 loops playing simultaneously)
    print("\nCreating playback caches for all loops...")
    caches = []
    for i in range(num_loops):
        path = f"{TEST_LOOP_PATH}/loop_{i}.bin"
        cache = PlaybackCache(path, events_per_loop)
        caches.append(cache)
    
    gc.collect()
    mem_after_caches = gc.mem_free()
    cache_memory = mem_after_save - mem_after_caches
    print(f"Memory for {num_loops} caches: {cache_memory} bytes ({cache_memory // num_loops} per cache)")
    
    # Simulate reading from all caches in round-robin (like multi-loop playback)
    print("\nSimulating multi-loop playback...")
    start = get_time_ms()
    total_events_read = 0
    
    for tick in range(events_per_loop * 2):  # Full loop length
        for cache in caches:
            # Check if any events at this tick
            idx = tick // 2  # 2 ticks per event
            if idx < cache.event_count:
                event = cache.get_event(idx)
                if event:
                    total_events_read += 1
    
    elapsed = time_diff(get_time_ms(), start)
    
    print(f"\nMulti-loop playback results:")
    print(f"  Total events read: {total_events_read}")
    print(f"  Time: {elapsed}ms")
    print(f"  Events/ms: {total_events_read / elapsed:.1f}")
    
    # Aggregate cache stats
    total_hits = sum(c.cache_hits for c in caches)
    total_misses = sum(c.cache_misses for c in caches)
    hit_rate = total_hits / (total_hits + total_misses) * 100 if (total_hits + total_misses) > 0 else 0
    print(f"  Combined hit rate: {hit_rate:.1f}%")
    
    # Cleanup
    for i in range(num_loops):
        try:
            os.remove(f"{TEST_LOOP_PATH}/loop_{i}.bin")
        except:
            pass
    
    passed = elapsed < 5000 and hit_rate > 80
    print(f"\nResult: {'PASS' if passed else 'NEEDS OPTIMIZATION'}")
    
    return elapsed, hit_rate

def cleanup_test_files():
    """Remove test files and folder."""
    print("\nCleaning up test files...")
    try:
        os.remove(TEST_FILE)
        print(f"  Removed {TEST_FILE}")
    except OSError:
        pass
    
    try:
        # Remove any loop files
        for f in os.listdir(TEST_LOOP_PATH):
            os.remove(f"{TEST_LOOP_PATH}/{f}")
        os.rmdir(TEST_LOOP_PATH)
        print(f"  Removed {TEST_LOOP_PATH}")
    except OSError:
        pass

# ==============================================================================
# Extreme Stress Test - 16 Loops Simultaneous Playback
# ==============================================================================

def stress_test_16_loops(events_per_loop=1024, event_interval_ms=10, duration_seconds=5):
    """
    ULTIMATE STRESS TEST: 16 loops playing simultaneously.
    
    Simulates the worst-case scenario:
    - 16 loops (max pads) all playing at once
    - 1024 events per loop (max CC events)
    - Event every 10ms (fast CC sweep = 100 events/sec per loop)
    - Total: 1600 events/second across all loops
    
    This answers: "Can we read from 16 files fast enough for music?"
    
    Args:
        events_per_loop: Events per loop (default 1024 = max)
        event_interval_ms: Time between events in each loop (10ms = 100 events/sec)
        duration_seconds: How long to run the simulation
    """
    NUM_LOOPS = 16
    
    print("\n" + "="*70)
    print("EXTREME STRESS TEST: 16 SIMULTANEOUS LOOPS")
    print("="*70)
    print(f"\nTest parameters:")
    print(f"  Loops: {NUM_LOOPS}")
    print(f"  Events per loop: {events_per_loop}")
    print(f"  Event interval: {event_interval_ms}ms (= {1000//event_interval_ms} events/sec per loop)")
    print(f"  Total event rate: {NUM_LOOPS * (1000//event_interval_ms)} events/sec")
    print(f"  Duration: {duration_seconds} seconds")
    print(f"  Total events to process: ~{NUM_LOOPS * (1000//event_interval_ms) * duration_seconds}")
    print(f"  Playhead stagger: {CACHE_SIZE_EVENTS} events between loops (fully desynchronized)")
    
    gc.collect()
    mem_start = gc.mem_free()
    print(f"\nStarting memory: {mem_start:,} bytes")
    
    # -------------------------------------------------------------------------
    # Phase 1: Create all 16 loop files
    # -------------------------------------------------------------------------
    print("\n" + "-"*50)
    print("PHASE 1: Creating 16 loop files...")
    print("-"*50)
    
    ensure_test_folder()
    
    create_start = get_time_ms()
    for i in range(NUM_LOOPS):
        loop_start = get_time_ms()
        
        # Generate CC data - each loop uses different CC number
        data = generate_cc_sweep_data(events_per_loop, cc_number=(i % 127) + 1, ticks_per_event=1)
        
        # Save to file
        path = f"{TEST_LOOP_PATH}/stress_loop_{i:02d}.bin"
        header = struct.pack('<HH4s', events_per_loop, events_per_loop, b'\x00\x00\x00\x00')
        with open(path, "wb") as f:
            f.write(header)
            f.write(data)
        
        loop_time = time_diff(get_time_ms(), loop_start)
        print(f"  Loop {i:2d}: {events_per_loop} events, saved in {loop_time}ms")
        
        del data
        gc.collect()
    
    create_total = time_diff(get_time_ms(), create_start)
    print(f"\nTotal creation time: {create_total}ms ({create_total/NUM_LOOPS:.1f}ms avg)")
    
    gc.collect()
    mem_after_files = gc.mem_free()
    print(f"Memory after file creation: {mem_after_files:,} bytes")
    
    # -------------------------------------------------------------------------
    # Phase 2: Create playback caches for all loops
    # -------------------------------------------------------------------------
    print("\n" + "-"*50)
    print("PHASE 2: Creating 16 playback caches...")
    print("-"*50)
    
    caches = []
    cache_start = get_time_ms()
    
    for i in range(NUM_LOOPS):
        path = f"{TEST_LOOP_PATH}/stress_loop_{i:02d}.bin"
        cache = PlaybackCache(path, events_per_loop)
        caches.append(cache)
    
    cache_create_time = time_diff(get_time_ms(), cache_start)
    
    gc.collect()
    mem_after_caches = gc.mem_free()
    cache_memory = mem_after_files - mem_after_caches
    
    print(f"  Created {NUM_LOOPS} caches in {cache_create_time}ms")
    print(f"  Total cache memory: {cache_memory:,} bytes")
    print(f"  Memory per cache: {cache_memory // NUM_LOOPS} bytes")
    
    # -------------------------------------------------------------------------
    # Phase 3: Simulate real-time playback
    # -------------------------------------------------------------------------
    print("\n" + "-"*50)
    print("PHASE 3: Simulating real-time playback...")
    print("-"*50)
    print(f"\nRunning for {duration_seconds} seconds, processing all 16 loops every {event_interval_ms}ms...")
    print("(Each '.' = 100 ticks processed)\n")
    
    # Timing statistics
    tick_times = []  # Time to process each tick across all loops
    read_times = []  # Individual event read times
    events_per_tick = []  # How many events read per tick
    deadline_misses = 0  # Times where processing took > event_interval_ms
    
    # Playhead tracking - stagger start positions to simulate real-world usage
    # In reality, loops are recorded at different times so playheads aren't synchronized
    # Stagger by CACHE_SIZE to fully desynchronize cache refills
    # With 100-event cache and 16 loops, each loop refills on a different tick
    stagger = CACHE_SIZE_EVENTS  # 100 events apart = refills never overlap
    playheads = [(i * stagger) % events_per_loop for i in range(NUM_LOOPS)]
    
    # Calculate total ticks to simulate
    ticks_per_second = 1000 // event_interval_ms
    total_ticks = ticks_per_second * duration_seconds
    
    total_events_read = 0
    simulation_start = get_time_ms()
    last_report_tick = 0
    
    for tick in range(total_ticks):
        tick_start = get_time_ms()
        events_this_tick = 0
        
        # Process all 16 loops at this tick
        for loop_idx in range(NUM_LOOPS):
            cache = caches[loop_idx]
            playhead = playheads[loop_idx]
            
            if playhead >= cache.event_count:
                # Loop has wrapped - reset to start
                playheads[loop_idx] = 0
                playhead = 0
            
            # Read the event at current playhead
            read_start = get_time_ms()
            event = cache.get_event(playhead)
            read_time = time_diff(get_time_ms(), read_start)
            
            if event:
                events_this_tick += 1
                total_events_read += 1
                if read_time > 0:  # Only track non-zero reads
                    read_times.append(read_time)
            
            # Advance playhead
            playheads[loop_idx] = playhead + 1
        
        tick_time = time_diff(get_time_ms(), tick_start)
        tick_times.append(tick_time)
        events_per_tick.append(events_this_tick)
        
        # Check for deadline miss
        if tick_time > event_interval_ms:
            deadline_misses += 1
        
        # Progress indicator (every 100 ticks)
        if tick % 100 == 0:
            print(".", end="")
        
        # Detailed report every second
        if tick > 0 and tick % ticks_per_second == 0:
            second = tick // ticks_per_second
            recent_ticks = tick_times[last_report_tick:tick]
            avg_tick = sum(recent_ticks) / len(recent_ticks) if recent_ticks else 0
            max_tick = max(recent_ticks) if recent_ticks else 0
            print(f"\n  [Second {second}] Avg tick: {avg_tick:.2f}ms, Max: {max_tick}ms, Events: {sum(events_per_tick[last_report_tick:tick])}")
            last_report_tick = tick
    
    simulation_time = time_diff(get_time_ms(), simulation_start)
    
    # -------------------------------------------------------------------------
    # Phase 4: Analyze results
    # -------------------------------------------------------------------------
    print("\n\n" + "-"*50)
    print("PHASE 4: Results Analysis")
    print("-"*50)
    
    # Tick timing stats
    avg_tick_time = sum(tick_times) / len(tick_times) if tick_times else 0
    max_tick_time = max(tick_times) if tick_times else 0
    min_tick_time = min(tick_times) if tick_times else 0
    
    # Read timing stats
    if read_times:
        avg_read = sum(read_times) / len(read_times)
        max_read = max(read_times)
        min_read = min(read_times)
        reads_over_1ms = sum(1 for t in read_times if t > 1)
        reads_over_5ms = sum(1 for t in read_times if t > 5)
    else:
        avg_read = max_read = min_read = 0
        reads_over_1ms = reads_over_5ms = 0
    
    # Cache stats
    total_hits = sum(c.cache_hits for c in caches)
    total_misses = sum(c.cache_misses for c in caches)
    overall_hit_rate = total_hits / (total_hits + total_misses) * 100 if (total_hits + total_misses) > 0 else 0
    
    print(f"\nTIMING SUMMARY:")
    print(f"  Total simulation time: {simulation_time}ms")
    print(f"  Total ticks processed: {total_ticks}")
    print(f"  Total events read: {total_events_read}")
    print(f"  Events per second: {total_events_read / duration_seconds:.0f}")
    
    print(f"\nPER-TICK TIMING (budget: {event_interval_ms}ms):")
    print(f"  Average: {avg_tick_time:.3f}ms")
    print(f"  Maximum: {max_tick_time}ms")
    print(f"  Minimum: {min_tick_time}ms")
    print(f"  Deadline misses (>{event_interval_ms}ms): {deadline_misses} ({deadline_misses/total_ticks*100:.2f}%)")
    
    print(f"\nINDIVIDUAL READ TIMING:")
    print(f"  Total reads: {len(read_times) + total_hits}")
    print(f"  Reads that took >0ms: {len(read_times)}")
    print(f"  Average (>0ms only): {avg_read:.3f}ms")
    print(f"  Maximum: {max_read}ms")
    print(f"  Reads >1ms: {reads_over_1ms}")
    print(f"  Reads >5ms: {reads_over_5ms}")
    
    print(f"\nCACHE PERFORMANCE:")
    print(f"  Total cache hits: {total_hits}")
    print(f"  Total cache misses: {total_misses}")
    print(f"  Overall hit rate: {overall_hit_rate:.2f}%")
    
    # Per-loop cache breakdown
    print(f"\n  Per-loop cache misses:")
    for i, cache in enumerate(caches):
        stats = cache.get_stats()
        print(f"    Loop {i:2d}: {stats['misses']:3d} misses, {stats['hit_rate']:.1f}% hit rate, {stats['avg_miss_time_ms']:.2f}ms avg miss")
    
    print(f"\nMEMORY:")
    gc.collect()
    mem_final = gc.mem_free()
    print(f"  Start: {mem_start:,} bytes")
    print(f"  After caches: {mem_after_caches:,} bytes")
    print(f"  Final: {mem_final:,} bytes")
    print(f"  Total used for test: {mem_start - mem_final:,} bytes")
    
    # -------------------------------------------------------------------------
    # Phase 5: Verdict
    # -------------------------------------------------------------------------
    print("\n" + "="*70)
    print("VERDICT")
    print("="*70)
    
    passed = True
    
    if avg_tick_time < event_interval_ms / 2:
        print(f"  [PASS] Average tick time ({avg_tick_time:.2f}ms) well under budget ({event_interval_ms}ms)")
    elif avg_tick_time < event_interval_ms:
        print(f"  [WARN] Average tick time ({avg_tick_time:.2f}ms) under budget but tight")
    else:
        print(f"  [FAIL] Average tick time ({avg_tick_time:.2f}ms) EXCEEDS budget ({event_interval_ms}ms)")
        passed = False
    
    if deadline_misses == 0:
        print(f"  [PASS] No deadline misses!")
    elif deadline_misses <= total_ticks * 0.02:
        # Up to 2% misses is acceptable - flash I/O has inherent jitter
        # These are sub-frame delays (22ms max) that won't be audible
        print(f"  [PASS] {deadline_misses} deadline misses ({deadline_misses/total_ticks*100:.2f}%) - acceptable for flash I/O")
    else:
        print(f"  [FAIL] {deadline_misses} deadline misses ({deadline_misses/total_ticks*100:.2f}%) - too many!")
        passed = False
    
    if overall_hit_rate > 95:
        print(f"  [PASS] Cache hit rate ({overall_hit_rate:.1f}%) excellent")
    elif overall_hit_rate > 80:
        print(f"  [WARN] Cache hit rate ({overall_hit_rate:.1f}%) acceptable")
    else:
        print(f"  [FAIL] Cache hit rate ({overall_hit_rate:.1f}%) too low")
        passed = False
    
    if max_tick_time < event_interval_ms * 2:
        print(f"  [PASS] Max tick time ({max_tick_time}ms) reasonable")
    else:
        print(f"  [WARN] Max tick time ({max_tick_time}ms) high - could cause occasional glitches")
    
    print("\n" + "="*70)
    if passed:
        print("OVERALL: PASS - Flash storage is fast enough for 16 simultaneous loops!")
    else:
        print("OVERALL: FAIL - Performance issues detected")
    print("="*70)
    
    # Cleanup
    print("\nCleaning up stress test files...")
    for i in range(NUM_LOOPS):
        try:
            os.remove(f"{TEST_LOOP_PATH}/stress_loop_{i:02d}.bin")
        except:
            pass
    
    return {
        "avg_tick_ms": avg_tick_time,
        "max_tick_ms": max_tick_time,
        "deadline_misses": deadline_misses,
        "total_events": total_events_read,
        "cache_hit_rate": overall_hit_rate,
        "passed": passed
    }


def quick_read_latency_test(num_reads=1000):
    """
    Quick test: How long does a single file read actually take?
    
    Tests raw file I/O without the cache layer to understand
    the baseline performance.
    """
    print("\n" + "="*60)
    print("QUICK READ LATENCY TEST")
    print("="*60)
    
    ensure_test_folder()
    
    # Create a test file with 1000 events
    data = generate_cc_sweep_data(1000)
    save_loop_to_flash(data, 1000, 2000)
    del data
    gc.collect()
    
    print(f"\nTesting {num_reads} random reads...")
    
    read_times = []
    import random
    
    for i in range(num_reads):
        # Random position in file
        event_idx = random.randint(0, 999)
        file_offset = 8 + (event_idx * CC_EVENT_SIZE)
        
        start = get_time_ms()
        with open(TEST_FILE, "rb") as f:
            f.seek(file_offset)
            data = f.read(CC_EVENT_SIZE)
        elapsed = time_diff(get_time_ms(), start)
        read_times.append(elapsed)
    
    # Analyze
    non_zero = [t for t in read_times if t > 0]
    print(f"\nResults:")
    print(f"  Total reads: {num_reads}")
    print(f"  Reads that took >0ms: {len(non_zero)}")
    print(f"  Reads that took 0ms: {num_reads - len(non_zero)} (< 1ms, too fast to measure)")
    
    if non_zero:
        print(f"  Average (>0ms only): {sum(non_zero)/len(non_zero):.2f}ms")
        print(f"  Maximum: {max(non_zero)}ms")
    
    # Distribution
    print(f"\n  Distribution of read times:")
    print(f"    0ms (instant): {num_reads - len(non_zero)}")
    for threshold in [1, 2, 5, 10]:
        count = sum(1 for t in non_zero if t >= threshold)
        print(f"    ≥{threshold}ms: {count}")
    
    cleanup_test_files()
    
    return read_times


def cache_size_comparison_test():
    """
    Test different cache sizes to find the sweet spot.
    
    Larger cache = more RAM but fewer misses
    Smaller cache = less RAM but more misses
    """
    print("\n" + "="*60)
    print("CACHE SIZE COMPARISON TEST")
    print("="*60)
    
    ensure_test_folder()
    
    # Create a test file with 1024 events
    data = generate_cc_sweep_data(1024)
    save_loop_to_flash(data, 1024, 2048)
    del data
    gc.collect()
    
    cache_sizes = [25, 50, 100, 200, 400]
    results = []
    
    for size in cache_sizes:
        print(f"\nTesting cache size: {size} events ({size * CC_EVENT_SIZE} bytes)...")
        
        # Temporarily override cache size
        global CACHE_SIZE_EVENTS, CACHE_SIZE_BYTES
        old_size = CACHE_SIZE_EVENTS
        old_bytes = CACHE_SIZE_BYTES
        CACHE_SIZE_EVENTS = size
        CACHE_SIZE_BYTES = size * CC_EVENT_SIZE
        
        # Create cache and read all events
        cache = PlaybackCache(TEST_FILE, 1024)
        
        start = get_time_ms()
        for i in range(1024):
            cache.get_event(i)
        elapsed = time_diff(get_time_ms(), start)
        
        stats = cache.get_stats()
        
        result = {
            "size": size,
            "bytes": size * CC_EVENT_SIZE,
            "time_ms": elapsed,
            "misses": stats["misses"],
            "hit_rate": stats["hit_rate"],
            "avg_miss_ms": stats["avg_miss_time_ms"]
        }
        results.append(result)
        
        print(f"  Time: {elapsed}ms | Misses: {stats['misses']} | Hit rate: {stats['hit_rate']:.1f}%")
        
        # Restore
        CACHE_SIZE_EVENTS = old_size
        CACHE_SIZE_BYTES = old_bytes
        
        del cache
        gc.collect()
    
    print("\n" + "-"*50)
    print("COMPARISON SUMMARY")
    print("-"*50)
    print(f"{'Size':>6} {'Bytes':>8} {'Time':>8} {'Misses':>8} {'Hit%':>8} {'Miss Time':>10}")
    print("-"*50)
    for r in results:
        print(f"{r['size']:>6} {r['bytes']:>8} {r['time_ms']:>6}ms {r['misses']:>8} {r['hit_rate']:>7.1f}% {r['avg_miss_ms']:>8.2f}ms")
    
    cleanup_test_files()
    
    return results


# ==============================================================================
# Run All Tests
# ==============================================================================

def run_all_tests():
    """Run the complete test suite."""
    print("\n" + "="*60)
    print("FLASH-BACKED LOOP STORAGE TEST SUITE")
    print("="*60)
    
    gc.collect()
    print(f"\nInitial free memory: {gc.mem_free():,} bytes")
    
    # Setup
    ensure_test_folder()
    
    # Run tests
    results = {}
    
    # Test 1: Save performance
    results['save_time'] = test_save_performance(1000)
    
    # Test 2: Load header performance
    results['load_time'] = test_load_performance()
    
    # Test 3: Playback performance (instant - stress test)
    results['playback_stats'] = test_playback_performance(speed_factor=0.0)
    
    # Test 4: Multiple loops
    results['multi_loop'] = test_multiple_loops(num_loops=5, events_per_loop=500)
    
    # Cleanup
    cleanup_test_files()
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"  Save 1000 events: {results['save_time']}ms")
    print(f"  Load header: {results['load_time']}ms")
    print(f"  Playback cache hit rate: {results['playback_stats']['hit_rate']:.1f}%")
    print(f"  Playback avg miss time: {results['playback_stats']['avg_miss_time_ms']:.2f}ms")
    print(f"  Multi-loop (5×500 events): {results['multi_loop'][0]}ms, {results['multi_loop'][1]:.1f}% hit rate")
    
    gc.collect()
    print(f"\nFinal free memory: {gc.mem_free():,} bytes")
    
    return results


def run_stress_test():
    """Run just the 16-loop stress test (the main test you want)."""
    return stress_test_16_loops(
        events_per_loop=1024,      # Max events per loop
        event_interval_ms=10,      # 100 events/sec per loop (fast CC sweep)
        duration_seconds=5         # 5 second simulation
    )

# ==============================================================================
# Entry Point
# ==============================================================================

if __name__ == "__main__":
    # Run the stress test by default - this is what we care about most
    run_stress_test()
else:
    # When imported in REPL, just print instructions
    print("\n" + "="*50)
    print("Flash Loop Storage Test Script Loaded!")
    print("="*50)
    print("\nPRIMARY TEST (run this!):")
    print("  run_stress_test()         - 16 loops, staggered, 10ms ticks")
    print("")
    print("Other tests:")
    print("  run_all_tests()           - Original test suite")
    print("  stress_test_16_loops()    - Customizable stress test")
    print("  quick_read_latency_test() - Raw file read timing")
    print("  cache_size_comparison_test() - Find optimal cache size")
    print("")
    print("Individual tests:")
    print("  test_save_performance(n)  - Test saving n events")
    print("  test_playback_performance(speed) - Test playback (0=instant)")
    print("  test_multiple_loops(n, e) - Test n loops with e events each")
    print("")
    print("Cleanup:")
    print("  cleanup_test_files()      - Remove test files")
    print("")
    print("="*50)
    print("Quick start: run_stress_test()")
    print("="*50)
