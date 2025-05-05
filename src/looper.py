from debug import free_memory  
free_memory()
import math
import random
import array  # Added for array-based storage
from utils import next_or_previous_index, show_memory, free_memory

import adafruit_ticks as ticks
from clock import clock
from debug import debug, print_debug
from display import display
from pixels import pixels
free_memory()
from midi import midi
from settings import settings
import settingsmenu
import constants

# Constants for debug strings to save memory
DEBUG_STR_NUM_NOTES = "num notes in looper:"

# Helper function for quantizing moved outside of method to avoid recreation
def _quantize_time_and_ticks(tick_count, quantization_percent, ticks_per_quantization_unit):
    """Helper function to quantize tick values."""
    # Tick-based quantization
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
    """Array-based storage for MIDI note events with dramatically reduced memory usage."""
    def __init__(self):
        # Use 'B' for unsigned char (0-255) - perfect for MIDI notes/velocities/pads
        self.notes = array.array('B', [])        # MIDI note (0-127)
        self.velocities = array.array('B', [])   # Velocity (0-127)
        self.pad_indices = array.array('B', [])  # Pad index (0-15)
        # Use 'H' for unsigned short (0-65535) - good for tick values
        self.ticks = array.array('H', [])        # Tick position (0-65535)
        
    def add_event(self, note, velocity, pad_idx, tick):
        """Add a note event with the provided parameters."""
        # Ensure tick value doesn't exceed unsigned short limit
        if tick > 65535:
            print_debug(f"Warning: Tick value {tick} exceeds limit, capping at 65535")
            tick = 65535
            
        self.notes.append(note)
        self.velocities.append(velocity)
        self.pad_indices.append(pad_idx)
        self.ticks.append(tick)
    
    def get_event(self, idx):
        """Return a tuple for compatibility with existing code."""
        if idx < 0:
            # Handle negative indexing for compatibility
            idx = len(self.notes) + idx
        return (self.notes[idx], self.velocities[idx], 
                self.pad_indices[idx], self.ticks[idx])
                
    def __len__(self):
        """Return the number of stored events."""
        return len(self.notes)
        
    def clear(self):
        """Clear all stored events."""
        # Recreate empty arrays to ensure memory is properly freed
        self.notes = array.array('B', [])
        self.velocities = array.array('B', [])
        self.pad_indices = array.array('B', [])
        self.ticks = array.array('H', [])
        
    def __getitem__(self, idx):
        """Allow direct indexing with brackets for backward compatibility."""
        return self.get_event(idx)
        
    def append(self, event_tuple):
        """Add an event from a tuple for backward compatibility."""
        note, vel, padidx, tick = event_tuple
        self.add_event(note, vel, padidx, tick)

class ArrayBasedCCStorage:
    """Array-based storage for CC events with dramatically reduced memory usage."""
    def __init__(self):
        self.cc_nums = array.array('B', [])     # CC number (0-127)
        self.values = array.array('B', [])      # CC value (0-127)
        self.ticks = array.array('H', [])       # Tick position
        
    def add_event(self, cc_num, value, tick):
        """Add a CC event with the provided parameters."""
        # Ensure tick value doesn't exceed unsigned short limit
        if tick > 65535:
            print_debug(f"Warning: Tick value {tick} exceeds limit, capping at 65535")
            tick = 65535
            
        self.cc_nums.append(cc_num)
        self.values.append(value)
        self.ticks.append(tick)
        
    def get_event(self, idx):
        """Return a tuple for compatibility with existing code."""
        if idx < 0:
            # Handle negative indexing for compatibility
            idx = len(self.cc_nums) + idx
        return (self.cc_nums[idx], self.values[idx], self.ticks[idx])
        
    def __len__(self):
        """Return the number of stored events."""
        return len(self.cc_nums)
        
    def clear(self):
        """Clear all stored events."""
        # Recreate empty arrays to ensure memory is properly freed
        self.cc_nums = array.array('B', [])
        self.values = array.array('B', [])
        self.ticks = array.array('H', [])
        
    def __getitem__(self, idx):
        """Allow direct indexing with brackets for backward compatibility."""
        return self.get_event(idx)
        
    def append(self, event_tuple):
        """Add an event from a tuple for backward compatibility."""
        cc_num, value, tick = event_tuple
        self.add_event(cc_num, value, tick)

