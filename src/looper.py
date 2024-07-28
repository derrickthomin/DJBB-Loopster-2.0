import constants
from debug import debug, print_debug
import display
import time
import random
from display import pixel_note_off, pixel_note_on
from midi import clear_all_notes, send_midi_note_off, get_note_time
from utils import free_memory

# Quantization menus
QUANTIZATION_OPTIONS = ["None", "1/4", "1/8", "1/16", "1/32"]
quantization_idx = 0

class MidiLoop:
    """
    A class representing a MIDI loop.

    Attributes:
        current_loop_idx (int): Index of the currently playing loop.
        loops (list): List to store all MidiLoop instances.
        current_loop_obj (MidiLoop): Reference to the current MidiLoop instance.
        loop_start_timestamp (float): Time in seconds when the loop started playing.
        total_loop_time (float): Total duration of the loop in seconds.
        current_loop_time (float): Current time position within the loop in seconds.
        loop_notes_on_time_ary (list): List to store tuples of (note, velocity, time) for notes played ON.
        loop_notes_off_time_ary (list): List to store tuples of (note, velocity, time) for notes played OFF.
        loop_notes_on_queue (list): Temporary list for notes to be played ON each loop.
        loop_notes_off_queue (list): Temporary list for notes to be played OFF each loop.
        loop_playstate (bool): Flag to indicate if the loop is currently playing.
        loop_record_state (bool): Flag to indicate if the loop is currently recording.

    Methods:
        reset_loop(): Resets the loop to start from the beginning.
        clear_loop(): Clears all recorded notes and resets loop attributes.
        loop_toggle_playstate(on_or_off=None): Toggles loop play state on or off.
        toggle_record_state(on_or_off=None): Toggles loop recording state on or off.
        add_loop_note(midi, velocity, padidx, add_or_remove): Adds a note to the loop record.
        remove_loop_note(idx): Removes a note from the loop record at the specified index.
        trim_silence(): Trims silence at the beginning and end of the loop.
        get_new_notes(): Checks for new notes to be played based on loop position.
    """

    current_loop_idx = 0
    loops = []
    current_loop_obj = None

    def __init__(self, loop_type="loop"):
        """
        Initializes a new MidiLoop instance.
        """
        self.loop_type = loop_type
        self.loop_start_timestamp = 0
        self.total_loop_time = 0
        self.current_loop_time = 0
        self.loop_notes_on_time_ary = []  # Note, Velocity, Time, pad idx
        self.loop_notes_off_time_ary = []
        self.loop_notes_on_queue = []  # Note, Velocity, Time, pad idx
        self.loop_notes_off_queue = []
        self.loop_playstate = False
        self.loop_record_state = False
        self.has_loop = False

        if self.loop_type == "loop":
            MidiLoop.loops.append(self)

    def reset_loop(self):
        """
        Resets the loop to start from the beginning.
        """
        self.loop_start_timestamp = time.monotonic()
        self.loop_notes_on_queue = []
        self.loop_notes_off_queue = []

        # Set up new note ary for next time around
        for note in self.loop_notes_on_time_ary:
            self.loop_notes_on_queue.append(note)
            send_midi_note_off(note[0])  # catch hanging notes
            pixel_note_off(note[3])  # Catch hanging pixels
        for note in self.loop_notes_off_time_ary:
            self.loop_notes_off_queue.append(note)

    def clear_loop(self):
        """
        Clears all recorded notes and resets loop attributes.
        """
        self.loop_notes_on_time_ary = []
        self.loop_notes_off_time_ary = []
        self.loop_notes_on_queue = []
        self.loop_notes_off_queue = []
        self.total_loop_time = 0
        self.loop_start_timestamp = 0
        self.loop_toggle_playstate(False)
        self.toggle_record_state(False)
        self.current_loop_time = 0
        self.has_loop = False

        clear_all_notes()  # Make sure nothing is caught in an on state

        display.display_notification("Loop Cleared")

    def loop_toggle_playstate(self, on_or_off=None):
        """
        Toggles loop play state on or off.

        Args:
            on_or_off (bool, optional): True to turn on, False to turn off. Default is None.
        """
        if on_or_off is True:
            self.loop_playstate = True
        elif on_or_off is False:
            self.loop_playstate = False
        else:
            self.loop_playstate = not self.loop_playstate

        self.current_loop_time = 0

        if self.loop_playstate:
            self.reset_loop()

        if not self.loop_playstate:
            self.loop_start_timestamp = 0

        if self.loop_type == "loop":
            display.toggle_play_icon(self.loop_playstate)

        debug.add_debug_line("Loop Playstate", self.loop_playstate)

    def toggle_record_state(self, on_or_off=None):
        """
        Toggles loop recording state on or off.

        Args:
            on_or_off (bool, optional): True to turn on, False to turn off. Default is None.
        """
        if on_or_off is True:
            self.loop_record_state = True
        elif on_or_off is False:
            self.loop_record_state = False
        else:
            self.loop_record_state = not self.loop_record_state

        display.toggle_recording_icon(self.loop_record_state)

        if self.loop_record_state and not self.has_loop:
            self.loop_start_timestamp = time.monotonic()
            self.loop_toggle_playstate(True)

        elif not self.loop_record_state and self.has_loop is False:
            self.total_loop_time = time.monotonic() - self.loop_start_timestamp
            self.has_loop = True

        debug.add_debug_line("Loop Record State", self.loop_record_state, True)

    def add_loop_note(self, midi, velocity, padidx, add_or_remove):
        """
        Adds a note to the loop.

        Args:
            midi (int): MIDI note number.
            velocity (int): Velocity of the note.
            add_or_remove (bool): True to add note to the ON queue, False to add note to the OFF queue.
        """
        if not self.loop_record_state:
            print_debug("Not in record mode.. can't add new notes")
            return

        if self.loop_start_timestamp == 0:
            print_debug("loop not playing, cannot add")
            display.display_notification(f"Play loop to record")
            self.toggle_record_state(False)
            return

        note_time_offset = time.monotonic() - self.loop_start_timestamp
        note_data = (midi, velocity, note_time_offset, padidx)
        free_memory()
        if len(self.loop_notes_on_time_ary) > constants.MIDI_NOTES_LIMIT:
            display.display_notification(f"MAX NOTES REACHED")
            self.toggle_record_state(False)
            return

        if add_or_remove:
            self.loop_notes_on_time_ary.append(note_data)
            debug.add_debug_line(f"Num Midi notes in looper", len(self.loop_notes_on_time_ary))
        else:
            self.loop_notes_off_time_ary.append(note_data)

    def remove_loop_note(self, idx):
        """
        Removes a note from the loop record at the specified index.

        Args:
            idx (int): Index of the note to be removed.
        """
        if idx < 0 or idx >= len(self.loop_notes_on_time_ary):
            print_debug("Cannot remove loop note - invalid index")
            return
        else:
            try:
                self.loop_notes_on_time_ary.pop(idx)
                self.loop_notes_off_time_ary.pop(idx)
            except IndexError:
                print_debug("Couldn't remove note")

    def trim_silence(self):
        """
        Trims silence at the beginning and end of the loop.
        """
        if len(self.loop_notes_on_time_ary) == 0:
            return

        first_hit_time = self.loop_notes_on_time_ary[0][2]
        last_note = self.loop_notes_on_time_ary[-1][0]
        last_hit_time_off = self.loop_notes_off_time_ary[-1][2]

        for idx, (note, vel, hit_time, padidx) in enumerate(self.loop_notes_on_time_ary):
            new_time = hit_time - first_hit_time
            self.loop_notes_on_time_ary[idx] = (note, vel, new_time, padidx)

        for idx, (note, vel, hit_time, padidx) in enumerate(self.loop_notes_off_time_ary):
            new_time = hit_time - first_hit_time
            self.loop_notes_off_time_ary[idx] = (note, vel, new_time, padidx)

        new_length = last_hit_time_off - first_hit_time + 0.5
        print_debug(f"Silence Trimmed. New Loop Len: {new_length}  Old Loop Len: {self.total_loop_time}  ")
        print_debug(f"First note timing: {self.loop_notes_on_time_ary[0][2]}")
        self.total_loop_time = new_length

        if len(self.loop_notes_on_time_ary) != len(self.loop_notes_off_time_ary):
            self.loop_notes_off_time_ary.append((last_note, 120, new_length - 0.5))
        return

    def get_new_notes(self):
        """
        Checks for new notes to be played based on loop position.

        Returns:
            tuple: Tuple in the form (on_array, off_array) containing new notes to play ON and OFF.
        """
        new_on_notes = []
        new_off_notes = []

        if not self.total_loop_time > 0 or self.loop_start_timestamp == 0:
            return None

        now_time = time.monotonic()
        if now_time - self.loop_start_timestamp > self.total_loop_time:
            print_debug(f"self.total_loop_time: {self.total_loop_time}")

            if self.loop_type == "loop":
                self.reset_loop()

            if self.loop_type == "chord":
                self.loop_toggle_playstate(False)

            return

        self.current_loop_time = time.monotonic() - self.loop_start_timestamp

        for idx, (note, vel, hit_time, padidx) in enumerate(self.loop_notes_on_queue):
            if hit_time < self.current_loop_time:
                new_on_notes.append((note, vel, padidx))
                self.loop_notes_on_queue.pop(idx)
                pixel_note_on(padidx)

        for idx, (note, vel, hit_time, padidx) in enumerate(self.loop_notes_off_queue):
            if hit_time < self.current_loop_time:
                new_off_notes.append((note, vel, padidx))
                self.loop_notes_off_queue.pop(idx)
                pixel_note_off(padidx)

        if len(new_on_notes) > 0 or len(new_off_notes) > 0:
            return new_on_notes, new_off_notes

    def quantize_notes(self, quantization_amt = "sixteenth"):
        """
        Quantizes the note timings based on the specified quantization amount.

        Args:
            quantization_amt (str): The quantization amount. Valid values are "whole", "half", "quarter", "eighth", "sixteenth", "1", "1/2", "1/4", ..., "1/32".

        Returns:
            None
        """
        if quantization_idx == 0: # No quantization selected
            return
        
        note_time_ms = get_note_time(quantization_amt)
        print_debug(f"Quantizing to {quantization_amt} notes - {note_time_ms} ms")

        # Quantize on notes
        for idx, (note, vel, hit_time, padidx) in enumerate(self.loop_notes_on_time_ary):
            if hit_time % note_time_ms > note_time_ms / 2:
                new_time = hit_time + (note_time_ms - hit_time % note_time_ms)
            else:
                new_time = hit_time - (hit_time % note_time_ms)

            self.loop_notes_on_time_ary[idx] = (note, vel, new_time, padidx)
        

