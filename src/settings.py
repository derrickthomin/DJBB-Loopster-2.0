import json
import constants

# This is the settings object that we will use throughout the program.
# It is initialized with default values, and can be updated with values from a .json file.
class Settings:
    """
    A class that represents the settings for the application.

    Attributes:
        DEBUG (bool): Flag indicating whether debug mode is enabled.
        PERFORMANCE_MODE (bool): Flag indicating whether performance mode is enabled.
        DEFAULT_MIDIBANK_IDX (int): The default MIDI bank index.
        MIDI_CHANNEL (int): The MIDI channel to use.
        DEFAULT_VELOCITY (int): The default velocity value.
        DEFAULT_BPM (int): The default BPM (beats per minute).
        MIDI_NOTES_DEFAULT (list): The default MIDI notes.
        MIDI_TYPE (str): The type of MIDI connection.
        DEFAULT_SCALE_IDX (int): The default scale index.
        DEFAULT_ROOTNOTE_IDX (int): The default root note index.
        DEFAULT_SCALENOTES_IDX (int): The default scale notes index.
        DEFAULT_SCALEBANK_IDX (int): The default scale bank index.
        STARTING_PLAYMODE (str): The starting play mode.
        MIDI_SYNC_STATUS (bool): Flag indicating the MIDI sync status.
        MIDI_SETTINGS_PAGE_INDICIES (list): The MIDI settings page indices.

        LOOPER:
        MIDI_NOTES_LIMIT (int): The limit for MIDI notes.

        MENUS / NAVIGATION:
        STARTUP_MENU_IDX (int): The index of the startup menu.

        DISPLAY:
        PIXEL_BRIGHTNESS (float): The brightness of the all_pixels.

    Methods:
        print_settings(): Prints all the settings.
        get_dict_from_settings(): Returns a dictionary representation of the settings.
        save_settings_from_dict(settings_dict): Updates the settings object using a dictionary.
        get_startup_preset(): Retrieves the startup preset from the presets file.
        get_preset_names(): Retrieves the names of all the presets.
        load_preset(preset_name): Loads a preset from the presets file.
        save_preset(preset_name): Saves the current settings as a preset.
        load_startup_preset(): Loads the startup preset.
    """

    def __init__(self):
        # Initialize all the settings attributes
        self.DEBUG = False
        self.PERFORMANCE_MODE = False
        self.DEFAULT_MIDIBANK_IDX = 3
        self.MIDI_CHANNEL = 0
        self.DEFAULT_VELOCITY = 120
        self.DEFAULT_BPM = 120
        self.MIDI_NOTES_DEFAULT = [36 + i for i in range(16)]
        self.MIDI_TYPE = "USB"
        self.DEFAULT_SCALE_IDX = 0
        self.DEFAULT_ROOTNOTE_IDX = 0
        self.DEFAULT_SCALENOTES_IDX = 2
        self.DEFAULT_SCALEBANK_IDX = 0
        self.STARTING_PLAYMODE = 'chord'
        self.MIDI_SYNC_STATUS = False
        self.MIDI_SETTINGS_PAGE_INDICIES = [0, 0, 0, 0, 0]

        # LOOPER / CHORDMODE
        self.MIDI_NOTES_LIMIT = 50
        self.CHORDMODE_DEFAULT_LOOPTYPE = "chordloop" 

        # QUANTIZER
        self.DEFAULT_QUANTIZE_AMT = "None" # "None", "1/4", "1/8", "1/16", "1/32" DJT - Use this somewhere
        self.QUANTIZE_STRENGTH = 1.0       # Lower to humanize DJT - Use this somewhere

        # MENUS / NAVIGATION
        self.STARTUP_MENU_IDX = 0

        # DISPLAY
        self.PIXEL_BRIGHTNESS = 0.3


    def print_settings(self):
        """
        Prints all the settings.
        """
        for key in self.__dict__:
            print(f"{key}: {self.__dict__[key]}")

    def get_dict_from_settings(self):
        """
        Returns a dictionary representation of the settings.

        Returns:
            dict: A dictionary containing the settings.
        """
        return self.__dict__

    def save_settings_from_dict(self, settings_dict):
        """
        Updates the settings object using a dictionary.

        Args:
            settings_dict (dict): A dictionary containing the settings to update.
        """
        for key in settings_dict:
            if key in self.__dict__:
                setattr(self, key, settings_dict[key])

    def get_startup_preset(self):
        """
        Retrieves the startup preset from the presets file.

        Returns:
            str: The name of the startup preset.
        """
        try:
            with open(constants.PRESETS_FILEPATH, 'r', encoding='utf-8') as json_file:
                settings_from_file = json.load(json_file)
                return settings_from_file["STARTUP_PRESET"]
        except Exception as e:
            errmsg = f"Error loading startup preset: {e}"
            print(errmsg)
            return errmsg

    def get_preset_names(self):
        """
        Retrieves the names of all the presets.

        Returns:
            list: A list of preset names.
        """
        try:
            with open(constants.PRESETS_FILEPATH, 'r', encoding='utf-8') as json_file:
                settings_from_file = json.load(json_file)
                names_list = [key for key in settings_from_file.keys() if key != 'STARTUP_PRESET']
                names_list.sort()
                names_list.append('*NEW*')
                return names_list
        except Exception as e:
            print(f"Error loading preset: {e}")
            return []

    def load_preset(self, preset_name):
        """
        Loads a preset from the presets file.

        Args:
            preset_name (str): The name of the preset to load.
        """
        try:
            with open(constants.PRESETS_FILEPATH, 'r', encoding='utf-8') as json_file:
                settings_from_file = json.load(json_file)
                settings_from_file = settings_from_file[preset_name]
            # Replace defaults with stuff from the .json file, if it exists.
            if len(settings_from_file) > 0:
                for key in self.__dict__:
                    if key in settings_from_file:
                        setattr(self, key, settings_from_file[key])
                        print(f"Loaded {key}: {settings_from_file[key]}")
        except Exception as e:
            print(f"Error loading preset: {e}")

    def save_preset(self, preset_name):
        """
        Saves the current settings as a preset.

        Args:
            preset_name (str): The name of the preset to save.
        """
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