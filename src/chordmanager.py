import constants
import looper
from display import set_blink_pixel, pixels_set_default_color, display_notification, pixel_set_color,get_default_color
from settings import settings
from clock import clock

class ChordManager:
    def __init__(self):
        self.pad_chords = [""] * 16  # Stores chord loop objects for pads
        self.chord_playback_queue = [False] * 16  # Play these when start midi msg
        self.is_playing_global = False
        self.recording_pad_idx = ""
        self.is_recording = False

    def add_remove_chord(self, pad_idx):
        """
        Either starts recording a chord if there is no chord on the pad at the given index,
        or deletes the chord if one exists.

        Args:
            pad_idx (int): The index of the pad to add or remove a chord from.
        """
        print(f"pad_idx: {pad_idx}")
        print(f"recording pad idx: {self.recording_pad_idx}")
        if self.pad_chords[pad_idx] == "" and self.recording_pad_idx == "":  # No chord - start recording
            display_notification("Recording Chord")
            self.pad_chords[pad_idx] = looper.MidiLoop(loop_type=settings.chordmode_looptype, assigned_pad_idx=pad_idx)
            self.pad_chords[pad_idx].toggle_record_state()
            self.recording_pad_idx = pad_idx
            self.is_recording = True
            set_blink_pixel(pad_idx, True, constants.RED)
            pixels_set_default_color(pad_idx, constants.CHORD_COLOR)

            
        elif self.recording_pad_idx == pad_idx or (not self.is_recording):
            pixels_set_default_color(pad_idx, constants.BLACK)
            set_blink_pixel(pad_idx, False)
            self.turn_off_chord_pixels(pad_idx)
            self.pad_chords[pad_idx] = ""
            self.recording_pad_idx = ""
            self.chord_playback_queue[pad_idx] = False
            self.is_recording = False
            display_notification(f"Chord Deleted on pad {pad_idx}")



    def chordmode_fn_press_function(self, action_type="press"):
        """
        Stops the recording of a chord if one is currently being recorded.

        Args:
            action_type (str, optional): The type of action performed. Default is "press".
        """
        if action_type != "release" and self.is_recording:
            self.pad_chords[self.recording_pad_idx].toggle_record_state(False)
            self.pad_chords[self.recording_pad_idx].trim_silence()
            self.pad_chords[self.recording_pad_idx].quantize_notes()
            self.pad_chords[self.recording_pad_idx].quantize_loop()
            if self.pad_chords[self.recording_pad_idx].loop_is_playing:
                pixels_set_default_color(self.recording_pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
            set_blink_pixel(self.recording_pad_idx, False)
            self.recording_pad_idx = ""
            self.is_recording = False

    def change_chord_loop_mode(self, button_idx):
        """
        Toggles between 1 shot mode and loop mode for the chord at the given index.

        Args:
            button_idx (int): The index of the pad to change the chord type of.
        """
        if self.pad_chords[button_idx] != "":
            self.pad_chords[button_idx].change_chord_loop_mode()
            self.pad_chords[button_idx].reset_loop_notes_and_pixels()
            self.pad_chords[button_idx].toggle_playstate(False)
            self.display_chord_loop_mode(button_idx)

    def display_chord_loop_mode(self, idx):
        """
        Displays the loop type of the chord at the given index.

        Args:
            idx (int): The index of the pad to display the loop type for.
        """
        if self.pad_chords[idx] != "":
            chord_mode = "1 shot" if self.pad_chords[idx].loop_type == "chord" else "Loop"
            display_notification(f"Chord Type: {chord_mode}")

    def toggle_chord_by_index(self, idx):
        """
        Processes a new button press event for the given index.

        Args:
            idx (int): The index of the button that was pressed.
        """
        if self.pad_chords[idx] and not self.is_recording:
            if settings.midi_sync:
                self.chord_playback_queue[idx] = not self.chord_playback_queue[idx]

                if not clock.is_playing:
                    set_blink_pixel(idx, self.chord_playback_queue[idx], constants.PIXEL_LOOP_PLAYING_COLOR)
                    return

            else:
                self.toggle_chord_playback(idx)

    def process_chord_on_queue(self):
        """
        Checks if there are any chords in the play queue and processes them if the clock is playing.
        """
        if clock.is_playing and not self.is_playing_global:
            self.is_playing_global = True
            for idx, play in enumerate(self.chord_playback_queue):
                if play:
                    self.toggle_chord_playback(idx)

    def stop_all_chords(self):
        """
        Stops all chords from playing. Called when MIDI stop message is received.
        """
        if self.is_playing_global and not clock.is_playing:
            self.is_playing_global = False
            for idx in range(16):
                if self.pad_chords[idx] != "":
                    if self.chord_playback_queue[idx] and self.pad_chords[idx].loop_is_playing:
                        set_blink_pixel(idx, True, constants.PIXEL_LOOP_PLAYING_COLOR)
                    else:
                        self.chord_playback_queue[idx] = False
                    self.pad_chords[idx].toggle_playstate(False)
                    self.pad_chords[idx].reset_loop_notes_and_pixels()
                    pixels_set_default_color(idx, constants.CHORD_COLOR)
    
    # def reset_chord_loops(self):
    #     """
    #     Resets all chord loops.
    #     """

    def toggle_chord_playback(self, idx):
        """
        Plays the chord at the given index.

        Args:
            idx (int): The index of the pad to play the chord from.
        """
        if self.pad_chords[idx] == "":
            return

        if self.pad_chords[idx].loop_type == "chordloop":
            self.pad_chords[idx].toggle_playstate()
            self.pad_chords[idx].reset_loop_notes_and_pixels()
        else:
            self.pad_chords[idx].toggle_playstate(True)

        set_blink_pixel(idx, False)

    def get_chord_notes(self, padidx):
        """
        Retrieves the notes of the chord at the given pad index.

        Args:
            padidx (int): The index of the pad to retrieve the chord notes from.

        Returns:
            list: The list of notes in the chord. Returns an empty list if there is no chord on the pad.
        """
        if self.pad_chords[padidx] != "":
            return self.pad_chords[padidx].get_all_notes_list()
        return []
    
    def turn_off_chord_pixels(self, pad_idx):
        """
        Turns off all chord pixels.
        """
        if self.pad_chords[pad_idx] != "":
            for _,_,pixel_idx in self.get_chord_notes(pad_idx):
                pixel_set_color(pixel_idx, get_default_color(pixel_idx))

chord_manager = ChordManager()
