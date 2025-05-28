import json
import constants
import os

class Settings:
    """
    A class that represents the settings that can be changed, loaded, and saved.

    Attributes:
        DEBUG (bool): Flag indicating whether debug mode is enabled.
        PERFORMANCE_MODE (bool): Flag indicating whether performance mode is enabled.
        MIDIBANK_IDX (int): The default MIDI bank index.
        MIDI_CHANNEL (int): The MIDI channel to use.
        DEFAULT_VELOCITY (int): The default velocity value.
        DEFAULT_BPM (int): The default BPM (beats per minute).
        MIDI_NOTES_DEFAULT (list): The default MIDI notes.
        MIDI_TYPE (str): The type of MIDI connection.
        SCALE_IDX (int): The default scale index.
        ROOTNOTE_IDX (int): The default root note index.
        SCALENOTES_IDX (int): The default scale notes index.
        SCALE_IDX (int): The default scale bank index.
        PLAYMODE (str): The starting play mode.
        MIDI_SYNC (bool): Flag indicating the MIDI sync status.
        midi_settings_page_indices (list): The MIDI settings page indices.

        LOOPER:
        LOOP_NOTES_LIMIT (int): The limit for MIDI notes.

        MENUS / NAVIGATION:
        startup_menu_idx (int): The index of the startup menu.

        DISPLAY:
        PIXEL_BRIGHTNESS (float): The brightness of the all_pixels.

    Methods:
        print_settings(): Prints all the settings.
        get_dict_from_settings(): Returns a dictionary representation of the settings.
        save_settings_from_dict(settings_dict): Updates the settings object using a dictionary.
        get_startup_preset(): Retrieves the startup preset from the presets file.
        get_preset_names_list(): Retrieves the names of all the presets.
        load_preset(preset_name): Loads a preset from the presets file.
        save_preset_to_file(preset_name): Saves the current settings as a preset.
        load_startup_preset(): Loads the startup preset.
        save_chords_to_file(chord_manager, base_path, folder_name): Saves chord data to a file.
    """

    def __init__(self):
        # Initialize all the settings attributes
        self.debug = False
        self.performance_mode = False
        self.midibank_idx = 3
        self.midi_channel_out = 0
        self.midi_channel_in = 0
        self.midi_channel_current = self.midi_channel_out # This is not saved, but used to track the current channel for MIDI messages
        self.default_velocity = 120
        self.default_bpm = 120
        self.midi_notes_default = [36 + i for i in range(16)]
        self.midi_type = "USB"
        self.midi_usb_io = "both" # "both", "in", "out"
        self.midi_aux_io = "both" # "both", "in", "out"
        self.scale_idx = 0
        self.rootnote_idx = 0
        self.scalenotes_idx = 2
        self.scale_idx = 0
        self.play_mode = 'chord'
        self.midi_sync = False
        self.midi_passthru = True
        self.record_cc = True
        self.clock_source = "AUTO"                # AUTO, USB, AUX
        self.notes_all_at_once = False            # Plays all notes at once when in oneshot mode, instead of in sequence
        self.midi_settings_page_indices = [0, 0, 0, 0, 0, 0, 0, 0, 1,0,0,1]  # Updated to include CC Resolution with default index 1 (value 10)
        self.settings_menu_option_indices = [0,0,0,0,0,0,0,0,0,0,0,0,0]
        self.midi_channel_pad_mapping = [None] * 16  # Default MIDI channel mapping for pads

        # LOOPER / CHORDMODE / Arp
        self.chordmode_looptype = "chordloop" # loop, chordloop, oneshot
        self.arpeggiator_type = "up" 
        self.arpeggiator_length = "1/8"  # "1", "1/2", "1/4", "1/8", "1/16", "1/32", "1/64"
        self.encoder_steps_per_arpnote = 1           # Higher = more turns for next note
        self.arp_is_polyphonic = True
        self.chord_file_to_load = False   # For preset loading, this is the chord file to load

        # QUANTIZER
        self.quantize_time = "none"      # "none", "1/4", "1/8", "1/16", "1/32" DJT 
        self.quantize_strength = 100     # 0-100      
        self.quantize_loop = "none"      # "none", "1", "1/2", "1/4", "1/8" DJT
        self.trim_silence_mode = "start" # "start", "end", "both", "none"
        self.cc_resolution = 1           # Default value from [1, 2, 5, 8, 16, 32, 64]
        self.quantize_cc = False

        # MENUS / NAVIGATION
        self.startup_menu_idx = 0

        # DISPLAY
        self.led_pixel_brightness = 0.3

        # Other Global Tracking
        self.velocity_mapped = False

    def get_startup_preset(self):
        """
        Retrieves the startup preset from the presets file.

        Returns:
            str: The name of the startup preset.
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
        Retrieves the names of all the presets.

        Returns:
            list: A list of preset names.
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
        Loads a preset from the presets file, and overwrites the current settings if they exist in the preset.

        Args:
            preset_name (str): The name of the preset to load.
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
                # from chordmanager import chord_manager
                # chord_path = f"/chords/{chord_file}"
                # print(f"[DEBUG] Loading chord file: {chord_path}")
                # chord_manager.load_chords_txt(chord_path)

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
        Saves the current settings as a preset and handles saving associated chords.
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
        Loads the startup preset.
        """
        self.load_preset(self.get_startup_preset())
    
    def set_play_mode(self, mode):
        """
        Sets the play mode.

        Args:
            mode (str): The play mode to set.
        """
        self.play_mode = mode

    def get_play_mode(self):
        """
        Returns the current play mode.

        Returns:
            str: The current play mode.
        """
        return self.play_mode

    def save_chords_to_file(self, chord_manager, base_path='/', folder_name='chords', existing_file=None):
        """
        Saves all chord data (on messages, off messages, CCs, and their timings) from the chord manager
        to the specified file in <base_path>/<folder_name>. If existing_file is provided, overwrite it.
        """
        # Use root on microcontroller as base path
        chords_dir = f"{base_path}{folder_name}"
        print(f"[DEBUG] saving chords to file: base_path={base_path}, folder_name={folder_name}, existing_file={existing_file}")
        try:
            # Create the directory if it doesn't exist
            try:
                os.mkdir(chords_dir)
            except OSError:
                pass

            # Determine filename: overwrite existing_file or choose next index
            if existing_file:
                chord_filename = existing_file
                # Delete old file to ensure clean overwrite
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
