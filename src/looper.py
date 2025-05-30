# Global setting for oneshot notes behavior
from debug import free_memory  
free_memory()
import math
import random
import array  # Added for array-based storage
from utils import next_or_previous_index, show_memory
from midi import midi

import adafruit_ticks as ticks
from clock import clock
from debug import debug, print_debug
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
        self.ticks = array.array('H', [])        # Tick position (0-65535)
        self.chord_index = array.array('B', [])  # Chord index (0-15) for chord loops
        
    def add_event(self, note, velocity, pad_idx, tick, chord_idx=DEFAULT_CHORDPAD_IDX):
        """Add a note event with the provided parameters."""
        # Ensure tick value doesn't exceed unsigned short limit
        if tick > 65535:
            print_debug(f"Warning: Tick value {tick} exceeds limit, capping at 65535")
            tick = 65535
            
        self.notes.append(note)
        self.velocities.append(velocity)
        self.pad_indices.append(pad_idx)
        self.ticks.append(tick)
        self.chord_index.append(chord_idx)
    
    def get_event(self, idx):
        """Return a tuple for compatibility with existing code."""
        if idx < 0:
            # Handle negative indexing for compatibility
            idx = len(self.notes) + idx
        return (self.notes[idx], self.velocities[idx], 
                self.pad_indices[idx], self.ticks[idx], self.chord_index[idx])
                
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
        self.chord_index = array.array('B', [])
        
    def __getitem__(self, idx):
        """Allow direct indexing with brackets for backward compatibility."""
        return self.get_event(idx)
        
    def append(self, event_tuple, chord_idx):
        """Add an event from a tuple for backward compatibility."""
        note, vel, padidx, tick = event_tuple
        self.add_event(note, vel, padidx, tick, chord_idx)

class ArrayBasedCCStorage:
    """Array-based storage for CC events with dramatically reduced memory usage."""
    def __init__(self):
        self.cc_nums = array.array('B', [])     # CC number (0-127)
        self.values = array.array('B', [])      # CC value (0-127)
        self.ticks = array.array('H', [])       # Tick position
        self.chord_index = array.array('B', [])  # Chord index (0-15) for chord loops
        
    def add_event(self, cc_num, value, tick, chord_idx= DEFAULT_CHORDPAD_IDX):
        """Add a CC event with the provided parameters."""
        # Ensure tick value doesn't exceed unsigned short limit
        if tick > 65535:
            tick = 65535
            
        self.cc_nums.append(cc_num)
        self.values.append(value)
        self.ticks.append(tick)
        self.chord_index.append(chord_idx)  # Default chord index for CC events
        
    def get_event(self, idx):
        """Return a tuple for compatibility with existing code."""
        if idx < 0:
            # Handle negative indexing for compatibility
            idx = len(self.cc_nums) + idx
        return (self.cc_nums[idx], self.values[idx], self.ticks[idx], self.chord_index[idx])
        
    def __len__(self):
        """Return the number of stored events."""
        return len(self.cc_nums)
        
    def clear(self):
        """Clear all stored events."""
        # Recreate empty arrays to ensure memory is properly freed
        self.cc_nums = array.array('B', [])
        self.values = array.array('B', [])
        self.ticks = array.array('H', [])
        self.chord_index = array.array('B', [])
        
    def __getitem__(self, idx):
        """Allow direct indexing with brackets for backward compatibility."""
        return self.get_event(idx)
        
    def append(self, event_tuple, chord_idx):
        """Add an event from a tuple for backward compatibility."""
        cc_num, value, tick = event_tuple
        self.add_event(cc_num, value, tick,chord_idx)

