"""
Flash-backed CC event storage for memory-efficient loop playback.

This module provides flash storage for CC events, allowing loops to be
stored on flash instead of RAM. A streaming cache provides low-latency
playback without loading all events into memory.

Phase 1: Standalone module - test via REPL before integrating.

Test on device:
    from loop_storage import save_cc_to_flash, load_cc_header, CCPlaybackCache
    
    # Create fake CC data
    class FakeStorage:
        def __init__(self):
            self.cc_nums = [1] * 100
            self.values = list(range(100))
            self.ticks = list(range(0, 200, 2))
            self.midi_channels = [0] * 100
        def __len__(self):
            return 100
    
    fake = FakeStorage()
    filename = save_cc_to_flash(fake, 0, 200, 120.0)
    print(f"Saved: {filename}")
    
    header = load_cc_header("/loops/loop_00_cc.bin")
    print(f"Header: {header}")
    
    cache = CCPlaybackCache("/loops/loop_00_cc.bin", 100)
    for i in range(5):
        print(cache.get_event(i))
"""

import struct
import os
import gc

# =============================================================================
# File Format Constants
# =============================================================================

HEADER_FORMAT = '<HHHH4s'  # magic, count, ticks, bpm*10, reserved
HEADER_SIZE = 12
CC_FORMAT = '<BBHB'        # cc_num, value, tick, channel
CC_EVENT_SIZE = 5
MAGIC_NUMBER = 0xCC01      # Version identifier for file format

# =============================================================================
# Storage Paths
# =============================================================================

LOOPS_DIR = "/loops"

# =============================================================================
# Cache Configuration
# =============================================================================

CACHE_SIZE_EVENTS = 100
CACHE_SIZE_BYTES = CACHE_SIZE_EVENTS * CC_EVENT_SIZE


def ensure_loops_folder():
    """Create /loops directory if needed."""
    try:
        os.mkdir(LOOPS_DIR)
    except OSError:
        pass  # Already exists


# =============================================================================
# CCPlaybackCache - Streaming cache for flash playback
# =============================================================================

class CCPlaybackCache:
    """
    Streaming cache for CC playback from flash.
    
    Loads chunks of events on demand, minimizing RAM usage while
    providing fast sequential access for playback.
    
    Attributes:
        file_path: Path to the CC binary file
        event_count: Total number of events in the file
        cache: Bytearray buffer for cached events
        cache_start_idx: Event index at start of cache
        cache_valid_events: Number of valid events in cache
    """
    
    def __init__(self, file_path, event_count):
        """
        Initialize cache for a CC file.
        
        Args:
            file_path: Path to the .bin file
            event_count: Total events in file (from header)
        """
        self.file_path = file_path
        self.event_count = event_count
        
        # Cache buffer - reused to avoid allocations
        self.cache = bytearray(CACHE_SIZE_BYTES)
        self.cache_start_idx = -1  # Invalid - forces load on first access
        self.cache_valid_events = 0
    
    def _load_cache(self, start_event_idx):
        """
        Load a chunk of events into cache starting at given index.
        
        Args:
            start_event_idx: First event index to load
        """
        # Calculate file offset (skip header)
        file_offset = HEADER_SIZE + (start_event_idx * CC_EVENT_SIZE)
        
        # Calculate how many events to read
        events_remaining = self.event_count - start_event_idx
        events_to_read = min(CACHE_SIZE_EVENTS, events_remaining)
        
        with open(self.file_path, "rb") as f:
            f.seek(file_offset)
            bytes_read = f.readinto(self.cache)
        
        self.cache_start_idx = start_event_idx
        self.cache_valid_events = bytes_read // CC_EVENT_SIZE
    
    def get_event(self, event_idx):
        """
        Get a single event by index. Loads cache if needed.
        
        Args:
            event_idx: Index of event to retrieve (0-based)
        
        Returns:
            Tuple (cc_num, value, tick, channel) or None if out of range
        """
        if event_idx >= self.event_count:
            return None
        
        # Check if event is in cache
        cache_offset = event_idx - self.cache_start_idx
        
        if cache_offset < 0 or cache_offset >= self.cache_valid_events:
            # Cache miss - load new chunk starting at requested index
            self._load_cache(event_idx)
            cache_offset = 0
        
        # Read from cache buffer
        byte_offset = cache_offset * CC_EVENT_SIZE
        return struct.unpack_from(CC_FORMAT, self.cache, byte_offset)
    
    def reset(self):
        """Reset cache for loop restart. Called when loop resets to beginning."""
        self.cache_start_idx = -1
        self.cache_valid_events = 0


