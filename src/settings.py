import json
import constants as C
import os
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
        self.clock_source = "AUTO"
        self.notes_all_at_once = False
        self.midi_settings_page_indices = [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0]
        self.settings_menu_option_indices = [0,0,0,0,0,0,0,0,0,0,0,0]
        self.midi_channel_pad_mapping = [None] * 16
        self.midi_channel_mode = "per_note"

        # Looper / Chord / Arp
        self.chordmode_looptype = "loop"
        self.arpeggiator_type = "up"
        self.arpeggiator_length = "1/8"
        self.arp_is_polyphonic = True
        self.chord_file_to_load = False

        # Quantizer
        self.quantize_time = "none"
        self.quantize_strength = 100
        self.quantize_loop = "none"
        self.trim_silence_mode = "start"
        self.cc_resolution = 1
        self.quantize_cc = False

        # Menus
        self.startup_menu_idx = 0

        # Display
        self.led_brightness = 0.3

        # State tracking
        self.velocity_mapped = False

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
            
            # Load chord data for this preset if available
            chord_file = settings_from_preset_file.get("chordref")
            if chord_file:
                self.chord_file_to_load = chord_file

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
            preset_settings[key] = getattr(self, key)

        from chordmanager import chord_manager
        old_ref = preset_settings.get("chordref")
        chord_filename = self.save_chords_to_file(chord_manager, existing_file=old_ref)
        preset_settings["chordref"] = chord_filename

        all_settings[preset_name] = preset_settings
        all_settings["STARTUP_PRESET"] = preset_name

        with open(C.PRESETS_FILEPATH, 'w', encoding='utf-8') as json_file:
            json.dump(all_settings, json_file)

    def load_startup_preset(self):
        self.load_preset(self.get_startup_preset())
    
    def set_play_mode(self, mode):
        self.play_mode = mode

    def get_play_mode(self):
        return self.play_mode

    def save_chords_to_file(self, chord_manager, base_path='/', folder_name='chords', existing_file=None):
        """Save chord data to file. Returns filename or None on error."""
        chords_dir = f"{base_path}{folder_name}"
        try:
            try:
                os.mkdir(chords_dir)
            except OSError:
                pass

            # Determine filename: overwrite existing_file or choose next index
            if existing_file:
                chord_filename = existing_file
                old_path = f"{chords_dir}/{existing_file}"
                try:
                    os.remove(old_path)
                except OSError:
                    pass
            else:
                existing_files = [f for f in os.listdir(chords_dir) if f.startswith("chord_") and f.endswith(".csv")]
                used_indices = set()
                for fname in existing_files:
                    try:
                        idx = int(fname.split("_")[1].split(".csv")[0])
                        used_indices.add(idx)
                    except ValueError:
                        pass
                new_idx = 1
                while new_idx in used_indices:
                    new_idx += 1
                chord_filename = f"chord_{new_idx}.csv"
            chord_path = f"{chords_dir}/{chord_filename}"

            # Stream out chord CSV via ChordManager helper
            chord_manager.save_chords_txt(chord_path)
            return chord_filename

        except Exception as e:
            if self.debug:
                print(f"[ERROR] save_chords_to_file exception: {e} (type: {type(e).__name__})")
            return None

settings = Settings()
settings.load_startup_preset()
gc.collect()  # Run garbage collection to free up memory after loading settings
