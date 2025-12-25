"""
Flash-backed loop event storage for memory-efficient loop playback.

This module provides flash storage for CC and note events, allowing loops to be
stored on flash instead of RAM. A streaming cache provides low-latency
CC playback without loading all events into memory. Notes are loaded to RAM
on preset load since they're small enough and need random access.

File Formats:
- CC: /loops/loop_XX_cc.bin (12-byte header + 5 bytes/event)
- Notes: /loops/loop_XX_notes.bin (12-byte header + 5 bytes/event)

Phase 1: CC storage - COMPLETE
Phase 5: Notes storage - COMPLETE

Test on device:
    from loop_storage import (
        save_cc_to_flash, load_cc_header, CCPlaybackCache,
        save_notes_to_flash, load_notes_from_flash, delete_notes_file
    )
    
    # Run the built-in test
    from loop_storage import run_quick_test
    run_quick_test()
"""

import struct
import os
import gc

# =============================================================================
# File Format Constants
# =============================================================================

# CC File Format
HEADER_FORMAT = '<HHHH4s'  # magic, count, ticks, bpm*10, reserved
HEADER_SIZE = 12
CC_FORMAT = '<BBHB'        # cc_num, value, tick, channel
CC_EVENT_SIZE = 5
MAGIC_NUMBER = 0xCC01      # Version identifier for CC file format

# Notes File Format (Phase 5)
NOTES_MAGIC = 0x4E01       # "N" for notes
NOTES_HEADER_FORMAT = '<HHHHH2s'  # magic, total_count, notes_on_count, total_ticks, bpm*10, reserved
NOTES_HEADER_SIZE = 12
NOTES_EVENT_FORMAT = '<BBBH'    # note, velocity, packed_pad_channel, tick
NOTES_EVENT_SIZE = 5

# =============================================================================
# Storage Paths
# =============================================================================

LOOPS_DIR = "/loops"

# =============================================================================
# File Path Helpers
# =============================================================================

def get_notes_path(loop_id):
    """Build path for notes binary file."""
    return f"{LOOPS_DIR}/loop_{loop_id:04d}_notes.bin"


def get_cc_path(loop_id):
    """Build path for CC binary file."""
    return f"{LOOPS_DIR}/loop_{loop_id:04d}_cc.bin"


def cleanup_orphan_loops(valid_loop_ids):
    """
    Delete loop files whose loop_id is not referenced by any preset.
    
    Call this on boot after collecting all loop IDs from presets.
    
    Args:
        valid_loop_ids: Set/list of valid loop IDs (e.g., {1, 2, 5})
    
    Returns:
        Number of files deleted
    """
    ensure_loops_folder()
    deleted_count = 0
    
    # Convert to set of ints for fast lookup
    valid_ids = set(valid_loop_ids)
    
    try:
        for filename in os.listdir(LOOPS_DIR):
            # Expected format: loop_XXXX_type.bin (e.g., loop_0001_notes.bin)
            if not filename.startswith('loop_') or not filename.endswith('.bin'):
                continue
            
            # Extract loop ID from filename
            parts = filename.split('_')
            if len(parts) < 3:
                continue
            
            try:
                file_loop_id = int(parts[1])
            except ValueError:
                continue
            
            if file_loop_id not in valid_ids:
                try:
                    os.remove(f"{LOOPS_DIR}/{filename}")
                    deleted_count += 1
                except OSError:
                    pass
    except OSError:
        pass
    
    return deleted_count


def delete_loop_files(loop_id):
    """Delete both notes and CC files for a given loop ID."""
    try:
        os.remove(get_notes_path(loop_id))
    except OSError:
        pass
    try:
        os.remove(get_cc_path(loop_id))
    except OSError:
        pass


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
        loop_id: Sequential loop ID (1, 2, 3...) for file naming
        total_ticks: Total loop length in ticks
        bpm: Recording BPM
    
    Returns:
        Filename string (e.g., "loop_0001_cc.bin") or None on failure
    """
    ensure_loops_folder()
    
    event_count = len(cc_storage)
    if event_count == 0:
        return None
    
    filename = f"loop_{loop_id:04d}_cc.bin"
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
        loop_id: Sequential loop ID
    """
    filepath = get_cc_path(loop_id)
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
# Notes Save/Load Functions (Phase 5)
# =============================================================================