# =============================================================================
# Save/Load Functions
# =============================================================================

def save_cc_to_flash(cc_storage, loop_id, total_ticks, bpm):
    """
    Flush CC events from RAM storage to flash file.
    
    Args:
        cc_storage: ArrayBasedCCStorage instance (or any object with
                    cc_nums, values, ticks, midi_channels arrays and __len__)
        loop_id: Pad index (0-15), used for filename
        total_ticks: Total loop length in ticks
        bpm: Recording BPM
    
    Returns:
        Filename string (e.g., "loop_03_cc.bin") or None on failure
    """
    ensure_loops_folder()
    
    event_count = len(cc_storage)
    if event_count == 0:
        return None
    
    filename = f"loop_{loop_id:02d}_cc.bin"
    filepath = f"{LOOPS_DIR}/{filename}"
    
    # Check available space (rough estimate)
    try:
        stat = os.statvfs('/')
        free_bytes = stat[0] * stat[3]  # block size × free blocks
        needed = event_count * CC_EVENT_SIZE + HEADER_SIZE + 4096  # 4KB buffer
        if free_bytes < needed:
            print("[WARN] Flash full, keeping CCs in RAM")
            return None
    except (OSError, AttributeError):
        pass  # Can't check, proceed anyway
    
    # Delete existing file if present
    try:
        os.remove(filepath)
    except OSError:
        pass
    
    try:
        with open(filepath, "wb") as f:
            # Write header
            bpm_x10 = int(bpm * 10)
            header = struct.pack(
                HEADER_FORMAT,
                MAGIC_NUMBER,
                event_count,
                total_ticks,
                bpm_x10,
                b'\x00\x00\x00\x00'  # Reserved bytes
            )
            f.write(header)
            
            # Write events one at a time to minimize RAM usage
            for i in range(event_count):
                cc_num = cc_storage.cc_nums[i]
                value = cc_storage.values[i]
                tick = cc_storage.ticks[i]
                channel = cc_storage.midi_channels[i]
                f.write(struct.pack(CC_FORMAT, cc_num, value, tick, channel))
        
        return filename
    
    except OSError as e:
        print(f"[ERROR] Flash save failed: {e}")
        return None


