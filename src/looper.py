from debug import free_memory  
import gc
import math
import array  
from utils import next_or_previous_index
from midi import midi
import adafruit_ticks as ticks
from clock import clock
from display import display
from pixels import pixels
from settings import settings
import settingsmenu
import constants as C
from loop_storage import (save_cc_to_flash, delete_cc_file, LOOPS_DIR, CCPlaybackCache, 
                          load_cc_header, read_all_cc_events,
                          save_notes_to_flash, delete_notes_file)

# Phase 3: Feature flag for flash CC playback
# Set to True to read CCs from flash cache, False for RAM playback
USE_FLASH_CC_PLAYBACK = True  # Phase 4: Enabled - RAM cleared after flash save

# TODO: DELETE THIS - Stress test globals (set by code.py at boot)
STRESS_TEST_MODE = False
STRESS_TEST_LOOP_COUNT = 0

# Pack/unpack pad index and MIDI channel into single byte
def pack_pad_channel(pad_idx, midi_channel):
    return ((midi_channel & 0x0F) << 4) | (pad_idx & 0x0F)

def unpack_pad_channel(packed):
    pad_idx = packed & 0x0F
    midi_channel = (packed >> 4) & 0x0F
    return pad_idx, midi_channel

def _calculate_quantized_tick(tick_count, quantization_percent, ticks_per_quantization_unit):
    if ticks_per_quantization_unit <= 0:
        return tick_count

    tick_remainder = tick_count % ticks_per_quantization_unit
    if tick_remainder > ticks_per_quantization_unit / 2:
        tick_update = int(round((ticks_per_quantization_unit - tick_remainder) * quantization_percent))
        new_ticks = tick_count + tick_update
    else:
        tick_update = int(round(tick_remainder * quantization_percent))
        new_ticks = tick_count - tick_update
    
    return new_ticks

class ArrayBasedEventStorage:
    """Array-based MIDI note event storage for memory efficiency."""
    def __init__(self):
        self.notes = array.array('B', [])        # MIDI note numbers (0-127)
        self.velocities = array.array('B', [])   # Note velocities (0-127)
        self.packed_pad_channel = array.array('B', [])  # Packed: pad_idx(4 bits) + midi_channel(4 bits)
        self.ticks = array.array('H', [])        # Tick positions (0-65535)
        
    def add_event(self, note, velocity, pad_idx, tick, midi_channel=0):
        # Clamp tick to unsigned short range
        if tick < 0:
            tick = 0
        elif tick > 65535:
            tick = 65535
            
        self.notes.append(note)
        self.velocities.append(velocity)
        self.packed_pad_channel.append(pack_pad_channel(pad_idx, midi_channel))
        self.ticks.append(tick)
    
    def get_event(self, idx):
        if idx < 0:
            idx = len(self.notes) + idx
        pad_idx, midi_channel = unpack_pad_channel(self.packed_pad_channel[idx])
        return (self.notes[idx], self.velocities[idx], 
                pad_idx, self.ticks[idx], midi_channel)
                
    def __len__(self):
        return len(self.notes)
        
    def clear(self):
        self.notes = array.array('B', [])
        self.velocities = array.array('B', [])
        self.packed_pad_channel = array.array('B', [])
        self.ticks = array.array('H', [])
        
    def __getitem__(self, idx):
        return self.get_event(idx)
        
    def append(self, event_tuple):
        if len(event_tuple) >= 5:  # New format with MIDI channel
            note, vel, padidx, tick, midi_channel = event_tuple[:5]
            self.add_event(note, vel, padidx, tick, midi_channel)
        else:  # Legacy format without MIDI channel
            note, vel, padidx, tick = event_tuple[:4]
            self.add_event(note, vel, padidx, tick, 0)

class ArrayBasedCCStorage:
    """Array-based MIDI CC event storage for memory efficiency."""
    def __init__(self):
        self.cc_nums = array.array('B', [])      # CC numbers (0-127)
        self.values = array.array('B', [])       # CC values (0-127)
        self.ticks = array.array('H', [])        # Tick positions (0-65535)
        self.midi_channels = array.array('B', [])  # MIDI channels (0-15)
        
    def add_event(self, cc_num, value, tick, midi_channel=0):
        # Clamp tick to unsigned short range
        if tick < 0:
            tick = 0
        elif tick > 65535:
            tick = 65535
            
        self.cc_nums.append(cc_num)
        self.values.append(value)
        self.ticks.append(tick)
        self.midi_channels.append(midi_channel)
        
    def get_event(self, idx):
        if idx < 0:
            idx = len(self.cc_nums) + idx
        return (self.cc_nums[idx], self.values[idx], self.ticks[idx], self.midi_channels[idx])
        
    def __len__(self):
        return len(self.cc_nums)
        
    def clear(self):
        self.cc_nums = array.array('B', [])
        self.values = array.array('B', [])
        self.ticks = array.array('H', [])
        self.midi_channels = array.array('B', [])
        
    def __getitem__(self, idx):
        return self.get_event(idx)
        
    def append(self, event_tuple):
        if len(event_tuple) >= 4:  # New format with MIDI channel
            cc_num, value, tick, midi_channel = event_tuple[:4]
            self.add_event(cc_num, value, tick, midi_channel)
        else:  # Legacy format without MIDI channel
            cc_num, value, tick = event_tuple[:3]
            self.add_event(cc_num, value, tick, 0)

