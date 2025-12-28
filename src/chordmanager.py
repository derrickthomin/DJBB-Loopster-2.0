import constants as C
from looper import make_midi_loop
from display import display
from pixels import pixels
from settings import settings
from clock import clock
from debug import free_memory
from loop_storage import load_notes_from_flash, load_cc_header, load_at_header, get_notes_path, get_cc_path, get_at_path

class ChordManager:
    """Manages chord recording, playback, and pad assignment."""
    def __init__(self):
        self.chord_loops = [""] * C.NUM_PADS    # Stores chord loop objects for pads
        self.play_queue = [False] * C.NUM_PADS  # Play these when MIDI start received
        self.any_chord_playing = False
        self.recording_pad = None
        self.is_recording = False
        self.recording_is_armed = False                 # Armed to record when transport starts or note played
        self.total_events_count = 0                     # Track total events across all pads
        self.last_debug_event_count = 0                 # Track when to print debug info
    
    def add_remove_chord(self, pad_idx):
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
        if self.total_events_count >= C.TOTAL_LOOP_EVENTS_LIMIT:
            display.show_notification("Max Events Reached")
            return

        free_memory()
        
        self.chord_loops[pad_idx] = make_midi_loop(
            loop_type=settings.chordmode_looptype,
            pad_idx=pad_idx
        )
        self.recording_pad = pad_idx
        self.is_recording = True
        
        pixels.set_default_color(pad_idx, C.CHORD_COLOR)
        
        # Arm recording if midi sync enabled but clock not playing
        if settings.midi_sync and not clock.is_playing:
            self.recording_is_armed = True
            pixels.set_blink(pad_idx, True, C.RED)  # Blinking red = armed/waiting
        else:
            self.recording_is_armed = False
            self.chord_loops[pad_idx].toggle_record_state()
            # Solid red for active recording
            pixels.set_blink(pad_idx, False)
            pixels.set_default_color(pad_idx, C.RED)
            pixels.set_color(pad_idx, C.RED)

    def _remove_chord(self, pad_idx):
        if self.chord_loops[pad_idx] != "":
            removed_events = self.chord_loops[pad_idx].count_events()
            self.total_events_count -= removed_events
        
        self.chord_loops[pad_idx].clear()
        self.chord_loops[pad_idx] = ""
        self.recording_pad = None
        self.play_queue[pad_idx] = False
        self.is_recording = False
        self.recording_is_armed = False
        pixels.set_default_color(pad_idx)
        pixels.set_blink(pad_idx, False)

    def check_event_limits(self):
        if self.recording_pad is None:
            return
        chord = self.chord_loops[self.recording_pad]
        
        # Debug: Print memory info every 25 events
        current_events = chord.count_events()
        if current_events > 0 and current_events % 25 == 0 and current_events != self.last_debug_event_count:
            import gc
            mem_free = gc.mem_free()
            mem_alloc = gc.mem_alloc()
            total_events = self.total_events_count + current_events
            if settings.debug:
                print(f"[DEBUG] Events: {total_events} | Free: {mem_free} | Alloc: {mem_alloc}")
            self.last_debug_event_count = current_events
        
        if chord.max_events_reached:
            self.handle_fn_press()

    def handle_fn_press(self, action_type="press"):
        """Stop chord recording on FN button press."""
        if action_type == "press" and self.is_recording:
            pad_idx = self.recording_pad  # Store for later use
            current_chord = self.chord_loops[pad_idx]
            self.recording_is_armed = False  # Clear armed state
            current_chord.toggle_record_state(False)
            pixels.set_blink(pad_idx, False)
            
            # Remove empty chord
            if not current_chord.has_events():
                self._remove_chord(pad_idx)
                return
            
            # If we get here, the loop has useful content - proceed with normal finish
            self.total_events_count += current_chord.count_events()
            
            # Hold mode: start in stopped state
            if current_chord.loop_type == "hold":
                self.chord_loops[pad_idx].toggle_playstate(False)
                pixels.set_blink(pad_idx, False)
                pixels.set_color(pad_idx, C.CHORD_COLOR)
                pixels.set_default_color(pad_idx, C.CHORD_COLOR)
                self.recording_pad = None
                self.is_recording = False
                return
            
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
        """Toggle between oneshot and loop mode for the chord."""
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
        if self.chord_loops[idx] != "":
            display.show_notification(f"Chord Type: {self.chord_loops[idx].loop_type}")

    def toggle_chord_playstate(self, idx, force_play=False, force_stop=False):
        """Handle pad press to toggle chord play/stop.
        
        Args:
            idx: Pad index
            force_play: If True, force start playing (for hold mode press)
            force_stop: If True, force stop playing (for hold mode release)
        """
        if self.is_recording or not self.chord_loops[idx]:  # This press is for a note if recording
            return
        
        # Handle forced states for hold mode
        if force_play:
            self.chord_loops[idx].toggle_playstate(True)
            self.play_queue[idx] = True
            pixels.set_blink(idx, False)
            pixels.set_color(idx, C.PIXEL_LOOP_PLAYING_COLOR)
            pixels.set_default_color(idx, C.PIXEL_LOOP_PLAYING_COLOR)
            return
        
        if force_stop:
            self.chord_loops[idx].toggle_playstate(False)
            self.play_queue[idx] = False
            pixels.set_blink(idx, False)
            pixels.set_color(idx, C.CHORD_COLOR)
            pixels.set_default_color(idx, C.CHORD_COLOR)
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

    def start_armed_recording(self):
        """Start recording if it was armed waiting for transport."""
        if not self.recording_is_armed or self.recording_pad is None:
            return
        
        self.recording_is_armed = False
        self.chord_loops[self.recording_pad].toggle_record_state()
        # Solid red for active recording (stop blinking, set default so note flashes return to red)
        pixels.set_blink(self.recording_pad, False)
        pixels.set_default_color(self.recording_pad, C.RED)
        pixels.set_color(self.recording_pad, C.RED)
        
        # if send_transport:
        #     print("[DEBUG] Sending MIDI Start to DAW")
        #     midi.send_start_stop(True)

    def process_chord_on_queue(self):
        # Start armed recording when transport starts
        if self.recording_is_armed:
            self.start_armed_recording()
        
        if clock.is_playing and not self.any_chord_playing:
            self.any_chord_playing = True
            for idx, play in enumerate(self.play_queue):
                if play:
                    self._play_chord(idx)

    def stop_all_chords(self):
        """Stop all playing chords. Called on MIDI stop."""
        if not self.any_chord_playing or clock.is_playing:
            return

        self.any_chord_playing = False
        for idx in range(C.NUM_PADS):
            chord_obj = self.chord_loops[idx]
            if chord_obj:
                self._stop_single_chord(idx, chord_obj)

    def _stop_single_chord(self, idx, chord_obj):
        if self.play_queue[idx] and chord_obj.loop_is_playing:
            pixels.set_blink(idx, True, C.PIXEL_LOOP_PLAYING_COLOR)
        else:
            self.play_queue[idx] = False
        
        chord_obj.toggle_playstate(False)
        chord_obj.clear_notes_and_pixels()
        pixels.set_default_color(idx, C.CHORD_COLOR)

    def _play_chord(self, idx, on_or_off=None):
        """Play or stop chord. If on_or_off is None, toggle."""
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
        if self.chord_loops[padidx] != "":
            return self.chord_loops[padidx].get_unique_notes()
        return []
    
    def unique_ccs(self, padidx):
        if self.chord_loops[padidx] != "":
            return self.chord_loops[padidx].get_unique_ccs()
        return []

    def initialize(self):
        # Reset the counter before loading
        self.total_events_count = 0
        
        # Phase 9: Load loops from binary files
        if settings.loops_to_load:
            self.load_loops_binary(settings.loops_to_load)
            if settings.debug:
                print(f"[DEBUG] Loaded {len(settings.loops_to_load)} loops from binary files")
        elif settings.debug:
            print("[DEBUG] No loops to load.")
        
        if settings.debug:
            print(f"[DEBUG] Total events loaded: {self.total_events_count}")
        
        # Reset the recording state
        self.recording_pad = None
        self.is_recording = False

    def load_loops_binary(self, loops_metadata):
        """Load loops from binary files using JSON metadata."""
        import time
        
        current_time = time.monotonic()
        last_blink_update = current_time
        
        pixels.indicate_preset_loading(True)
        
        for pad_idx_str, meta in loops_metadata.items():
            pad_idx = int(pad_idx_str)
            
            # Update loading indicator
            if time.monotonic() - last_blink_update >= 0.2:
                pixels.process_blinks(force_update=True)
                last_blink_update = time.monotonic()
            
            # Create loop with metadata from JSON
            loop = make_midi_loop(loop_type=meta.get("loop_type", "loop"), pad_idx=pad_idx)
            loop.total_midi_ticks = meta.get("total_midi_ticks", 0)
            loop.total_time_seconds = meta.get("total_time_seconds", 0.0)
            loop.recording_bpm = meta.get("recording_bpm", 120.0)
            loop.loop_id = meta.get("loop_id")  # Sequential loop ID for file lookup
            
            # Skip if no loop_id (stale/invalid metadata)
            if loop.loop_id is None:
                if settings.debug:
                    print(f"[LOAD] Pad {pad_idx}: Skipped (no loop_id in metadata)")
                continue
            
            # Track if we found any actual data
            has_notes = False
            has_ccs = False
            
            # Load notes from binary file (into RAM for playback)
            notes_path = get_notes_path(loop.loop_id)
            try:
                on_count, off_count = load_notes_from_flash(notes_path, loop.notes_on, loop.notes_off)
                if on_count > 0 or off_count > 0:
                    loop.notes_file_path = notes_path
                    has_notes = True
                    if settings.debug:
                        print(f"[LOAD] Pad {pad_idx}: {on_count} notes_on, {off_count} notes_off (loop_id={loop.loop_id})")
            except Exception as e:
                pass  # File doesn't exist - that's OK
            
            # Set up CC file path (cache created lazily on first play)
            cc_path = get_cc_path(loop.loop_id)
            try:
                header = load_cc_header(cc_path)
                if header and header.get('event_count', 0) > 0:
                    loop.cc_file_path = cc_path
                    has_ccs = True
                    if settings.debug:
                        print(f"[LOAD] Pad {pad_idx}: {header['event_count']} CCs from flash (loop_id={loop.loop_id})")
            except Exception as e:
                pass  # File doesn't exist - that's OK
            
            # Set up aftertouch file path (cache created lazily on first play)
            at_path = get_at_path(loop.loop_id)
            try:
                header = load_at_header(at_path)
                if header and header.get('event_count', 0) > 0:
                    loop.at_file_path = at_path
                    has_ccs = True  # Count AT as controller data (same as CC for has_events check)
                    if settings.debug:
                        print(f"[LOAD] Pad {pad_idx}: {header['event_count']} ATs from flash (loop_id={loop.loop_id})")
            except Exception as e:
                pass  # File doesn't exist - that's OK
            
            # Skip this pad if no files exist (stale JSON metadata)
            if not has_notes and not has_ccs:
                if settings.debug:
                    print(f"[LOAD] Pad {pad_idx}: Skipped (no binary files found for loop_id={loop.loop_id})")
                continue
            
            # We have data - finalize the loop
            loop.has_loop = True
            self.chord_loops[pad_idx] = loop
            pixels.set_default_color(pad_idx, C.CHORD_COLOR)
            self.finalize_chord_load(pad_idx)
            
            free_memory()
        
        pixels.indicate_preset_loading(False)

    def update_pad_pixels(self):
        for pad_idx, loop in enumerate(self.chord_loops):
            if loop == "":
                pixels.set_default_color(pad_idx)
                pixels.set_color(pad_idx, C.BLACK)
                continue
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

    def handle_midi_sync_change(self):
        """Stop all chords and clear play queue when MIDI sync mode changes."""
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
