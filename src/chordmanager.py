import constants
from looper import make_midi_loop
from display import display
from pixels import pixels
from settings import settings
from clock import clock
from debug import free_memory

class ChordManager:
    def __init__(self):
        self.chord_loops = [""] * constants.NUM_PADS  # Stores chord loop objects for pads
        self.play_queue = [False] * constants.NUM_PADS  # Play these when start midi msg
        self.any_chord_playing = False
        self.recording_pad = None
        self.is_recording = False
    
    def add_remove_chord(self, pad_idx):
        """ Add or remove a chord at the specified pad index. """
        
        # No chord so create chord
        if self.chord_loops[pad_idx] == "" and self.recording_pad is None:
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
        self.recording_pad = None
        self.play_queue[pad_idx] = False
        self.is_recording = False
        display.show_notification(f"Chord Deleted on pad {pad_idx}")

    def check_event_limits(self):
        """
        Checks if the number of events in the chord loops exceeds the limit.
        If it does, it stops all chords and clears the play queue.
        """
        if self.recording_pad is None:
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
            self.recording_pad = None
            self.is_recording = False

    def change_chord_loop_mode(self, button_idx):
        """
        Toggles between 1 shot mode and loop mode for the chord at the given index.

        Args:
            button_idx (int): The index of the pad to change the chord type of.
        """
        if self.chord_loops[button_idx] != "":
            loop_type = self.chord_loops[button_idx].change_chord_loop_mode()
            self.chord_loops[button_idx].clear_notes_and_pixels()
            self.chord_loops[button_idx].toggle_playstate(False)
            self.display_chord_loop_mode(button_idx)
            if loop_type != settings.chordmode_looptype:
                settings.chordmode_looptype = loop_type

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

                        self.chord_loops[idx].toggle_playstate(False) 
                        self.chord_loops[idx].toggle_playstate(True)  
                        pixels.set_blink(idx, False)
                        pixels.set_color(idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                        pixels.set_default_color(idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                    else:
                        self.play_queue[idx] = False
                        pixels.set_blink(idx, False)
                        pixels.set_color(idx, constants.CHORD_COLOR)
                        pixels.set_default_color(idx, constants.CHORD_COLOR)
                else:
                    self.play_queue[idx] = True
                    if is_clock_playing:
                        self.chord_loops[idx].toggle_playstate(True)
                        pixels.set_blink(idx, False)
                        pixels.set_color(idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                        pixels.set_default_color(idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                    else:
                        pixels.set_blink(idx, True, constants.PIXEL_LOOP_PLAYING_COLOR)
            else:
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
        for idx in range(constants.NUM_PADS):
            chord_obj = self.chord_loops[idx]
            if chord_obj:
                self._stop_single_chord(idx, chord_obj)

    def _stop_single_chord(self, idx, chord_obj):
        """
        Stops a chord at the given index, clearing states/pixels, etc.
        """
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
        
        if self.chord_loops[idx].loop_type == "chordloop":
            previous_state = self.chord_loops[idx].loop_is_playing
            self.chord_loops[idx].toggle_playstate(on_or_off)
            # Now On
            if previous_state and not self.chord_loops[idx].loop_is_playing:
                self.chord_loops[idx].clear_notes_and_pixels()
                pixels.set_default_color(idx, constants.CHORD_COLOR)
            # Now Off
            elif not previous_state and self.chord_loops[idx].loop_is_playing:
                self.chord_loops[idx].clear_notes_and_pixels()
                pixels.set_default_color(idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                pixels.set_color(idx, constants.PIXEL_LOOP_PLAYING_COLOR)
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


    def save_chords_txt(self, filepath):
        """
        Stream out each pad's chord data as CSV (notes on/off and CC) into a text file.

        Args:
            filepath (str): Full path to write the chord CSV.
        """
        # Import the CSV helper
        from looper import write_pad_events_csv
        with open(filepath, "w", encoding="utf-8") as f:
            for pad_idx, loop in enumerate(self.chord_loops):
                # Only write for pads that have a loop
                if loop == "" or not loop.has_loop:
                    continue
                write_pad_events_csv(loop, pad_idx, f)

    def initialize(self):
        """
        Initializes the chord manager by loading chords from the specified file.
        """
        if settings.chord_file_to_load:
            self.load_chords_txt(settings.chord_file_to_load)
            print(f"[DEBUG] Loaded chord file: {settings.chord_file_to_load}")
        else:
            print("[DEBUG] No chord file to load. Skipping initialization.")
        
        # Reset the recording state
        self.recording_pad = None
        self.is_recording = False

    def update_pad_pixels(self):
        """
        Updates the pixel colors for each pad based on the current state of the chord loops.

        Use when loading chords or changing playmode
        """
        for pad_idx, loop in enumerate(self.chord_loops):
            if loop == "":
                pixels.set_default_color(pad_idx)
                pixels.set_color(pad_idx, constants.BLACK)
                return
            pixels.set_default_color(pad_idx, constants.CHORD_COLOR)

            # playing
            if loop.loop_is_playing:
                pixels.set_color(pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
                pixels.set_default_color(pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)

            # not playing
            elif self.play_queue[pad_idx]:
                pixels.set_blink(pad_idx, True, constants.PIXEL_LOOP_PLAYING_COLOR)
            else:
                pixels.set_default_color(pad_idx, constants.CHORD_COLOR)
                pixels.set_color(pad_idx, constants.CHORD_COLOR)

    def finalize_chord_load(self, pad_idx):

        if pad_idx is None or self.chord_loops[pad_idx] == "":
            print("[DEBUG] No chord loop to finalize.")
            return
        
        self.chord_loops[pad_idx]._update_oneshot_ccs()
        self.chord_loops[pad_idx]._update_oneshot_notes()
        self.chord_loops[pad_idx].trim_loaded_ccs()        # Prevents long loop eventhough loaded CCs are all oneshot
        display.show_notification(f"Chord {pad_idx} loaded..", force_display=True)
        return


    def load_chords_txt(self, filename):
        """
        Assumes path is set to /chords/ and filename is the name of the file to load.
        Load chord data from a CSV-style file with headers:
          ##PADn##       - start pad n
          #METADATA#    - loop_type,ticks,time,bpm
          #NOTES_ON#    - note,vel,pad_idx,tick lines
          #NOTES_OFF#   - note,vel,pad_idx,tick lines
          #CC#          - cc_num,vel,tick lines
        """
        import time
        filepath = f"/chords/{filename}"

        current_phase = None
        loop = None
        pad_idx = None
        last_blink_update = time.monotonic()
        blink_update_interval = 0.2  # Update blinks every 0.2 seconds
        line_counter = 0
        memory_cleanup_interval = 100  # Call free_memory every 100 lines
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                pixels.indicate_preset_loading(True)  # Show loading indicator on pixels
                for raw in f:
                    line = raw.strip()
                    line_counter += 1
                    current_time = time.monotonic()
                    
                    # Only update blinks every 0.2 seconds
                    if current_time - last_blink_update >= blink_update_interval:
                        pixels.process_blinks(force_update=True)  # Update pixel blinks
                        last_blink_update = current_time
                    
                    if line.startswith("##PAD") and line.endswith("##"):
                        self.finalize_chord_load(pad_idx)
                        pad_idx = int(line[5:-2])
                        pixels.set_default_color(pad_idx, constants.CHORD_COLOR)
                        loop = make_midi_loop(loop_type="loop", pad_idx=pad_idx)
                        self.chord_loops[pad_idx] = loop
                        current_phase = None
                        continue
                    if line == "#METADATA#":
                        current_phase = "metadata"
                        continue
                    elif line == "#NOTES_ON#":
                        current_phase = "notes_on"
                        continue
                    elif line == "#NOTES_OFF#":
                        current_phase = "notes_off"
                        continue
                    elif line == "#CC#":
                        current_phase = "cc"
                        continue
                    if not line or not loop:
                        continue
                    # parse according to current phase
                    if current_phase == "metadata":
                        key,val = line.split(",",1)
                        print(f"[DEBUG] Metadata: {key} = {val}")
                        if key == "loop_type":        loop.loop_type = val
                        elif key == "ticks":         loop.total_midi_ticks = int(val)
                        elif key == "time":          loop.total_time_seconds = float(val)
                        elif key == "bpm":           loop.recording_bpm = float(val)
                        loop.has_loop = True
                    elif current_phase == "notes_on":
                        n, v, pad_i, t = map(int, line.split(",",3))
                        loop.notes_on.add_event(n, v, pad_i, t, pad_idx)
                    elif current_phase == "notes_off":
                        n, v, pad_i, t = map(int, line.split(",",3))
                        loop.notes_off.add_event(n, v, pad_i, t, pad_idx)
                    elif current_phase == "cc":
                        c,v,t = map(int, line.split(",",2))
                        loop.cc_events.add_event(c, v, t, pad_idx)
                    
                    # Only call free_memory every 100 lines
                    if line_counter % memory_cleanup_interval == 0:
                        free_memory()
                
                self.finalize_chord_load(pad_idx)
                pixels.indicate_preset_loading(False)
        except OSError as e:
            print(f"Error loading chord CSV: {e}")

chord_manager = ChordManager()
