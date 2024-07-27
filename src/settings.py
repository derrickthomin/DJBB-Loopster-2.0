import json


# This is the settings object that we will use throughout the program.
# It is initialized with default values, and can be updated with values from a .json file.
class Settings:
    def __init__(self):
        
        self.DEBUG = False
        self.PERFORMANCE_MODE = False
        self.DEFAULT_MIDIBANK_IDX = 3
        self.MIDI_CHANNEL = 0
        self.DEFAULT_VELOCITY = 120
        self.DEFAULT_BPM = 120
        self.DEFAULT_SINGLENOTE_MODE_VELOCITIES = [8, 15, 22, 29, 36, 43, 50, 57, 64, 71, 78, 85, 92, 99, 106, 127]
        self.MIDI_NOTES_DEFAULT = [36 + i for i in range(16)]
        self.MIDI_TYPE = "USB"
        self.DEFAULT_SCALE_IDX = 0
        self.DEFAULT_ROOTNOTE_IDX = 0
        self.DEFAULT_SCALENOTES_IDX = 2
        self.DEFAULT_SCALEBANK_IDX = 0
        self.STARTING_PLAYMODE = 'chord'
        self.MIDI_SYNC_STATUS = False
        self.MIDI_SETTINGS_PAGE_INDICIES = [0, 0, 0, 0, 0]

        # LOOPER
        self.MIDI_NOTES_LIMIT = 50

        # MENUS / NAVIGATION
        self.STARTUP_MENU_IDX = 0
        self.NAV_BUTTONS_POLL_S = 0.02
        self.BUTTON_HOLD_THRESH_S = 0.5
        self.DBL_PRESS_THRESH_S = 0.4

        # DISPLAY
        self.NOTIFICATION_THRESH_S = 2
        self.DISPLAY_NOTIFICATION_METERING_THRESH = 0.08
        self.PIXEL_BRIGHTNESS = 0.3

        self.presets_filepath = "presets.json"   # In root directory


    def print_settings(self):
        for key in self.__dict__:
            print(f"{key}: {self.__dict__[key]}")

    def get_dict_from_settings(self):
        return self.__dict__
    
    # Update the settings object that we are using.
    def save_settings_from_dict(self, settings_dict):
        for key in settings_dict:
            if key in self.__dict__:
                setattr(self, key, settings_dict[key])
    
    def get_startup_preset(self):
        try:
            with open(self.presets_filepath, 'r', encoding='utf-8') as json_file:
                settings_from_file = json.load(json_file)
                print(f"STARTUP_PRESET: {settings_from_file['STARTUP_PRESET']}")
                return settings_from_file["STARTUP_PRESET"]
        except Exception as e: 
            print(f"Error loading preset: {e}")
            return
        
    
    def load_preset(self, preset_name):
        try:
            with open(self.presets_filepath, 'r', encoding='utf-8') as json_file:
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
        try:
            with open(self.presets_filepath, 'r', encoding='utf-8') as json_file:
                all_settings = json.load(json_file)
                preset_settings = all_settings[preset_name]
                #new_preset_settings = {}
                for key in self.__dict__:
                    preset_settings[key] = getattr(self, key)
                all_settings[preset_name] = preset_settings
                all_settings["STARTUP_PRESET"] = preset_name
            with open(self.presets_filepath, 'w', encoding='utf-8') as json_file:
                json.dump(all_settings, json_file)
        except Exception as e: 
            print(f"Error saving preset: {e}")
        
    def load_startup_preset(self):
        self.load_preset(self.get_startup_preset())

settings = Settings()
settings.load_startup_preset()