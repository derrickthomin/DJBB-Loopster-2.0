import constants
from debug import free_memory
from looper import make_midi_loop
from display import display
from pixels import pixels
from settings import settings
from clock import clock

class ChordManager:
    def __init__(self):
        self.chord_loops = [""] * 16  # Stores chord loop objects for pads
        self.play_queue = [False] * 16  # Play these when start midi msg
        self.any_chord_playing = False
        self.recording_pad = ""
        self.is_recording = False
    
    def add_remove_chord(self, pad_idx):
        """
        Add or remove a chord at the specified pad index.
        """
        # No chord so create chord
        if self.chord_loops[pad_idx] == "" and self.recording_pad == "":
            self._create_new_chord(pad_idx)

        # Else, remove chord
        elif self.recording_pad == pad_idx or (not self.is_recording):
            self._remove_chord(pad_idx)
    
    def _create_new_chord(self, pad_idx):
        free_memory()
        display.show_notification("Recording Chord")
        self.chord_loops[pad_idx] = make_midi_loop(
            loop_type=settings.chordmode_looptype, 
            pad_idx=pad_idx
        )
        self.chord_loops[pad_idx].toggle_record_state()
        self.recording_pad = pad_idx
        self.is_recording = True
        pixels.set_blink(pad_idx, True, constants.RED)
        pixels.set_default_color(pad_idx, constants.CHORD_COLOR)

    def _remove_chord(self, pad_idx):
        pixels.set_default_color(pad_idx)
        pixels.set_blink(pad_idx, False)
        self.chord_loops[pad_idx].clear_notes_and_pixels()
        self.chord_loops[pad_idx] = ""
        self.recording_pad = ""
        self.play_queue[pad_idx] = False
        self.is_recording = False
        display.show_notification(f"Chord Deleted on pad {pad_idx}")

    def check_event_limits(self):
        """
        Checks if the number of events in the chord loops exceeds the limit.
        If it does, it stops all chords and clears the play queue.
        """
        if self.recording_pad == "":
            return
        chord = self.chord_loops[self.recording_pad]
        
        if chord.max_events_reached:
            self.handle_fn_press()

    def handle_fn_press(self, action_type="press"):
        """
        Stops the recording of a chord if one is currently being recorded.

        Args:
            action_type (str, optional): The type of action performed. Default is "press".
        """
        if action_type == "press" and self.is_recording:
            pad_idx = self.recording_pad  # Store for later use
            self.chord_loops[pad_idx].toggle_record_state(False)

            # Always turn off blinking when recording stops
            pixels.set_blink(pad_idx, False)
            
            if settings.midi_sync:
                # MIDI sync mode behavior
                self.play_queue[pad_idx] = True
                if clock.is_playing:
                    self.chord_loops[pad_idx].toggle_playstate(True)
                    # Set the color to playing
                    pixels.set_color(pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                    pixels.set_default_color(pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                else:
                    # Queue for play but don't start yet
                    pixels.set_blink(pad_idx, True, constants.PIXEL_LOOP_PLAYING_COLOR)
            else:
                # Non-MIDI sync mode - immediately start playing the recorded chord
                # Ensure loop is playing (should already be true from recording)
                if not self.chord_loops[pad_idx].loop_is_playing:
                    self.chord_loops[pad_idx].toggle_playstate(True)
                
                # Always set the color to indicate playing state
                pixels.set_color(pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                pixels.set_default_color(pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)

            # Clear recording state
            self.recording_pad = ""
            self.is_recording = False

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
            chord_mode = "1 shot" if self.chord_loops[idx].loop_type == "oneshot" else "Loop"
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

        if settings.midi_sync:
            # Special handling for oneshot chords
            if self.chord_loops[idx].loop_type == "oneshot":
                is_clock_playing = clock.is_playing
                
                # If the chord is already in the play queue
                if self.play_queue[idx]:
                    if is_clock_playing:
                        # If clock is playing and chord is in queue, restart it
                        self.chord_loops[idx].toggle_playstate(False)  # First stop it
                        self.chord_loops[idx].toggle_playstate(True)   # Then restart it
                        # Visual feedback - solid playing color
                        pixels.set_blink(idx, False)
                        pixels.set_color(idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                        pixels.set_default_color(idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                    else:
                        # If clock is not playing and chord is in queue, remove it
                        self.play_queue[idx] = False
                        # Only toggle the visual state, don't affect playback state
                        pixels.set_blink(idx, False)
                        pixels.set_color(idx, constants.CHORD_COLOR)
                        pixels.set_default_color(idx, constants.CHORD_COLOR)
                else:
                    # Not in queue, add it
                    self.play_queue[idx] = True
                    
                    if is_clock_playing:
                        # If clock is playing, start it immediately
                        self.chord_loops[idx].toggle_playstate(True)
                        # Visual feedback - solid playing color
                        pixels.set_blink(idx, False)
                        pixels.set_color(idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                        pixels.set_default_color(idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                    else:
                        # If clock is not playing, just queue it without starting
                        # Don't trigger playback
                        pixels.set_blink(idx, True, constants.PIXEL_LOOP_PLAYING_COLOR)
            else:
                # Standard behavior for loop chords - toggle queue state
                self.play_queue[idx] = not self.play_queue[idx]
                pixels.set_blink(idx, self.play_queue[idx], constants.PIXEL_LOOP_PLAYING_COLOR)

            # If clock is already playing, start/restart the chord now
            if clock.is_playing:
                self._play_chord(idx)
                print("clock is playing, playing chord")
        else:
            # Non-MIDI sync mode - always just play the chord
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
        # If we queued this chord and it's playing, leave its blink on
        if self.play_queue[idx] and chord_obj.loop_is_playing:
            pixels.set_blink(idx, True, constants.PIXEL_LOOP_PLAYING_COLOR)
        else:
            self.play_queue[idx] = False
        
        chord_obj.toggle_playstate(False)
        chord_obj.clear_notes_and_pixels()
        pixels.set_default_color(idx, constants.CHORD_COLOR)

    def _play_chord(self, idx, on_or_off=None):
        """
        Plays or stops the chord at the given index.

        Args:
            idx (int): The index of the pad to play the chord from.
            on_or_off (bool, optional): Force playstate on or off. If None, toggle the current state.
        """
        if self.chord_loops[idx] == "":
            return
        
        # Toggle the playstate as needed
        if self.chord_loops[idx].loop_type == "chordloop":
            # Toggle or set the play state
            previous_state = self.chord_loops[idx].loop_is_playing
            self.chord_loops[idx].toggle_playstate(on_or_off)
            print(f"Chord {idx} playstate: {self.chord_loops[idx].loop_is_playing}")

            # If we're turning off (or toggling from on to off), make sure to clear notes
            if previous_state and not self.chord_loops[idx].loop_is_playing:
                self.chord_loops[idx].clear_notes_and_pixels()
                pixels.set_default_color(idx, constants.CHORD_COLOR)
            elif not previous_state and self.chord_loops[idx].loop_is_playing:
                # When starting, clear any lingering notes and reset the timestamp
                self.chord_loops[idx].clear_notes_and_pixels()
                pixels.set_default_color(idx, constants.PIXEL_LOOP_PLAYING_COLOR)
        else:
            # For one-shot mode, always play
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
            return self.chord_loops[padidx].get_unique_notes()
        return []
    
    def unique_ccs(self, padidx):
        """
        Retrieves the CCs of the chord at the given pad index.

        Args:
            padidx (int): The index of the pad to retrieve the chord CCs from.

        Returns:
            list: The list of CCs in the chord. Returns an empty list if there is no chord on the pad.
        """
        if self.chord_loops[padidx] != "":
            return self.chord_loops[padidx].get_unique_ccs()
        return []
    
    def _reset_pixels(self, pad_idx):
        """
        Turns off all chord pixels.
        """
        if self.chord_loops[pad_idx] != "":
            for _,_,pixel_idx in self.unique_notes(pad_idx):
                pixels.set_color(pixel_idx, pixels.get_default_color(pixel_idx))

chord_manager = ChordManager()
