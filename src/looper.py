# Global setting for oneshot notes behavior
from debug import free_memory  
free_memory()
import math
import array  # Added for array-based storage
from utils import next_or_previous_index
from midi import midi

import adafruit_ticks as ticks
from clock import clock
from display import display
from pixels import pixels
free_memory()
from settings import settings
import settingsmenu
import constants
from constants import DEFAULT_CHORDPAD_IDX

# Constants for debug strings to save memory
DEBUG_STR_NUM_NOTES = "num notes in looper:"

# Helper function for quantizing moved outside of method to avoid recreation
def _calculate_quantized_tick(tick_count, quantization_percent, ticks_per_quantization_unit):
    """Helper function to quantize tick values."""

    if ticks_per_quantization_unit <= 0:
        return tick_count

    tick_remainder = tick_count % ticks_per_quantization_unit
    if tick_remainder > ticks_per_quantization_unit / 2:
        tick_update = int((ticks_per_quantization_unit - tick_remainder) * quantization_percent)
        new_ticks = tick_count + tick_update
    else:
        tick_update = int(tick_remainder * quantization_percent)
        new_ticks = tick_count - tick_update
    
    return new_ticks

# Array-based storage classes for memory optimization
class ArrayBasedEventStorage:
    # Efficient array-based storage for MIDI note events to reduce memory usage
    def __init__(self):
        self.notes = array.array('B', [])        # MIDI note numbers (0-127)
        self.velocities = array.array('B', [])   # Note velocities (0-127)
        self.pad_indices = array.array('B', [])  # Source pad indices (0-15)
        self.ticks = array.array('H', [])        # Tick positions (0-65535)
        self.chord_index = array.array('B', [])  # Chord indices (0-15) for chord loops
        
    def add_event(self, note, velocity, pad_idx, tick, chord_idx=DEFAULT_CHORDPAD_IDX):
        """Adds a new note event to storage."""
        if tick > 65535: #unsigned short limit
            tick = 65535
            
        self.notes.append(note)
        self.velocities.append(velocity)
        self.pad_indices.append(pad_idx)
        self.ticks.append(tick)
        self.chord_index.append(chord_idx)
    
    def get_event(self, idx):
        """Returns event data as a tuple for compatibility with list-based code."""
        if idx < 0:
            idx = len(self.notes) + idx # Handle negative indexing for compatibility
        return (self.notes[idx], self.velocities[idx], 
                self.pad_indices[idx], self.ticks[idx], self.chord_index[idx])
                
    def __len__(self):
        """Returns the number of events in storage."""
        return len(self.notes)
        
    def clear(self):
        """Clears all event data from storage."""
        self.notes = array.array('B', [])
        self.velocities = array.array('B', [])
        self.pad_indices = array.array('B', [])
        self.ticks = array.array('H', [])
        self.chord_index = array.array('B', [])
        
    def __getitem__(self, idx):
        """Enables direct indexing with brackets for compatibility with list-based code."""
        return self.get_event(idx)
        
    def append(self, event_tuple, chord_idx):
        """Adds an event from a tuple for backward compatibility."""
        note, vel, padidx, tick = event_tuple
        self.add_event(note, vel, padidx, tick, chord_idx)