class MidiLoop:


    current_loop_idx = 0
    loops = []
    current_loop = None

    def __init__(self, loop_type="loop", assigned_pad_idx=DEFAULT_CHORDPAD_IDX):
        """
        Initializes a new MidiLoop instance.

        Args:
            loop_type (str, optional): The type of loop. Default is "loop".
        """
        self.loop_type = loop_type
        self.start_timestamp = 0
        self.start_tickstamp = 0
        self.total_time_seconds = 0
        self.current_loop_time = 0
        self.total_midi_ticks = 0
        self.current_midi_ticks = 0
        
        # Store events as arrays instead of strings for memory efficiency
        self.notes_on = ArrayBasedEventStorage()
        self.notes_off = ArrayBasedEventStorage()
        self.cc_events = ArrayBasedCCStorage()
        self.cc_oneshot = [] # Only 1 value per CC number
        self.notes_oneshot = [] # For playing all notes at once in oneshot mode
        self.all_ccs_sent = True      # Flag to control CC sending - oneshot mode
        self.all_notes_sent = False   # Flag to control oneshot notes all-at-once mode
        
        self.queue_index_notes_on = 0
        self.queue_index_notes_off = 0
        self.queue_index_cc = 0
        self.loop_is_playing = False
        self.is_recording = False
        self.has_loop = False
        self.assigned_pad_idx = assigned_pad_idx
        self.recording_bpm = clock.bpm_current
        self.stuck_on_notes = []
        self.max_events_reached = False

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
        
        self.clear_notes_and_pixels()
        
        if settings.midi_sync and clock.is_playing:
            ticks_since_last_quarter = clock.midi_ticks_elapsed % 24
            if ticks_since_last_quarter == 0:
                ticks_until_next_quarter = 0
            else:
                ticks_until_next_quarter = clock.TICKS_PER_QUARTER_NOTE - ticks_since_last_quarter
            self.start_tickstamp = clock.midi_ticks_elapsed + ticks_until_next_quarter

        self.queue_index_notes_on = 0
        self.queue_index_notes_off = 0  
        self.queue_index_cc = 0
        self.current_midi_ticks = 0
        self.all_ccs_sent = False  # Reset CC sending flag
        self.all_notes_sent = False  # Reset oneshot notes flag

        if settings.midi_sync and clock.is_playing:
            self.current_midi_ticks = 0 - ticks_until_next_quarter # Start on next quarter note
            print(f"current_midi_ticks set to {self.current_midi_ticks} (sync)")
        self.start_tickstamp = clock.midi_ticks_elapsed
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
            midi.send_note_off(note, self.assigned_pad_idx)
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
        self.cc_oneshot.clear()
        
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
        self.start_tickstamp = 0
        self.current_midi_ticks = 0
        self.clear_notes_and_pixels()
    
    def toggle_playstate(self, on_or_off=None):
        """
        Toggles loop play state on or off.

        Args:
            on_or_off (bool, optional): True to turn on, False to turn off. Default is None.
        """
        # show clock state
        prev_state = self.loop_is_playing
        self.loop_is_playing = on_or_off if on_or_off is not None else not self.loop_is_playing
        self.current_loop_time = 0
        assigned_pad_idx = self.assigned_pad_idx

        print(" ------- TOGGLE PLAYSTATE -------")
        print(f"pad={assigned_pad_idx}, play state change={prev_state}->{self.loop_is_playing}")
        print(f"loop_type={self.loop_type}, midi_sync={settings.midi_sync}, clock_playing={clock.is_playing}")
        

        if self.loop_type in ["chordloop", "oneshot"]:
            # Playing
            if self.loop_is_playing:
                self.reset()
                if 0 <= assigned_pad_idx <= 15:
                    pixels.set_color(assigned_pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                    pixels.set_default_color(assigned_pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                
                # # Send CCs and Notes immediately if needed
                # send_cc_now = self.loop_type == "oneshot" and len(self.cc_events) > 0
                # send_notes_now = self.loop_type == "oneshot" and len(self.notes_on) > 0 and settings.notes_all_at_once
                # # CC Mode - Send one-shot CCs after reset to prevent duplicate sending
                # if send_cc_now:
                #     print(f"Sending {len(self.cc_oneshot)} oneshot CCs")
                #     # Send only the latest value for each CC number
                #     for cc_num, cc_val in self.cc_oneshot:
                #         midi.send_cc(cc_num, cc_val)
                #     self.all_ccs_sent = True  # Prevent sending CCs again until next play
                #     if len(self.notes_on) < 1:
                #         self._handle_loop_end() # End loop - only CCs
                # if send_notes_now:
                #     print(f"Sending {len(self.notes_oneshot)} oneshot notes")
                #     # Send all notes at once with their respective velocities
                #     for note, velocity, pad_idx in self.notes_oneshot:
                #         midi.send_note_on(note, velocity)
                #         pixels.set_note_on(pad_idx)
                #     self.all_notes_sent = True
            # Not Playing
            else:                   
                self.reset_timing()
                if 0 <= assigned_pad_idx <= 15:
                    pixels.set_color(assigned_pad_idx, constants.CHORD_COLOR)
                    pixels.set_default_color(assigned_pad_idx, constants.CHORD_COLOR)

        if self.loop_type == "loop":
            if self.loop_is_playing: # Play Loop
                self.reset()
            else:                    # Stop Loop
                self.reset_timing()
            display.toggle_play_icon(self.loop_is_playing)
            
        print(" ------- TOGGLE PLAYSTATE END -------")

    def toggle_record_state(self, on_or_off=None):
        """
        Toggles loop recording state on or off.

        Args:
            on_or_off (bool, optional): True to turn on, False to turn off. Default is None.
        """
        self.is_recording = on_or_off if on_or_off is not None else not self.is_recording
        display.toggle_recording_icon(self.is_recording)
        if not self.is_recording:
            self.max_events_reached = False

        # Recording a new loop
        if self.is_recording and not self.has_loop:
            self.start_timestamp = ticks.ticks_ms()
            self.start_tickstamp = clock.midi_ticks_elapsed
            self.recording_bpm = clock.bpm_current
            self.toggle_playstate(True)

        # Record mode off and we have events (notes or CCs)
        elif not self.is_recording and ((self.has_loop and on_or_off is not False) 
                                      or self.loop_type in ["oneshot", "chordloop"]):
            if self.total_time_seconds < 0.1:
                # Deal with stuck on notes - Add them to the loop: timestamp = Now
                if len(self.stuck_on_notes) > 0:
                    for note in self.stuck_on_notes:
                        self.add_note(note, 0, 0, False,True)
                    self.stuck_on_notes = []

                # Find the end time from the last event (note or CC)
                last_tick = 0
                if len(self.notes_off) > 0:
                    last_tick = max(last_tick, self.notes_off[-1][3])
                if len(self.cc_events) > 0:
                    last_tick = max(last_tick, self.cc_events[-1][2])
                
                # Calculate total time directly from ticks to ensure consistency
                time_from_ticks = clock.ticks_to_seconds(last_tick, self.recording_bpm)
                time_from_elapsed = ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0
                print(f"Time from ticks: {time_from_ticks}, Time from elapsed: {time_from_elapsed}")
                self.total_time_seconds = max(time_from_ticks, time_from_elapsed)
                # Use last_tick directly instead of converting back and forth
                self.total_midi_ticks = last_tick + 1
                
            
            if settings.midi_sync and not clock.get_playstate() and self.loop_type in ["oneshot", "chordloop"]:
                self.toggle_playstate(False)
            self.trim_silence()
            self.quantize_events()
            self.quantize_loop()
            self._update_oneshot_ccs()
            self._update_oneshot_notes()


  
    def add_note(self, midi_note, velocity, padidx, add_or_remove,force_add=False):
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

        if self.start_timestamp == 0:
            display.show_notification("Play loop to record")
            self.toggle_record_state(False)
            return
        
        free_memory()

        tick_count = clock.seconds_to_ticks(
            ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0, self.recording_bpm
        )
        
        if len(self.notes_on) > constants.LOOP_NOTES_LIMIT:    
            display.show_notification("MAX NOTES REACHED")
            self.max_events_reached = True
            if self.loop_type in ["loop"]:
                self.toggle_record_state(False)
            return

        chord_idx = self.assigned_pad_idx
        if chord_idx < 0 or chord_idx > 15:
            chord_idx = DEFAULT_CHORDPAD_IDX

        if add_or_remove:
            if not self.has_loop:
                self.has_loop = True
            self.notes_on.add_event(midi_note, velocity, padidx, tick_count,chord_idx)
            self.stuck_on_notes.append(midi_note)
            # Increment global event counter
            debug.increment_midi_event_counter()
        else:
            self.notes_off.add_event(midi_note, velocity, padidx, tick_count,chord_idx)
            # Remove the note from the stuck_on_notes list
            if midi_note in self.stuck_on_notes:
                self.stuck_on_notes.remove(midi_note)

            # Increment global event counter
            debug.increment_midi_event_counter()
            
        if len(self.notes_on) % 10 == 0:  # Run GC every 10 notes to reduce overhead
            free_memory()

    def get_number_of_events(self):
        """
        Returns the number of events in the loop.

        Returns:
            int: Number of events in the loop.
        """
        return len(self.notes_on) + len(self.notes_off) + len(self.cc_events)
    
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
                self.notes_on.chord_index.pop(idx)
                
                # Do the same for note-off events if possible
                if idx < len(self.notes_off):
                    self.notes_off.notes.pop(idx)
                    self.notes_off.velocities.pop(idx)
                    self.notes_off.pad_indices.pop(idx)
                    self.notes_off.ticks.pop(idx)
                    self.notes_off.chord_index.pop(idx)
                        
                print_debug(f"Removed note at index {idx}")
            except Exception as e:
                print_debug(f"Couldn't remove note: {e}")

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
        if cc_events_length >= constants.CC_EVENTS_LIMIT:
            self.max_events_reached = True
            display.show_notification("MAX CCS REACHED")
            if self.loop_type in ["loop"]:
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

        chord_idx = self.assigned_pad_idx
        if chord_idx < 0 or chord_idx > 15:
            chord_idx = DEFAULT_CHORDPAD_IDX

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
            self.cc_events.add_event(cc_num, cc_value, tick_count, chord_idx)
            
            # Increment global event counter for CC events but avoid debug output
            debug.total_midi_events += 1
            
            # Run garbage collection at critical thresholds
            if cc_events_length >= 110:  # When approaching the critical limit
                free_memory()
                
            # Only print CC event counts at 10-event intervals to reduce console output
            new_count = cc_events_length + 1
            if new_count % 100 == 0:
                print("Num CC events in looper:", new_count)

    # def _debug_print_notes_info(self, label):
    #     """
    #     Prints debugging information about the current state of notes and CC messages.

    #     This method outputs the details of the notes currently in the `notes_on`,
    #     `notes_off`, and `cc_events` to the console, along with a label for context.

    #     Args:
    #         label (str): A descriptive label to identify the context of the debug output.
    #     """
    #     pass
    #     # print(f"<--------------- {label} ---------------->")
    #     # print("Notes On:")
    #     # for i in range(len(self.notes_on)):
    #     #     note_info = self.notes_on.get_event(i)
    #     #     print(f"  Note: {note_info}")
    #     # print("Notes Off:")
    #     # for i in range(len(self.notes_off)):
    #     #     note_info = self.notes_off.get_event(i)
    #     #     print(f"  Note: {note_info}")
    #     # print("CC Messages:")
    #     # for i in range(len(self.cc_events)):
    #     #     cc_info = self.cc_events.get_event(i)
    #     #     print(f"  CC: {cc_info}")

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
                    ,self.notes_off.chord_index[i]
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
            
        # Safeguard: if the first event tick is very large or zero, don't perform trimming
        if first_event_tick >= 65535 or first_event_tick == 0:
            return

        try:
            # Update note-on events directly in the arrays (in-place)
            for i in range(len(self.notes_on)):
                if self.notes_on.ticks[i] >= first_event_tick:  # Ensure we don't create negative values
                    self.notes_on.ticks[i] -= first_event_tick
                else:
                    self.notes_on.ticks[i] = 0  # Set to beginning if smaller than first event

            # Update note-off events directly in the arrays (in-place)
            for i in range(len(self.notes_off)):
                if self.notes_off.ticks[i] >= first_event_tick:  # Ensure we don't create negative values
                    self.notes_off.ticks[i] -= first_event_tick
                else:
                    self.notes_off.ticks[i] = 0  # Set to beginning if smaller than first event

            # Update CC events directly in the arrays (in-place)
            for i in range(len(self.cc_events)):
                if self.cc_events.ticks[i] >= first_event_tick:  # Ensure we don't create negative values
                    self.cc_events.ticks[i] -= first_event_tick
                else:
                    self.cc_events.ticks[i] = 0  # Set to beginning if smaller than first event

            if self.total_midi_ticks > first_event_tick:
                self.total_midi_ticks -= first_event_tick

        except Exception as e:
            pass
    
    def trim_loaded_ccs(self):
        """
        Used for preset loading code. Since we are only storing them as oneshots, update the loop
        length to some static value. Use the BPM and the static value to calculate the ticks.

        Modifies:
            - `self.cc_events`: Updates tick counts of CC events
        """
        CC_ONLY_LOOP_LENGTH_SECONDS = 1.0  # Static length for CC-only loops
        if len(self.notes_on) > 0 or len(self.cc_events) == 0: # Only trim if CC only loop.
            return
        # Calculate the total ticks based on the static length and current BPM
        total_ticks = clock.seconds_to_ticks(CC_ONLY_LOOP_LENGTH_SECONDS, self.recording_bpm)
        self.total_midi_ticks = total_ticks
        self.total_time_seconds = CC_ONLY_LOOP_LENGTH_SECONDS
        print(f"CC-only loop length set to {CC_ONLY_LOOP_LENGTH_SECONDS} seconds, total ticks: {total_ticks}")

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

        if len(self.notes_on) == 0: #djt - might want to allow trimming silence even if no notes are present
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

        # Handle missing off notes
        if len(self.notes_on) != len(self.notes_off):

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

    def trim_silence(self):
        """
        Trims silence at the beginning and/or end of the loop based on the 
        configured trim_silence_mode in the settings.

        The method performs the following steps:
        1. If there are no notes in the notes_on, it exits early unless there are CC events.
        2. Removes any "note off" events that occur before the first "note on" event.
        3. Depending on the trim_silence_mode, trims silence at the start, end, or both:
           - "none": No trimming is performed (except for CC-only loops).
           - "start": Trims silence at the beginning of the loop.
           - "end": Trims silence at the end of the loop.
           - "both": Trims silence at both the beginning and end of the loop.
        4. Debug information about the notes is printed before and after trimming.

        Special case:
           - If there are only CC events and no notes, always trim silence from both
             the beginning and end regardless of the trim_silence_mode setting.

        Note:
            This method relies on the settings.trim_silence_mode configuration 
            and assumes the presence of helper methods `_remove_leading_off_notes`, 
            `_trim_silence_start`, and `_trim_silence_end` for specific operations.
        """
        # Special case: if there are only CC events (no notes), always trim both start and end
        if len(self.notes_on) == 0 and len(self.cc_events) > 0:
            #self._debug_print_notes_info("Before CC-only Trim")
            self._trim_silence_start()
            self._trim_silence_end()
            #self._debug_print_notes_info("After CC-only Trim")
            free_memory()
            return
            
        # Normal case: handle based on whether there are notes
        if len(self.notes_on) == 0:
            return

        # Remove any off notes occurring before the first note-on tick
        if len(self.notes_off) > 0:
            self._remove_leading_off_notes()

        trim_mode = settings.trim_silence_mode
        if trim_mode == "none":
            return

        #self._debug_print_notes_info("Before Trim")

        if trim_mode in ["start", "both"]:
            self._trim_silence_start()
            
        if trim_mode in ["end", "both"]:
            self._trim_silence_end()
        
        #self._debug_print_notes_info("After Trim")
        
        # Add garbage collection after trimming to reclaim memory from discarded data
        free_memory()

  
    def _handle_loop_end(self):
        """Reset or stop loop if needed."""
        if self.loop_type in ('loop', 'chordloop'):
            self.reset()

        elif self.loop_type == "oneshot":
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
            event_type = "NOTE-ON" if is_note_on else ("NOTE-OFF" if is_note_off else "CC")

            if queue_index < events_len:
                tick = event_storage.ticks[queue_index]

                
        while queue_index < events_len:
            # Direct array access for better performance
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
                    
                    if is_midi_sync:
                        event_type = "NOTE-ON" if is_note_on else "NOTE-OFF"
                    
                    new_events.append((note, vel, padidx, self.assigned_pad_idx))
                    # Update pixel display based on note type
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
        # Quick exit conditions - check these first for efficiency
        if not self.total_time_seconds > 0 or not self.loop_is_playing:
            return None
            
        # No events in the loop
        if len(self.notes_on) == 0 and len(self.notes_off) == 0 and len(self.cc_events) == 0:
            return None
        
        if len(self.notes_off) < 1 and self.all_ccs_sent:
            # If no note-off events and all CCs sent, we can stop the loop
            self.toggle_playstate(False)
            return None
        
        # print(f"curr loop time: {self.current_loop_time:.2f}s, total time: {self.total_time_seconds:.2f}s")
        # Pre-allocate result arrays just once
        new_notes_on = []
        new_notes_off = []
        new_cc_events = []

        is_midi_sync = settings.midi_sync
        
        # Handle one-shot CC mode for chord loops
        if (settings.notes_all_at_once or self.loop_type == "oneshot") and not self.all_ccs_sent:
            self.all_ccs_sent = True
            if len(self.cc_oneshot) > 0:
                for cc_num, cc_val in self.cc_oneshot:
                    new_cc_events.append((cc_num, cc_val, self.assigned_pad_idx))

        # Handle one-shot notes all-at-once mode
        if settings.notes_all_at_once and not self.all_notes_sent:
            self.all_notes_sent = True
            if len(self.notes_oneshot) > 0:
                for note, vel, padidx in self.notes_oneshot:
                    new_notes_on.append((note, vel, padidx, self.assigned_pad_idx))

        # Only increment ticks when using MIDI sync
        if is_midi_sync and clock.new_tick:
            self.current_midi_ticks += 1

        # Get current time and calculate loop position once - used throughout the method
        now_time = ticks.ticks_ms()
        self.current_loop_time = ticks.ticks_diff(now_time, self.start_timestamp) / 1000.0
        
        if is_midi_sync:
            current_ticks = self.current_midi_ticks
            
            # Loop is Complete
            if current_ticks >= self.total_midi_ticks:
                self._handle_loop_end()
                return None
        else:
            # For non-MIDI sync, calculate current ticks based on elapsed time
            current_ticks = clock.seconds_to_ticks(self.current_loop_time, self.recording_bpm)
            
            # Check for loop end condition using both tick and time measurements
            if current_ticks >= self.total_midi_ticks or self.current_loop_time >= self.total_time_seconds:

                self._handle_loop_end()
                return None
        
        # Process all event types using the helper method
        # Note-on events - Only if not all sent
        if not self.all_notes_sent:
            old_queue_idx = self.queue_index_notes_on
            self.queue_index_notes_on = self._process_event_queue(
                current_ticks, 
                self.queue_index_notes_on,
                self.notes_on,
                new_notes_on,
                is_note_on=True,
                is_midi_sync=is_midi_sync
            )

        # Note-off events
        old_queue_idx = self.queue_index_notes_off
        self.queue_index_notes_off = self._process_event_queue(
            current_ticks,
            self.queue_index_notes_off,
            self.notes_off,
            new_notes_off,
            is_note_off=True,
            is_midi_sync=is_midi_sync
        )
        
        # CC events - only process if not in one-shot mode or one-shot hasn't been sent
        #print(f"all ccs sent: {self.all_ccs_sent}")
        if not self.all_ccs_sent or self.loop_type != "oneshot":
            old_queue_idx = self.queue_index_cc
            self.queue_index_cc = self._process_event_queue(
                current_ticks,
                self.queue_index_cc,
                self.cc_events,
                new_cc_events,
                is_midi_sync=is_midi_sync
            )
        
        # Only call garbage collection if we actually processed events
        if new_notes_on or new_notes_off or new_cc_events:
            if (self.queue_index_notes_on + self.queue_index_notes_off + self.queue_index_cc) % 16 == 0:
                free_memory()
            return new_notes_on, new_notes_off, new_cc_events
        
        return None
    
    def _update_oneshot_ccs(self):
        """
        Returns the most recent value for each CC number in the loop,
        based on the timestamp (tick value) of each CC event.
        
        Returns:
            list: A list of tuples (cc_num, cc_value) with one entry per unique CC number.
        """
        # Dictionary to track the most recent value for each CC number
        latest_cc_values = {}
        
        # First pass: Find the latest value of each CC number based on tick timestamps
        for i in range(len(self.cc_events)):
            cc_num = self.cc_events.cc_nums[i]
            cc_val = self.cc_events.values[i]
            cc_tick = self.cc_events.ticks[i]
            cc_pad_idx = self.assigned_pad_idx
            
            # If we've never seen this CC number before, or if this is a more recent value
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
        Similar to _update_oneshot_ccs but for note events.
        
        Returns:
            list: A list of tuples (note, velocity, pad_idx) with unique notes.
        """
        # For oneshot notes, we want one instance of each unique note value
        # with its velocity and pad index
        unique_notes = set()
        
        for i in range(len(self.notes_on)):
            note = self.notes_on.notes[i]
            velocity = self.notes_on.velocities[i]
            pad_idx = self.notes_on.pad_indices[i]
            chordpad_idx = self.assigned_pad_idx
            unique_notes.add((note, velocity, pad_idx, chordpad_idx))
        
        self.notes_oneshot = list(unique_notes)
        
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
        
        # Calculate the number of quantization units in the loop
        num_quant_units = max(1, math.ceil(self.total_midi_ticks / quantization_ticks))
        
        # Set the total loop ticks to be an exact multiple of the quantization unit
        new_total_ticks = num_quant_units * quantization_ticks
        
        # Sanity check - don't allow extremely large values
        if new_total_ticks > 10000:
            # Limit to a reasonable value (10 bars at 4/4)
            new_total_ticks = min(new_total_ticks, 24 * 4 * 10)
            
        self.total_midi_ticks = new_total_ticks
        
        # Also update time in seconds to keep both in sync
        self.total_time_seconds = clock.ticks_to_seconds(self.total_midi_ticks, self.recording_bpm)
        

    def quantize_events(self):
        """
        Quantizes the timing of all events (notes and CC messages) based on the specified 
        quantization amount and quantization percentage.
        """
        if settings.quantize_time == "none":
            return
        
        quantize_cc = settings.quantize_cc

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
        if quantize_cc:
            for i in range(len(self.cc_events)):
                tick_count = self.cc_events.ticks[i]
                new_tick_count = _quantize_time_and_ticks(
                    tick_count, quantization_percent, ticks_per_quantization_unit
                )
                self.cc_events.ticks[i] = new_tick_count
            #self._debug_print_notes_info("After CC Quantization")
        
        # Run garbage collection after quantization to reclaim memory
        free_memory()

    def change_chord_loop_mode(self, mode=""):
        """
        Changes the chord mode setting to the next value in the list.

        Returns:
            new mode
        """
        if mode and mode in ["oneshot", "chordloop"]:
            self.loop_type = mode
        else:
            self.loop_type = "oneshot" if self.loop_type == "chordloop" else "chordloop"
        self.reset()
        return self.loop_type

    def get_unique_notes(self):
        """
        Returns a list of unique note-on/velocity combinations.

        This method is useful for features like an arpeggiator, where unique
        notes and their velocities are required.

        Returns:
            list: A list of tuples containing unique (note, velocity) pairs.
        """
        unique_notes = set()
        for i in range(len(self.notes_on)):
            unique_notes.add((self.notes_on.notes[i], self.notes_on.velocities[i], self.notes_on.pad_indices[i], self.assigned_pad_idx))
        return list(unique_notes)
    
    def get_unique_ccs(self):
        """
        Returns a list of unique CC number and value combinations.

        This method is useful for features that require unique CC messages.

        Returns:
            list: A list of tuples containing unique (CC number, CC value, pad index) triples.
        """
        unique_ccs = set()
        for i in range(len(self.cc_events)):
            unique_ccs.add((self.cc_events.cc_nums[i], self.cc_events.values[i], self.assigned_pad_idx))
        return list(unique_ccs)

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

def make_midi_loop(loop_type="loop", pad_idx=255):
    """
    Creates a new MIDI loop and sets it as the current loop object.

    Returns:
        None
    """
    return MidiLoop(loop_type=loop_type, assigned_pad_idx=pad_idx)

# Helper to stream-pad chord events as CSV lines
def write_pad_events_csv(loop, pad_idx, f):
    """Write one pad's note-on, note-off, and CC events as CSV under headers."""
    f.write(f"##PAD{pad_idx}##\n")
    # METADATA block with essential loop parameters
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
    # Save only one entry per CC number, with zero ticks for minimal RAM on load
    for c, v in loop.get_unique_ccs():
        f.write(f"{c},{v},0\n")

# def run_memory_stress_test():
#     import gc
#     import time
    
#     print("Starting MIDI Loop Memory Stress Test...")
#     print("This will add note events until memory runs out.")
    
#     # Create a test loop
#     test_loop = MidiLoop(loop_type="loop", assigned_pad_idx=0)
#     test_loop.toggle_record_state(True)  # Start recording
#     test_loop.start_timestamp = ticks.ticks_ms()
#     test_loop.start_tickstamp = 0
#     test_loop.recording_bpm = 120
    
#     event_count = 0
#     test_results = {
#         'success': False,
#         'final_event_count': 0,
#         'final_notes_on': 0,
#         'final_notes_off': 0,
#         'final_free_ram': 0,
#         'final_used_ram': 0,
#         'error_type': None,
#         'error_message': None
#     }
    
#     try:
#         while True:
#             # Add a note-on event
#             test_loop.add_note(
#                 midi_note=60 + (event_count % 12),  # Cycle through notes
#                 velocity=100,
#                 padidx=event_count % 16,  # Cycle through pads
#                 add_or_remove=True,  # Note on
#                 force_add=True
#             )
#             event_count += 1
            
#             # Add corresponding note-off event
#             test_loop.add_note(
#                 midi_note=60 + ((event_count - 1) % 12),
#                 velocity=0,
#                 padidx=(event_count - 1) % 16,
#                 add_or_remove=False,  # Note off
#                 force_add=True
#             )
#             event_count += 1
            
#             # Print status every 100 events
#             if event_count % 100 == 0:
#                 # Force garbage collection
#                 gc.collect()
                
#                 # Get memory info
#                 free_mem = gc.mem_free()
#                 alloc_mem = gc.mem_alloc()
#                 total_mem = free_mem + alloc_mem
                
#                 print(f"Events: {event_count}")
#                 print(f"Notes ON: {len(test_loop.notes_on)}")
#                 print(f"Notes OFF: {len(test_loop.notes_off)}")
#                 print(f"Free RAM: {free_mem} bytes")
#                 print(f"Used RAM: {alloc_mem} bytes")
#                 print(f"Total RAM: {total_mem} bytes")
#                 print(f"RAM Usage: {(alloc_mem/total_mem)*100:.1f}%")
#                 print("-" * 40)
                
#                 # Update test results with latest values
#                 test_results.update({
#                     'final_event_count': event_count,
#                     'final_notes_on': len(test_loop.notes_on),
#                     'final_notes_off': len(test_loop.notes_off),
#                     'final_free_ram': free_mem,
#                     'final_used_ram': alloc_mem
#                 })
                
#                 # Small delay to prevent overwhelming the output
#                 time.sleep(0.1)
            
#     except MemoryError as e:
#         print(f"\nMEMORY ERROR at {event_count} events!")
#         print(f"Final event count: {event_count}")
#         print(f"Notes ON in loop: {len(test_loop.notes_on)}")
#         print(f"Notes OFF in loop: {len(test_loop.notes_off)}")
#         print(f"Error: {e}")
        
#         test_results.update({
#             'final_event_count': event_count,
#             'final_notes_on': len(test_loop.notes_on),
#             'final_notes_off': len(test_loop.notes_off),
#             'error_type': 'MemoryError',
#             'error_message': str(e)
#         })
        
#         # Try to get final memory stats
#         try:
#             gc.collect()
#             test_results.update({
#                 'final_free_ram': gc.mem_free(),
#                 'final_used_ram': gc.mem_alloc()
#             })
#             print(f"Final Free RAM: {test_results['final_free_ram']} bytes")
#             print(f"Final Used RAM: {test_results['final_used_ram']} bytes")
#         except:
#             print("Could not get final memory stats")
            
#     except Exception as e:
#         print(f"\nUNEXPECTED ERROR at {event_count} events!")
#         print(f"Error type: {type(e).__name__}")
#         print(f"Error: {e}")
#         print(f"Final event count: {event_count}")
        
#         test_results.update({
#             'final_event_count': event_count,
#             'error_type': type(e).__name__,
#             'error_message': str(e)
#         })
        
#     print("Memory stress test completed.")
#     return test_results

# if __name__ == "__main__":
#     run_memory_stress_test()