def save_notes_to_flash(notes_on, notes_off, loop_id, total_ticks, bpm):
    """
    Save note events to binary file.
    
    Creates a single file containing both notes_on and notes_off events.
    Header stores counts so loader knows where notes_on ends and notes_off begins.
    
    Args:
        notes_on: ArrayBasedEventStorage for note-on events
        notes_off: ArrayBasedEventStorage for note-off events
        loop_id: Sequential loop ID for file naming
        total_ticks: Total loop length in ticks (stored for reference)
        bpm: Recording BPM (stored for reference)
    
    Returns:
        Filename string (e.g., "loop_0001_notes.bin") or None on failure
    """
    ensure_loops_folder()
    
    notes_on_count = len(notes_on)
    notes_off_count = len(notes_off)
    total_count = notes_on_count + notes_off_count
    
    if total_count == 0:
        return None
    
    filename = f"loop_{loop_id:04d}_notes.bin"
    filepath = f"{LOOPS_DIR}/{filename}"
    
    # Check available space
    try:
        stat = os.statvfs('/')
        free_bytes = stat[0] * stat[3]
        needed = total_count * NOTES_EVENT_SIZE + NOTES_HEADER_SIZE + 4096
        if free_bytes < needed:
            print("[WARN] Flash full, cannot save notes")
            return None
    except (OSError, AttributeError):
        pass
    
    # Delete existing file if present
    try:
        os.remove(filepath)
    except OSError:
        pass
    
    try:
        with open(filepath, "wb") as f:
            # Write header (matches CC header: includes total_ticks and bpm)
            bpm_x10 = int(bpm * 10)
            header = struct.pack(
                NOTES_HEADER_FORMAT,
                NOTES_MAGIC,
                total_count,
                notes_on_count,
                total_ticks,
                bpm_x10,
                b'\x00\x00'  # Reserved bytes
            )
            f.write(header)
            
            # Write notes_on events
            for i in range(notes_on_count):
                note = notes_on.notes[i]
                velocity = notes_on.velocities[i]
                packed = notes_on.packed_pad_channel[i]
                tick = notes_on.ticks[i]
                f.write(struct.pack(NOTES_EVENT_FORMAT, note, velocity, packed, tick))
            
            # Write notes_off events
            for i in range(notes_off_count):
                note = notes_off.notes[i]
                velocity = notes_off.velocities[i]
                packed = notes_off.packed_pad_channel[i]
                tick = notes_off.ticks[i]
                f.write(struct.pack(NOTES_EVENT_FORMAT, note, velocity, packed, tick))
        
        return filename
    
    except OSError as e:
        print(f"[ERROR] Notes flash save failed: {e}")
        return None


def load_notes_from_flash(file_path, notes_on_storage, notes_off_storage):
    """
    Load notes from binary file into provided storage objects.
    
    Populates the given ArrayBasedEventStorage objects with events
    read from the binary file. Storage objects should be empty.
    
    Args:
        file_path: Full path to the .bin file
        notes_on_storage: ArrayBasedEventStorage to populate with note-on events
        notes_off_storage: ArrayBasedEventStorage to populate with note-off events
    
    Returns:
        Tuple (notes_on_count, notes_off_count) or (0, 0) on error
    """
    try:
        with open(file_path, "rb") as f:
            # Read and validate header
            header_bytes = f.read(NOTES_HEADER_SIZE)
            if len(header_bytes) < NOTES_HEADER_SIZE:
                return (0, 0)
            
            magic, total_count, notes_on_count, total_ticks, bpm_x10, _ = struct.unpack(
                NOTES_HEADER_FORMAT, header_bytes
            )
            
            if magic != NOTES_MAGIC:
                print(f"[FLASH] Invalid notes magic: {magic:04X}")
                return (0, 0)
            
            notes_off_count = total_count - notes_on_count
            
            # Read notes_on events
            for _ in range(notes_on_count):
                event_bytes = f.read(NOTES_EVENT_SIZE)
                if len(event_bytes) < NOTES_EVENT_SIZE:
                    break
                note, vel, packed, tick = struct.unpack(NOTES_EVENT_FORMAT, event_bytes)
                # Unpack pad_idx and midi_channel from packed byte
                pad_idx = packed & 0x0F
                midi_ch = (packed >> 4) & 0x0F
                notes_on_storage.add_event(note, vel, pad_idx, tick, midi_ch)
            
            # Read notes_off events
            for _ in range(notes_off_count):
                event_bytes = f.read(NOTES_EVENT_SIZE)
                if len(event_bytes) < NOTES_EVENT_SIZE:
                    break
                note, vel, packed, tick = struct.unpack(NOTES_EVENT_FORMAT, event_bytes)
                pad_idx = packed & 0x0F
                midi_ch = (packed >> 4) & 0x0F
                notes_off_storage.add_event(note, vel, pad_idx, tick, midi_ch)
            
            return (notes_on_count, notes_off_count)
    
    except OSError:
        # File doesn't exist - this is expected for stale metadata or CC-only loops
        return (0, 0)


