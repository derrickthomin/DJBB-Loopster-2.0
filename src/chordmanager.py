import constants
from looper import MidiLoop
from display import display
from pixels import pixels
from settings import settings
from clock import clock
from debug import print_debug

class ChordManager:
    def __init__(self):
        self.chord_loops = [""] * 16  # Stores chord loop objects for pads
        self.play_queue = [False] * 16  # Play these when start midi msg
        self.any_chord_playing = False
        self.recording_pad = ""
        self.is_recording = False
    
    def add_remove_chord(self, pad_idx):
        """
        Either starts recording a chord if there is no chord on the pad at the given index,
        or deletes the chord if one exists.

        Args:
            pad_idx (int): The index of the pad to add or remove a chord from.
        """
        print_debug(f"pad_idx: {pad_idx}")
        print_debug(f"recording pad idx: {self.recording_pad}")

        # No chord so create chord
        if self.chord_loops[pad_idx] == "" and self.recording_pad == "":
            self._create_new_chord(pad_idx)

        # Else, remove chord
        elif self.recording_pad == pad_idx or (not self.is_recording):
            self._remove_chord(pad_idx)

    def _create_new_chord(self, pad_idx):
        display.show_notification("Recording Chord")
        self.chord_loops[pad_idx] = MidiLoop(
            loop_type=settings.chordmode_looptype, 
            assigned_pad_idx=pad_idx
        )
        self.chord_loops[pad_idx].toggle_record_state()
        self.recording_pad = pad_idx
        self.is_recording = True
        pixels.set_blink(pad_idx, True, constants.RED)
        pixels.set_default_color(pad_idx, constants.CHORD_COLOR)
        print_debug(f"Chord created on pad {pad_idx}")

    def _remove_chord(self, pad_idx):
        pixels.set_default_color(pad_idx)
        pixels.set_blink(pad_idx, False)
        self._reset_pixels(pad_idx)
        self.chord_loops[pad_idx] = ""
        self.recording_pad = ""
        self.play_queue[pad_idx] = False
        self.is_recording = False
        display.show_notification(f"Chord Deleted on pad {pad_idx}")
        print_debug(f"Chord removed from pad {pad_idx}")

    def _finalize_recording(self):
        self.chord_loops[self.recording_pad].trim_silence()
        self.chord_loops[self.recording_pad].quantize_notes()
        self.chord_loops[self.recording_pad].quantize_loop()

    def handle_fn_press(self, action_type="press"):
        """
        Stops the recording of a chord if one is currently being recorded.

        Args:
            action_type (str, optional): The type of action performed. Default is "press".
        """
        if action_type == "press" and self.is_recording:
            self.chord_loops[self.recording_pad].toggle_record_state(False)
            self._finalize_recording()
            pixels.set_blink(self.recording_pad, False)
            if settings.midi_sync:
                self.play_queue[self.recording_pad] = True
                if clock.is_playing:
                    self.chord_loops[self.recording_pad].toggle_playstate(True)
                else:
                    pixels.set_blink(self.recording_pad, True, constants.PIXEL_LOOP_PLAYING_COLOR)

            elif self.chord_loops[self.recording_pad].loop_is_playing:
                pixels.set_default_color(self.recording_pad, constants.PIXEL_LOOP_PLAYING_COLOR)

            self.recording_pad = ""
            self.is_recording = False

            print_debug("Chord recording stopped")

    def change_chord_loop_mode(self, button_idx):
        """
        Toggles between 1 shot mode and loop mode for the chord at the given index.

        Args:
            button_idx (int): The index of the pad to change the chord type of.
        """
        if self.chord_loops[button_idx] != "":
            self.chord_loops[button_idx].change_chord_loop_mode()
            self.chord_loops[button_idx].clear_notes_and_pixels()
            self.chord_loops[button_idx].toggle_playstate(False)
            self.display_chord_loop_mode(button_idx)

    def display_chord_loop_mode(self, idx):
        """
        Displays the loop type of the chord at the given index.

        Args:
            idx (int): The index of the pad to display the loop type for.
        """
        if self.chord_loops[idx] != "":
            chord_mode = "1 shot" if self.chord_loops[idx].loop_type == "chord" else "Loop"
            display.show_notification(f"Chord Type: {chord_mode}")

    def toggle_chord_playstate(self, idx):
        """
        Processes a new button press event for the given index.
        Either adds it to the play queue, starts playback, or both

        Args:
            idx (int): The index of the button that was pressed.
        """
        if self.is_recording or not self.chord_loops[idx]: # This press is for a note if recording
            return
        
        sync_on = settings.midi_sync

        if sync_on:
            is_queued = not self.play_queue[idx]
            self.play_queue[idx] = is_queued
            pixels.set_blink(idx, is_queued, constants.PIXEL_LOOP_PLAYING_COLOR)

            if clock.is_playing:
                self._play_chord(idx, is_queued)
        else:
            self._play_chord(idx)


    def process_chord_on_queue(self):
        """
        Checks if there are any chords in the play queue and processes them if the clock is playing.
        """
        if clock.is_playing and not self.any_chord_playing:
            self.any_chord_playing = True
            for idx, play in enumerate(self.play_queue):
                if play:
                    self._play_chord(idx)

    def stop_all_chords(self):
        """
        Stops all chords from playing. Called when MIDI stop message is received.
        """
        if not self.any_chord_playing or clock.is_playing:
            return

        self.any_chord_playing = False
        for idx in range(16):
            chord_obj = self.chord_loops[idx]
            if chord_obj:
                self._stop_single_chord(idx, chord_obj)

    def _stop_single_chord(self, idx, chord_obj):
        """
        Stops a chord at the given index, clearing states/pixels, etc.
        """
        # If we queued this chord and it’s playing, leave its blink on
        if self.play_queue[idx] and chord_obj.loop_is_playing:
            pixels.set_blink(idx, True, constants.PIXEL_LOOP_PLAYING_COLOR)
        else:
            self.play_queue[idx] = False
        
        chord_obj.toggle_playstate(False)
        chord_obj.clear_notes_and_pixels()
        pixels.set_default_color(idx, constants.CHORD_COLOR)

    def _play_chord(self, idx, on_or_off=None):
        """
        Plays the chord at the given index.

        Args:
            idx (int): The index of the pad to play the chord from.
        """
        if self.chord_loops[idx] == "":
            return

        if self.chord_loops[idx].loop_type == "chordloop":
            self.chord_loops[idx].toggle_playstate(on_or_off)
            self.chord_loops[idx].clear_notes_and_pixels()
        else:
            self.chord_loops[idx].toggle_playstate(True)

        pixels.set_blink(idx, False)

    def unique_notes(self, padidx):
        """
        Retrieves the notes of the chord at the given pad index.

        Args:
            padidx (int): The index of the pad to retrieve the chord notes from.

        Returns:
            list: The list of notes in the chord. Returns an empty list if there is no chord on the pad.
        """
        if self.chord_loops[padidx] != "":
            return self.chord_loops[padidx].get_all_notes_list()
        return []
    
    def _reset_pixels(self, pad_idx):
        """
        Turns off all chord pixels.
        """
        if self.chord_loops[pad_idx] != "":
            for _,_,pixel_idx in self.unique_notes(pad_idx):
                pixels.set_color(pixel_idx, pixels.get_default_color(pixel_idx))
                print_debug(f"Turning off pixel {pixel_idx}")

chord_manager = ChordManager()
