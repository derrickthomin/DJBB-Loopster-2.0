import constants as C
from looper import make_midi_loop
from display import display
from pixels import pixels
from settings import settings
from clock import clock
from debug import free_memory

class ChordManager:
    """
    Manages chord recording, playback and assignment to pads
    """
    def __init__(self):
        self.chord_loops = [""] * C.NUM_PADS    # Stores chord loop objects for pads
        self.play_queue = [False] * C.NUM_PADS  # Play these when MIDI start received
        self.any_chord_playing = False
        self.recording_pad = None
        self.is_recording = False
        self.total_events_count = 0                     # Track total events across all pads
    
    def add_remove_chord(self, pad_idx):
        """ 
        Adds or removes a chord at the specified pad index.
        """
        
        # Add
        if self.chord_loops[pad_idx] == "" and self.recording_pad is None:
            self._create_new_chord(pad_idx)

        # Switch recording pad
        elif self.chord_loops[pad_idx] == "" and self.recording_pad is not None and self.recording_pad != pad_idx:
            current_chord = self.chord_loops[self.recording_pad]
            if not current_chord.has_events():
                self._remove_chord(self.recording_pad)
            else:
                self.total_events_count += current_chord.count_events()
                current_chord.toggle_record_state(False)
                pixels.set_blink(self.recording_pad, False)
            self._create_new_chord(pad_idx)

        # Remove
        elif self.recording_pad == pad_idx or (not self.is_recording):
            self._remove_chord(pad_idx)

    def _create_new_chord(self, pad_idx):
        """
        Creates a new chord recording on the specified pad
        """
        if self.total_events_count >= C.TOTAL_LOOP_EVENTS_LIMIT:
            display.show_notification("Max Events Reached")
            return

        free_memory()
        self.chord_loops[pad_idx] = make_midi_loop(
            loop_type=settings.chordmode_looptype,
            pad_idx=pad_idx
        )
        self.chord_loops[pad_idx].toggle_record_state()
        self.recording_pad = pad_idx
        self.is_recording = True
        pixels.set_blink(pad_idx, True, C.RED)
        pixels.set_default_color(pad_idx, C.CHORD_COLOR)

    def _remove_chord(self, pad_idx):
        """
        Removes a chord from the specified pad and clears related states
        """
        if self.chord_loops[pad_idx] != "":
            removed_events = self.chord_loops[pad_idx].count_events()
            self.total_events_count -= removed_events
        
        self.chord_loops[pad_idx].clear()
        self.chord_loops[pad_idx] = ""
        self.recording_pad = None
        self.play_queue[pad_idx] = False
        self.is_recording = False
        pixels.set_default_color(pad_idx)
        pixels.set_blink(pad_idx, False)

    def check_event_limits(self):
        """
        Checks if chord recording events exceed limit and stops recording if needed.
        """
        if self.recording_pad is None:
            return
        chord = self.chord_loops[self.recording_pad]
        
        if chord.max_events_reached:
            self.handle_fn_press()

    def handle_fn_press(self, action_type="press"):
        """
        Handles function button press to stop chord recording.
        
        Args:
            action_type (str): Type of button action ("press" or "release")
        """
        if action_type == "press" and self.is_recording:
            pad_idx = self.recording_pad  # Store for later use
            current_chord = self.chord_loops[pad_idx]
            current_chord.toggle_record_state(False)
            pixels.set_blink(pad_idx, False)
            
            # Remove empty chord
            if not current_chord.has_events():
                self._remove_chord(pad_idx)
                return
            
            # If we get here, the loop has useful content - proceed with normal finish
            self.total_events_count += current_chord.count_events()
            
            if settings.midi_sync:
                self.play_queue[pad_idx] = True
                if clock.is_playing:
                    self.chord_loops[pad_idx].toggle_playstate(True)
                    pixels.set_color(pad_idx, C.PIXEL_LOOP_PLAYING_COLOR)
                    pixels.set_default_color(pad_idx, C.PIXEL_LOOP_PLAYING_COLOR)
                else:
                    pixels.set_blink(pad_idx, True, C.PIXEL_LOOP_PLAYING_COLOR)
            else:
                if not self.chord_loops[pad_idx].loop_is_playing:
                    self.chord_loops[pad_idx].toggle_playstate(True)
                
                pixels.set_color(pad_idx, C.PIXEL_LOOP_PLAYING_COLOR)
                pixels.set_default_color(pad_idx, C.PIXEL_LOOP_PLAYING_COLOR)

            self.recording_pad = None
            self.is_recording = False

    def change_loop_mode(self, button_idx):
        """
        Toggles between oneshot mode and loop mode for the chord at the given index.

        Args:
            button_idx (int): The index of the pad to change the chord type of.
        """
        if self.chord_loops[button_idx] != "":
            loop_type = self.chord_loops[button_idx].change_loop_mode()
            self.chord_loops[button_idx].clear_notes_and_pixels()
            self.chord_loops[button_idx].toggle_playstate(False)
            self.play_queue[button_idx] = False
            pixels.set_blink(button_idx, False)
            self.display_chord_loop_mode(button_idx)
            if loop_type != settings.chordmode_looptype:
                settings.chordmode_looptype = loop_type

    def display_chord_loop_mode(self, idx):
        """
        Displays the loop type of the chord at the given index.
        """
        if self.chord_loops[idx] != "":
            display.show_notification(f"Chord Type: {self.chord_loops[idx].loop_type}")

    def toggle_chord_playstate(self, idx):
        """
        Processes a new button press event for the given index.
        """
        if self.is_recording or not self.chord_loops[idx]:  # This press is for a note if recording
            return

        if settings.midi_sync:
            if self.chord_loops[idx].loop_type == "oneshot":
                is_clock_playing = clock.is_playing
            
                if self.play_queue[idx]:
                    if is_clock_playing:
                        self.chord_loops[idx].toggle_playstate(False)
                        self.chord_loops[idx].toggle_playstate(True)
                        pixels.set_blink(idx, False)
                        pixels.set_color(idx, C.PIXEL_LOOP_PLAYING_COLOR)
                        pixels.set_default_color(idx, C.PIXEL_LOOP_PLAYING_COLOR)
                    else:
                        self.play_queue[idx] = False
                        pixels.set_blink(idx, False)
                        pixels.set_color(idx, C.CHORD_COLOR)
                        pixels.set_default_color(idx, C.CHORD_COLOR)
                else:
                    self.play_queue[idx] = True
                    if is_clock_playing:
                        self.chord_loops[idx].toggle_playstate(True)
                        pixels.set_blink(idx, False)
                        pixels.set_color(idx, C.PIXEL_LOOP_PLAYING_COLOR)
                        pixels.set_default_color(idx, C.PIXEL_LOOP_PLAYING_COLOR)
                    else:
                        pixels.set_blink(idx, True, C.PIXEL_LOOP_PLAYING_COLOR)
            else:
                self.play_queue[idx] = not self.play_queue[idx]
                pixels.set_blink(idx, self.play_queue[idx], C.PIXEL_LOOP_PLAYING_COLOR)

            if clock.is_playing:
                self._play_chord(idx)
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
        for idx in range(C.NUM_PADS):
            chord_obj = self.chord_loops[idx]
            if chord_obj:
                self._stop_single_chord(idx, chord_obj)

    def _stop_single_chord(self, idx, chord_obj):
        """
        Stops a chord at the given index, clearing states/pixels, etc.
        """
        if self.play_queue[idx] and chord_obj.loop_is_playing:
            pixels.set_blink(idx, True, C.PIXEL_LOOP_PLAYING_COLOR)
        else:
            self.play_queue[idx] = False
        
        chord_obj.toggle_playstate(False)
        chord_obj.clear_notes_and_pixels()
        pixels.set_default_color(idx, C.CHORD_COLOR)

    def _play_chord(self, idx, on_or_off=None):
        """
        Plays or stops the chord at the given index.

        Args:
            idx (int): The index of the pad to play the chord from.
            on_or_off (bool, optional): Force playstate on or off. If None, toggle the current state.
        """
        if self.chord_loops[idx] == "":
            return
        
        if self.chord_loops[idx].loop_type == "loop":
            previous_state = self.chord_loops[idx].loop_is_playing
            self.chord_loops[idx].toggle_playstate(on_or_off)

            # Now Off
            if previous_state and not self.chord_loops[idx].loop_is_playing:
                self.chord_loops[idx].clear_notes_and_pixels()
                pixels.set_default_color(idx, C.CHORD_COLOR)

            # Now On
            elif not previous_state and self.chord_loops[idx].loop_is_playing:
                self.chord_loops[idx].clear_notes_and_pixels()
                pixels.set_default_color(idx, C.PIXEL_LOOP_PLAYING_COLOR)
                pixels.set_color(idx, C.PIXEL_LOOP_PLAYING_COLOR)
        else:
            self.chord_loops[idx].toggle_playstate(True)

        pixels.set_blink(idx, False)

    def unique_notes(self, padidx):
        """
        Retrieves the unique Notes of the chord at the given pad index.
        """
        if self.chord_loops[padidx] != "":
            return self.chord_loops[padidx].get_unique_notes()
        return []
    
    def unique_ccs(self, padidx):
        """
        Returns the unique CCs of the chord at the given pad index.
        """
        if self.chord_loops[padidx] != "":
            return self.chord_loops[padidx].get_unique_ccs()
        return []


    def save_chords_txt(self, filepath):
        """
        Stream out each pad's chord data as CSV (notes on/off and CC) into a text file for the given path.
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
        # Reset the counter before loading
        self.total_events_count = 0
        
        if settings.chord_file_to_load:
            self.load_chords_txt(settings.chord_file_to_load)
            print(f"[DEBUG] Loaded chord file: {settings.chord_file_to_load}")
        else:
            print("[DEBUG] No chord file to load. Skipping initialization.")
        
        print(f"[DEBUG] Total events loaded: {self.total_events_count}")
        
        # Reset the recording state
        self.recording_pad = None
        self.is_recording = False

    def update_pad_pixels(self):
        """
        Updates the pixel colors for each pad based on the current state of the chord loops.
        """
        for pad_idx, loop in enumerate(self.chord_loops):
            if loop == "":
                pixels.set_default_color(pad_idx)
                pixels.set_color(pad_idx, C.BLACK)
                return
            pixels.set_default_color(pad_idx, C.CHORD_COLOR)

            # Playing
            if loop.loop_is_playing:
                pixels.set_color(pad_idx, C.PIXEL_LOOP_PLAYING_COLOR)
                pixels.set_default_color(pad_idx, C.PIXEL_LOOP_PLAYING_COLOR)

            # Not playing
            elif self.play_queue[pad_idx]:
                pixels.set_blink(pad_idx, True, C.PIXEL_LOOP_PLAYING_COLOR)
            else:
                pixels.set_default_color(pad_idx, C.CHORD_COLOR)
                pixels.set_color(pad_idx, C.CHORD_COLOR)

    def finalize_chord_load(self, pad_idx):

        if pad_idx is None or self.chord_loops[pad_idx] == "":
            return
        
        # Update total events counter for the loaded chord
        loaded_events = self.chord_loops[pad_idx].count_events()
        self.total_events_count += loaded_events
        
        self.chord_loops[pad_idx].create_oneshot_ccs()
        self.chord_loops[pad_idx].update_oneshot_notes()
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
        current_time = time.monotonic()
        last_blink_update = current_time
        blink_update_interval = 0.2  # Update blinks every 0.2 seconds
        line_counter = 0
        memory_cleanup_interval = 100  # Call free_memory every 100 lines
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                pixels.indicate_preset_loading(True)  # Show loading indicator on pixels
                for raw in f:
                    line = raw.strip()
                    line_counter += 1
                    
                    # Only update blinks every 0.2 seconds
                    if current_time - last_blink_update >= blink_update_interval:
                        pixels.process_blinks(force_update=True)  # Update pixel blinks
                        last_blink_update = current_time
                    
                    if line.startswith("##PAD") and line.endswith("##"):
                        self.finalize_chord_load(pad_idx)
                        pad_idx = int(line[5:-2])
                        pixels.set_default_color(pad_idx, C.CHORD_COLOR)
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
                    # Parse according to current phase
                    if current_phase == "metadata":
                        key,value = line.split(",",1)
                        print(f"[DEBUG] Metadata: {key} = {value}")
                        if key == "loop_type":       loop.loop_type = value
                        elif key == "ticks":         loop.total_midi_ticks = int(value)
                        elif key == "time":          loop.total_time_seconds = float(value)
                        elif key == "bpm":           loop.recording_bpm = float(value)
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

    def handle_midi_sync_change(self):
        """
        Handles the change in MIDI sync mode.
        If MIDI sync is disabled, stops all chords and clears the play queue.
        Forces user to manually restart chords they want to continue playing.
        """

        # MIDI sync disabled - stop all playing chords and clear play queue
        for idx in range(C.NUM_PADS):
            chord_obj = self.chord_loops[idx]
            if chord_obj and chord_obj != "":
                # Stop the chord if it's playing
                if chord_obj.loop_is_playing:
                    chord_obj.toggle_playstate(False)
                    chord_obj.clear_notes_and_pixels()
                
                # Clear from play queue
                self.play_queue[idx] = False
                
                # Reset pixel colors to default chord color
                pixels.set_blink(idx, False)
                pixels.set_default_color(idx, C.CHORD_COLOR)
                pixels.set_color(idx, C.CHORD_COLOR)
        
        # Reset any global chord playing state
        self.any_chord_playing = False

chord_manager = ChordManager()