def load_cc_header(file_path):
    """
    Load just header metadata without loading events.
    
    Args:
        file_path: Full path to the .bin file
    
    Returns:
        Dict with 'event_count', 'total_ticks', 'bpm' keys,
        or empty dict on error
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(HEADER_SIZE)
        
        if len(header) < HEADER_SIZE:
            return {}
        
        magic, count, ticks, bpm_x10 = struct.unpack('<HHHH', header[:8])
        
        if magic != MAGIC_NUMBER:
            print(f"[ERROR] Invalid CC file magic: {file_path}")
            return {}
        
        return {
            'event_count': count,
            'total_ticks': ticks,
            'bpm': bpm_x10 / 10.0
        }
    
    except OSError:
        return {}


def delete_cc_file(loop_id):
    """
    Remove CC file when loop is deleted.
    
    Args:
        loop_id: Pad index (0-15)
    """
    filepath = f"{LOOPS_DIR}/loop_{loop_id:02d}_cc.bin"
    try:
        os.remove(filepath)
    except OSError:
        pass  # File doesn't exist, that's fine


def read_all_cc_events(file_path):
    """
    Read all CC events from flash file.
    
    Used for oneshot CC list creation where we need to scan
    all events to find the latest value of each CC number.
    
    Args:
        file_path: Full path to the .bin file
    
    Returns:
        List of (cc_num, value, tick, channel) tuples
    """
    header = load_cc_header(file_path)
    if not header:
        return []
    
    events = []
    try:
        with open(file_path, "rb") as f:
            f.seek(HEADER_SIZE)  # Skip header
            for _ in range(header['event_count']):
                data = f.read(CC_EVENT_SIZE)
                if len(data) < CC_EVENT_SIZE:
                    break
                events.append(struct.unpack(CC_FORMAT, data))
    except OSError:
        pass
    
    return events


def list_cc_files():
    """
    List all CC files in the loops directory.
    
    Returns:
        List of filenames (not full paths)
    """
    try:
        ensure_loops_folder()
        files = os.listdir(LOOPS_DIR)
        return [f for f in files if f.endswith('_cc.bin')]
    except OSError:
        return []


def cleanup_all_cc_files():
    """
    Delete all CC files. Use with caution!
    
    Returns:
        Number of files deleted
    """
    files = list_cc_files()
    count = 0
    for f in files:
        try:
            os.remove(f"{LOOPS_DIR}/{f}")
            count += 1
        except OSError:
            pass
    return count


# =============================================================================
# Test Helper (for REPL testing)
# =============================================================================

def run_quick_test():
    """
    Quick test of save/load functionality.
    Run this in REPL to verify the module works on device.
    """
    print("=" * 50)
    print("Loop Storage Quick Test")
    print("=" * 50)
    
    # Create fake CC storage that mimics ArrayBasedCCStorage
    class FakeStorage:
        def __init__(self, count=100):
            self.cc_nums = [1] * count  # All CC #1
            self.values = [i % 128 for i in range(count)]  # 0-127 sweep
            self.ticks = [i * 2 for i in range(count)]  # Every 2 ticks
            self.midi_channels = [0] * count  # Channel 0
        def __len__(self):
            return len(self.cc_nums)
    
    gc.collect()
    mem_before = gc.mem_free()
    print(f"\nMemory before: {mem_before} bytes")
    
    # Test save
    print("\n1. Testing save...")
    fake = FakeStorage(100)
    filename = save_cc_to_flash(fake, 0, 200, 120.0)
    if filename:
        print(f"   PASS: Saved to {filename}")
    else:
        print("   FAIL: Save returned None")
        return False
    
    # Test load header
    print("\n2. Testing load header...")
    header = load_cc_header(f"{LOOPS_DIR}/{filename}")
    if header:
        print(f"   PASS: event_count={header['event_count']}, ticks={header['total_ticks']}, bpm={header['bpm']}")
        if header['event_count'] != 100:
            print(f"   WARN: Expected 100 events, got {header['event_count']}")
    else:
        print("   FAIL: Could not load header")
        return False
    
    # Test cache
    print("\n3. Testing cache...")
    cache = CCPlaybackCache(f"{LOOPS_DIR}/{filename}", header['event_count'])
    
    # Read first 5 events
    for i in range(5):
        event = cache.get_event(i)
        if event:
            cc_num, value, tick, channel = event
            expected_value = i % 128
            expected_tick = i * 2
            if value == expected_value and tick == expected_tick:
                print(f"   Event {i}: CC={cc_num}, val={value}, tick={tick}, ch={channel} - OK")
            else:
                print(f"   Event {i}: MISMATCH - got val={value}, tick={tick}")
        else:
            print(f"   Event {i}: FAIL - None returned")
            return False
    
    # Test cache miss (read from middle)
    print("\n4. Testing cache miss (reading event 50)...")
    event = cache.get_event(50)
    if event and event[1] == 50 and event[2] == 100:
        print(f"   PASS: Event 50 = {event}")
    else:
        print(f"   FAIL: Event 50 = {event}")
        return False
    
    # Test read_all_cc_events
    print("\n5. Testing read_all_cc_events...")
    all_events = read_all_cc_events(f"{LOOPS_DIR}/{filename}")
    if len(all_events) == 100:
        print(f"   PASS: Read {len(all_events)} events")
    else:
        print(f"   FAIL: Expected 100, got {len(all_events)}")
        return False
    
    # Cleanup
    print("\n6. Testing delete...")
    delete_cc_file(0)
    files = list_cc_files()
    if filename not in files:
        print("   PASS: File deleted")
    else:
        print("   FAIL: File still exists")
        return False
    
    gc.collect()
    mem_after = gc.mem_free()
    print(f"\nMemory after: {mem_after} bytes (delta: {mem_after - mem_before})")
    
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
    return True


# =============================================================================
# Entry Point - Run quick test when executed directly
# =============================================================================

if __name__ == "__main__":
    run_quick_test()