def load_notes_header(file_path):
    """
    Load just notes header metadata without loading events.
    
    Args:
        file_path: Full path to the .bin file
    
    Returns:
        Dict with 'total_count', 'notes_on_count', 'notes_off_count',
        'total_ticks', 'bpm' keys, or empty dict on error
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(NOTES_HEADER_SIZE)
        
        if len(header) < NOTES_HEADER_SIZE:
            return {}
        
        magic, total_count, notes_on_count, total_ticks, bpm_x10, _ = struct.unpack(
            NOTES_HEADER_FORMAT, header
        )
        
        if magic != NOTES_MAGIC:
            return {}
        
        return {
            'total_count': total_count,
            'notes_on_count': notes_on_count,
            'notes_off_count': total_count - notes_on_count,
            'total_ticks': total_ticks,
            'bpm': bpm_x10 / 10.0
        }
    
    except OSError:
        return {}


def delete_notes_file(loop_id):
    """
    Remove notes file when loop is deleted.
    
    Args:
        loop_id: Sequential loop ID
    """
    filepath = get_notes_path(loop_id)
    try:
        os.remove(filepath)
    except OSError:
        pass  # File doesn't exist


def list_notes_files():
    """
    List all notes files in the loops directory.
    
    Returns:
        List of filenames (not full paths)
    """
    try:
        ensure_loops_folder()
        files = os.listdir(LOOPS_DIR)
        return [f for f in files if f.endswith('_notes.bin')]
    except OSError:
        return []


# =============================================================================
# Test Helper (for REPL testing)
# =============================================================================

def run_quick_test():
    """
    Quick test of save/load functionality for CC and Notes.
    Run this in REPL to verify the module works on device.
    
    Tests edge cases:
    - Packed byte encoding (pad_idx + midi_channel)
    - Boundary values (note 0, note 127, tick 0, high tick)
    - Unequal notes_on/notes_off counts
    - Only notes_on (no notes_off)
    - Empty storage (should return None)
    """
    import array
    
    print("=" * 50)
    print("Loop Storage Quick Test (CC + Notes)")
    print("=" * 50)
    
    # Create fake CC storage that mimics ArrayBasedCCStorage
    class FakeCCStorage:
        def __init__(self, count=100):
            self.cc_nums = [1] * count  # All CC #1
            self.values = [i % 128 for i in range(count)]  # 0-127 sweep
            self.ticks = [i * 2 for i in range(count)]  # Every 2 ticks
            self.midi_channels = [0] * count  # Channel 0
        def __len__(self):
            return len(self.cc_nums)
    
    # Create fake note storage that mimics ArrayBasedEventStorage
    class FakeNoteStorage:
        def __init__(self, count=0):
            self.notes = array.array('B')
            self.velocities = array.array('B')
            self.packed_pad_channel = array.array('B')
            self.ticks = array.array('H')
            # Optionally populate with test data
            for i in range(count):
                self.notes.append(60 + i)
                self.velocities.append(100)
                self.packed_pad_channel.append(0)
                self.ticks.append(i * 24)
        
        def __len__(self):
            return len(self.notes)
        
        def add_event(self, note, vel, pad_idx, tick, midi_ch):
            self.notes.append(note)
            self.velocities.append(vel)
            self.packed_pad_channel.append((midi_ch << 4) | pad_idx)
            self.ticks.append(tick)
        
        def add_raw(self, note, vel, packed, tick):
            """Add event with pre-packed byte (for test setup)."""
            self.notes.append(note)
            self.velocities.append(vel)
            self.packed_pad_channel.append(packed)
            self.ticks.append(tick)
    
    gc.collect()
    mem_before = gc.mem_free()
    print(f"\nMemory before: {mem_before:,} bytes")
    
    # Test loop IDs (start at 9001 to avoid conflict with real data)
    TEST_LOOP_ID_START = 9001
    
    # Clean up any leftover test files from previous runs
    for i in range(TEST_LOOP_ID_START, TEST_LOOP_ID_START + 6):
        delete_cc_file(i)
        delete_notes_file(i)
    
    test_num = 0
    def test(name, condition, detail=""):
        nonlocal test_num
        test_num += 1
        if condition:
            print(f"   {test_num}. PASS: {name}" + (f" ({detail})" if detail else ""))
            return True
        else:
            print(f"   {test_num}. FAIL: {name}" + (f" ({detail})" if detail else ""))
            return False
    
    # ===== CC TESTS =====
    print("\n--- CC Basic Tests ---")
    
    fake_cc = FakeCCStorage(100)
    cc_filename = save_cc_to_flash(fake_cc, TEST_LOOP_ID_START, 200, 120.0)
    if not test("CC save", cc_filename is not None, cc_filename):
        return False
    
    header = load_cc_header(f"{LOOPS_DIR}/{cc_filename}")
    if not test("CC header", header and header['event_count'] == 100):
        return False
    
    cache = CCPlaybackCache(f"{LOOPS_DIR}/{cc_filename}", header['event_count'])
    event = cache.get_event(0)
    if not test("CC cache read first", event and event[0] == 1 and event[1] == 0):
        return False
    
    # Test cache chunk boundary (events 99 and 100 span cache boundary if cache is 100)
    event99 = cache.get_event(99)
    if not test("CC cache last event", event99 and event99[1] == 99):
        return False
    
    delete_cc_file(TEST_LOOP_ID_START)
    
    # ===== CC EDGE CASES =====
    print("\n--- CC Edge Cases ---")
    
    # Create CC storage with varied realistic data
    class VariedCCStorage:
        def __init__(self):
            self.cc_nums = []
            self.values = []
            self.ticks = []
            self.midi_channels = []
        def add(self, cc, val, tick, ch):
            self.cc_nums.append(cc)
            self.values.append(val)
            self.ticks.append(tick)
            self.midi_channels.append(ch)
        def __len__(self):
            return len(self.cc_nums)
    
    # Test boundary values
    varied_cc = VariedCCStorage()
    varied_cc.add(0, 0, 0, 0)        # CC 0, value 0, tick 0, ch 0 (all minimums)
    varied_cc.add(127, 127, 100, 15) # CC 127, value 127, ch 15 (all maximums)
    varied_cc.add(1, 64, 65000, 0)   # High tick value
    varied_cc.add(74, 100, 65500, 8) # Different CC, different channel
    
    fn = save_cc_to_flash(varied_cc, TEST_LOOP_ID_START + 1, 65535, 120.0)
    if not test("CC varied data save", fn is not None):
        return False
    
    # Verify via cache read
    hdr = load_cc_header(f"{LOOPS_DIR}/{fn}")
    cache2 = CCPlaybackCache(f"{LOOPS_DIR}/{fn}", hdr['event_count'])
    
    ev0 = cache2.get_event(0)
    if not test("CC boundary: cc=0, val=0, tick=0", ev0 == (0, 0, 0, 0)):
        return False
    
    ev1 = cache2.get_event(1)
    if not test("CC boundary: cc=127, val=127, ch=15", ev1 == (127, 127, 100, 15)):
        return False
    
    ev2 = cache2.get_event(2)
    if not test("CC high tick (65000)", ev2 and ev2[2] == 65000):
        return False
    
    ev3 = cache2.get_event(3)
    if not test("CC different channel (8)", ev3 and ev3[3] == 8):
        return False
    
    delete_cc_file(TEST_LOOP_ID_START + 1)
    
    # Empty CC storage should return None
    empty_cc = VariedCCStorage()
    fn = save_cc_to_flash(empty_cc, TEST_LOOP_ID_START + 2, 100, 120.0)
    if not test("CC empty returns None", fn is None):
        return False
    
    # ===== NOTES TESTS =====
    print("\n--- Notes Basic Tests ---")
    
    # Test 1: Basic save/load with realistic varied data
    notes_on = FakeNoteStorage()
    notes_off = FakeNoteStorage()
    
    # Add varied realistic data: different pads, channels, velocities
    # Note: pad 0-15, channel 0-15, packed = (ch << 4) | pad
    test_notes = [
        # (note, vel, pad, channel, tick)
        (60, 127, 0, 0, 0),       # C4, max vel, pad 0, ch 0, tick 0
        (64, 80, 3, 1, 24),       # E4, pad 3, ch 1
        (67, 100, 7, 2, 48),      # G4, pad 7, ch 2
        (72, 1, 15, 15, 96),      # C5, min vel, max pad, max ch
        (0, 64, 8, 8, 120),       # Note 0 (boundary)
        (127, 64, 0, 0, 144),     # Note 127 (boundary)
    ]
    
    for note, vel, pad, ch, tick in test_notes:
        packed = (ch << 4) | pad
        notes_on.add_raw(note, vel, packed, tick)
        # Note-off 20 ticks later, velocity 0
        notes_off.add_raw(note, 0, packed, tick + 20)
    
    notes_filename = save_notes_to_flash(notes_on, notes_off, TEST_LOOP_ID_START + 1, 200, 120.0)
    if not test("Notes save (varied data)", notes_filename is not None, notes_filename):
        return False
    
    # Verify header (now includes total_ticks and bpm)
    hdr = load_notes_header(f"{LOOPS_DIR}/{notes_filename}")
    if not test("Notes header counts", hdr and hdr['notes_on_count'] == 6 and hdr['notes_off_count'] == 6):
        return False
    if not test("Notes header ticks/bpm", hdr['total_ticks'] == 200 and hdr['bpm'] == 120.0,
                f"ticks={hdr.get('total_ticks')}, bpm={hdr.get('bpm')}"):
        return False
    
    # Load and verify packed byte encoding roundtrip
    loaded_on = FakeNoteStorage()
    loaded_off = FakeNoteStorage()
    counts = load_notes_from_flash(f"{LOOPS_DIR}/{notes_filename}", loaded_on, loaded_off)
    
    if not test("Notes load count", counts == (6, 6)):
        return False
    
    # Verify packed byte encoding/decoding for note index 3 (pad=15, ch=15)
    # packed should be (15 << 4) | 15 = 255
    packed_val = loaded_on.packed_pad_channel[3]
    decoded_pad = packed_val & 0x0F
    decoded_ch = (packed_val >> 4) & 0x0F
    if not test("Packed byte encode/decode", decoded_pad == 15 and decoded_ch == 15, 
                f"packed={packed_val}, pad={decoded_pad}, ch={decoded_ch}"):
        return False
    
    # Verify boundary notes
    if not test("Note 0 stored", loaded_on.notes[4] == 0):
        return False
    if not test("Note 127 stored", loaded_on.notes[5] == 127):
        return False
    
    # Verify velocities
    if not test("Max velocity (127)", loaded_on.velocities[0] == 127):
        return False
    if not test("Min velocity (1)", loaded_on.velocities[3] == 1):
        return False
    
    # Verify tick 0 preserved
    if not test("Tick 0 preserved", loaded_on.ticks[0] == 0):
        return False
    
    delete_notes_file(TEST_LOOP_ID_START + 1)  # Clean up this test
    
    # ===== EDGE CASE TESTS =====
    print("\n--- Notes Edge Cases ---")
    
    # Edge case: Only notes_on, no notes_off (recording stopped mid-note)
    only_on = FakeNoteStorage()
    only_on.add_raw(60, 100, 0, 0)
    only_on.add_raw(64, 100, 0, 24)
    empty_off = FakeNoteStorage()
    
    fn = save_notes_to_flash(only_on, empty_off, TEST_LOOP_ID_START + 2, 100, 120.0)
    if not test("Only notes_on (no off)", fn is not None):
        return False
    
    hdr = load_notes_header(f"{LOOPS_DIR}/{fn}")
    if not test("Only on: header correct", hdr['notes_on_count'] == 2 and hdr['notes_off_count'] == 0):
        return False
    
    load_on = FakeNoteStorage()
    load_off = FakeNoteStorage()
    counts = load_notes_from_flash(f"{LOOPS_DIR}/{fn}", load_on, load_off)
    if not test("Only on: load correct", counts == (2, 0) and len(load_off) == 0):
        return False
    
    delete_notes_file(TEST_LOOP_ID_START + 2)
    
    # Edge case: Unequal counts (more on than off - common with sustain pedal)
    unequal_on = FakeNoteStorage()
    unequal_off = FakeNoteStorage()
    for i in range(5):
        unequal_on.add_raw(60 + i, 100, 0, i * 10)
    for i in range(3):  # Only 3 note-offs
        unequal_off.add_raw(60 + i, 0, 0, i * 10 + 50)
    
    fn = save_notes_to_flash(unequal_on, unequal_off, TEST_LOOP_ID_START + 3, 200, 120.0)
    if not test("Unequal counts save", fn is not None):
        return False
    
    hdr = load_notes_header(f"{LOOPS_DIR}/{fn}")
    if not test("Unequal: 5 on, 3 off", hdr['notes_on_count'] == 5 and hdr['notes_off_count'] == 3):
        return False
    
    delete_notes_file(TEST_LOOP_ID_START + 3)
    
    # Edge case: Empty storage (should return None, not create empty file)
    empty_on = FakeNoteStorage()
    empty_off = FakeNoteStorage()
    fn = save_notes_to_flash(empty_on, empty_off, TEST_LOOP_ID_START + 4, 100, 120.0)
    if not test("Empty storage returns None", fn is None):
        return False
    
    # Edge case: High tick value (near uint16 max)
    high_tick = FakeNoteStorage()
    high_tick.add_raw(60, 100, 0, 65000)  # Near 65535 max
    high_tick.add_raw(61, 100, 0, 65500)
    empty = FakeNoteStorage()
    
    fn = save_notes_to_flash(high_tick, empty, TEST_LOOP_ID_START + 5, 65535, 120.0)
    if not test("High tick save", fn is not None):
        return False
    
    load_ht = FakeNoteStorage()
    load_empty = FakeNoteStorage()
    load_notes_from_flash(f"{LOOPS_DIR}/{fn}", load_ht, load_empty)
    if not test("High tick preserved", load_ht.ticks[0] == 65000 and load_ht.ticks[1] == 65500):
        return False
    
    delete_notes_file(TEST_LOOP_ID_START + 5)
    
    # ===== CLEANUP =====
    print("\n--- Cleanup ---")
    
    # Verify test files were deleted (loop IDs 9001-9006)
    cc_files = list_cc_files()
    notes_files = list_notes_files()
    
    # Check that none of our test loop IDs have leftover files
    test_cc_remaining = [f for f in cc_files if any(f"loop_{(TEST_LOOP_ID_START + i):04d}_" in f for i in range(6))]
    test_notes_remaining = [f for f in notes_files if any(f"loop_{(TEST_LOOP_ID_START + i):04d}_" in f for i in range(6))]
    
    if not test("Test files deleted", len(test_cc_remaining) == 0 and len(test_notes_remaining) == 0,
                f"remaining: cc={test_cc_remaining}, notes={test_notes_remaining}"):
        return False
    
    # Info only: report other files that exist (not an error)
    other_cc = [f for f in cc_files if f not in test_cc_remaining]
    if other_cc:
        print(f"   (Note: {len(other_cc)} other CC files exist from previous use)")
    
    gc.collect()
    mem_after = gc.mem_free()
    print(f"\nMemory after: {mem_after:,} bytes (delta: {mem_after - mem_before:+,})")
    
    print("\n" + "=" * 50)
    print(f"ALL {test_num} TESTS PASSED")
    print("=" * 50)
    return True


# =============================================================================
# Entry Point - Run quick test when executed directly
# =============================================================================

if __name__ == "__main__":
    run_quick_test()
