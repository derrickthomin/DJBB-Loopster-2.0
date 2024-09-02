# 

import constants
import looper
from display import set_blink_pixel, set_default_color, display_notification, set_blink_color
from settings import settings
from debug import print_debug
from clock import clock

class ChordManager:
    def __init__(self):
        self.pad_chords = [""] * 16  # Stores chord loop objects for pads
        self.queued_for_playback = [False] * 16  # Play these when start midi msg
        self.global_play_state = False
        self.recording_pad_idx = ""
        self.recording = False

    def add_remove_chord(self, pad_idx):
        """
        Either starts recording a chord if there is no chord on the pad at the given index,
        or deletes the chord if one exists.

        Args:
            pad_idx (int): The index of the pad to add or remove a chord from.
        """
        if self.pad_chords[pad_idx] == "":  # No chord - start recording
            display_notification("Recording Chord")
            self.pad_chords[pad_idx] = looper.MidiLoop(loop_type=settings.CHORDMODE_LOOPTYPE)
            self.pad_chords[pad_idx].toggle_record_state()
            self.recording_pad_idx = pad_idx
            self.recording = True
            set_blink_pixel(pad_idx, True, constants.RED)
            set_default_color(pad_idx, constants.CHORD_COLOR)
        else:  # Chord exists - delete it
            self.pad_chords[pad_idx] = ""
            self.queued_for_playback[pad_idx] = False
            self.recording = False
            display_notification(f"Chord Deleted on pad {pad_idx}")
            set_default_color(pad_idx, constants.BLACK)
            set_blink_pixel(pad_idx, False)

    def chordmode_fn_press_function(self, action_type="press"):
        """
        Stops the recording of a chord if one is currently being recorded.

        Args:
            action_type (str, optional): The type of action performed. Default is "press".
        """
        if action_type != "release" and self.recording:
            self.pad_chords[self.recording_pad_idx].toggle_record_state(False)
            self.pad_chords[self.recording_pad_idx].trim_silence()
            self.pad_chords[self.recording_pad_idx].quantize_notes()
            self.pad_chords[self.recording_pad_idx].quantize_loop()
            if self.pad_chords[self.recording_pad_idx].loop_playstate:
                set_default_color(self.recording_pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
            set_blink_pixel(self.recording_pad_idx, False)
            self.recording = False

    def toggle_chord_loop_type(self, button_idx):
        """
        Toggles between 1 shot mode and loop mode for the chord at the given index.

        Args:
            button_idx (int): The index of the pad to change the chord type of.
        """
        if self.pad_chords[button_idx] != "":
            self.pad_chords[button_idx].toggle_chord_loop_type()
            self.pad_chords[button_idx].reset_loop_notes_and_pixels()
            self.pad_chords[button_idx].loop_toggle_playstate(False)
            self.display_chord_loop_type(button_idx)

    def display_chord_loop_type(self, idx):
        """
        Displays the loop type of the chord at the given index.

        Args:
            idx (int): The index of the pad to display the loop type for.
        """
        if self.pad_chords[idx] != "":
            chordmodetype = "1 shot" if self.pad_chords[idx].loop_type == "chord" else "Loop"
            display_notification(f"Chord Type: {chordmodetype}")

    def process_new_button_press(self, idx):
        """
        Processes a new button press event for the given index.

        Args:
            idx (int): The index of the button that was pressed.
        """
        if self.pad_chords[idx] and not self.recording:
            if settings.MIDI_SYNC:
                self.queued_for_playback[idx] = not self.queued_for_playback[idx]

                if not clock.play_state:
                    set_blink_pixel(idx, self.queued_for_playback[idx], constants.PIXEL_LOOP_PLAYING_COLOR)
                    return

            self.toggle_chord(idx)

    def check_process_chord_on_queue(self):
        """
        Checks if there are any chords in the play queue and processes them if the clock is playing.
        """
        if clock.play_state and not self.global_play_state:
            self.global_play_state = True
            for idx, play in enumerate(self.queued_for_playback):
                if play:
                    self.toggle_chord(idx)

    def check_stop_all_chords(self):
        """
        Stops all chords from playing. Called when MIDI stop message is received.
        """
        if self.global_play_state and not clock.play_state:
            self.global_play_state = False
            for idx in range(16):
                if self.pad_chords[idx] != "":
                    if self.queued_for_playback[idx] and self.pad_chords[idx].loop_playstate:
                        set_blink_pixel(idx, True, constants.PIXEL_LOOP_PLAYING_COLOR)
                    else:
                        self.queued_for_playback[idx] = False
                    self.pad_chords[idx].loop_toggle_playstate(False)
                    self.pad_chords[idx].reset_loop_notes_and_pixels()
                    set_default_color(idx, constants.CHORD_COLOR)

    def toggle_chord(self, idx):
        """
        Plays the chord at the given index.

        Args:
            idx (int): The index of the pad to play the chord from.
        """
        if self.pad_chords[idx] == "":
            return

        if self.pad_chords[idx].loop_type == "chordloop":
            self.pad_chords[idx].loop_toggle_playstate()
            self.pad_chords[idx].reset_loop_notes_and_pixels()
        else:
            self.pad_chords[idx].reset_loop()

        # Update pixel colors based on play state
        color = constants.PIXEL_LOOP_PLAYING_COLOR if self.pad_chords[idx].loop_playstate else constants.CHORD_COLOR
        set_default_color(idx, color)
        set_blink_pixel(idx, False)

    def get_current_chord_notes(self, padidx):
        """
        Retrieves the notes of the chord at the given pad index.

        Args:
            padidx (int): The index of the pad to retrieve the chord notes from.

        Returns:
            list: The list of notes in the chord. Returns an empty list if there is no chord on the pad.
        """
        if self.pad_chords[padidx] != "":
            return self.pad_chords[padidx].get_all_notes()
        return []

chord_manager = ChordManager()