class MidiLoop:
    """MIDI loop: recording, playback, and event manipulation."""
    def __init__(self, loop_type="loop", assigned_pad_idx=C.DEFAULT_CHORDPAD_IDX):
        self.loop_type = loop_type
        self.assigned_pad_idx = assigned_pad_idx
        
        # Timing
        self.start_timestamp = 0
        self.start_tickstamp = 0
        self.total_time_seconds = 0
        self.current_loop_time = 0
        self.total_midi_ticks = 0
        self.current_midi_ticks = 0
        self.recording_bpm = clock.bpm_current
        
        # Event storage
        self.notes_on = ArrayBasedEventStorage()
        self.notes_off = ArrayBasedEventStorage()
        self.cc_events = ArrayBasedCCStorage()
        self.cc_oneshot = []
        self.notes_oneshot = []
        self.oneshot_note_offs = []
        self.stuck_on_notes = []
        self.unique_notes = []
        self.cached_unique_ccs = []  # Phase 4: Cache to avoid flash reads in hot path
        
        # Playback queue indices
        self.queue_index_notes_on = 0
        self.queue_index_notes_off = 0
        self.queue_index_cc = 0
        self.queue_idx_oneshot_offs = 0
        
        # Loop identity and flash storage
        self.loop_id = None  # Sequential loop ID for file naming (assigned on record)
        self.cc_file_path = None
        self.notes_file_path = None
        
        # Flash CC playback cache (Phase 3)
        self.cc_cache = None
        
        # State flags
        self.loop_is_playing = False
        self.is_recording = False
        self.has_loop = False
        
        # Completion tracking
        self.note_ons_complete = False
        self.note_offs_complete = False
        self.ccs_complete = True
        self.max_events_reached = False

    def reset(self):
        """Reset loop for playback."""
        self.clear_notes_and_pixels()
        
        # Sync with MIDI clock
        ticks_until_next_quarter = 0
        if settings.midi_sync and clock.is_playing:
            ticks_since_last_quarter = clock.midi_ticks_elapsed % 24
            if ticks_since_last_quarter != 0:
                ticks_until_next_quarter = clock.TICKS_PER_QUARTER_NOTE - ticks_since_last_quarter
            self.start_tickstamp = clock.midi_ticks_elapsed + ticks_until_next_quarter
        
        # Reset queue positions
        self.queue_index_notes_on = 0
        self.queue_index_notes_off = 0
        self.queue_index_cc = 0
        self.queue_idx_oneshot_offs = 0
        self.current_midi_ticks = 0
        
        # Reset state flags
        self.ccs_complete = False
        self.note_ons_complete = False
        self.note_offs_complete = False
        
        # Phase 3: Create or reset flash CC cache 
        if USE_FLASH_CC_PLAYBACK and self.cc_file_path:
            if self.cc_cache is None:
                header = load_cc_header(self.cc_file_path)
                if header and header.get('event_count', 0) > 0:
                    gc.collect()
                    mem_before = gc.mem_free()
                    self.cc_cache = CCPlaybackCache(self.cc_file_path, header['event_count'])
                    gc.collect()
                    mem_after = gc.mem_free()
                    print(f"[FLASH] Created CC cache for pad {self.assigned_pad_idx}: {header['event_count']} total events, buffer=100, cost={mem_before - mem_after:,} bytes ({mem_after:,} free)")
            elif self.cc_cache:
                self.cc_cache.reset()
        
        # Configure timing
        if settings.midi_sync and clock.is_playing:
            self.current_midi_ticks = 0 - ticks_until_next_quarter  # Start on next quarter note
        else:
            self.start_tickstamp = clock.midi_ticks_elapsed
        self.start_timestamp = ticks.ticks_ms()


    def clear_notes_and_pixels(self):
        """Send note-offs for all unique notes and reset their pixels."""
        unique_notes_data = set()  # (note, pad_idx, midi_channel) tuples
        unique_pixels = set()
        
        # Get unique notes with their channel info
        for i in range(len(self.notes_on)):
            note = self.notes_on.notes[i]
            pad_idx, midi_channel = unpack_pad_channel(self.notes_on.packed_pad_channel[i])
            unique_notes_data.add((note, pad_idx, midi_channel))
            unique_pixels.add(pad_idx)

        # Send note-offs with correct channel routing based on mode
        for note, pad_idx, midi_channel in unique_notes_data:
            if settings.midi_channel_mode == "per_note":
                midi.send_note_off(note, midi_channel)  # Use stored channel directly
            elif settings.midi_channel_mode == "per_pad":
                midi.send_note_off(note, pad_idx)  # Pass pad index for channel lookup
            else:  # global mode
                midi.send_note_off(note, None)  # Uses global channel
        
        for pixel in unique_pixels:
            pixels.set_note_off(pixel)

    def clear(self):
        self.clear_notes_and_pixels()
        
        # Delete flash files using loop_id (orphan cleanup will handle on next boot)
        # Note: We don't delete files immediately anymore since they might be shared
        # by other presets. Orphan cleanup on boot will delete unreferenced files.
        self.cc_file_path = None
        self.cc_cache = None
        self.notes_file_path = None
        self.loop_id = None
        
        # Clear event arrays
        self.notes_on.clear()
        self.notes_off.clear()
        self.cc_events.clear()
        self.cc_oneshot.clear()
        self.oneshot_note_offs.clear()
        self.unique_notes.clear()
        self.cached_unique_ccs = []
        
        # Reset states / timing
        self.total_time_seconds = 0
        self.start_timestamp = 0
        self.current_midi_ticks = 0
        self.total_midi_ticks = 0
        self.toggle_playstate(False)
        self.toggle_record_state(False)
        self.current_loop_time = 0
        self.has_loop = False

        free_memory()

    def count_events(self):
        # Phase 4: Check flash header if RAM CC storage is empty
        cc_count = len(self.cc_events)
        if cc_count == 0 and self.cc_file_path:
            header = load_cc_header(self.cc_file_path)
            if header:
                cc_count = header.get('event_count', 0)
        return len(self.notes_on) + len(self.notes_off) + cc_count

    def reset_timing(self):
        self.start_timestamp = 0
        self.start_tickstamp = 0
        self.current_midi_ticks = 0
    
    def toggle_playstate(self, on_or_off=None):
        self.loop_is_playing = on_or_off if on_or_off is not None else not self.loop_is_playing
        self.current_loop_time = 0
        assigned_pad_idx = self.assigned_pad_idx

        if self.loop_type in ["loop", "oneshot"]:
            # Playing
            if self.loop_is_playing:
                self.reset()
                if 0 <= assigned_pad_idx <= 15 and not self.is_recording:
                    pixels.set_color(assigned_pad_idx, C.PIXEL_LOOP_PLAYING_COLOR)
                    pixels.set_default_color(assigned_pad_idx, C.PIXEL_LOOP_PLAYING_COLOR)
            # Stopping
            else:                   
                self.reset_timing()
                if 0 <= assigned_pad_idx <= 15:
                    pixels.set_color(assigned_pad_idx, C.CHORD_COLOR)
                    pixels.set_default_color(assigned_pad_idx, C.CHORD_COLOR)

    def toggle_record_state(self, on_or_off=None):
        global STRESS_TEST_MODE, STRESS_TEST_LOOP_COUNT
        # Update recording state
        self.is_recording = on_or_off if on_or_off is not None else not self.is_recording
        if not self.is_recording:
            self.max_events_reached = False

        # --- STARTING RECORDING ---
        if self.is_recording and not self.has_loop:
            self.start_timestamp = ticks.ticks_ms()             # Set real-time start timestamp
            self.start_tickstamp = clock.midi_ticks_elapsed     # Set MIDI tick reference
            self.recording_bpm = clock.bpm_current              # Store current BPM
            self.toggle_playstate(True)

        # --- STOPPING RECORDING ---
        elif not self.is_recording and ((self.has_loop and on_or_off is not False) 
                                      or self.loop_type in ["oneshot", "loop"]):
            # Always calculate total time based on actual recording duration
            actual_recording_time = ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0
            self.total_time_seconds = actual_recording_time
            
            # Calculate total_midi_ticks based on sync mode
            if settings.midi_sync:
                # Use direct tick count (consistent with how events were recorded)
                self.total_midi_ticks = clock.midi_ticks_elapsed - self.start_tickstamp
                self.recording_bpm = clock.bpm_current  # Update to actual detected BPM
            else:
                # Use time-based conversion for non-synced mode
                self.total_midi_ticks = clock.seconds_to_ticks(actual_recording_time, self.recording_bpm)

            # Handle any stuck notes that need to be closed
            if len(self.stuck_on_notes) > 0:
                for note in self.stuck_on_notes:
                    self.add_note(note, 0, 0, False, True)
                self.stuck_on_notes = []
            
            # Handle MIDI sync playback state    
            if settings.midi_sync and not clock.get_playstate():
                self.toggle_playstate(False)
            
            # --- POST-PROCESSING ---
            # Memory debug: Post-processing start
            gc.collect()
            print(f"[MEM] Post-process start: {gc.mem_free():,} free")
            
            self.trim_silence()       # Remove silence at beginning/end
            self.quantize_events()    # Align events to grid
            self.quantize_loop()      # Adjust loop length to musical boundary
            
            # Memory debug: Before oneshot creation (crash point)
            gc.collect()
            print(f"[MEM] Before create_oneshot_ccs: {gc.mem_free():,} free")
            
            self.create_oneshot_ccs() 
            self.update_oneshot_notes()
            
            # Phase 4: Cache unique_ccs before clearing RAM (used by arp polling)
            self.cached_unique_ccs = self._compute_unique_ccs()
            
            # Assign new loop ID for this recording
            self.loop_id = settings.get_next_loop_id()
            
            # Save CCs to flash
            if len(self.cc_events) > 0:
                flash_start = ticks.ticks_ms()
                cc_count_before_clear = len(self.cc_events)
                filename = save_cc_to_flash(
                    self.cc_events,
                    self.loop_id,
                    self.total_midi_ticks,
                    self.recording_bpm
                )
                flash_elapsed = ticks.ticks_diff(ticks.ticks_ms(), flash_start)
                if filename:
                    self.cc_file_path = f"{LOOPS_DIR}/{filename}"
                    bytes_written = cc_count_before_clear * 5 + 12  # 5 bytes per event + 12 byte header
                    print(f"[FLASH] Saved {cc_count_before_clear} CCs ({bytes_written} bytes) to {filename} in {flash_elapsed}ms")
                    
                    # Free RAM now that CCs are on flash
                    mem_before = gc.mem_free()
                    self.cc_events.clear()
                    gc.collect()
                    mem_after = gc.mem_free()
                    print(f"[MEM] Freed CC RAM: {mem_after - mem_before:+,} bytes ({mem_after:,} free)")
                    
                    # Create CC cache immediately so playback works without waiting for reset()
                    if USE_FLASH_CC_PLAYBACK:
                        self.cc_cache = CCPlaybackCache(self.cc_file_path, cc_count_before_clear)
            
            # Save notes to flash (for preset persistence only - keep in RAM for playback)
            if len(self.notes_on) > 0 or len(self.notes_off) > 0:
                notes_filename = save_notes_to_flash(
                    self.notes_on,
                    self.notes_off,
                    self.loop_id,
                    self.total_midi_ticks,
                    self.recording_bpm
                )
                if notes_filename:
                    self.notes_file_path = f"{LOOPS_DIR}/{notes_filename}"
                    print(f"[FLASH] Saved {len(self.notes_on)} notes_on, {len(self.notes_off)} notes_off to {notes_filename}")
                # NOTE: Do NOT clear notes - needed for RAM playback
            
            # Defragment memory after all post-processing allocations complete
            gc.collect()
            
            # Memory debug: Recording stop
            total_events = len(self.notes_on) + len(self.notes_off) + len(self.cc_events)
            if STRESS_TEST_MODE:
                print(f"[MEM] Recording stop (Loop {STRESS_TEST_LOOP_COUNT}): {gc.mem_free():,} free, {total_events} total events")
                # Increment loop counter for next recording
                STRESS_TEST_LOOP_COUNT += 1
            else:
                print(f"[MEM] Recording stop: {gc.mem_free():,} free, {total_events} total events")
  
    def add_note(self, midi_note, velocity, padidx, add_or_remove, force_add=False, midi_channel=0):
        """Add note to loop. add_or_remove=True for note-on, False for note-off."""
        if not self.is_recording and not force_add:
            return

        if not force_add and self.start_timestamp == 0:
            display.show_notification("Play loop to record")
            self.toggle_record_state(False)
            return

        # --- TIMING CALCULATION ---
        if settings.midi_sync and clock.is_playing:
            # Use direct tick count from MIDI clock (BPM-independent, more accurate)
            tick_count = clock.midi_ticks_elapsed - self.start_tickstamp
        else:
            # Use real-time conversion (for non-synced mode)
            tick_count = clock.seconds_to_ticks(
                ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0, self.recording_bpm)
        
        if len(self.notes_on) > C.LOOP_NOTES_LIMIT:    
            display.show_notification("MAX NOTES REACHED")
            self.max_events_reached = True # Event limit flag
            return

        # Add
        if add_or_remove:
            if not self.has_loop:
                self.has_loop = True
            self.notes_on.add_event(midi_note, velocity, padidx, tick_count, midi_channel)
            self.stuck_on_notes.append(midi_note)

        # Remove
        else:
            self.notes_off.add_event(midi_note, velocity, padidx, tick_count, midi_channel)
            if midi_note in self.stuck_on_notes:
                self.stuck_on_notes.remove(midi_note)
            
        # Periodic memory management
        if len(self.notes_on) % C.MEMORY_CLEANUP_INTERVAL == 0:
            free_memory()
        
        # Memory debug: Every 50 note events
        total_notes = len(self.notes_on) + len(self.notes_off)
        if total_notes > 0 and total_notes % 50 == 0:
            import gc
            gc.collect()
            if STRESS_TEST_MODE:
                print(f"[MEM] L{STRESS_TEST_LOOP_COUNT} Events={total_notes} (notes): {gc.mem_free():,} free")
            else:
                print(f"[MEM] Events={total_notes} (notes): {gc.mem_free():,} free")
        
        # Auto-stop for benchmarking (normal test mode only - stress test uses real limits)
        if not STRESS_TEST_MODE and total_notes >= 700:
            self.max_events_reached = True
            display.show_notification("TEST: 700 notes reached")

    def has_events(self):
        # Check RAM storage OR flash CC file
        has_cc = len(self.cc_events) > 0 or self.cc_file_path is not None
        return len(self.notes_on) > 0 or has_cc

    def add_cc(self, cc_num, cc_value, midi_channel=0):
        """Add CC event. Only records if value differs significantly from previous."""
        global STRESS_TEST_MODE, STRESS_TEST_LOOP_COUNT
        if not self.is_recording:
            return

        if self.start_timestamp == 0:
            display.show_notification("Play loop to record")
            self.toggle_record_state(False)
            return

        cc_events_length = len(self.cc_events)
        if cc_events_length >= C.CC_EVENTS_LIMIT:
            self.max_events_reached = True
            display.show_notification("MAX CCS REACHED")
            return
        
        # --- VALUE CHANGE DETECTION ---
        # Find if we've ever recorded this CC number before
        last_cc_value = None
        found_previous_value = False
        
        for i in range(cc_events_length-1, -1, -1):  # Iterate in reverse for efficiency
            if self.cc_events.cc_nums[i] == cc_num:
                last_cc_value = self.cc_events.values[i]
                found_previous_value = True
                break

        # --- CC RECORDING ---
        # Only record if it's a new CC or has changed significantly
        if (last_cc_value is None and not found_previous_value) or \
           (found_previous_value and abs(cc_value - last_cc_value) > settings.cc_resolution):
            
            # Calculate tick position
            if settings.midi_sync and clock.is_playing:
                # Use direct tick count from MIDI clock (BPM-independent, more accurate)
                tick_count = clock.midi_ticks_elapsed - self.start_tickstamp
            else:
                # Use real-time conversion (for non-synced mode)
                tick_count = clock.seconds_to_ticks(
                    ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0, self.recording_bpm
                )
            
            if not self.has_loop:
                self.has_loop = True
            
            # Memory management
            if cc_events_length % C.MEMORY_CLEANUP_INTERVAL == 0:
                free_memory()
            
            # Memory debug: Every 50 CC events
            if (cc_events_length + 1) % 50 == 0:
                import gc
                gc.collect()
                if STRESS_TEST_MODE:
                    print(f"[MEM] L{STRESS_TEST_LOOP_COUNT} Events={cc_events_length + 1} (CCs): {gc.mem_free():,} free")
                else:
                    print(f"[MEM] Events={cc_events_length + 1} (CCs): {gc.mem_free():,} free")
            
            # Auto-stop for benchmarking (normal test mode only - stress test uses real CC_EVENTS_LIMIT)
            if not STRESS_TEST_MODE and (cc_events_length + 1) >= 1000:
                self.max_events_reached = True
                display.show_notification("TEST: 1000 CCs reached")
                    
            self.cc_events.add_event(cc_num, cc_value, tick_count, midi_channel)

    def _remove_leading_off_notes(self):
        if len(self.notes_on) == 0 or len(self.notes_off) == 0:
            return
            
        first_note_on_tick = self.notes_on.ticks[0]
        new_notes_off = ArrayBasedEventStorage()
        
        # Only keep note-off events that occur at or after the first note-on
        for i in range(len(self.notes_off)):
            if self.notes_off.ticks[i] >= first_note_on_tick:
                pad_idx, midi_channel = unpack_pad_channel(self.notes_off.packed_pad_channel[i])
                new_notes_off.add_event(
                    self.notes_off.notes[i],
                    self.notes_off.velocities[i],
                    pad_idx,
                    self.notes_off.ticks[i],
                    midi_channel
                )
        self.notes_off = new_notes_off

    def _trim_silence_start(self):
        first_event_tick = None
        if len(self.notes_on) > 0:
            first_event_tick = self.notes_on.ticks[0]
        
        if len(self.cc_events) > 0:
            cc_first_tick = self.cc_events.ticks[0]
            if first_event_tick is None or cc_first_tick < first_event_tick:
                first_event_tick = cc_first_tick
    
        if first_event_tick is None or first_event_tick == 0:
            return
        try:
            for i in range(len(self.notes_on)):
                if self.notes_on.ticks[i] >= first_event_tick:  # Ensure we don't create negative values
                    self.notes_on.ticks[i] -= first_event_tick
                else:
                    self.notes_on.ticks[i] = 0

            for i in range(len(self.notes_off)):
                if self.notes_off.ticks[i] >= first_event_tick:
                    self.notes_off.ticks[i] -= first_event_tick
                else:
                    self.notes_off.ticks[i] = 0

            for i in range(len(self.cc_events)):
                if self.cc_events.ticks[i] >= first_event_tick:
                    self.cc_events.ticks[i] -= first_event_tick
                else:
                    self.cc_events.ticks[i] = 0

            if self.total_midi_ticks > first_event_tick:
                self.total_midi_ticks -= first_event_tick

        except Exception as e:
            if settings.debug:
                print("[ERROR] in _trim_silence_start:", e)
            display.show_notification("[ERR] trimming silence")
    
    def trim_loaded_ccs(self):
        if len(self.notes_on) > 0 or len(self.cc_events) == 0: # Only trim if CC only loop.
            return

        total_ticks = clock.seconds_to_ticks(C.CC_ONLY_LOOP_LENGTH_SECONDS, self.recording_bpm)
        self.total_midi_ticks = total_ticks
        self.total_time_seconds = C.CC_ONLY_LOOP_LENGTH_SECONDS
    
    def _trim_silence_end(self):
        if len(self.notes_on) == 0:
            return
            
        # Find the last event tick
        last_event_ticks = 0
        if len(self.notes_off) > 0:
            note_off_len = len(self.notes_off.ticks)
            last_note_off_ticks = self.notes_off.ticks[note_off_len - 1]
            last_event_ticks = last_note_off_ticks

        if len(self.cc_events) > 0:
            cc_len = len(self.cc_events.ticks)
            last_cc_ticks = self.cc_events.ticks[cc_len - 1]
            if last_cc_ticks > last_event_ticks:
                last_event_ticks = last_cc_ticks

        self.total_midi_ticks = last_event_ticks + 1

        # Handle missing off notes
        if len(self.notes_on) != len(self.notes_off):
            for i, note in enumerate(self.notes_on.notes):
                has_off = False
                for off_note in self.notes_off.notes:
                    if off_note == note:
                        has_off = True
                        break
                if not has_off:
                    padidx, midi_channel = unpack_pad_channel(self.notes_on.packed_pad_channel[i])
                    self.notes_off.add_event(note, 0, padidx, self.total_midi_ticks - 1, midi_channel)

    def trim_silence(self):
        """Trim silence at start/end based on settings.trim_silence_mode."""
        # Only CCs - always trim both start and end
        if len(self.notes_on) == 0 and len(self.cc_events) > 0:
            self._trim_silence_start()
            self._trim_silence_end()
            return
        
        if len(self.notes_on) == 0:
            return

        if len(self.notes_off) > 0:
            self._remove_leading_off_notes()

        trim_mode = settings.trim_silence_mode

        if trim_mode == "none":
            return
        if trim_mode in ["start", "both"]:
            self._trim_silence_start()
        if trim_mode in ["end", "both"]:
            self._trim_silence_end()

    def _handle_loop_end(self):
        if self.loop_type == "loop":
            self.reset()

        if self.loop_type == "oneshot":
            self.toggle_playstate(False)

    def _process_cc_queue_flash(self, current_ticks, queue_index, new_events, is_midi_sync=False):
        """Process CC events from flash cache. Returns updated queue_index."""
        if not self.cc_cache:
            return queue_index
        
        while queue_index < self.cc_cache.event_count:
            event = self.cc_cache.get_event(queue_index)
            if event is None:
                break
            cc_num, value, tick, channel = event
            
            if is_midi_sync:
                comparison = current_ticks >= tick
            else:
                comparison = tick <= current_ticks
            
            if comparison:
                new_events.append((cc_num, value, channel))
                queue_index += 1
            else:
                break
        
        return queue_index

    def _process_event_queue(self, current_ticks, queue_index, event_storage, new_events, is_note_on=False, is_note_off=False, is_midi_sync=False):
        """Process event queue and collect events at current tick. Returns updated queue_index."""
        events_len = len(event_storage)
        if is_midi_sync:
            if queue_index < events_len:
                tick = event_storage.ticks[queue_index]

        while queue_index < events_len:
            tick = event_storage.ticks[queue_index]
            
            comparison_result = False
            if not is_midi_sync:
                comparison_result = tick <= current_ticks
            else:
                comparison_result = current_ticks >= tick
                
            if comparison_result:
                if is_note_on or is_note_off:
                    note = event_storage.notes[queue_index]
                    vel = event_storage.velocities[queue_index]
                    padidx, stored_midi_channel = unpack_pad_channel(event_storage.packed_pad_channel[queue_index])
                    # Pass stored channel as the chord index for channel routing in playback
                    new_events.append((note, vel, padidx, stored_midi_channel))
                    if is_note_on:
                        pixels.set_note_on(padidx)
                    elif is_note_off:
                        pixels.set_note_off(padidx)
                else:  # CC events
                    cc_num = event_storage.cc_nums[queue_index]
                    cc_val = event_storage.values[queue_index]
                    stored_midi_channel = event_storage.midi_channels[queue_index]
                    new_events.append((cc_num, cc_val, stored_midi_channel))
                
                queue_index += 1
            else:
                break
                 
        return queue_index

    def get_new_events(self):
        """Get notes and CCs to play at current position. Returns (on, off, cc) or None."""
        # ===== EARLY EXIT CONDITIONS =====
        if not self.total_time_seconds > 0 or not self.loop_is_playing:
            return None
        
        # Check if we have any events (RAM or flash)
        has_cc_events = len(self.cc_events) > 0 or (self.cc_cache and self.cc_cache.event_count > 0)
        if (len(self.notes_on) == 0 and len(self.notes_off) == 0 and not has_cc_events):
            return None
            
        if len(self.notes_on) == 0 and self.ccs_complete:
            self.toggle_playstate(False)
            return None
        
        # ===== INITIALIZE EVENT ARRAYS =====
        new_notes_on = []
        new_notes_off = []
        new_cc_events = []
        
        # ===== ONESHOT IMMEDIATE EVENTS =====
        # Process CC events for oneshot mode
        if self.loop_type == "oneshot" and not self.ccs_complete:
            self.ccs_complete = True
            if len(self.cc_oneshot) > 0:
                for cc_num, cc_val, stored_channel in self.cc_oneshot:
                    new_cc_events.append((cc_num, cc_val, stored_channel))
                    
        # Process notes_all_at_once for oneshot mode
        if settings.notes_all_at_once and self.loop_type == "oneshot" and not self.note_ons_complete:
            if len(self.notes_oneshot) > 0:
                for note in self.notes_oneshot:
                    new_notes_on.append(note)
            self.note_ons_complete = True

        # ===== COMPLETION STATUS TRACKING =====
        if settings.notes_all_at_once and self.loop_type == "oneshot":
            self.note_offs_complete = self.queue_idx_oneshot_offs >= len(self.oneshot_note_offs)
        else:
            if not self.note_ons_complete and self.queue_index_notes_on >= len(self.notes_on):
                self.note_ons_complete = True
            if not self.note_offs_complete and self.queue_index_notes_off >= len(self.notes_off):
                self.note_offs_complete = True

        # Early exit for completed oneshot loops
        if self.loop_type == "oneshot":
            notes_completed = len(self.notes_on) == 0 or (self.note_ons_complete and self.note_offs_complete)
            ccs_completed = len(self.cc_events) == 0 or self.ccs_complete
            if notes_completed and ccs_completed:
                self.toggle_playstate(False)
                return new_notes_on, new_notes_off, new_cc_events

        # ===== TIMING CALCULATION =====
        if settings.midi_sync and clock.new_tick:
            self.current_midi_ticks += 1

        now_time = ticks.ticks_ms()
        self.current_loop_time = ticks.ticks_diff(now_time, self.start_timestamp) / 1000.0
        
        if settings.midi_sync:
            current_ticks = self.current_midi_ticks
            if current_ticks >= self.total_midi_ticks:
                self._handle_loop_end()
                return None
        else:
            current_ticks = clock.seconds_to_ticks(self.current_loop_time, self.recording_bpm)
            if current_ticks >= self.total_midi_ticks or self.current_loop_time >= self.total_time_seconds:
                self._handle_loop_end()
                return None
    
        # ===== TIMED EVENT PROCESSING =====
        # Process note-on events (skip if using notes_all_at_once in oneshot mode)
        if not (settings.notes_all_at_once and self.loop_type == "oneshot") and not self.note_ons_complete:
            self.queue_index_notes_on = self._process_event_queue(
                current_ticks, 
                self.queue_index_notes_on,
                self.notes_on,
                new_notes_on,
                is_note_on=True,
                is_midi_sync=settings.midi_sync
            )

        # Process oneshot note-offs with individual timing
        if settings.notes_all_at_once and self.loop_type == "oneshot" and self.queue_idx_oneshot_offs < len(self.oneshot_note_offs):
            while self.queue_idx_oneshot_offs < len(self.oneshot_note_offs):
                note, vel, pad_idx, tick_offset, stored_channel = self.oneshot_note_offs[self.queue_idx_oneshot_offs]
                if current_ticks >= tick_offset:
                    new_notes_off.append((note, vel, pad_idx, stored_channel))
                    pixels.set_note_off(pad_idx)
                    self.queue_idx_oneshot_offs += 1
                else:
                    break

        # Process regular note-off events (skip if using notes_all_at_once in oneshot mode)
        if not (settings.notes_all_at_once and self.loop_type == "oneshot"):
            self.queue_index_notes_off = self._process_event_queue(
                current_ticks,
                self.queue_index_notes_off,
                self.notes_off,
                new_notes_off,
                is_note_off=True,
                is_midi_sync=settings.midi_sync
            )
        
        # Process CC events (skip if already sent in oneshot mode)
        if not self.ccs_complete or self.loop_type != "oneshot":
            # Phase 3: Use flash cache if available and flag enabled
            if USE_FLASH_CC_PLAYBACK and self.cc_cache:
                self.queue_index_cc = self._process_cc_queue_flash(
                    current_ticks,
                    self.queue_index_cc,
                    new_cc_events,
                    is_midi_sync=settings.midi_sync
                )
            else:
                # Original RAM-based path
                self.queue_index_cc = self._process_event_queue(
                    current_ticks,
                    self.queue_index_cc,
                    self.cc_events,
                    new_cc_events,
                    is_midi_sync=settings.midi_sync
                )
        
        # ===== RETURN RESULTS =====
        if new_notes_on or new_notes_off or new_cc_events:
            return new_notes_on, new_notes_off, new_cc_events
        
        return None
    
    def create_oneshot_ccs(self):
        latest_cc_values = {}
        
        # Phase 4: Read from flash if RAM CC storage is empty
        if len(self.cc_events) == 0 and self.cc_file_path:
            events = read_all_cc_events(self.cc_file_path)
            for cc_num, cc_val, cc_tick, cc_midi_channel in events:
                if cc_num not in latest_cc_values or cc_tick >= latest_cc_values[cc_num][1]:
                    latest_cc_values[cc_num] = (cc_val, cc_tick, cc_midi_channel)
        else:
            # Original RAM-based logic
            for i in range(len(self.cc_events)):
                cc_num = self.cc_events.cc_nums[i]
                cc_val = self.cc_events.values[i]
                cc_tick = self.cc_events.ticks[i]
                cc_midi_channel = self.cc_events.midi_channels[i]
                
                if cc_num not in latest_cc_values or cc_tick >= latest_cc_values[cc_num][1]:
                    latest_cc_values[cc_num] = (cc_val, cc_tick, cc_midi_channel)

        # Convert the dictionary to our final list format
        oneshot_ccs = [(cc_num, val_tick[0], val_tick[2]) for cc_num, val_tick in latest_cc_values.items()]
        
        self.cc_oneshot = oneshot_ccs
        return oneshot_ccs

    def update_oneshot_notes(self):
        """Create unique notes list and matching note-offs for oneshot mode."""
        seen = set()
        self.unique_notes = []
        
        # Create unique notes list (existing logic)
        for i in range(len(self.notes_on)):
            note = self.notes_on.notes[i]
            velocity = self.notes_on.velocities[i]
            pad_idx, stored_midi_channel = unpack_pad_channel(self.notes_on.packed_pad_channel[i])
            # Use stored channel as the assigned channel for oneshot mode
            note_tuple = (note, velocity, pad_idx, stored_midi_channel)
            if note_tuple not in seen:
                seen.add(note_tuple)
                self.unique_notes.append(note_tuple)
        
        self.notes_oneshot = self.unique_notes
        
        # Create matching note-offs with timing
        self.oneshot_note_offs = []
        
        for note, vel, pad_idx, stored_channel in self.unique_notes:
            first_note_on_tick = None
            for i in range(len(self.notes_on)):
                stored_pad_idx, _ = unpack_pad_channel(self.notes_on.packed_pad_channel[i])
                if (self.notes_on.notes[i] == note and 
                    self.notes_on.velocities[i] == vel and 
                    stored_pad_idx == pad_idx):
                    first_note_on_tick = self.notes_on.ticks[i]
                    break
            
            if first_note_on_tick is None:
                continue
                
            # Find first matching note-off that occurs after this note-on
            matching_note_off_tick = None
            for i in range(len(self.notes_off)):
                if (self.notes_off.notes[i] == note and 
                    self.notes_off.ticks[i] > first_note_on_tick):
                    matching_note_off_tick = self.notes_off.ticks[i]
                    break
            
            # Calculate timing offset relative to this individual note-on
            if matching_note_off_tick is not None:
                tick_offset = matching_note_off_tick - first_note_on_tick
            else:
                tick_offset = self.total_midi_ticks - first_note_on_tick if self.total_midi_ticks > first_note_on_tick else 1
            tick_offset = max(1, tick_offset)
            self.oneshot_note_offs.append((note, 0, pad_idx, tick_offset, stored_channel))
        
        self.oneshot_note_offs.sort(key=lambda x: x[3])

    def quantize_loop(self):
        """Quantize loop length to musical bar divisions based on settings.quantize_loop."""
        amount = settings.quantize_loop
        if amount == "none":
            return

        ticks_per_quarter_note = 24  # Standard MIDI Clock ticks per quarter note
        quantization_ticks = int(ticks_per_quarter_note * 4 * float(amount))
        
        num_quant_units = max(1, math.ceil(self.total_midi_ticks / quantization_ticks))
        new_total_ticks = num_quant_units * quantization_ticks
        self.total_midi_ticks = new_total_ticks
        self.total_time_seconds = clock.ticks_to_seconds(self.total_midi_ticks, self.recording_bpm)
        
    def quantize_events(self):
        if settings.quantize_time == "none":
            return
    
        ticks_per_quantization_unit = clock.seconds_to_ticks(
            clock.get_note_duration_seconds(settings.quantize_time), self.recording_bpm
        )
        quantization_percent = get_quantization_percent()

        if len(self.notes_on) > 0:
            for i in range(len(self.notes_on)):
                original_tick = self.notes_on.ticks[i]
                new_tick_count = _calculate_quantized_tick(
                    original_tick, quantization_percent, ticks_per_quantization_unit
                )
                self.notes_on.ticks[i] = new_tick_count

        if len(self.notes_off) > 0:
            for i in range(len(self.notes_off)):
                original_tick = self.notes_off.ticks[i]
                new_tick_count = _calculate_quantized_tick(
                    original_tick, quantization_percent, ticks_per_quantization_unit
                )
                self.notes_off.ticks[i] = new_tick_count
            
        if settings.quantize_cc and len(self.cc_events) > 0:
            for i in range(len(self.cc_events)):
                original_tick = self.cc_events.ticks[i]
                new_tick_count = _calculate_quantized_tick(
                    original_tick, quantization_percent, ticks_per_quantization_unit
                )
                self.cc_events.ticks[i] = new_tick_count

        free_memory()

    def change_loop_mode(self, mode=""):
        """Set or toggle loop mode between 'oneshot' and 'loop'."""
        if mode and mode in ["oneshot", "loop"]:
            self.loop_type = mode
        else:
            self.loop_type = "oneshot" if self.loop_type == "loop" else "loop"
        self.reset()
        return self.loop_type

    def get_unique_notes(self):
        return self.unique_notes
    
    def get_unique_ccs(self):
        """Get CC min/max value pairs in chronological order."""
        # Phase 4: Return cached result if available (avoids flash reads in hot path)
        if self.cached_unique_ccs:
            return self.cached_unique_ccs
        return self._compute_unique_ccs()
    
    def _compute_unique_ccs(self):
        """Compute CC min/max value pairs. Called once at recording stop."""
        cc_ranges = {}  # {cc_num: {'min': value, 'max': value, 'min_idx': idx, 'max_idx': idx}}
        
        # Phase 4: Read from flash if RAM CC storage is empty
        if len(self.cc_events) == 0 and self.cc_file_path:
            events = read_all_cc_events(self.cc_file_path)
            for i, (cc_num, cc_value, _, cc_channel) in enumerate(events):
                if cc_num not in cc_ranges:
                    cc_ranges[cc_num] = {
                        'min': cc_value, 'max': cc_value,
                        'min_idx': i, 'max_idx': i,
                        'min_ch': cc_channel, 'max_ch': cc_channel
                    }
                else:
                    if cc_value < cc_ranges[cc_num]['min']:
                        cc_ranges[cc_num]['min'] = cc_value
                        cc_ranges[cc_num]['min_idx'] = i
                        cc_ranges[cc_num]['min_ch'] = cc_channel
                    if cc_value > cc_ranges[cc_num]['max']:
                        cc_ranges[cc_num]['max'] = cc_value
                        cc_ranges[cc_num]['max_idx'] = i
                        cc_ranges[cc_num]['max_ch'] = cc_channel
            
            # Build result from flash data
            unique_ccs = []
            for cc_num, r in cc_ranges.items():
                if r['min'] == r['max']:
                    unique_ccs.append((cc_num, r['min'], r['min_ch']))
                elif r['min_idx'] < r['max_idx']:
                    unique_ccs.append((cc_num, r['min'], r['min_ch']))
                    unique_ccs.append((cc_num, r['max'], r['max_ch']))
                else:
                    unique_ccs.append((cc_num, r['max'], r['max_ch']))
                    unique_ccs.append((cc_num, r['min'], r['min_ch']))
            return unique_ccs
        
        # Original RAM-based logic
        # Find min and max values for each CC number and track their positions
        for i in range(len(self.cc_events)):
            cc_num = self.cc_events.cc_nums[i]
            cc_value = self.cc_events.values[i]
            
            if cc_num not in cc_ranges:
                cc_ranges[cc_num] = {
                    'min': cc_value, 
                    'max': cc_value,
                    'min_idx': i,
                    'max_idx': i
                }
            else:
                if cc_value < cc_ranges[cc_num]['min']:
                    cc_ranges[cc_num]['min'] = cc_value
                    cc_ranges[cc_num]['min_idx'] = i
                if cc_value > cc_ranges[cc_num]['max']:
                    cc_ranges[cc_num]['max'] = cc_value
                    cc_ranges[cc_num]['max_idx'] = i
        
        # Build result list preserving chronological order
        unique_ccs = []
        for cc_num, range_info in cc_ranges.items():
            min_val = range_info['min']
            max_val = range_info['max']
            min_idx = range_info['min_idx']
            max_idx = range_info['max_idx']
            min_channel = self.cc_events.midi_channels[min_idx]
            max_channel = self.cc_events.midi_channels[max_idx]
            
            # If min and max are the same, just add one entry
            if min_val == max_val:
                unique_ccs.append((cc_num, min_val, min_channel))
            else:
                # Add min and max in the order they occurred
                if min_idx < max_idx:
                    unique_ccs.append((cc_num, min_val, min_channel))
                    unique_ccs.append((cc_num, max_val, max_channel))
                else:
                    unique_ccs.append((cc_num, max_val, max_channel))
                    unique_ccs.append((cc_num, min_val, min_channel))
        
        return unique_ccs

