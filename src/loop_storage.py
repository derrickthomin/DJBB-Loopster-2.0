"""
Flash-backed loop event storage for memory-efficient loop playback.

This module provides flash storage for CC, aftertouch, and note events, allowing
loops to be stored on flash instead of RAM. A streaming cache provides low-latency
playback without loading all events into memory. Notes are loaded to RAM
on preset load since they're small enough and need random access.

File Formats:
- CC: /loops/loop_XX_cc.bin (12-byte header + 5 bytes/event)
- Aftertouch: /loops/loop_XX_at.bin (12-byte header + 5 bytes/event)
- Notes: /loops/loop_XX_notes.bin (12-byte header + 5 bytes/event)

Phase 1: CC storage - COMPLETE
Phase 5: Notes storage - COMPLETE
Phase 6: Aftertouch storage - COMPLETE

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

# CC/Aftertouch File Format (shared structure)
HEADER_FORMAT = '<HHHH4s'  # magic, count, ticks, bpm*10, reserved
HEADER_SIZE = 12
CC_FORMAT = '<BBHB'        # cc_num/note, value/pressure, tick, channel
CC_EVENT_SIZE = 5
MAGIC_NUMBER = 0xCC01      # Version identifier for CC file format
AT_MAGIC = 0xA001          # Version identifier for aftertouch file format

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


def get_at_path(loop_id):
    """Build path for aftertouch binary file."""
    return f"{LOOPS_DIR}/loop_{loop_id:04d}_at.bin"


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
    """Delete notes, CC, and aftertouch files for a given loop ID."""
    try:
        os.remove(get_notes_path(loop_id))
    except OSError:
        pass
    try:
        os.remove(get_cc_path(loop_id))
    except OSError:
        pass
    try:
        os.remove(get_at_path(loop_id))
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
# Save/Load Functions (CC and Aftertouch share same format)
# =============================================================================

def save_controller_to_flash(storage, loop_id, total_ticks, bpm, event_type="cc"):
    """
    Save CC or aftertouch events from RAM storage to flash file.
    
    Args:
        storage: ArrayBasedCCStorage instance (or any object with
                 cc_nums, values, ticks, midi_channels arrays and __len__)
        loop_id: Sequential loop ID (1, 2, 3...) for file naming
        total_ticks: Total loop length in ticks
        bpm: Recording BPM
        event_type: "cc" or "at" (aftertouch)
    
    Returns:
        Filename string (e.g., "loop_0001_cc.bin") or None on failure
    """
    ensure_loops_folder()
    
    event_count = len(storage)
    if event_count == 0:
        return None
    
    # Select magic and suffix based on type
    if event_type == "at":
        magic = AT_MAGIC
        suffix = "_at.bin"
        type_name = "aftertouch"
    else:
        magic = MAGIC_NUMBER
        suffix = "_cc.bin"
        type_name = "CC"
    
    filename = f"loop_{loop_id:04d}{suffix}"
    filepath = f"{LOOPS_DIR}/{filename}"
    
    # Check available space (rough estimate)
    try:
        stat = os.statvfs('/')
        free_bytes = stat[0] * stat[3]  # block size × free blocks
        needed = event_count * CC_EVENT_SIZE + HEADER_SIZE + 4096  # 4KB buffer
        if free_bytes < needed:
            print(f"[WARN] Flash full, keeping {type_name} in RAM")
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
                magic,
                event_count,
                total_ticks,
                bpm_x10,
                b'\x00\x00\x00\x00'  # Reserved bytes
            )
            f.write(header)
            
            # Write events one at a time to minimize RAM usage
            for i in range(event_count):
                cc_num = storage.cc_nums[i]
                value = storage.values[i]
                tick = storage.ticks[i]
                channel = storage.midi_channels[i]
                f.write(struct.pack(CC_FORMAT, cc_num, value, tick, channel))
        
        return filename
    
    except OSError as e:
        print(f"[ERROR] Flash save failed: {e}")
        return None


def save_cc_to_flash(cc_storage, loop_id, total_ticks, bpm):
    """Save CC events to flash. Wrapper for save_controller_to_flash."""
    return save_controller_to_flash(cc_storage, loop_id, total_ticks, bpm, "cc")


def save_at_to_flash(at_storage, loop_id, total_ticks, bpm):
    """Save aftertouch events to flash. Wrapper for save_controller_to_flash."""
    return save_controller_to_flash(at_storage, loop_id, total_ticks, bpm, "at")


def load_controller_header(file_path, expected_magic=None):
    """
    Load header metadata for CC or aftertouch file.
    
    Args:
        file_path: Full path to the .bin file
        expected_magic: If provided, validate against this magic number.
                       If None, accepts both CC and AT magic.
    
    Returns:
        Dict with 'event_count', 'total_ticks', 'bpm', 'type' keys,
        or empty dict on error
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(HEADER_SIZE)
        
        if len(header) < HEADER_SIZE:
            return {}
        
        magic, count, ticks, bpm_x10 = struct.unpack('<HHHH', header[:8])
        
        # Validate magic number
        if expected_magic is not None:
            if magic != expected_magic:
                return {}
        elif magic not in (MAGIC_NUMBER, AT_MAGIC):
            return {}
        
        return {
            'event_count': count,
            'total_ticks': ticks,
            'bpm': bpm_x10 / 10.0,
            'type': 'cc' if magic == MAGIC_NUMBER else 'at'
        }
    
    except OSError:
        return {}


def load_cc_header(file_path):
    """Load CC file header. Wrapper for load_controller_header."""
    return load_controller_header(file_path, MAGIC_NUMBER)


def load_at_header(file_path):
    """Load aftertouch file header. Wrapper for load_controller_header."""
    return load_controller_header(file_path, AT_MAGIC)


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


def delete_at_file(loop_id):
    """
    Remove aftertouch file when loop is deleted.
    
    Args:
        loop_id: Sequential loop ID
    """
    filepath = get_at_path(loop_id)
    try:
        os.remove(filepath)
    except OSError:
        pass  # File doesn't exist, that's fine


def read_all_controller_events(file_path, expected_magic=None):
    """
    Read all CC or aftertouch events from flash file.
    
    Used for oneshot list creation where we need to scan
    all events to find the latest value of each controller.
    
    Args:
        file_path: Full path to the .bin file
        expected_magic: If provided, validate against this magic number.
    
    Returns:
        List of (num, value, tick, channel) tuples
    """
    header = load_controller_header(file_path, expected_magic)
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


def read_all_cc_events(file_path):
    """Read all CC events from flash file. Wrapper for read_all_controller_events."""
    return read_all_controller_events(file_path, MAGIC_NUMBER)


def read_all_at_events(file_path):
    """Read all aftertouch events from flash file. Wrapper for read_all_controller_events."""
    return read_all_controller_events(file_path, AT_MAGIC)


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


def list_at_files():
    """
    List all aftertouch files in the loops directory.
    
    Returns:
        List of filenames (not full paths)
    """
    try:
        ensure_loops_folder()
        files = os.listdir(LOOPS_DIR)
        return [f for f in files if f.endswith('_at.bin')]
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
                # print(f"[FLASH] Invalid notes magic: {magic:04X}")
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