class ArrayBasedCCStorage:
    # Efficient array-based storage for MIDI CC events to reduce memory usage
    def __init__(self):
        self.cc_nums = array.array('B', [])      # CC numbers (0-127)
        self.values = array.array('B', [])       # CC values (0-127)
        self.ticks = array.array('H', [])        # Tick positions (0-65535)
        self.chord_index = array.array('B', [])  # Chord indices for chord loops
        
    def add_event(self, cc_num, value, tick, chord_idx=DEFAULT_CHORDPAD_IDX):
        """Adds a new CC event to storage."""
        if tick > 65535: #unsigned short limit
            tick = 65535
            
        self.cc_nums.append(cc_num)
        self.values.append(value)
        self.ticks.append(tick)
        self.chord_index.append(chord_idx)  # Default chord index for CC events
        
    def get_event(self, idx):
        """Returns CC event data as a tuple for compatibility with list-based code."""
        if idx < 0:
            # Handle negative indexing for compatibility
            idx = len(self.cc_nums) + idx
        return (self.cc_nums[idx], self.values[idx], self.ticks[idx], self.chord_index[idx])
        
    def __len__(self):
        """Returns the number of CC events in storage."""
        return len(self.cc_nums)
        
    def clear(self):
        """Clears all CC event data from storage."""
        self.cc_nums = array.array('B', [])
        self.values = array.array('B', [])
        self.ticks = array.array('H', [])
        self.chord_index = array.array('B', [])
        
    def __getitem__(self, idx):
        """Enables direct indexing with brackets for compatibility with list-based code."""
        return self.get_event(idx)
        
    def append(self, event_tuple, chord_idx):
        """Adds an event from a tuple for backward compatibility."""
        cc_num, value, tick = event_tuple
        self.add_event(cc_num, value, tick, chord_idx)

