import json
import constants as C
import gc

class Settings:
    """Device settings manager."""

    def __init__(self):
        self.debug = False
        self.performance_mode = False
        self.midibank_idx = 3
        self.midi_channel_out = 0
        self.midi_channel_in = -1  # -1 = ALL channels
        self.midi_channel_current = self.midi_channel_out
        self.default_velocity = 120
        self.default_bpm = 120
        self.midi_notes_default = [36 + i for i in range(16)]
        self.midi_type = "USB"
        self.midi_usb_io = "both"
        self.midi_aux_io = "both"
        self.scale_idx = 0
        self.rootnote_idx = 0
        self.scalenotes_idx = 2
        self.play_mode = 'chord'
        self.midi_sync = False
        self.midi_passthru = True
        self.record_cc = True
        self.clock_source = "USB"
        self.notes_all_at_once = False
        self.midi_settings_page_indices = [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0]
        self.settings_menu_option_indices = [0,0,0,0,0,0,0,0,0,0,0,0,0]
        self.midi_channel_pad_mapping = [None] * 16
        self.midi_channel_mode = "per_note"

        # Looper / Chord / Arp
        self.chordmode_looptype = "loop"
        self.arpeggiator_type = "up"
        self.arpeggiator_length = "1/8"
        self.arp_is_polyphonic = True
        self.loops_to_load = {}  # Binary loops metadata from preset (pad_idx -> loop info with loop_id)
        self.next_loop_id = 1    # Next available loop ID (persisted in presets.json root)

        # Quantizer
        self.quantize_time = "none"
        self.quantize_strength = 100
        self.quantize_loop = "none"
        self.trim_silence_mode = "start"
        self.cc_resolution = 1
        self.quantize_cc = False
        self.cc_stream_to_flash = False  # False = RAM mode (deferred save), True = flash streaming

        # Menus
        self.startup_menu_idx = 0

        # Display
        self.led_brightness = 0.3

        # State tracking
        self.velocity_mapped = False

    def get_next_loop_id(self):
        """Get and increment the next available loop ID."""
        loop_id = self.next_loop_id
        self.next_loop_id += 1
        return loop_id

    def _get_all_loop_ids(self):
        """Get set of all loop IDs referenced by any preset."""
        try:
            with open(C.PRESETS_FILEPATH, 'r', encoding='utf-8') as f:
                all_settings = json.load(f)
            loop_ids = set()
            for preset_name, preset_data in all_settings.items():
                if preset_name in ("STARTUP_PRESET", "next_loop_id"):
                    continue
                if isinstance(preset_data, dict) and "loops" in preset_data:
                    for pad_str, loop_meta in preset_data["loops"].items():
                        if isinstance(loop_meta, dict) and "loop_id" in loop_meta:
                            loop_ids.add(loop_meta["loop_id"])
            return loop_ids
        except Exception:
            return set()

    def cleanup_orphan_loops(self):
        """Delete loop files whose loop_id is not referenced by any preset."""
        from loop_storage import cleanup_orphan_loops
        valid_ids = self._get_all_loop_ids()
        # Always run cleanup even if no valid IDs (deletes ALL orphans)
        deleted = cleanup_orphan_loops(valid_ids)
        if deleted > 0 and self.debug:
            print(f"[CLEANUP] Deleted {deleted} orphan loop files")

    def get_startup_preset(self):
        try:
            with open(C.PRESETS_FILEPATH, 'r', encoding='utf-8') as json_file:
                settings_from_preset_file = json.load(json_file)
                return settings_from_preset_file["STARTUP_PRESET"]
        except Exception as e:
            if self.debug:
                print(f"Error loading startup preset: {e}")
            return "DEFAULT"

    def get_preset_names_list(self):
        try:
            with open(C.PRESETS_FILEPATH, 'r', encoding='utf-8') as json_file:
                settings_from_preset_file = json.load(json_file)
                names_list = [key for key in settings_from_preset_file.keys() if key != 'STARTUP_PRESET']
                names_list.sort()
                names_list.append('*NEW*')
                return names_list
        except Exception as e:
            if self.debug:
                print(f"[ERROR] loading preset: {e}")
            return []

    def load_preset(self, preset_name):
        all_settings_from_file = {}  # Initialize to prevent UnboundLocalError

        try:
            with open(C.PRESETS_FILEPATH, 'r', encoding='utf-8') as json_file:
                all_settings_from_file = json.load(json_file)
                settings_from_preset_file = all_settings_from_file[preset_name]

            # Replace defaults with stuff from the .json file, if it exists.
            if len(settings_from_preset_file) > 0:
                for key in self.__dict__:
                    if key in settings_from_preset_file:
                        setattr(self, key, settings_from_preset_file[key])
            
            # Load loops metadata for binary loading (includes loop_id for each pad)
            self.loops_to_load = settings_from_preset_file.get("loops", {})
            
            # Load next_loop_id from root level (shared across all presets)
            self.next_loop_id = all_settings_from_file.get("next_loop_id", 1)

        except Exception as e:
            if self.debug:
                print("[ERROR] loading preset:", e)
            return

        # Save the preset as the default preset when loaded
        try:
            with open(C.PRESETS_FILEPATH, 'w', encoding='utf-8') as json_file:
                all_settings_from_file["STARTUP_PRESET"] = preset_name
                json.dump(all_settings_from_file, json_file)
        except OSError:
            if self.debug:
                print("[ERROR] saving default preset")

    def save_preset_to_file(self, preset_name):
        # Load existing presets; handle missing or invalid JSON
        try:
            with open(C.PRESETS_FILEPATH, 'r', encoding='utf-8') as json_file:
                all_settings = json.load(json_file)
        except ValueError as e:
            all_settings = {}

        if preset_name == '*NEW*':
            preset_name = f"PRESET_{len(all_settings) - 1}"
            preset_settings = {}
        else:
            preset_settings = all_settings.get(preset_name, {})

        for key in self.__dict__:
            if key == "loops_to_load":
                continue  # Runtime variable, not saved (we save "loops" explicitly)
            if key == "next_loop_id":
                continue  # Saved at root level, not per-preset
            preset_settings[key] = getattr(self, key)

        # Build loops metadata from chord_manager (includes loop_id for each pad)
        from chordmanager import chord_manager
        loops_metadata = {}
        for pad_idx in range(16):
            loop = chord_manager.chord_loops[pad_idx]
            if loop == "" or not loop.has_loop:
                continue
            loops_metadata[str(pad_idx)] = {
                "loop_id": loop.loop_id,  # Sequential ID for file lookup
                "loop_type": loop.loop_type,
                "total_midi_ticks": loop.total_midi_ticks,
                "total_time_seconds": loop.total_time_seconds,
                "recording_bpm": loop.recording_bpm
            }
        
        preset_settings["loops"] = loops_metadata
        
        # Save notes to flash for all loops that have notes but no notes file yet
        # (Deferred save - notes only written to flash at preset save time)
        from loop_storage import save_notes_to_flash, save_cc_to_flash, LOOPS_DIR
        from display import display
        display.show_notification("Saving loops...", force_display=True)
        for pad_idx in range(16):
            loop = chord_manager.chord_loops[pad_idx]
            if loop == "" or not loop.has_loop:
                continue
            # Only save if loop has notes but no file yet (recorded this session)
            if (len(loop.notes_on) > 0 or len(loop.notes_off) > 0) and loop.notes_file_path is None:
                notes_filename = save_notes_to_flash(
                    loop.notes_on,
                    loop.notes_off,
                    loop.loop_id,
                    loop.total_midi_ticks,
                    loop.recording_bpm
                )
                if notes_filename:
                    loop.notes_file_path = f"{LOOPS_DIR}/{notes_filename}"
            
            # CCs: Save if in RAM and no flash file yet (deferred save for RAM mode)
            if len(loop.cc_events) > 0 and loop.cc_file_path is None:
                cc_filename = save_cc_to_flash(
                    loop.cc_events,
                    loop.loop_id,
                    loop.total_midi_ticks,
                    loop.recording_bpm
                )
                if cc_filename:
                    loop.cc_file_path = f"{LOOPS_DIR}/{cc_filename}"
                    # print(f"[PRESET] Deferred save: {len(loop.cc_events)} CCs to {cc_filename}")
        
        # Log what we're saving
        if self.debug:
            print(f"[PRESET] Saving {len(loops_metadata)} loops to preset '{preset_name}'")
            for pad_str, meta in loops_metadata.items():
                print(f"  Pad {pad_str}: loop_id={meta['loop_id']}, {meta['loop_type']}")

        all_settings[preset_name] = preset_settings
        all_settings["STARTUP_PRESET"] = preset_name
        all_settings["next_loop_id"] = self.next_loop_id  # Persist at root level

        with open(C.PRESETS_FILEPATH, 'w', encoding='utf-8') as json_file:
            json.dump(all_settings, json_file)

    def load_startup_preset(self):
        self.cleanup_orphan_loops()  # Delete files from removed presets
        self.load_preset(self.get_startup_preset())
    
    def set_play_mode(self, mode):
        self.play_mode = mode

    def get_play_mode(self):
        return self.play_mode

settings = Settings()
settings.load_startup_preset()
gc.collect()  # Run garbage collection to free up memory after loading settings
