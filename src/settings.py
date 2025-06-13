import json
import constants
import os
import gc

class Settings:
    # A class that manages device settings that can be changed, loaded, and saved

    def __init__(self):
        self.debug = False                         # Flag indicating whether debug mode is enabled
        self.performance_mode = False              # Flag indicating whether performance mode is enabled
        self.midibank_idx = 3                      # The default MIDI bank index
        self.midi_channel_out = 0                  # Output MIDI channel (0-15)
        self.midi_channel_in = 0                   # Input MIDI channel (0-15)
        self.midi_channel_current = self.midi_channel_out  # Current channel for MIDI messages (not saved)
        self.default_velocity = 120                # Default MIDI note velocity
        self.default_bpm = 120                     # Default tempo in beats per minute
        self.midi_notes_default = [36 + i for i in range(16)]  # Default MIDI note values
        self.midi_type = "USB"                     # Type of MIDI connection (USB/DIN)
        self.midi_usb_io = "both"                  # USB MIDI direction: "both", "in", "out"
        self.midi_aux_io = "both"                  # AUX MIDI direction: "both", "in", "out"
        self.scale_idx = 0                         # Default scale index
        self.rootnote_idx = 0                      # Default root note index
        self.scalenotes_idx = 2                    # Default scale notes index
        self.scale_idx = 0                         # Default scale bank index
        self.play_mode = 'chord'                   # Default play mode
        self.midi_sync = False                     # MIDI clock sync status
        self.midi_passthru = True                  # Whether to pass MIDI messages through
        self.record_cc = True                      # Whether to record CC messages
        self.clock_source = "AUTO"                 # MIDI clock source: AUTO, USB, AUX
        self.notes_all_at_once = False             # Play all notes at once in oneshot mode
        self.midi_settings_page_indices = [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1]  # MIDI settings page indices
        self.settings_menu_option_indices = [0,0,0,0,0,0,0,0,0,0,0,0,0]  # Settings menu option indices
        self.midi_channel_pad_mapping = [None] * 16  # MIDI channel mapping for each pad

        # LOOPER / CHORDMODE / Arp
        self.chordmode_looptype = "chordloop"      # Loop type: loop, chordloop, oneshot
        self.arpeggiator_type = "up"               # Arpeggiator pattern direction
        self.arpeggiator_length = "1/8"            # Arp note length: "1", "1/2", "1/4", "1/8", "1/16", "1/32", "1/64"
        self.encoder_steps_per_arpnote = 1         # Encoder steps per arp note (higher = more turns)
        self.arp_is_polyphonic = True              # Whether arpeggiator can play multiple notes at once
        self.chord_file_to_load = False            # Chord file to load for preset

        # QUANTIZER
        self.quantize_time = "none"                # Note quantization: "none", "1/4", "1/8", "1/16", "1/32"
        self.quantize_strength = 100               # Quantization strength (0-100)
        self.quantize_loop = "none"                # Loop quantization: "none", "1", "1/2", "1/4", "1/8"
        self.trim_silence_mode = "start"           # Silence trimming: "start", "end", "both", "none"
        self.cc_resolution = 1                     # CC resolution from [1, 2, 5, 8, 16, 32, 64]
        self.quantize_cc = False                   # Whether to quantize CC events

        # MENUS / NAVIGATION
        self.startup_menu_idx = 0                  # Index of the startup menu

        # DISPLAY
        self.led_pixel_brightness = 0.3            # Brightness of the LED pixels (0.0-1.0)

        # Other Global Tracking
        self.velocity_mapped = False               # Whether velocity is mapped to another parameter

    def get_startup_preset(self):
        """
        Gets the name of the startup preset from settings file.
        
        Returns:
            str: Name of the startup preset.
        """
        try:
            with open(constants.PRESETS_FILEPATH, 'r', encoding='utf-8') as json_file:
                settings_from_preset_file = json.load(json_file)
                return settings_from_preset_file["STARTUP_PRESET"]
        except Exception as e:
            errmsg = f"Error loading startup preset: {e}"
            print(errmsg)
            return errmsg

    def get_preset_names_list(self):
        """
        Gets a sorted list of all available preset names.
        
        Returns:
            list: Available preset names.
        """
        try:
            with open(constants.PRESETS_FILEPATH, 'r', encoding='utf-8') as json_file:
                settings_from_preset_file = json.load(json_file)
                names_list = [key for key in settings_from_preset_file.keys() if key != 'STARTUP_PRESET']
                names_list.sort()
                names_list.append('*NEW*')
                return names_list
        except Exception as e:
            print(f"Error loading preset: {e}")
            return []

    def load_preset(self, preset_name):
        """
        Loads a preset and applies its settings.
        
        Args:
            preset_name (str): Name of the preset to load.
        """

        try:
            with open(constants.PRESETS_FILEPATH, 'r', encoding='utf-8') as json_file:
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
            print("Error loading preset:", e)

        # Save the preset as the default preset when loaded
        try:
            with open(constants.PRESETS_FILEPATH, 'w', encoding='utf-8') as json_file:
                all_settings_from_file["STARTUP_PRESET"] = preset_name
                json.dump(all_settings_from_file, json_file)
        except OSError:
            print("Error saving default preset")

    def save_preset_to_file(self, preset_name):
        """
        Saves current settings as a preset with associated chord data.
        """
        # Load existing presets; handle missing or invalid JSON
        try:
            with open(constants.PRESETS_FILEPATH, 'r', encoding='utf-8') as json_file:
                all_settings = json.load(json_file)
        # except FileNotFoundError:
        #     all_settings = {}
        except ValueError as e:
            all_settings = {}

        if preset_name == '*NEW*':
            preset_name = f"PRESET_{len(all_settings) - 1}"
            preset_settings = {}
        else:
            preset_settings = all_settings.get(preset_name, {})

        for key in self.__dict__:
            print(f"[DEBUG] Setting key {key} = {getattr(self, key)}")
            preset_settings[key] = getattr(self, key)

        from chordmanager import chord_manager
        old_ref = preset_settings.get("chordref")
        chord_filename = self.save_chords_to_file(chord_manager, existing_file=old_ref)
        preset_settings["chordref"] = chord_filename

        all_settings[preset_name] = preset_settings
        all_settings["STARTUP_PRESET"] = preset_name

        with open(constants.PRESETS_FILEPATH, 'w', encoding='utf-8') as json_file:
            json.dump(all_settings, json_file)
        print(f"[DEBUG] Preset {preset_name} saved successfully")

    def load_startup_preset(self):
        """
        Loads the default startup preset.
        """
        self.load_preset(self.get_startup_preset())
    
    def set_play_mode(self, mode):
        """
        Sets the current play mode.
        
        Args:
            mode (str): Play mode to set.
        """
        self.play_mode = mode

    def get_play_mode(self):
        """
        Gets the current play mode.
        
        Returns:
            str: Current play mode.
        """
        return self.play_mode

    def save_chords_to_file(self, chord_manager, base_path='/', folder_name='chords', existing_file=None):
        """
        Saves chord data to a file.
        
        Args:
            chord_manager: Source of chord data to save
            base_path (str): Base directory path
            folder_name (str): Folder to store chord files
            existing_file (str): Name of existing file to overwrite
            
        Returns:
            str: Filename of the saved chord data file or None on error
        """

        chords_dir = f"{base_path}{folder_name}"
        print(f"[DEBUG] saving chords to file: base_path={base_path}, folder_name={folder_name}, existing_file={existing_file}")
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
            print(f"[DEBUG] Chord CSV written to {chord_path}")
            return chord_filename

        except Exception as e:
            print(f"[ERROR] save_chords_to_file exception: {e} (type: {type(e).__name__})")
            return None

settings = Settings()
settings.load_startup_preset()
gc.collect()  # Run garbage collection to free up memory after loading settings