def set_next_or_prev_quantization(up_or_down=True):
    settingsmenu.set_next_or_prev_quantization_time(up_or_down)

def get_quantization_text():
    return f"Qnt: {settings.quantize_time}"

def get_quantization_display_value():
    return settings.quantize_time

def set_quantization_percent(up_or_down=True):
    settings.quantize_strength = next_or_previous_index(
        settings.quantize_strength, 100, up_or_down, False
    )

def get_quantization_percent(return_integer=False):
    if return_integer:
        return settings.quantize_strength
    return settings.quantize_strength / 100

def make_midi_loop(loop_type="loop", pad_idx=C.DEFAULT_CHORDPAD_IDX):
    return MidiLoop(loop_type=loop_type, assigned_pad_idx=pad_idx)

def write_pad_events_csv(loop, pad_idx, f):
    f.write(f"##PAD{pad_idx}##\n")
    f.write("#METADATA#\n")
    f.write(f"loop_type,{loop.loop_type}\n")
    f.write(f"ticks,{loop.total_midi_ticks}\n")
    f.write(f"time,{loop.total_time_seconds}\n")
    f.write(f"bpm,{loop.recording_bpm}\n")
    f.write("#NOTES_ON#\n")
    for i in range(len(loop.notes_on)):
        n = loop.notes_on.notes[i]
        v = loop.notes_on.velocities[i]
        pad_i, midi_ch = unpack_pad_channel(loop.notes_on.packed_pad_channel[i])
        t = loop.notes_on.ticks[i]
        f.write(f"{n},{v},{pad_i},{t},{midi_ch}\n")
    f.write("#NOTES_OFF#\n")
    for i in range(len(loop.notes_off)):
        n = loop.notes_off.notes[i]
        v = loop.notes_off.velocities[i]
        pad_i, midi_ch = unpack_pad_channel(loop.notes_off.packed_pad_channel[i])
        t = loop.notes_off.ticks[i]
        f.write(f"{n},{v},{pad_i},{t},{midi_ch}\n")
    f.write("#CC#\n")
    for i in range(len(loop.cc_events)):
        c = loop.cc_events.cc_nums[i]
        v = loop.cc_events.values[i]
        t = loop.cc_events.ticks[i]
        midi_ch = loop.cc_events.midi_channels[i]
        f.write(f"{c},{v},{t},{midi_ch}\n")