class MidiLoop:
    """
    A class representing a MIDI loop.

    Attributes:
        current_loop_idx (int): Index of the currently playing loop.
        loops (list): List to store all MidiLoop instances.
        current_loop (MidiLoop): Reference to the current MidiLoop instance.
        start_timestamp (int): Time in milliseconds when the loop started playing.
        total_time_seconds (float): Total duration of the loop in seconds.
        current_loop_time (float): Current time position within the loop in seconds.
        notes_on (ArrayBasedEventStorage): Array-based storage for note on events.
        notes_off (ArrayBasedEventStorage): Array-based storage for note off events.
        cc_events (ArrayBasedCCStorage): Array-based storage for CC events.
        queue_index_notes_on (int): Index for processing notes ON.
        queue_index_notes_off (int): Index for processing notes OFF.
        queue_index_cc (int): Index for processing CC events.
        loop_is_playing (bool): Flag to indicate if the loop is currently playing.
        is_recording (bool): Flag to indicate if the loop is currently recording.
        has_loop (bool): Flag indicating if the loop has recorded notes.

    Methods:
        reset(): Resets the loop to start from the beginning.
        clear(): Clears all recorded notes and resets loop attributes.
        toggle_playstate(on_or_off=None): Toggles loop play state on or off.
        toggle_record_state(on_or_off=None): Toggles loop recording state on or off.
        add_note(midi, velocity, padidx, add_or_remove): Adds a note to the loop record.
        remove_note(idx): Removes a note from the loop record at the specified index.
        trim_silence(trim_mode=settings.trim_silence_mode): Trims silence at the beginning and end of the loop.
        get_new_notes(): Checks for new notes to be played based on loop position.
        quantize_loop(): Quantizes the loop length based on the current quantization setting.
        quantize_notes(): Quantizes the note timings based on the specified quantization amount.
        change_chord_loop_mode(): Changes the chord mode setting to the next value in the list.
        get_all_notes_list(): Returns all notes in the loop.
    """

    current_loop_idx = 0
    loops = []
    current_loop = None

    def __init__(self, loop_type="loop", assigned_pad_idx=-1):
        """
        Initializes a new MidiLoop instance.

        Args:
            loop_type (str, optional): The type of loop. Default is "loop".
        """
        self.loop_type = loop_type
        self.start_timestamp = 0
        self.total_time_seconds = 0
        self.current_loop_time = 0
        self.total_midi_ticks = 0
        self.current_midi_ticks = 0
        
        # Store events as arrays instead of strings for memory efficiency
        self.notes_on = ArrayBasedEventStorage()
        self.notes_off = ArrayBasedEventStorage()
        self.cc_events = ArrayBasedCCStorage()
        
        self.queue_index_notes_on = 0
        self.queue_index_notes_off = 0
        self.queue_index_cc = 0
        self.loop_is_playing = False
        self.is_recording = False
        self.has_loop = False
        self.assigned_pad_idx = assigned_pad_idx
        self.recording_bpm = clock.bpm_current

        if self.loop_type == "loop":
            MidiLoop.loops.append(self)

    def reset(self):
        """
        Resets the looper's state, synchronizing with the MIDI clock if enabled.

        This method resets the looper's internal state, including timestamps, 
        note queues, CC queues, and MIDI tick counters. If MIDI synchronization is enabled 
        and the clock is playing, it calculates the time until the next quarter 
        note and adjusts the start timestamp accordingly.

        Note: Resets all queues (notes on/off and CC) to their original lists for replay.
        """
        # Explicitly turn off all notes first to prevent hanging notes
        self.clear_notes_and_pixels()
        
        if settings.midi_sync and clock.is_playing:
            time_since_last_quarter = ticks.ticks_diff(ticks.ticks_ms(), clock.last_clock_time)
            time_until_next_quarter = int((clock.quarternote_duration * 1000) - time_since_last_quarter)

            # Handle negative values if we're already past the next beat
            if time_until_next_quarter < 0:
                time_until_next_quarter += int(clock.quarternote_duration * 1000)
            self.start_timestamp = ticks.ticks_add(ticks.ticks_ms(), time_until_next_quarter)
        else:
            self.start_timestamp = ticks.ticks_ms()

        # Ensure all counters are properly reset
        self.queue_index_notes_on = 0
        self.queue_index_notes_off = 0  
        self.queue_index_cc = 0
        self.current_midi_ticks = 0
        
        print_debug(f"Loop reset: queue indices zeroed, timestamp={self.start_timestamp}")
        
        # Special case for loops that start at the beginning
        if len(self.notes_on) > 0 and self.notes_on.ticks[0] == 0:
            self.start_timestamp = ticks.ticks_ms()

    def clear_notes_and_pixels(self):
        """
        Turns off all unique notes and pixels in the loop.
        """
        # Use a set to collect unique notes and pixels from the active notes
        unique_notes = set()
        unique_pixels = set()
        
        # Access array attributes directly for better performance
        for i in range(len(self.notes_on)):
            unique_notes.add(self.notes_on.notes[i])  # note number
            unique_pixels.add(self.notes_on.pad_indices[i])  # pad index

        # Turn off all notes and pixels
        for note in unique_notes:
            midi.send_note_off(note)
        for pixel in unique_pixels:
            pixels.set_note_off(pixel)

    def clear(self):
        """
        Clears all recorded notes, CC messages and resets loop attributes.
        """
        self.clear_notes_and_pixels()
        
        # Clear all event arrays
        self.notes_on.clear()
        self.notes_off.clear()
        self.cc_events.clear()
        
        # Reset other state
        self.total_time_seconds = 0
        self.start_timestamp = 0
        self.current_midi_ticks = 0
        self.total_midi_ticks = 0
        self.toggle_playstate(False)
        self.toggle_record_state(False)
        self.current_loop_time = 0
        self.has_loop = False
        
        free_memory()  # Add garbage collection here to reclaim memory

        display.show_notification("Loop Cleared")

    def reset_timing(self):
        self.start_timestamp = 0
        self.current_midi_ticks = 0
        self.clear_notes_and_pixels()
    
    def toggle_playstate(self, on_or_off=None):
        """
        Toggles loop play state on or off.

        Args:
            on_or_off (bool, optional): True to turn on, False to turn off. Default is None.
        """
        self.loop_is_playing = on_or_off if on_or_off is not None else not self.loop_is_playing
        self.current_loop_time = 0
        assigned_pad_idx = self.assigned_pad_idx

        if self.loop_type not in ["loop"]:
            if self.loop_is_playing: # Play Loop
                self.reset()
                if assigned_pad_idx > -1:
                    pixels.set_color(assigned_pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                    pixels.set_default_color(assigned_pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
            else:                     # Stop Loop
                self.reset_timing()
                if assigned_pad_idx > -1:
                    pixels.set_color(assigned_pad_idx,constants.CHORD_COLOR)
                    pixels.set_default_color(assigned_pad_idx,constants.CHORD_COLOR)

        if self.loop_type == "loop":
            if self.loop_is_playing: # Play Loop
                self.reset()
            else:                    # Stop Loop
                self.reset_timing()
            display.toggle_play_icon(self.loop_is_playing)

    def toggle_record_state(self, on_or_off=None):
        """
        Toggles loop recording state on or off.

        Args:
            on_or_off (bool, optional): True to turn on, False to turn off. Default is None.
        """
        self.is_recording = on_or_off if on_or_off is not None else not self.is_recording
        display.toggle_recording_icon(self.is_recording)

        # Recording a new loop
        if self.is_recording and not self.has_loop:
            self.start_timestamp = ticks.ticks_ms()
            self.recording_bpm = clock.bpm_current
            self.toggle_playstate(True)

        # Record mode off and we have events (notes or CCs)
        elif not self.is_recording and ((self.has_loop and on_or_off is not False) 
                                      or self.loop_type in ["chord", "chordloop"]):
            if self.total_time_seconds < 0.1:
                # Find the end time from the last event (note or CC)
                last_tick = 0
                if len(self.notes_off) > 0:
                    last_tick = max(last_tick, self.notes_off[-1][3])
                if len(self.cc_events) > 0:
                    last_tick = max(last_tick, self.cc_events[-1][2])
                
                # Calculate total time directly from ticks to ensure consistency
                time_from_ticks = clock.ticks_to_seconds(last_tick, self.recording_bpm)
                time_from_elapsed = ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0
                
                self.total_time_seconds = max(time_from_ticks, time_from_elapsed)
                # Use last_tick directly instead of converting back and forth
                self.total_midi_ticks = last_tick + 1
                print_debug(f"Setting total_midi_ticks to {self.total_midi_ticks}")
            
            if settings.midi_sync and not clock.get_playstate() and self.loop_type in ["chord", "chordloop"]:
                self.toggle_playstate(False)
            print_debug(f"time total: {self.total_time_seconds}")

        debug.add_debug_line("Loop Record State", self.is_recording, True)

  
    def add_note(self, midi_note, velocity, padidx, add_or_remove):
        """
        Adds a note to the loop.

        Args:
            midi_note (int): MIDI note number.
            velocity (int): Velocity of the note.
            padidx (int): Index of the pad.
            add_or_remove (bool): True to add note to the ON queue, False to add note to the OFF queue.
        """
        if not self.is_recording:
            return

        if self.start_timestamp == 0:
            display.show_notification("Play loop to record")
            self.toggle_record_state(False)
            return
        
        free_memory()

        tick_count = clock.seconds_to_ticks(
            ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0, self.recording_bpm
        )
        
        # Check note limit only if debug mode is off
        if not debug.DEBUG_MODE and len(self.notes_on) > constants.LOOP_NOTES_LIMIT:
            display.show_notification("MAX NOTES REACHED")
            self.toggle_record_state(False)
            return

        if add_or_remove:
            if not self.has_loop:
                self.has_loop = True
            self.notes_on.add_event(midi_note, velocity, padidx, tick_count)
            # Increment global event counter
            debug.increment_midi_event_counter()
            print_debug(f"{DEBUG_STR_NUM_NOTES} {len(self.notes_on)}")
        else:
            self.notes_off.add_event(midi_note, velocity, padidx, tick_count)
            # Increment global event counter
            debug.increment_midi_event_counter()
            
        # Call garbage collection after adding notes to prevent memory fragmentation
        # when recording many notes in quick succession
        if len(self.notes_on) % 10 == 0:  # Run GC every 10 notes to reduce overhead
            free_memory()

    def remove_note(self, idx):
        """
        Removes a note from the loop record at the specified index.

        Args:
            idx (int): Index of the note to be removed.
        """
        if 0 <= idx < len(self.notes_on):
            try:
                # Remove the note-on event by removing from each array at the given index
                self.notes_on.notes.pop(idx)
                self.notes_on.velocities.pop(idx)
                self.notes_on.pad_indices.pop(idx)
                self.notes_on.ticks.pop(idx)
                
                # Do the same for note-off events if possible
                if idx < len(self.notes_off):
                    self.notes_off.notes.pop(idx)
                    self.notes_off.velocities.pop(idx)
                    self.notes_off.pad_indices.pop(idx)
                    self.notes_off.ticks.pop(idx)
                        
                print_debug(f"Removed note at index {idx}")
            except Exception as e:
                print_debug(f"Couldn't remove note: {e}")
        else:
            print_debug(f"Cannot remove loop note - invalid index {idx} (max: {len(self.notes_on)-1})")

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

        # Memory-critical section - check limit only if debug mode is off
        cc_events_length = len(self.cc_events)
        if not debug.DEBUG_MODE and cc_events_length >= constants.CC_EVENTS_LIMIT:
            display.show_notification("MAX CCS REACHED")
            self.toggle_record_state(False)
            return
            
        cc_resolution_threshold = settings.cc_resolution
        
        # Find if we've ever recorded this CC number before using direct array access
        last_cc_value = None
        found_previous_value = False
        
        for i in range(cc_events_length-1, -1, -1):  # Iterate in reverse for efficiency
            if self.cc_events.cc_nums[i] == cc_num:
                last_cc_value = self.cc_events.values[i]
                found_previous_value = True
                break
        
        # Only record if:
        # - This is the first CC of this number we've seen (last_cc_value is None and we didn't find a previous value)
        # - OR the change is significant enough (exceeds threshold)
        if (last_cc_value is None and not found_previous_value) or \
           (found_previous_value and abs(cc_value - last_cc_value) > cc_resolution_threshold):
            
            # Calculate tick values once
            tick_count = clock.seconds_to_ticks(
                ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0, self.recording_bpm
            )
            
            if not self.has_loop:
                self.has_loop = True
            
            # Run garbage collection before adding event to reduce memory fragmentation
            if cc_events_length % 8 == 0:  # Run GC more frequently for CC events
                free_memory()
                    
            # Add event directly to array-based storage
            self.cc_events.add_event(cc_num, cc_value, tick_count)
            
            # Increment global event counter for CC events but avoid debug output
            debug.total_midi_events += 1
            
            # Run garbage collection at critical thresholds
            if cc_events_length >= 110:  # When approaching the critical limit
                free_memory()
                
            # Only print CC event counts at 10-event intervals to reduce console output
            new_count = cc_events_length + 1
            if new_count % 100 == 0:
                print("Num CC events in looper:", new_count)

    def _debug_print_notes_info(self, label):
        """
        Prints debugging information about the current state of notes and CC messages.

        This method outputs the details of the notes currently in the `notes_on`,
        `notes_off`, and `cc_events` to the console, along with a label for context.

        Args:
            label (str): A descriptive label to identify the context of the debug output.
        """
        print(f"<--------------- {label} ---------------->")
        print("Notes On:")
        for i in range(len(self.notes_on)):
            note_info = self.notes_on.get_event(i)
            print(f"  Note: {note_info}")
        print("Notes Off:")
        for i in range(len(self.notes_off)):
            note_info = self.notes_off.get_event(i)
            print(f"  Note: {note_info}")
        print("CC Messages:")
        for i in range(len(self.cc_events)):
            cc_info = self.cc_events.get_event(i)
            print(f"  CC: {cc_info}")

    def _remove_leading_off_notes(self):
        """
        Removes any "note off" events that occur before the first "note on" event.

        This method ensures that the `notes_off` only contains "note off" events
        that happen at or after the time of the first "note on" event in `notes_on`.
        """
        if len(self.notes_on) == 0 or len(self.notes_off) == 0:
            return
            
        # Get the tick position of the first note-on event
        first_note_on_tick = self.notes_on.ticks[0]
        
        # Create a new storage for filtered note-off events
        new_notes_off = ArrayBasedEventStorage()
        
        # Only keep note-off events that occur at or after the first note-on
        for i in range(len(self.notes_off)):
            if self.notes_off.ticks[i] >= first_note_on_tick:
                new_notes_off.add_event(
                    self.notes_off.notes[i],
                    self.notes_off.velocities[i],
                    self.notes_off.pad_indices[i],
                    self.notes_off.ticks[i]
                )
        
        # Replace the original notes_off with the filtered version
        self.notes_off = new_notes_off

    def _trim_silence_start(self):
        """
        Adjusts the timing of note and CC events in the looper by removing the initial 
        silence at the start of the recording. This is achieved by normalizing the tick 
        counts of all events relative to the first event (whether note or CC).

        Modifies:
            - `self.notes_on`: Updates tick counts of note-on events
            - `self.notes_off`: Updates tick counts of note-off events
            - `self.cc_events`: Updates tick counts of CC events
            - `self.total_midi_ticks`: Reduces total MIDI ticks by first event tick count

        Notes:
            - Events from both note and CC lists are considered to find the true start
            - All timing adjustments use the earliest event as reference
        """
        # Find the earliest event tick across both notes and CCs
        first_event_tick = float('inf')

        if len(self.notes_on) > 0:
            first_event_tick = min(first_event_tick, self.notes_on.ticks[0])

        if len(self.cc_events) > 0:
            first_event_tick = min(first_event_tick, self.cc_events.ticks[0])

        # Update note-on events directly in the arrays (in-place)
        for i in range(len(self.notes_on)):
            self.notes_on.ticks[i] -= first_event_tick

        # Update note-off events directly in the arrays (in-place)
        for i in range(len(self.notes_off)):
            self.notes_off.ticks[i] -= first_event_tick

        # Update CC events directly in the arrays (in-place)
        for i in range(len(self.cc_events)):
            self.cc_events.ticks[i] -= first_event_tick

        if self.total_midi_ticks > 0:
            self.total_midi_ticks -= first_event_tick

    def _trim_silence_end(self):
        """
        Trims silence at the end of the sequence by finding the latest event 
        (note-off or CC) and adjusting the total ticks accordingly.

        The method:
        1. Finds the last note-off and last CC event ticks
        2. Uses the later of these as the end point
        3. Adjusts total MIDI ticks based on this end point
        4. Handles any missing note-off events
        """
        if len(self.notes_on) == 0:
            return
            
        # Find the latest event tick from both note-offs and CCs
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
        print_debug(f"End trimming: total_midi_ticks set to {self.total_midi_ticks}")

        # Handle missing off notes
        if len(self.notes_on) != len(self.notes_off):
            print_debug(f"Missing note-offs detected ({len(self.notes_on)} on events, {len(self.notes_off)} off events)")
            
            # For each note-on event
            for i in range(len(self.notes_on.notes)):
                # Find if this note has a corresponding off event
                note = self.notes_on.notes[i]
                has_off = False
                
                # Check all note-off events
                for j in range(len(self.notes_off.notes)):
                    if self.notes_off.notes[j] == note:
                        has_off = True
                        break
                        
                if not has_off:
                    # Add a note-off event at the end of the loop
                    padidx = self.notes_on.pad_indices[i]
                    self.notes_off.add_event(note, 0, padidx, self.total_midi_ticks - 1)
                    print_debug(f"Added missing note-off for note {note} at tick {self.total_midi_ticks - 1}")

    def trim_silence(self):
        """
        Trims silence at the beginning and/or end of the loop based on the 
        configured trim_silence_mode in the settings.

        The method performs the following steps:
        1. If there are no notes in the notes_on, it exits early.
        2. Removes any "note off" events that occur before the first "note on" event.
        3. Depending on the trim_silence_mode, trims silence at the start, end, or both:
           - "none": No trimming is performed.
           - "start": Trims silence at the beginning of the loop.
           - "end": Trims silence at the end of the loop.
           - "both": Trims silence at both the beginning and end of the loop.
        4. Debug information about the notes is printed before and after trimming.

        Note:
            This method relies on the settings.trim_silence_mode configuration 
            and assumes the presence of helper methods `_remove_leading_off_notes`, 
            `_trim_silence_start`, and `_trim_silence_end` for specific operations.
        """
        if len(self.notes_on) == 0:
            return

        # Remove any off notes occurring before the first note-on tick
        if len(self.notes_off) > 0:
            self._remove_leading_off_notes()

        trim_mode = settings.trim_silence_mode
        if trim_mode == "none":
            return

        self._debug_print_notes_info("Before Trim")

        if trim_mode in ["start", "both"]:
            self._trim_silence_start()
            
        if trim_mode in ["end", "both"]:
            self._trim_silence_end()
        
        self._debug_print_notes_info("After Trim")
        
        # Add garbage collection after trimming to reclaim memory from discarded data
        free_memory()

  
    def _handle_loop_end(self):
        """Reset or stop loop if needed."""
        if self.loop_type in ('loop', 'chordloop'):
            print_debug(f"Loop reached end at {self.current_loop_time:.2f}s, resetting...")
            # Reset the loop to start again from beginning
            self.reset()
            # Force-reset queue indices to ensure notes play again
            self.queue_index_notes_on = 0
            self.queue_index_notes_off = 0
            self.queue_index_cc = 0
            self.current_midi_ticks = 0
        elif self.loop_type == "chord":
            self.toggle_playstate(False)

    def get_new_notes(self):
        """
        Checks for new notes and CC messages to be played based on loop position.

        Returns:
            tuple: (on_array, off_array, cc_array) containing new notes to play ON/OFF and CC messages
            None: if no new events need to be processed
        """
        # Pre-allocate arrays instead of creating in the loop
        new_notes_on = []
        new_notes_off = []
        new_cc_events = []
        
        # Only increment ticks when using MIDI sync
        if settings.midi_sync and clock.new_tick:
            self.current_midi_ticks += 1

        # Quick exit if no loop content or not playing
        if not self.total_time_seconds > 0 or not self.loop_is_playing:
            return None

        # Get current time once - used throughout the method
        now_time = ticks.ticks_ms()

        # Calculate current position once
        self.current_loop_time = ticks.ticks_diff(now_time, self.start_timestamp) / 1000.0
        
        # When not using MIDI sync, calculate current ticks based on elapsed time
        if not settings.midi_sync:
            current_ticks = clock.seconds_to_ticks(self.current_loop_time, self.recording_bpm)
            
            # Check for loop end condition using the calculated ticks
            if current_ticks >= self.total_midi_ticks or self.current_loop_time >= self.total_time_seconds:
                # Only print at loop end, not constantly
                self._handle_loop_end()
                return None
        else:
            # For MIDI sync, use the midi tick counter
            current_ticks = self.current_midi_ticks
            
            # Check for loop end condition
            if self.current_midi_ticks >= self.total_midi_ticks:
                self._handle_loop_end()
                return None
        
        # No events in the loop
        if len(self.notes_on) == 0 and len(self.notes_off) == 0 and len(self.cc_events) == 0:
            return None
        
        # Process without MIDI sync (using seconds)
        if not settings.midi_sync:
            # Process all notes in one pass without re-checking sync mode
            notes_on_len = len(self.notes_on)
            while self.queue_index_notes_on < notes_on_len:
                # Direct array access for better performance
                tick = self.notes_on.ticks[self.queue_index_notes_on]
                if tick <= current_ticks:  # Use <= for exact matches
                    note = self.notes_on.notes[self.queue_index_notes_on]
                    vel = self.notes_on.velocities[self.queue_index_notes_on]
                    padidx = self.notes_on.pad_indices[self.queue_index_notes_on]
                    
                    new_notes_on.append((note, vel, padidx))  # (note, vel, padidx)
                    pixels.set_note_on(padidx)
                    self.queue_index_notes_on += 1
                else:
                    break

            notes_off_len = len(self.notes_off)
            while self.queue_index_notes_off < notes_off_len:
                # Direct array access for better performance
                tick = self.notes_off.ticks[self.queue_index_notes_off]
                if tick <= current_ticks:  # Use <= for exact matches
                    note = self.notes_off.notes[self.queue_index_notes_off]
                    vel = self.notes_off.velocities[self.queue_index_notes_off]
                    padidx = self.notes_off.pad_indices[self.queue_index_notes_off]
                    
                    new_notes_off.append((note, vel, padidx))  # (note, vel, padidx)
                    pixels.set_note_off(padidx)
                    self.queue_index_notes_off += 1
                else:
                    break

            cc_events_len = len(self.cc_events)
            while self.queue_index_cc < cc_events_len:
                # Direct array access for better performance
                tick = self.cc_events.ticks[self.queue_index_cc]
                if tick <= current_ticks:  # Use <= for exact matches
                    cc_num = self.cc_events.cc_nums[self.queue_index_cc]
                    cc_val = self.cc_events.values[self.queue_index_cc]
                    
                    new_cc_events.append((cc_num, cc_val))  # (cc_num, cc_value)
                    self.queue_index_cc += 1
                else:
                    break
        else:
            # Process with MIDI sync (using ticks) - same pattern as above
            notes_on_len = len(self.notes_on)
            while self.queue_index_notes_on < notes_on_len:
                # Direct array access for better performance
                tick = self.notes_on.ticks[self.queue_index_notes_on]
                if current_ticks >= tick:
                    note = self.notes_on.notes[self.queue_index_notes_on]
                    vel = self.notes_on.velocities[self.queue_index_notes_on]
                    padidx = self.notes_on.pad_indices[self.queue_index_notes_on]
                    
                    new_notes_on.append((note, vel, padidx))  # (note, vel, padidx)
                    pixels.set_note_on(padidx)
                    self.queue_index_notes_on += 1
                else:
                    break

            notes_off_len = len(self.notes_off)
            while self.queue_index_notes_off < notes_off_len:
                # Direct array access for better performance
                tick = self.notes_off.ticks[self.queue_index_notes_off]
                if current_ticks >= tick:
                    note = self.notes_off.notes[self.queue_index_notes_off]
                    vel = self.notes_off.velocities[self.queue_index_notes_off]
                    padidx = self.notes_off.pad_indices[self.queue_index_notes_off]
                    
                    new_notes_off.append((note, vel, padidx))  # (note, vel, padidx)
                    pixels.set_note_off(padidx)
                    self.queue_index_notes_off += 1
                else:
                    break

            cc_events_len = len(self.cc_events)
            while self.queue_index_cc < cc_events_len:
                # Direct array access for better performance
                tick = self.cc_events.ticks[self.queue_index_cc]
                if current_ticks >= tick:
                    cc_num = self.cc_events.cc_nums[self.queue_index_cc]
                    cc_val = self.cc_events.values[self.queue_index_cc]
                    
                    new_cc_events.append((cc_num, cc_val))  # (cc_num, cc_value)
                    self.queue_index_cc += 1
                else:
                    break
        
        # Only call garbage collection if we actually processed events
        if new_notes_on or new_notes_off or new_cc_events:
            # Don't run garbage collection every time - it's expensive
            # Only run it every few events to balance memory usage with performance
            if (self.queue_index_notes_on + self.queue_index_notes_off + self.queue_index_cc) % 16 == 0:
                free_memory()
            return new_notes_on, new_notes_off, new_cc_events
        
        return None

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
        quantization_ticks = int(ticks_per_quarter_note * (4 / int(amount)))
        
        print("<--------------- Quantizing Loop ---------------->")
        print(f"Quantization amount: {amount}")
        print(f"Original total_midi_ticks: {self.total_midi_ticks}")
        print(f"Quantization unit (ticks): {quantization_ticks}")
        
        # Calculate the number of quantization units in the loop
        num_quant_units = max(1, math.ceil(self.total_midi_ticks / quantization_ticks))
        
        # Set the total loop ticks to be an exact multiple of the quantization unit
        new_total_ticks = num_quant_units * quantization_ticks
        
        # Sanity check - don't allow extremely large values
        if new_total_ticks > 10000:
            print_debug(f"Warning: Loop length quantization produced a very large value: {new_total_ticks}")
            # Limit to a reasonable value (10 bars at 4/4)
            new_total_ticks = min(new_total_ticks, 24 * 4 * 10)
            
        self.total_midi_ticks = new_total_ticks
        
        # Also update time in seconds to keep both in sync
        self.total_time_seconds = clock.ticks_to_seconds(self.total_midi_ticks, self.recording_bpm)
        
        print(f"Quantized loop length to {self.total_midi_ticks} ticks ({num_quant_units} units of {quantization_ticks} ticks).")

    def quantize_notes(self):
        """
        Quantizes the timing of all events (notes and CC messages) based on the specified 
        quantization amount and quantization percentage.
        """
        if settings.quantize_time == "none":
            return

        # Calculate these values once, outside the loops
        ticks_per_quantization_unit = clock.seconds_to_ticks(
            clock.get_note_duration_seconds(settings.quantize_time), self.recording_bpm
        )
        quantization_percent = get_quantization_percent()

        # Quantize note-on events using direct array access for better memory efficiency
        for i in range(len(self.notes_on)):
            tick_count = self.notes_on.ticks[i]
            new_tick_count = _quantize_time_and_ticks(
                tick_count, quantization_percent, ticks_per_quantization_unit
            )
            self.notes_on.ticks[i] = new_tick_count

        # Quantize note-off events using direct array access
        for i in range(len(self.notes_off)):
            tick_count = self.notes_off.ticks[i]
            new_tick_count = _quantize_time_and_ticks(
                tick_count, quantization_percent, ticks_per_quantization_unit
            )
            self.notes_off.ticks[i] = new_tick_count

        # Quantize CC events using direct array access
        for i in range(len(self.cc_events)):
            tick_count = self.cc_events.ticks[i]
            new_tick_count = _quantize_time_and_ticks(
                tick_count, quantization_percent, ticks_per_quantization_unit
            )
            self.cc_events.ticks[i] = new_tick_count
        
        # Run garbage collection after quantization to reclaim memory
        free_memory()

    def change_chord_loop_mode(self, mode=""):
        """
        Changes the chord mode setting to the next value in the list.

        Returns:
            None
        """
        if mode and mode in ["chord", "chordloop"]:
            self.loop_type = mode
        else:
            self.loop_type = "chord" if self.loop_type == "chordloop" else "chordloop"
        self.reset()

    def get_all_notes_list(self):
        """
        Returns all notes in the loop.

        Returns:
            list: A list of tuples containing note, velocity, and pad index.
        """
        result = []
        for i in range(len(self.notes_on)):
            result.append((
                self.notes_on.notes[i],
                self.notes_on.velocities[i],
                self.notes_on.pad_indices[i]
            ))
        return result


def get_loopermode_display_text():
    """
    Returns the display text for the looper mode.

    Returns:
        list: The display text.
    """
    return ["<- click = record ", "   dbl  = st/stop", "   hold = clear loop"]

def update_play_rec_icons():
    """
    Updates the play and record icons on the display.

    Returns:
        None
    """
    display.toggle_play_icon(MidiLoop.current_loop.loop_is_playing)
    display.toggle_recording_icon(MidiLoop.current_loop.is_recording)

def process_select_btn_press(action_type="press"):
    """
    Processes the fn button press in the menu.

    Args:
        action_type (str): The type of action performed. Default is "press".

    Returns:
        None
    """
    if action_type == "press":
        MidiLoop.current_loop.toggle_record_state()

def clear_all_loops(released=True):
    """
    Clears all playing loops.

    Args:
        released (bool, optional): Whether this was called on button release. Default is True.

    Returns:
        None
    """
    MidiLoop.current_loop.clear()

def toggle_loops_playstate():
    """
    Stops all playing loops and turns off recording.

    Returns:
        None
    """
    MidiLoop.current_loop.toggle_playstate()
    MidiLoop.current_loop.toggle_record_state(False)

def encoder_chg_function(direction):
    """
    Called when the encoder changes in the looper menu.

    Args:
        direction (bool): True for clockwise, False for counterclockwise.

    Returns:
        None
    """
    notes_ary_length = len(MidiLoop.current_loop.notes_on)
    if notes_ary_length < 1:
        return

    if not direction:
        remove_idx = random.randint(0, notes_ary_length - 1)
        MidiLoop.current_loop.remove_note(remove_idx)
        display.show_notification(f"Removed note: {remove_idx + 1}")

def setup_midi_loops():
    """
    Initializes a MIDI loop and sets it as the current loop object.

    Returns:
        None
    """
    _ = MidiLoop()
    show_memory("Setup Looper")
    free_memory()
    MidiLoop.current_loop_idx = 0
    MidiLoop.current_loop = MidiLoop.loops[MidiLoop.current_loop_idx]
    show_memory("Setup Looper")

def set_next_or_prev_quantization(up_or_down=True):
    """
    Changes the quantization setting to the next value in the list.

    Args:
        up_or_down (bool, optional): True to go forward, False to go backwards. Default is True.

    Returns:
        None
    """
    settingsmenu.set_next_or_prev_quantization_time(up_or_down)

def get_quantization_text():
    """
    Returns the display text for the current quantization setting.

    Returns:
        str: The display text.
    """
    return f"Qnt: {settings.quantize_time}"

def get_quantization_display_value():
    """
    Returns the quantization value.

    Returns:
        str: The quantization value.
    """
    return settings.quantize_time

def set_quantization_percent(up_or_down=True):
    """
    Changes the quantization setting to the next value in the list.

    Args:
        up_or_down (bool, optional): True to go forward, False to go backwards. Default is True.

    Returns:
        None
    """
    settings.quantize_strength = next_or_previous_index(
        settings.quantize_strength, 100, up_or_down, False
    )

def get_quantization_percent(return_integer=False):
    """
    Returns the quantization value.

    Args:
        return_integer (bool, optional): Whether to return the value as an integer. Default is False.

    Returns:
        float: The quantization value.
    """
    if return_integer:
        return settings.quantize_strength
    return settings.quantize_strength / 100

def make_midi_loop(loop_type="loop", pad_idx=-1):
    """
    Creates a new MIDI loop and sets it as the current loop object.

    Returns:
        None
    """
    return MidiLoop(loop_type=loop_type, assigned_pad_idx=pad_idx)