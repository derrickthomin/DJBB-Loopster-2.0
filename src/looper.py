import math
import random

import adafruit_ticks as ticks
from clock import clock
from debug import debug, print_debug
from display import display
from pixels import pixels
from midi import midi
from settings import settings
import settingsmenu
from utils import next_or_previous_index, show_memory, free_memory
import constants

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
        notes_on_list (list): List to store tuples of (note, velocity, time) for notes played ON.
        notes_off_list (list): List to store tuples of (note, velocity, time) for notes played OFF.
        notes_on_queue (list): Temporary list for notes to be played ON each loop.
        notes_off_queue (list): Temporary list for notes to be played OFF each loop.
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
        self.notes_on_list = []
        self.notes_off_list = []
        self.notes_on_queue = []
        self.notes_off_queue = []
        self.loop_is_playing = False
        self.is_recording = False
        self.has_loop = False
        self.assigned_pad_idx = assigned_pad_idx # For chord loops
        self.recording_bpm = clock.bpm_current

        if self.loop_type == "loop":
            MidiLoop.loops.append(self)

    def reset(self):
        """
        Resets the looper's state, synchronizing with the MIDI clock if enabled.

        This method resets the looper's internal state, including timestamps, 
        note queues, and MIDI tick counters. If MIDI synchronization is enabled 
        and the clock is playing, it calculates the time until the next quarter 
        note and adjusts the start timestamp accordingly. Otherwise, it sets the 
        start timestamp to the current time. Additionally, it ensures the start 
        timestamp is updated if the first note in the `notes_on_list` has a 
        velocity of 0.

        Attributes Updated:
            - self.start_timestamp: The timestamp for the start of the loop.
            - self.notes_on_queue: A copy of the current `notes_on_list`.
            - self.notes_off_queue: A copy of the current `notes_off_list`.
            - self.current_midi_ticks: Resets the MIDI tick counter to 0.

        Calls:
            - self.clear_notes_and_pixels(): Clears loop notes and associated 
              pixel data.
        """
        if settings.midi_sync and clock.is_playing:
            time_since_last_quarter = ticks.ticks_diff(ticks.ticks_ms(), clock.last_clock_time)
            time_until_next_quarter = int((clock.quarternote_duration * 1000) - time_since_last_quarter)

            # Handle negative values if we're already past the next beat
            if time_until_next_quarter < 0:
                time_until_next_quarter += int(clock.quarternote_duration * 1000)
            self.start_timestamp = ticks.ticks_add(ticks.ticks_ms(), time_until_next_quarter)
        else:
            self.start_timestamp = ticks.ticks_ms()
        if self.notes_on_list and self.notes_on_list[0][2] == 0:
            self.start_timestamp = ticks.ticks_ms()
        self.notes_on_queue = self.notes_on_list[:]
        self.notes_off_queue = self.notes_off_list[:]
        self.current_midi_ticks = 0
        self.clear_notes_and_pixels()

    def clear_notes_and_pixels(self):
        """
        Turns off all unique notes and pixels in the loop.
        """
        unique_notes = {note for note, _, _, _, _ in self.notes_on_list}
        unique_pixels = {padidx for _, _, _, padidx, _ in self.notes_on_list}

        for note in unique_notes:
            midi.send_note_off(note)
        for pixel in unique_pixels:
            pixels.set_note_off(pixel)

    def clear(self):
        """
        Clears all recorded notes and resets loop attributes.
        """
        self.clear_notes_and_pixels()
        self.notes_on_list.clear()
        self.notes_off_list.clear()
        self.notes_on_queue.clear()
        self.notes_off_queue.clear()
        self.total_time_seconds = 0
        self.start_timestamp = 0
        self.current_midi_ticks = 0
        self.total_midi_ticks = 0
        self.toggle_playstate(False)
        self.toggle_record_state(False)
        self.current_loop_time = 0
        self.has_loop = False

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

        # Record mode off and we have notes
        elif not self.is_recording and ((self.has_loop and on_or_off is not False) or self.loop_type in ["chord", "chordloop"]):
            if self.total_time_seconds < 0.1:
                self.total_time_seconds = ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0  # Convert to seconds
                self.total_midi_ticks = clock.seconds_to_ticks(self.total_time_seconds, self.recording_bpm)
            if settings.midi_sync and not clock.get_playstate() and self.loop_type in ["chord", "chordloop"]:
                self.toggle_playstate(False)
            print_debug(f"time total: {self.total_time_seconds}")

        debug.add_debug_line("Loop Record State", self.is_recording, True)

  
    def add_note(self, midi, velocity, padidx, add_or_remove):
        """
        Adds a note to the loop.

        Args:
            midi (int): MIDI note number.
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

        note_time_offset = ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0  # convert to seconds
        note_data = (midi, velocity, note_time_offset, padidx, clock.seconds_to_ticks(note_time_offset, self.recording_bpm))

        if len(self.notes_on_list) > constants.LOOP_NOTES_LIMIT:
            display.show_notification("MAX NOTES REACHED")
            self.toggle_record_state(False)
            return

        if add_or_remove:
            if not self.has_loop:
                self.has_loop = True
            self.notes_on_list.append(note_data)
            print_debug(f"num notes in looper: {len(self.notes_on_list)}")
            
        else:
            self.notes_off_list.append(note_data)

        debug.add_debug_line("Num Midi notes in looper", len(self.notes_on_list))

    def remove_note(self, idx):
        """
        Removes a note from the loop record at the specified index.

        Args:
            idx (int): Index of the note to be removed.
        """
        if 0 <= idx < len(self.notes_on_list):
            try:
                self.notes_on_list.pop(idx)
                self.notes_off_list.pop(idx)
            except IndexError:
                print_debug("Couldn't remove note")
        else:
            print_debug("Cannot remove loop note - invalid index")


    def _debug_print_notes_info(self, label):
        """
        Prints debugging information about the current state of notes.

        This method outputs the details of the notes currently in the `notes_on_list`
        and `notes_off_list` to the console, along with a label for context.

        Args:
            label (str): A descriptive label to identify the context of the debug output.
        """
        print(f"<--------------- {label} ---------------->")
        print("Notes On:")
        for note in self.notes_on_list:
            print(f"  Note: {note}")
        print("Notes Off:")
        for note in self.notes_off_list:
            print(f"  Note: {note}")

    def _remove_leading_off_notes(self):
        """
        Removes any "note off" events that occur before the first "note on" event.

        This method ensures that the `notes_off_list` only contains "note off" events
        that happen at or after the time of the first "note on" event in `notes_on_list`.

        Attributes:
            notes_on_list (list): A list of "note on" events, where each event is a tuple
                containing information about the note (e.g., pitch, velocity, time).
            notes_off_list (list): A list of "note off" events, where each event is a tuple
                containing information about the note (e.g., pitch, velocity, time).

        Side Effects:
            Modifies the `notes_off_list` attribute by filtering out "note off" events
            that occur before the first "note on" event.
        """
        first_note_on_time = self.notes_on_list[0][2]
        self.notes_off_list = [
            note_off for note_off in self.notes_off_list
            if note_off[2] >= first_note_on_time
        ]

    def _trim_silence_start(self):
        """
        Adjusts the timing of note-on and note-off events in the looper by 
        removing the initial silence at the start of the recording. This is 
        achieved by normalizing the hit times and tick counts of all events 
        relative to the first note-on event.

        Modifies:
            - `self.notes_on_list`: Updates the hit times and tick counts of 
              all note-on events to start from zero.
            - `self.notes_off_list`: Updates the hit times and tick counts of 
              all note-off events to align with the adjusted note-on events.
            - `self.total_time_seconds`: Reduces the total time by the time 
              of the first note-on event.
            - `self.total_midi_ticks`: Reduces the total MIDI ticks by the 
              tick count of the first note-on event, if applicable.

        Notes:
            - Assumes `self.notes_on_list` and `self.notes_off_list` are 
              populated and sorted by their respective event times.
            - Assumes `self.total_midi_ticks` is greater than zero if MIDI 
              ticks are being tracked.
        """
        first_note_on_time = self.notes_on_list[0][2]
        first_tick_count = self.notes_on_list[0][4]
        for idx, (note, vel, hit_time, padidx, tick_count) in enumerate(self.notes_on_list):
            self.notes_on_list[idx] = (
                note,
                vel,
                hit_time - first_note_on_time,
                padidx,
                tick_count - first_tick_count,
            )
        for idx, (note, vel, hit_time, padidx, tick_count) in enumerate(self.notes_off_list):
            self.notes_off_list[idx] = (
                note,
                vel,
                hit_time - first_note_on_time,
                padidx,
                tick_count - first_tick_count,
            )

        self.total_time_seconds -= first_note_on_time
        if self.total_midi_ticks > 0:
            self.total_midi_ticks -= first_tick_count

    def _trim_silence_end(self):
        """
        Trims the silence at the end of the MIDI sequence by adjusting the total time
        and ensuring the notes_off_list is properly updated.

        This method calculates the new length of the MIDI sequence based on the time
        difference between the first note-on event and the last note-off event. It also
        handles cases where there are missing note-off events by appending a synthetic
        note-off event to the notes_off_list.

        Attributes Updated:
            - self.total_midi_ticks: Total MIDI ticks, incremented by 1 from the last note-off tick.
            - self.total_time_seconds: Total time in seconds for the MIDI sequence.

        Notes:
            - If the number of note-on events does not match the number of note-off events,
              a debug message ("oops") is printed, and a synthetic note-off event is added
              to the notes_off_list.

        Synthetic Note-Off Event:
            - The synthetic note-off event is created using the last note-on event's note,
              pad, and tick value, with a time slightly before the calculated new length.

        """
        first_note_on_time = self.notes_on_list[0][2]
        last_note_off_time = self.notes_off_list[-1][2]
        self.total_midi_ticks = self.notes_off_list[-1][4] + 1
        new_length = last_note_off_time - first_note_on_time + 0.01
        self.total_time_seconds = new_length

        # Handle missing off notes
        if len(self.notes_on_list) != len(self.notes_off_list):
            print_debug("oops")
            last_note = self.notes_on_list[-1][0]
            last_pad = self.notes_on_list[-1][3]
            tick_value = self.notes_on_list[-1][4] + 1
            self.notes_off_list.append((last_note, 0, new_length - 0.05, last_pad, tick_value))

    def trim_silence(self):
        """
        Trims silence at the beginning and/or end of the loop based on the 
        configured trim_silence_mode in the settings.

        The method performs the following steps:
        1. If there are no notes in the notes_on_list, it exits early.
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
        if not self.notes_on_list:
            return

        # Remove any off notes occurring before the first note-on time
        if self.notes_off_list:
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

  
    def _handle_loop_end(self):
        """Reset or stop loop if needed."""
        if self.loop_type in ('loop', 'chordloop'):
            self.reset()
        if self.loop_type == "chord":
            self.toggle_playstate(False)

    def get_new_notes(self):
        """
        Checks for new notes to be played based on loop position.

        Returns:
            tuple: Tuple in the form (on_array, off_array) containing new notes to play ON and OFF.
        """
        new_notes_on = []
        new_notes_off = []
        
        if clock.new_tick:
            self.current_midi_ticks += 1

        if not self.total_time_seconds > 0:
            return None

        now_time = ticks.ticks_ms()

        # If no MIDI sync
        time_diff_ms = ticks.ticks_diff(now_time, self.start_timestamp)
        if (not settings.midi_sync) and time_diff_ms > self.total_time_seconds * 1000:
            self._handle_loop_end()
            return None

        # If MIDI sync
        if settings.midi_sync and self.current_midi_ticks >= self.total_midi_ticks:
            self._handle_loop_end()
            # Extra check or logic if needed
            if self.current_midi_ticks >= self.total_midi_ticks:
                self.reset()
                return None

        self.current_loop_time = ticks.ticks_diff(now_time, self.start_timestamp) / 1000.0  # Convert to seconds

        # ------------- Check for new notes -------------

        # No Midi Sync - Seconds
        if not settings.midi_sync:
            for idx, (note, vel, hit_time, padidx, tick_count) in enumerate(self.notes_on_queue):
                if hit_time < self.current_loop_time:
                    new_notes_on.append((note, vel, padidx))
                    self.notes_on_queue.pop(idx)
                    pixels.set_note_on(padidx)
                    #break

            for idx, (note, vel, hit_time, padidx, tick_count) in enumerate(self.notes_off_queue):
                if hit_time < self.current_loop_time:
                    new_notes_off.append((note, vel, padidx))
                    self.notes_off_queue.pop(idx)
                    pixels.set_note_off(padidx)
        
        # Midi Sync - Midi Ticks
        if settings.midi_sync:
            for idx, (note, vel, hit_time, padidx, tick_count) in enumerate(self.notes_on_queue):
                if self.current_midi_ticks >= tick_count:
                    print(f"current_midi_ticks: {self.current_midi_ticks}, tick_count: {tick_count}, note: {note}, padidx: {padidx}")
                    new_notes_on.append((note, vel, padidx))
                    self.notes_on_queue.pop(idx)
                    pixels.set_note_on(padidx)


            for idx, (note, vel, hit_time, padidx, tick_count) in enumerate(self.notes_off_queue):
                if self.current_midi_ticks >= tick_count:
                    new_notes_off.append((note, vel, padidx))
                    self.notes_off_queue.pop(idx)
                    pixels.set_note_off(padidx)

        if new_notes_on or new_notes_off:
            return new_notes_on, new_notes_off


    def quantize_loop(self):
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
        num_quant_units = math.ceil(self.total_midi_ticks / quantization_ticks)
        
        # Set the total loop ticks to be an exact multiple of the quantization unit
        self.total_midi_ticks = num_quant_units * quantization_ticks
        
        print(f"Quantized loop length to {self.total_midi_ticks} ticks ({num_quant_units} units of {quantization_ticks} ticks).")

    def quantize_notes(self):
        """
        Quantizes the note timings based on the specified quantization amount.

        Returns:
            None
        """
            
        if settings.quantize_time == "none":
            return

        note_time_ms = clock.get_note_duration_seconds(settings.quantize_time)
        quantization_percent = get_quantization_percent()  # Assume this returns a value between 0 and 1

        def quantize_time_and_ticks(hit_time, tick_count):
            """
            Quantizes a given hit time and its corresponding tick count to the nearest quantization amount.

            Args:
                hit_time (float): The original hit time in seconds.
                tick_count (int): The original MIDI tick count.

            Returns:
                tuple: (quantized_time, quantized_ticks) - The quantized time and tick count.
            """
            # Time-based quantization
            remainder = hit_time % note_time_ms
            if remainder > note_time_ms / 2:
                update_amt = (note_time_ms - remainder) * quantization_percent
                new_time = hit_time + update_amt
            else:
                update_amt = remainder * quantization_percent
                new_time = hit_time - update_amt
            
            # Tick-based quantization
            ticks_per_quantization_unit = clock.seconds_to_ticks(note_time_ms, self.recording_bpm)


            # Prevent divide by zero error
            if ticks_per_quantization_unit <= 0:
                return new_time, tick_count
            tick_remainder = tick_count % ticks_per_quantization_unit
            
            if tick_remainder > ticks_per_quantization_unit / 2:
                tick_update = int((ticks_per_quantization_unit - tick_remainder) * quantization_percent)
                new_ticks = tick_count + tick_update
            else:
                tick_update = int(tick_remainder * quantization_percent)
                new_ticks = tick_count - tick_update
            
            return new_time, new_ticks

        on_quant_time_deltas = []
        on_quant_tick_deltas = []
        # Quantize note on times
        for idx, (note, vel, hit_time, padidx, tick_count) in enumerate(self.notes_on_list):
            if idx == 0 and settings.trim_silence_mode in ["start", "both"]:
                on_quant_time_deltas.append(0)
                on_quant_tick_deltas.append(0)
                continue

            new_time, new_tick_count = quantize_time_and_ticks(hit_time, tick_count)
            # deltas
            on_quant_time_deltas.append(new_time - hit_time)
            on_quant_tick_deltas.append(new_tick_count - tick_count)
            print_debug(f"Original On Hit Time: {hit_time}, Quantized On Hit Time: {new_time}")
            self.notes_on_list[idx] = (note, vel, new_time, padidx, new_tick_count)

        # Adjust off times
        for off_idx, (off_note, off_vel, off_time, off_padidx, off_tick) in enumerate(self.notes_off_list):
            on_time = None
            on_ticks = None
            # Find the corresponding note on for this note off
            for on_note, on_vel, on_time, on_padidx, on_ticks in self.notes_on_list:
                if on_note == off_note and on_padidx == off_padidx and on_time <= off_time:
                    # Adjust the off note's time and ticks based on the deltas from the on times quantization
                    time_delta = on_quant_time_deltas[self.notes_on_list.index((on_note, on_vel, on_time, on_padidx, on_ticks))]
                    tick_delta = on_quant_tick_deltas[self.notes_on_list.index((on_note, on_vel, on_time, on_padidx, on_ticks))]
                    off_time += time_delta
                    off_tick += tick_delta
                    break

            new_time = off_time
            new_tick_count = off_tick
            self.notes_off_list[off_idx] = (off_note, off_vel, new_time, off_padidx, new_tick_count)

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
        return [(note[0], note[1], note[3]) for note in self.notes_on_list]


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

def clear_all_loops(onRelease=True):
    """
    Clears all playing loops.

    Args:
        released (bool, optional): Not used. Default is False.

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
    notes_ary_length = len(MidiLoop.current_loop.notes_on_list)
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