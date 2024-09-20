import adafruit_ticks as ticks
import random
import constants
from debug import debug, print_debug
import display
from midi import send_midi_note_off
from clock import clock
from utils import next_or_previous_index
from settings import settings
import settingsmenu
from display import set_blink_pixel

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
        reset_loop(): Resets the loop to start from the beginning.
        clear_loop(): Clears all recorded notes and resets loop attributes.
        toggle_playstate(on_or_off=None): Toggles loop play state on or off.
        toggle_record_state(on_or_off=None): Toggles loop recording state on or off.
        add_loop_note(midi, velocity, padidx, add_or_remove): Adds a note to the loop record.
        remove_loop_note(idx): Removes a note from the loop record at the specified index.
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
        self.notes_on_list = []
        self.notes_off_list = []
        self.notes_on_queue = []
        self.notes_off_queue = []
        self.loop_is_playing = False
        self.is_recording = False
        self.has_loop = False
        self.assigned_pad_idx = assigned_pad_idx # For chord loops

        if self.loop_type == "loop":
            MidiLoop.loops.append(self)

    def reset_loop(self):
        """
        Resets the loop to start from the beginning.
        """
        self.start_timestamp = ticks.ticks_ms()
        self.notes_on_queue = self.notes_on_list[:]
        self.notes_off_queue = self.notes_off_list[:]
        self.reset_loop_notes_and_pixels()

    def reset_loop_notes_and_pixels(self):
        """
        Turns off all notes and pixels in the loop.
        """
        note_list_reset = set(note[0] for note in self.notes_on_list)
        pixel_list_reset = set(note[3] for note in self.notes_on_list)

        for note in note_list_reset:
            send_midi_note_off(note)
        for pixel in pixel_list_reset:
            display.pixel_set_note_off(pixel)

    def clear_loop(self):
        """
        Clears all recorded notes and resets loop attributes.
        """
        self.notes_on_list.clear()
        self.notes_off_list.clear()
        self.notes_on_queue.clear()
        self.notes_off_queue.clear()
        self.total_time_seconds = 0
        self.start_timestamp = 0
        self.toggle_playstate(False)
        self.toggle_record_state(False)
        self.current_loop_time = 0
        self.has_loop = False

        display.display_notification("Loop Cleared")

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
            if self.loop_is_playing:
                self.reset_loop()
                if assigned_pad_idx > -1:
                    display.pixel_set_color(assigned_pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                    display.pixels_set_default_color(assigned_pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
            else:
                self.start_timestamp = 0
                self.reset_loop_notes_and_pixels()
                if assigned_pad_idx > -1:
                    display.pixel_set_color(assigned_pad_idx,constants.CHORD_COLOR)
                    display.pixels_set_default_color(assigned_pad_idx,constants.CHORD_COLOR)

        if self.loop_type == "loop":
            if self.loop_is_playing:
                self.reset_loop()
            else:
                self.reset_loop_notes_and_pixels()
                self.start_timestamp = 0
            display.toggle_play_icon(self.loop_is_playing)

        debug.add_debug_line("Loop Playstate", self.loop_is_playing)

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
            self.toggle_playstate(True)

        # Record mode off and we have notes
        elif not self.is_recording and ((self.has_loop and on_or_off is not False) or self.loop_type in ["chord", "chordloop"]):
            print(f"time total: {self.total_time_seconds}")
            if self.total_time_seconds < 0.1:
                self.total_time_seconds = ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0  # Convert to seconds
            if settings.midi_sync and not clock.get_playstate():
                self.toggle_playstate(False)

        debug.add_debug_line("Loop Record State", self.is_recording, True)

    def add_loop_note(self, midi, velocity, padidx, add_or_remove):
        """
        Adds a note to the loop.

        Args:
            midi (int): MIDI note number.
            velocity (int): Velocity of the note.
            padidx (int): Index of the pad.
            add_or_remove (bool): True to add note to the ON queue, False to add note to the OFF queue.
        """
        if not self.is_recording:
            print_debug("Not in record mode.. can't add new notes")
            return

        if self.start_timestamp == 0:
            print_debug("loop not playing, cannot add")
            display.display_notification("Play loop to record")
            self.toggle_record_state(False)
            return

        note_time_offset = ticks.ticks_diff(ticks.ticks_ms(), self.start_timestamp) / 1000.0  # Convert to seconds
        note_data = (midi, velocity, note_time_offset, padidx)

        if len(self.notes_on_list) > constants.LOOP_NOTES_LIMIT:
            display.display_notification("MAX NOTES REACHED")
            self.toggle_record_state(False)
            return

        if add_or_remove:
            if not self.has_loop:
                self.has_loop = True
            self.notes_on_list.append(note_data)
            print(f"num notes in looper: {len(self.notes_on_list)}")
        else:
            self.notes_off_list.append(note_data)

        debug.add_debug_line("Num Midi notes in looper", len(self.notes_on_list))

    def remove_loop_note(self, idx):
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

    def trim_silence(self):
        """
        Trims silence at the beginning and end of the loop.

        Args:
            trim_mode (str): The trim mode to use. Can be one of the following:
                - "none": No trimming will be performed.
                - "start": Trims silence only at the beginning of the loop.
                - "end": Trims silence only at the end of the loop.
                - "both": Trims silence at both the beginning and end of the loop.

        Returns:
            None
        """
        if not self.notes_on_list:
            return
        
        trim_mode=settings.trim_silence_mode

        if trim_mode == "none":
            print("No trimming")
            return

        if trim_mode in ["start", "both"]:
            first_note_on_time = self.notes_on_list[0][2]
            for idx, (note, vel, hit_time, padidx) in enumerate(self.notes_on_list):
                new_time = hit_time - first_note_on_time + 0.075
                self.notes_on_list[idx] = (note, vel, new_time, padidx)

            for idx, (note, vel, hit_time, padidx) in enumerate(self.notes_off_list):
                new_time = hit_time - first_note_on_time + 0.075
                self.notes_off_list[idx] = (note, vel, new_time, padidx)
            
            self.total_time_seconds -= first_note_on_time + 0.075

        if trim_mode in ["end", "both"]:
            first_note_on_time = self.notes_on_list[0][2]
            last_note_off_time = self.notes_off_list[-1][2]
            new_length = last_note_off_time - first_note_on_time + 0.01
            self.total_time_seconds = new_length

            if len(self.notes_on_list) != len(self.notes_off_list):
                print("oops")
                last_note = self.notes_on_list[-1][0]
                self.notes_off_list.append(
                    (last_note, 0, new_length - 0.05, self.notes_on_list[-1][3])
                )

    def get_new_notes(self):
        """
        Checks for new notes to be played based on loop position.

        Returns:
            tuple: Tuple in the form (on_array, off_array) containing new notes to play ON and OFF.
        """
        new_notes_on = []
        new_notes_off = []

        if not self.total_time_seconds > 0 or self.start_timestamp == 0:
            return None

        now_time = ticks.ticks_ms()
        if ticks.ticks_diff(now_time, self.start_timestamp) > self.total_time_seconds * 1000:  # Convert to milliseconds
            print_debug(f"self.total_time_seconds: {self.total_time_seconds}")

            if self.loop_type in ('loop', 'chordloop'):
                self.reset_loop()

            if self.loop_type == "chord":
                self.toggle_playstate(False)

            return None

        self.current_loop_time = ticks.ticks_diff(now_time, self.start_timestamp) / 1000.0  # Convert to seconds

        for idx, (note, vel, hit_time, padidx) in enumerate(self.notes_on_queue):
            if hit_time < self.current_loop_time:
                new_notes_on.append((note, vel, padidx))
                self.notes_on_queue.pop(idx)
                display.pixel_set_note_on(padidx)

        for idx, (note, vel, hit_time, padidx) in enumerate(self.notes_off_queue):
            if hit_time < self.current_loop_time:
                new_notes_off.append((note, vel, padidx))
                self.notes_off_queue.pop(idx)
                display.pixel_set_note_off(padidx)

        if new_notes_on or new_notes_off:
            return new_notes_on, new_notes_off

    def quantize_loop(self):
        """
        Quantizes the loop length based on the current quantization setting.

        Returns:
            None
        """
        amount = settings.quantize_loop
        if amount == "none":
            return
        
        quantization_ms = clock.get_note_duration_seconds(amount)
        remainder = self.total_time_seconds % quantization_ms
        adjustment = quantization_ms - remainder
        self.total_time_seconds += adjustment

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

        def quantize_time(hit_time):
            """
            Quantizes a given hit time to the nearest quantization amount.

            Args:
                hit_time (float): The original hit time.

            Returns:
                float: The quantized hit time.
            """
            remainder = hit_time % note_time_ms
            if remainder > note_time_ms / 2:
                update_amt = (note_time_ms - remainder) * quantization_percent
                new_time = hit_time + update_amt
            else:
                update_amt = remainder * quantization_percent
                new_time = hit_time - update_amt
            return new_time

        # Quantize note on times
        for idx, (note, vel, hit_time, padidx) in enumerate(self.notes_on_list):
            if idx == 0 and settings.trim_silence_mode in ["start", "both"]:
                continue

            new_time = quantize_time(hit_time)
            print(f"Original On Hit Time: {hit_time}, Quantized On Hit Time: {new_time}")
            self.notes_on_list[idx] = (note, vel, new_time, padidx)

        # Quantize note off times
        for idx, (note, vel, hit_time, padidx) in enumerate(self.notes_off_list):
            new_time = quantize_time(hit_time)
            print(f"Original Off Hit Time: {hit_time}, Quantized Off Hit Time: {new_time}")
            self.notes_off_list[idx] = (note, vel, new_time, padidx)

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
        self.reset_loop()
        print_debug(f"Chord Loop Type: {self.loop_type}")

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
    print_debug("Clearing all loops")
    MidiLoop.current_loop.clear_loop()

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
        MidiLoop.current_loop.remove_loop_note(remove_idx)
        display.display_notification(f"Removed note: {remove_idx + 1}")

def setup_midi_loops():
    """
    Initializes a MIDI loop and sets it as the current loop object.

    Returns:
        None
    """
    _ = MidiLoop()
    MidiLoop.current_loop = MidiLoop.loops[MidiLoop.current_loop_idx]

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