from settings import settings
import midi
import display
import looper
from chordmanager import chord_manager
import presets
import playmenu
import settingsmenu
from utils import next_or_previous_index

class Menu:
    """
    Represents a menu in the application.

    Attributes:
        menus (list): List of all menu objects created.
        current_menu_idx (int): Index of the current menu.
        number_of_menus (int): Total number of menus.
        current_menu (Menu): Current menu object.
        menu_nav_mode (bool): True if controls change menus, False if controls change settings on current menu.
        notification_text_title (str): Temporary notification text to be displayed on the screen.
        notification_ontime (int): Timer to turn off notification after a certain time.
        prev_top_text (str): Previous top text displayed on the screen.
    """
    menus = []            
    current_menu_idx = settings.STARTUP_MENU_IDX 
    number_of_menus = 0
    current_menu = None
    menu_nav_mode = False
    menu_lock_mode = False
    notification_text_title = None
    notification_ontime = -1
    prev_top_text = ""

    def __init__(self, menu_title, actions=None):
        """
        Initializes a new Menu object.

        Args:
            menu_title (str): The title of the menu.
            actions (dict, optional): Dictionary of actions and their corresponding functions. Defaults to None.
        """
        self.menu_number = Menu.number_of_menus + 1
        self.menu_title = menu_title
        self.actions = actions if actions is not None else {}

        Menu.number_of_menus += 1
        Menu.menus.append(self)
    
    @classmethod
    def change_menu(cls, up_or_down):
        """
        Changes the current menu to the next or previous menu.

        Args:
            up_or_down (bool): True to move to the next menu, False to move to the previous menu.
        """
        cls.current_menu_idx = next_or_previous_index(cls.current_menu_idx, cls.number_of_menus, up_or_down)
        cls.current_menu = cls.menus[cls.current_menu_idx]
        display.display_text_top(cls.get_current_title_text())
        display.turn_off_all_dots()
        cls.current_menu.display()
        cls.current_menu.setup()
    
    @classmethod
    def toggle_nav_mode(cls, on_or_off=None):
        """
        Toggles the navigation mode of the menu.

        Args:
            on_or_off (bool, optional): The desired navigation mode. If None, the navigation mode will be toggled.
        """
        if on_or_off is None:
            cls.menu_nav_mode = not cls.menu_nav_mode
        elif isinstance(on_or_off, bool):
            cls.menu_nav_mode = on_or_off

        display.toggle_menu_navmode_icon(cls.menu_nav_mode)

    @classmethod
    def toggle_lock_mode(cls, on_or_off=None):
        """
        Toggles the lock mode of the menu.

        Args:
            on_or_off (bool, optional): The desired lock mode. If None, the lock mode will be toggled.
        """
        if on_or_off is None:
            cls.menu_lock_mode = not cls.menu_lock_mode
        elif isinstance(on_or_off, bool):
            cls.menu_lock_mode = on_or_off
        display.toggle_menu_lock_icon(cls.menu_lock_mode, cls.menu_nav_mode)
                                      
    @classmethod       
    def toggle_fn_button_icon(cls, on_or_off):
        display.toggle_fn_button_icon(on_or_off)

    @classmethod
    def display_notification(cls, msg=None):
        display.display_notification(msg)

    @classmethod
    def display_clear_notifications(cls):
        display.display_clear_notifications(cls.get_current_title_text())
    
    @classmethod
    def initialize(cls):
        cls.current_menu = cls.menus[cls.current_menu_idx]
        menu = cls.current_menu
        menu.display()
        display.display_text_top(cls.get_current_title_text())

    @classmethod
    def get_current_title_text(cls):
        menu = cls.current_menu
        return f"{menu.menu_number}) {menu.menu_title}"
    
    def display(self):
        display_text = self.actions.get('primary_display_function', lambda: "")()
        display.display_text_middle(display_text)
    
    def setup(self):
        self.actions.get('setup_function', lambda: None)()

# ------------- Set up each menu ---------------------- #

# Play Menu
midibank_menu = Menu(
    "Play",
    {
        'primary_display_function': playmenu.get_midi_bank_display_text,
        'encoder_change_function': playmenu.change_and_display_midi_bank,
        'pad_held_function': playmenu.pad_held_function,
        'fn_button_press_function': chord_manager.chordmode_fn_press_function,
        'fn_button_dbl_press_function': playmenu.double_click_func_btn,
        'fn_button_held_function': playmenu.fn_button_held_function,
        'encoder_button_press_and_turn_function': playmenu.encoder_button_press_and_turn_function,
        'fn_button_held_and_encoder_change_function': playmenu.fn_button_held_and_encoder_turned_function,
        'encoder_button_held_function': playmenu.encoder_button_held_function,
    }
)

# Scale Menu
scale_menu = Menu(
    "Scale Select",
    {
        'primary_display_function': midi.get_current_scale_display_text,
        'setup_function': midi.scale_setup_function,
        'encoder_change_function': midi.chg_scale,
        'fn_button_press_function': midi.scale_fn_press_function,
        'fn_button_dbl_press_function': midi.chg_root,
        'fn_button_held_function': midi.scale_fn_held_function,
        'fn_button_held_and_encoder_change_function': midi.chg_root,
    }
)

# Looper Menu
looper_menu = Menu(
    "Looper",
    {
        'primary_display_function': looper.get_loopermode_display_text,
        'setup_function': looper.update_play_rec_icons,
        'encoder_change_function': looper.encoder_chg_function,
        'fn_button_press_function': looper.process_select_btn_press,
        'fn_button_dbl_press_function': looper.toggle_loops_playstate,
        'fn_button_held_function': looper.clear_all_loops,
    }
)

# MIDI Settings Menu
midi_menu = Menu(
    "MIDI Settings",
    {
        'primary_display_function': settingsmenu.get_midi_settings_display_text,
        'encoder_change_function': settingsmenu.midi_settings_menu_encoder_change_function,
        'fn_button_press_function': settingsmenu.midi_settings_menu_fn_press_function,
        'fn_button_dbl_press_function': settingsmenu.midi_settings_menu_fn_press_function,
        'fn_button_held_function': settingsmenu.generic_settings_fn_hold_function_dots,
        'fn_button_held_and_encoder_change_function': settingsmenu.midi_settings_menu_fn_btn_encoder_chg_function,
    }
)

# Other Settings Menu
settings_menu = Menu(
    "Other Settings",
    {
        'primary_display_function': settingsmenu.get_settings_display_text,
        'encoder_change_function': settingsmenu.settings_menu_encoder_change_function,
        'fn_button_press_function': settingsmenu.settings_menu_fn_press_function,
        'fn_button_dbl_press_function': settingsmenu.settings_menu_fn_press_function,
        'fn_button_held_function': settingsmenu.generic_settings_fn_hold_function_dots,
        'fn_button_held_and_encoder_change_function': settingsmenu.settings_menu_fn_btn_encoder_chg_function,
    }
)

# Preset Load Menu
preset_load_menu = Menu(
    "Load Preset",
    {
        'primary_display_function': presets.get_preset_display_text,
        'encoder_change_function': presets.load_next_or_previous_preset,
        'fn_button_press_function': presets.load_preset,
    }
)

# Preset Save Menu
preset_save_menu = Menu(
    "Save Preset",
    {
        'primary_display_function': presets.get_preset_display_text,
        'encoder_change_function': presets.select_next_or_previous_preset,
        'fn_button_press_function': presets.save_preset,
    }
)