def get_loopermode_display_text():
    """
    Returns the display text for the looper mode.
    """
    disp_text = ["<- click = record ",
                 "   dbl  = st/stop",
                 "   hold = clear loop"]
    return disp_text


def update_play_rec_icons():
    """
    Updates the play and record icons on the display.
    """
    display.toggle_play_icon(MidiLoop.current_loop_obj.loop_playstate)
    display.toggle_recording_icon(MidiLoop.current_loop_obj.loop_record_state)


def process_select_btn_press():
    """
    Processes the select button press in the menu.
    """
    MidiLoop.current_loop_obj.toggle_record_state()


def clear_all_loops():
    """
    Clears all playing loops.
    """
    print_debug("Clearing all loops")
    MidiLoop.current_loop_obj.clear_loop()


def toggle_loops_playstate():
    """
    Stops all playing loops and turns off recording.
    """
    MidiLoop.current_loop_obj.loop_toggle_playstate()
    MidiLoop.current_loop_obj.toggle_record_state(False)


def encoder_chg_function(direction):
    """
    Called when the encoder changes in the looper menu.

    Args:
        direction (bool): True for clockwise, False for counterclockwise.
    """
    notes_ary_length = len(MidiLoop.current_loop_obj.loop_notes_on_time_ary)
    if notes_ary_length < 1:
        return
    if direction:
        return
    else:
        remove_idx = random.randint(0, notes_ary_length - 1)
        MidiLoop.current_loop_obj.remove_loop_note(remove_idx)
        display.display_notification(f"Removed note: {remove_idx + 1}")


def setup_midi_loops():
    """
    Initializes a MIDI loop and sets it as the current loop object.
    """
    _ = MidiLoop()
    MidiLoop.current_loop_obj = MidiLoop.loops[MidiLoop.current_loop_idx]

def next_quantization(forward=True):
    """
    Changes the quantization setting to the next value in the list.

    Args:
        forward (bool, optional): True to go forward, False to go backwards. Default is True.
    """
    global quantization_idx
    if forward:
        quantization_idx += 1
        if quantization_idx >= len(QUANTIZATION_OPTIONS):
            quantization_idx = 0
    else:
        quantization_idx -= 1
        if quantization_idx < 0:
            quantization_idx = len(QUANTIZATION_OPTIONS) - 1

def get_quantization_text():
    """
    Returns the display text for the current quantization setting.
    """
    return f"Quantize: {QUANTIZATION_OPTIONS[quantization_idx]}"