class MidiLoop:
    # Handles recording, playback and manipulation of MIDI note and CC event loops
    def __init__(self, loop_type="loop", assigned_pad_idx=DEFAULT_CHORDPAD_IDX):
        """
        Initializes a MIDI loop with specified type and pad assignment.
        
        Args:
            loop_type (str): Loop behavior type ("loop", "oneshot", "chordloop")
            assigned_pad_idx (int): Index of pad this loop is assigned to
        """
        # Basic loop configuration
        self.loop_type = loop_type                   # Type of loop behavior
        self.assigned_pad_idx = assigned_pad_idx     # Pad index this loop is assigned to
        
        # Timing properties
        self.start_timestamp = 0                     # Real-time loop start timestamp (ms)
        self.start_tickstamp = 0                     # MIDI tick count at loop start
        self.total_time_seconds = 0                  # Total loop duration in seconds
        self.current_loop_time = 0                   # Current playback position in seconds
        self.total_midi_ticks = 0                    # Total loop duration in MIDI ticks
        self.current_midi_ticks = 0                  # Current playback position in MIDI ticks
        self.recording_bpm = clock.bpm_current       # BPM when loop was recorded
        
        # Event storage
        self.notes_on = ArrayBasedEventStorage()     # Note-on events
        self.notes_off = ArrayBasedEventStorage()    # Note-off events 
        self.cc_events = ArrayBasedCCStorage()       # CC events
        self.cc_oneshot = []                         # CC events for oneshot mode (one per CC#)
        self.notes_oneshot = []                      # Note events for oneshot mode
        self.stuck_on_notes = []                     # Notes that are on but not yet off
        
        # Playback queue indices
        self.queue_index_notes_on = 0                # Current position in notes_on
        self.queue_index_notes_off = 0               # Current position in notes_off
        self.queue_index_cc = 0                      # Current position in cc_events
        
        # State flags
        self.loop_is_playing = False                 # Whether loop is currently playing
        self.is_recording = False                    # Whether loop is currently recording
        self.has_loop = False                        # Whether loop contains any events
        self.all_ccs_sent = True                     # Whether all CCs have been sent in oneshot mode
        self.all_notes_sent = False                  # Whether all notes have been sent in oneshot mode
        self.max_events_reached = False              # Whether event limit has been reached

    def reset(self):
        """
        Resets the loop to its initial state for playback.
        
        - Clears any playing notes and resets pixel displays
        - Synchronizes with MIDI clock if enabled
        - Resets queue position indices and playback state flags
        - Sets up timestamps for proper playback timing
        """
        # Clear all current playback state
        self.clear_notes_and_pixels()
        
        # Sync with MIDI clock if enabled
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
        self.current_midi_ticks = 0
        
        # Reset state flags
        self.all_ccs_sent = False    # Ensure CCs are sent on next playback
        self.all_notes_sent = False  # Ensure notes are sent on next playback
        
        # Configure timing for playback
        if settings.midi_sync and clock.is_playing:
            self.current_midi_ticks = 0 - ticks_until_next_quarter  # Start on next quarter note
        self.start_tickstamp = clock.midi_ticks_elapsed
        self.start_timestamp = ticks.ticks_ms()


    def clear_notes_and_pixels(self):
        """
        Turns off all unique notes and pixels in the loop.
        """
        unique_notes = set()
        unique_pixels = set()
        
        # Get unique notes
        for i in range(len(self.notes_on)):
            unique_notes.add(self.notes_on.notes[i])  # note number
            unique_pixels.add(self.notes_on.pad_indices[i])  # pad index

        # Send note-off, pixel offs
        for note in unique_notes:
            midi.send_note_off(note, self.assigned_pad_idx)
        for pixel in unique_pixels:
            pixels.set_note_off(pixel)

    def clear(self):
        """
        Clears all recorded notes, CC messages and resets loop attributes.
        """
        self.clear_notes_and_pixels()
        
        # Clear event arrays
        self.notes_on.clear()
        self.notes_off.clear()
        self.cc_events.clear()
        self.cc_oneshot.clear()
        
        # Reset states / timing
        self.total_time_seconds = 0
        self.start_timestamp = 0
        self.current_midi_ticks = 0
        self.total_midi_ticks = 0
        self.toggle_playstate(False)
        self.toggle_record_state(False)
        self.current_loop_time = 0
        self.has_loop = False

        display.show_notification("Loop Cleared")
        free_memory()

    def reset_timing(self):
        """
        Resets the timing-related attributes to their initial state.
        """
        self.start_timestamp = 0
        self.start_tickstamp = 0
        self.current_midi_ticks = 0
        self.clear_notes_and_pixels()
    
    def toggle_playstate(self, on_or_off=None):
        """
        Toggles loop play state on or off.
        """
        self.loop_is_playing = on_or_off if on_or_off is not None else not self.loop_is_playing
        self.current_loop_time = 0
        assigned_pad_idx = self.assigned_pad_idx

        if self.loop_type in ["chordloop", "oneshot"]:
            # Playing
            if self.loop_is_playing:
                self.reset()
                if 0 <= assigned_pad_idx <= 15:
                    pixels.set_color(assigned_pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                    pixels.set_default_color(assigned_pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
            # Stopping
            else:                   
                self.reset_timing()
                if 0 <= assigned_pad_idx <= 15:
                    pixels.set_color(assigned_pad_idx, constants.CHORD_COLOR)
                    pixels.set_default_color(assigned_pad_idx, constants.CHORD_COLOR)

    def toggle_record_state(self, on_or_off=None):
        """
        Toggles loop recording state on or off.
        """
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
                                      or self.loop_type in ["oneshot", "chordloop"]):
            if self.total_time_seconds < 0.1:
                if len(self.stuck_on_notes) > 0:
                    for note in self.stuck_on_notes:
                        self.add_note(note, 0, 0, False, True)
                    self.stuck_on_notes = []
                  
                # Find the last event timestamp
                last_tick = 0
                if len(self.notes_off) > 0:
                    last_tick = max(last_tick, self.notes_off[-1][3])
                if len(self.cc_events) > 0:
                    last_tick = max(last_tick, self.cc_events[-1][2])
                
                # Calculate loop duration
                time_from_ticks = clock.ticks_to_seconds(last_tick, self.recording_bpm)
                time_from_elapsed = ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0
                print(f"Time from ticks: {time_from_ticks}, Time from elapsed: {time_from_elapsed}")
                self.total_time_seconds = max(time_from_ticks, time_from_elapsed)
                self.total_midi_ticks = last_tick + 1
            
            # Handle MIDI sync playback state    
            if settings.midi_sync and not clock.get_playstate():
                self.toggle_playstate(False)
            
            # --- POST-PROCESSING ---
            self.trim_silence()       # Remove silence at beginning/end
            self.quantize_events()    # Align events to grid
            self.quantize_loop()      # Adjust loop length to musical boundary
            self.create_oneshot_ccs() 
            self._update_oneshot_notes()


  
    def add_note(self, midi_note, velocity, padidx, add_or_remove, force_add=False):
        """
        Adds a note to the loop.

        Args:
            midi_note (int): MIDI note number.
            velocity (int): Velocity of the note.
            padidx (int): Index of the pad.
            add_or_remove (bool): True to add note to the ON queue, False to add note to the OFF queue.
            force_add (bool): Force add the note even if recording is off.
        """
        if not self.is_recording and not force_add:
            return

        if not force_add and self.start_timestamp == 0:
            display.show_notification("Play loop to record")
            self.toggle_record_state(False)
            return
        
        free_memory()

        # --- TIMING CALCULATION ---
        # Calculate tick position from elapsed time
        tick_count = clock.seconds_to_ticks(
            ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0, self.recording_bpm)
        
        if len(self.notes_on) > constants.LOOP_NOTES_LIMIT:    
            display.show_notification("MAX NOTES REACHED")
            self.max_events_reached = True # Event limit flag
            return

        # --- CHORD ASSIGNMENT ---
        # Ensure valid chord index for storage
        chord_idx = self.assigned_pad_idx
        if chord_idx < 0 or chord_idx > 15:
            chord_idx = DEFAULT_CHORDPAD_IDX

        # Add
        if add_or_remove:
            if not self.has_loop:
                self.has_loop = True
            self.notes_on.add_event(midi_note, velocity, padidx, tick_count,chord_idx)
            self.stuck_on_notes.append(midi_note)

        # Remove
        else:
            self.notes_off.add_event(midi_note, velocity, padidx, tick_count,chord_idx)
            if midi_note in self.stuck_on_notes:
                self.stuck_on_notes.remove(midi_note)
            
        # Periodic memory management
        if len(self.notes_on) % 10 == 0:
            free_memory()

    def has_events(self):
        """
        Returns True if the loop has any note or CC events, False otherwise.
        """
        return (len(self.notes_on) + len(self.cc_events)) > 0
    
    def remove_note(self, idx):
        """
        Removes a note from the loop record at the specified index.
        """
        if 0 <= idx < len(self.notes_on):
            self.notes_on.notes.pop(idx)
            self.notes_on.velocities.pop(idx)
            self.notes_on.pad_indices.pop(idx)
            self.notes_on.ticks.pop(idx)
            self.notes_on.chord_index.pop(idx)
            if idx < len(self.notes_off):
                self.notes_off.notes.pop(idx)
                self.notes_off.velocities.pop(idx)
                self.notes_off.pad_indices.pop(idx)
                self.notes_off.ticks.pop(idx)
                self.notes_off.chord_index.pop(idx)

    def add_cc(self, cc_num, cc_value):
        """
        Adds a MIDI CC event to the loop.

        Args:
            cc_num (int): MIDI CC number.
            cc_value (int): Value of the MIDI CC.

        The CC event is only recorded if:
        - It's the first value ever received for this CC number
        - OR if we've seen this CC number before, the new value differs from
          the last recorded value by more than CC_VALUE_THRESHOLD
        """
        if not self.is_recording:
            return

        if self.start_timestamp == 0:
            display.show_notification("Play loop to record")
            self.toggle_record_state(False)
            return

        cc_events_length = len(self.cc_events)
        if cc_events_length >= constants.CC_EVENTS_LIMIT:
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

        chord_idx = self.assigned_pad_idx
        if chord_idx < 0 or chord_idx > 15:
            chord_idx = DEFAULT_CHORDPAD_IDX

        # --- CC RECORDING ---
        # Only record if it's a new CC or has changed significantly
        if (last_cc_value is None and not found_previous_value) or \
           (found_previous_value and abs(cc_value - last_cc_value) > settings.cc_resolution):
            
            # Calculate Ticks from Time
            tick_count = clock.seconds_to_ticks(
                ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0, self.recording_bpm
            )
            
            if not self.has_loop:
                self.has_loop = True
            
            # Memory management
            if cc_events_length % 8 == 0:
                free_memory()
                    
            self.cc_events.add_event(cc_num, cc_value, tick_count, chord_idx)

    def _remove_leading_off_notes(self):
        """
        Removes any "note off" events that occur before the first "note on" event.
        """
        if len(self.notes_on) == 0 or len(self.notes_off) == 0:
            return
            
        first_note_on_tick = self.notes_on.ticks[0]
        new_notes_off = ArrayBasedEventStorage() # DJT AI - is this really the best way to do this?? a whole new array??
        
        # Only keep note-off events that occur at or after the first note-on
        for i in range(len(self.notes_off)):
            if self.notes_off.ticks[i] >= first_note_on_tick:
                new_notes_off.add_event(
                    self.notes_off.notes[i],
                    self.notes_off.velocities[i],
                    self.notes_off.pad_indices[i],
                    self.notes_off.ticks[i]
                    ,self.notes_off.chord_index[i]
                )
        self.notes_off = new_notes_off

    def _trim_silence_start(self):
        """
        Adjusts the timing of note and CC events in the looper by removing the initial 
        silence at the start of the recording.
        """
        # Find the earliest event tick across both notes and CCs
        first_event_tick = float('inf') # DJT AI - why are we doing it this way... has to be something simpler than infinite?

        if len(self.notes_on) > 0:
            first_event_tick = min(first_event_tick, self.notes_on.ticks[0])

        if len(self.cc_events) > 0:
            first_event_tick = min(first_event_tick, self.cc_events.ticks[0])
        
        # DJT AI - do we need this? Is this a real risk that the first tick is this large? Couldn't it be 0?
        # Safeguard: if the first event tick is very large or zero, don't perform trimming
        if first_event_tick >= 65535 or first_event_tick == 0:
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

        except Exception as e: # DJT AI - what would be a smarter thing to do here rather than pass or throw an error?
            pass
    
    def trim_loaded_ccs(self):
        """
        Used for preset loading code. Since we are only storing them as oneshots, update the loop
        length to some static value. Use the BPM and the static value to calculate the ticks.
        """
        if len(self.notes_on) > 0 or len(self.cc_events) == 0: # Only trim if CC only loop.
            return

        total_ticks = clock.seconds_to_ticks(constants.CC_ONLY_LOOP_LENGTH_SECONDS, self.recording_bpm)
        self.total_midi_ticks = total_ticks
        self.total_time_seconds = constants.CC_ONLY_LOOP_LENGTH_SECONDS
    
    def _trim_silence_end(self):
        """
        Trims silence at the end of the sequence by finding the latest event 
        (note-off or CC) and adjusting the total ticks accordingly.
        """

        if len(self.notes_on) == 0: #djt - might want to allow trimming silence even if no notes are present
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
                    padidx = self.notes_on.pad_indices[i]
                    self.notes_off.add_event(note, 0, padidx, self.total_midi_ticks - 1)

    def trim_silence(self):
        """
        Trims silence at the beginning and/or end of the loop based on the 
        configured trim_silence_mode in the settings.
        """

        # Only CCs - always trim both start and end
        if len(self.notes_on) == 0 and len(self.cc_events) > 0:
            self._trim_silence_start()
            self._trim_silence_end()
            free_memory()
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
        
        free_memory()

    def _handle_loop_end(self):
        """Reset or stop loop if needed."""

        if self.loop_type == "chordloop":
            self.reset()

        if self.loop_type == "oneshot":
            self.toggle_playstate(False)

    def _process_event_queue(self, current_ticks, queue_index, event_storage, new_events, is_note_on=False, is_note_off=False, is_midi_sync=False):
        """
        Helper function to process an event queue (notes_on, notes_off, or cc_events)
        and collect new events that should be triggered at the current tick position.
        
        Args:
            current_ticks: Current tick position in the loop
            queue_index: Current position in the queue (self.queue_index_*)
            event_storage: Array storage to process (self.notes_on, self.notes_off, self.cc_events)
            new_events: List to append new events to
            is_note_on: True if processing note-on events
            is_note_off: True if processing note-off events
            is_midi_sync: True if using MIDI sync mode, False for non-MIDI sync
            
        Returns:
            Updated queue index
        """
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
                    padidx = event_storage.pad_indices[queue_index]
                    new_events.append((note, vel, padidx, self.assigned_pad_idx))
                    if is_note_on:
                        pixels.set_note_on(padidx)
                    elif is_note_off:
                        pixels.set_note_off(padidx)
                else:  # CC events
                    cc_num = event_storage.cc_nums[queue_index]
                    cc_val = event_storage.values[queue_index]
                    new_events.append((cc_num, cc_val, self.assigned_pad_idx))
                
                queue_index += 1
            else:
                break
                 
        return queue_index

    def get_new_notes(self):
        """
        Checks for new notes and CC messages to be played based on loop position.

        Returns:
            tuple: (on_array, off_array, cc_array) containing new notes to play ON/OFF and CC messages
            None: if no new events need to be processed
        """
        # Consolidated early exit conditions - check these first for efficiency
        if (not self.total_time_seconds > 0 or not self.loop_is_playing or # DJT AI - too many booleans erwarning ror in vscode fix
            (len(self.notes_on) == 0 and len(self.notes_off) == 0 and len(self.cc_events) == 0) or
            (len(self.notes_off) < 1 and self.all_ccs_sent)):
            if len(self.notes_off) < 1 and self.all_ccs_sent:
                self.toggle_playstate(False)
            return None
        
        new_notes_on = []
        new_notes_off = []
        new_cc_events = []
        
        # Oneshot CC
        if (settings.notes_all_at_once or self.loop_type == "oneshot") and not self.all_ccs_sent:
            self.all_ccs_sent = True
            if len(self.cc_oneshot) > 0:
                for cc_num, cc_val in self.cc_oneshot:
                    new_cc_events.append((cc_num, cc_val, self.assigned_pad_idx))
                    
        # Oneshot Notes All At Once
        if settings.notes_all_at_once and not self.all_notes_sent:
            if len(self.notes_oneshot) > 0:
                for note, vel, padidx in self.notes_oneshot:
                    new_notes_on.append((note, vel, padidx, self.assigned_pad_idx))

        # Check if all note-offs have been sent for proper completion tracking
        if not self.all_notes_sent and self.queue_index_notes_off >= len(self.notes_off):
            self.all_notes_sent = True

        if self.loop_type == "oneshot":
            notes_completed = len(self.notes_on) == 0 or self.all_notes_sent
            ccs_completed = len(self.cc_events) == 0 or self.all_ccs_sent
            if notes_completed and ccs_completed:
                self.toggle_playstate(False)
                return new_notes_on, new_notes_off, new_cc_events

        if settings.midi_sync and clock.new_tick:
            self.current_midi_ticks += 1

        now_time = ticks.ticks_ms()
        self.current_loop_time = ticks.ticks_diff(now_time, self.start_timestamp) / 1000.0
        
        if settings.midi_sync:
            current_ticks = self.current_midi_ticks
            if current_ticks >= self.total_midi_ticks:  # Loop Complete
                self._handle_loop_end()
                return None
        else:
            current_ticks = clock.seconds_to_ticks(self.current_loop_time, self.recording_bpm)
            if current_ticks >= self.total_midi_ticks or self.current_loop_time >= self.total_time_seconds:
                self._handle_loop_end()
                return None
    
        # Note-on
        if not self.all_notes_sent:
            self.queue_index_notes_on = self._process_event_queue(
                current_ticks, 
                self.queue_index_notes_on,
                self.notes_on,
                new_notes_on,
                is_note_on=True,
                is_midi_sync=settings.midi_sync
            )

        # Note-off 
        self.queue_index_notes_off = self._process_event_queue(
            current_ticks,
            self.queue_index_notes_off,
            self.notes_off,
            new_notes_off,
            is_note_off=True,
            is_midi_sync=settings.midi_sync
        )
        
        # CC
        if not self.all_ccs_sent or self.loop_type != "oneshot":
            self.queue_index_cc = self._process_event_queue(
                current_ticks,
                self.queue_index_cc,
                self.cc_events,
                new_cc_events,
                is_midi_sync=settings.midi_sync
            )
        
        if new_notes_on or new_notes_off or new_cc_events:
            if (self.queue_index_notes_on + self.queue_index_notes_off + self.queue_index_cc) % 16 == 0:
                free_memory()
            return new_notes_on, new_notes_off, new_cc_events
        
        return None
    
    def create_oneshot_ccs(self):
        """
        Returns the most recent value for each CC number in the loop
        """

        latest_cc_values = {}
        
        # First pass: Find the latest value of each CC number based on tick timestamps
        for i in range(len(self.cc_events)):
            cc_num = self.cc_events.cc_nums[i]
            cc_val = self.cc_events.values[i]
            cc_tick = self.cc_events.ticks[i]
            cc_pad_idx = self.assigned_pad_idx
            
            # Either new, or newer value for this CC number
            if cc_num not in latest_cc_values or cc_tick >= latest_cc_values[cc_num][1]:
                latest_cc_values[cc_num] = (cc_val, cc_tick, cc_pad_idx)

        # Convert the dictionary to our final list format
        oneshot_ccs = [(cc_num, val_tick[0]) for cc_num, val_tick in latest_cc_values.items()]
        
        self.cc_oneshot = oneshot_ccs
        print(f"Oneshot CCs: {self.cc_oneshot}")

        return oneshot_ccs

    def _update_oneshot_notes(self):
        """
        Creates a list of unique notes to play simultaneously in oneshot mode.
        Similar to create_oneshot_ccs but for note events.
        
        Returns:
            list: A list of tuples (note, velocity, pad_idx) with unique notes.
        """
        seen = set()
        unique_notes = []
        
        for i in range(len(self.notes_on)):
            note = self.notes_on.notes[i]
            velocity = self.notes_on.velocities[i]
            pad_idx = self.notes_on.pad_indices[i]
            note_tuple = (note, velocity, pad_idx)
            if note_tuple not in seen:
                seen.add(note_tuple)
                unique_notes.append(note_tuple)
        
        self.notes_oneshot = unique_notes
        
        return self.notes_oneshot

    def quantize_loop(self):
        """
        Quantizes the loop length to match musical bar divisions.
        This ensures loops have musically sensible lengths (e.g. whole bars).
        
        The method uses the quantize_loop setting to determine how to quantize:
        - "none": No quantization is performed
        - "1": Quantize to 1/4 notes (beats)
        - "2": Quantize to 1/2 notes
        - "4": Quantize to whole notes
        - etc.
        """
        amount = settings.quantize_loop
        if amount == "none":
            return

        ticks_per_quarter_note = 24  # Standard MIDI Clock ticks per quarter note
        quantization_ticks = int(ticks_per_quarter_note * 4 * float(amount))
        
        num_quant_units = max(1, math.ceil(self.total_midi_ticks / quantization_ticks))
        new_total_ticks = num_quant_units * quantization_ticks
        
        # DJT AI - is there any reason to care about the number of total ticks? Is there some limit we are worried about?
        # Sanity check - don't allow extremely large values
        if new_total_ticks > 10000:
            # Limit to a reasonable value (10 bars at 4/4)
            new_total_ticks = min(new_total_ticks, 24 * 4 * 10)
            
        self.total_midi_ticks = new_total_ticks
        self.total_time_seconds = clock.ticks_to_seconds(self.total_midi_ticks, self.recording_bpm)
        

    def quantize_events(self):
        """
        Quantizes the timing of all events (notes and CC messages) based on the specified 
        quantization amount and quantization percentage.
        """
        if settings.quantize_time == "none":
            print("DEBUG: Quantization disabled (quantize_time = 'none')")
            return
    
        ticks_per_quantization_unit = clock.seconds_to_ticks(
            clock.get_note_duration_seconds(settings.quantize_time), self.recording_bpm
        )
        quantization_percent = get_quantization_percent()

        if len(self.notes_on) > 0:
            print("Quantizing NOTE-ON events:")
            for i in range(len(self.notes_on)):
                original_tick = self.notes_on.ticks[i]
                new_tick_count = _calculate_quantized_tick(
                    original_tick, quantization_percent, ticks_per_quantization_unit
                )
                self.notes_on.ticks[i] = new_tick_count

        if len(self.notes_off) > 0:
            print("Quantizing NOTE-OFF events:")
            for i in range(len(self.notes_off)):
                original_tick = self.notes_off.ticks[i]
                new_tick_count = _calculate_quantized_tick(
                    original_tick, quantization_percent, ticks_per_quantization_unit
                )
                self.notes_off.ticks[i] = new_tick_count
            
        if settings.quantize_cc and len(self.cc_events) > 0:
            print("Quantizing CC events:")
            for i in range(len(self.cc_events)):
                original_tick = self.cc_events.ticks[i]
                new_tick_count = _calculate_quantized_tick(
                    original_tick, quantization_percent, ticks_per_quantization_unit
                )
                self.cc_events.ticks[i] = new_tick_count

        free_memory()

    def change_loop_mode(self, mode=""):
        """
        Pass in or toggle chord loop mode: "oneshot" or "chordloop".
        """
        if mode and mode in ["oneshot", "chordloop"]:
            self.loop_type = mode
        else:
            self.loop_type = "oneshot" if self.loop_type == "chordloop" else "chordloop"
        self.reset()
        return self.loop_type

    def get_unique_notes(self):
        """
        a list of unique note-on/velocity combinations.

        Returns:
            list: A list of tuples containing unique (note, velocity, pad index, assigned pad index)
        """
        seen = set()
        unique_notes = []
        for i in range(len(self.notes_on)):
            note_tuple = (self.notes_on.notes[i], self.notes_on.velocities[i], self.notes_on.pad_indices[i], self.assigned_pad_idx)
            if note_tuple not in seen:
                seen.add(note_tuple)
                unique_notes.append(note_tuple)
        return unique_notes
    
    def get_unique_ccs(self):
        """
        Returns a list of unique CC number and value combinations.
        """
        seen = set()
        unique_ccs = []
        for i in range(len(self.cc_events)):
            cc_tuple = (self.cc_events.cc_nums[i], self.cc_events.values[i], self.assigned_pad_idx)
            if cc_tuple not in seen:
                seen.add(cc_tuple)
                unique_ccs.append(cc_tuple)
        return unique_ccs

def set_next_or_prev_quantization(up_or_down=True):
    """
    Changes the quantization setting to the next value in the list.
    """
    settingsmenu.set_next_or_prev_quantization_time(up_or_down)

def get_quantization_text():
    """
    Returns the display text for the current quantization setting.
    """
    return f"Qnt: {settings.quantize_time}"

def get_quantization_display_value():
    """
    Returns the quantization value.
    """
    return settings.quantize_time

def set_quantization_percent(up_or_down=True):
    """
    Changes the quantization setting to the next value in the list.
    """
    settings.quantize_strength = next_or_previous_index(
        settings.quantize_strength, 100, up_or_down, False
    )

def get_quantization_percent(return_integer=False):
    """
    Returns the quantization value.
    """
    if return_integer:
        return settings.quantize_strength
    return settings.quantize_strength / 100

# DJT AI - does it make sense to use this at all? Or just directly use MidiLoop? are there performance implications?
def make_midi_loop(loop_type="chordloop", pad_idx=255):
    """
    Returns a new Midiloop object with the specified loop type and pad index.
    """
    return MidiLoop(loop_type=loop_type, assigned_pad_idx=pad_idx)

# Helper to stream-pad chord events as CSV lines
def write_pad_events_csv(loop, pad_idx, f):
    """Write one pad's note-on, note-off, and CC events as CSV under headers."""
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
        pad_i = loop.notes_on.pad_indices[i]
        t = loop.notes_on.ticks[i]
        f.write(f"{n},{v},{pad_i},{t}\n")
    f.write("#NOTES_OFF#\n")
    for i in range(len(loop.notes_off)):
        n = loop.notes_off.notes[i]
        v = loop.notes_off.velocities[i]
        pad_i = loop.notes_off.pad_indices[i]
        t = loop.notes_off.ticks[i]
        f.write(f"{n},{v},{pad_i},{t}\n")
    f.write("#CC#\n")

    for c, v in loop.get_unique_ccs():
        f.write(f"{c},{v},0\n")