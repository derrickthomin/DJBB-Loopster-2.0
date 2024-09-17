import json
import constants

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
    """

    def __init__(self):
        # Initialize all the settings attributes
        self.debug = False
        self.performance_mode = False
        self.midibank_idx = 3
        self.midi_channel = 0
        self.default_velocity = 120
        self.default_bpm = 120
        self.midi_notes_default = [36 + i for i in range(16)]
        self.midi_type = "USB"
        self.scale_idx = 0
        self.rootnote_idx = 0
        self.scalenotes_idx = 2
        self.scale_idx = 0
        self.playmode = 'chord'
        self.midi_sync = False
        self.midi_settings_page_indices = [0, 0, 0, 0, 0]
        self.settings_menu_option_indices = [0,0,0,0,0,0,0,0,0,0,0]

        # LOOPER / CHORDMODE / Arp
        self.chordmode_looptype = "chordloop" # 
        self.arpeggiator_type = "up" 
        self.arpeggiator_length = "1/8"  # "1", "1/2", "1/4", "1/8", "1/16", "1/32", "1/64"
        self.encoder_steps_per_arpnote = 1           # Higher = more turns for next note
        self.arp_is_polyphonic = True

        # QUANTIZER
        self.quantize_time = "none"       # "none", "1/4", "1/8", "1/16", "1/32" DJT 
        self.quantize_strength = 100     # 0-100      
        self.quantize_loop = "none"      # "none", "1", "1/2", "1/4", "1/8" DJT
        self.trim_silence_mode = "start" # "start", "end", "both", "none"

        # MENUS / NAVIGATION
        self.startup_menu_idx = 0

        # DISPLAY
        self.led_pixel_brightness = 0.3

    def __repr__(self):
        for key in self.__dict__:
            print(f"{key}: {self.__dict__[key]}")

    # def print_settings(self):
    #     """
    #     Prints all the settings.
    #     """
    #     for key in self.__dict__:
    #         print(f"{key}: {self.__dict__[key]}")

    # def get_dict_from_settings(self):
    #     """
    #     Returns a dictionary representation of the settings.

    #     Returns:
    #         dict: A dictionary containing the settings.
    #     """
    #     return self.__dict__

    # def save_settings_from_dict(self, settings_dict):
    #     """
    #     Updates the settings object using a dictionary.

    #     Args:
    #         settings_dict (dict): A dictionary containing the settings to update.
    #     """
    #     for key in settings_dict:
    #         if key in self.__dict__:
    #             setattr(self, key, settings_dict[key])

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
                        print(f"Loaded {key}: {settings_from_preset_file[key]}")
        except Exception as e:
            print(f"Error loading preset: {e}")

        # Save the preset as the default preset when loaded
        try:
            with open(constants.PRESETS_FILEPATH, 'w', encoding='utf-8') as json_file:
                all_settings_from_file["STARTUP_PRESET"] = preset_name
                json.dump(all_settings_from_file, json_file)
        except Exception as e:
            print(f"Error saving default preset")

    def save_preset_to_file(self, preset_name):
        """
        Saves the current settings as a preset.

        Args:
            preset_name (str): The name of the preset to save.
        """
        #self.print_settings()
        try:
            with open(constants.PRESETS_FILEPATH, 'r', encoding='utf-8') as json_file:
                all_settings = json.load(json_file)
                if preset_name == '*NEW*':
                    preset_name = f"PRESET_{len(all_settings)-1}"
                    preset_settings = {}
                else:
                    preset_settings = all_settings[preset_name]

                for key in self.__dict__:
                    preset_settings[key] = getattr(self, key)
                all_settings[preset_name] = preset_settings
                all_settings["STARTUP_PRESET"] = preset_name
            with open(constants.PRESETS_FILEPATH, 'w', encoding='utf-8') as json_file:
                json.dump(all_settings, json_file)
        except Exception as e:
            print(f"Error saving preset: {e}")

    def load_startup_preset(self):
        """
        Loads the startup preset.
        """
        self.load_preset(self.get_startup_preset())


settings = Settings()
settings.load_startup_preset()