import time
import presets
import playmenu
import settingsmenu
from loopmanager import loop_manager
from display import display
from midi import midi
from utils import next_or_previous_index

class Menu:
    """Menu navigation and action dispatch."""
    menus = []         
    current_idx = 0  # Always start at first menu
    num_menus = 0
    current_menu = None
    is_nav_mode = False
    is_locked = False
    _last_nav_time = 0
    _nav_pending = False

    def __init__(self, menu_title, actions=None):
        self.menu_number = Menu.num_menus + 1
        self.menu_title = menu_title
        self.actions = actions if actions is not None else {}

        Menu.num_menus += 1
        Menu.menus.append(self)
    
    @classmethod
    def next_or_prev_menu(cls, up_or_down, jump_to_index=None):
        if jump_to_index is not None:
            cls.current_idx = jump_to_index
        else:
            cls.current_idx = next_or_previous_index(cls.current_idx, cls.num_menus, up_or_down, False)

        cls.current_menu = cls.menus[cls.current_idx]

        # Direct jumps should render immediately (not deferred)
        if jump_to_index is not None:
            cls._nav_pending = False
            display.show_text_top(cls.get_current_title_text())
            cls._render_full_current_menu()
            return

        # Encoder nav scrolling: update title now, defer expensive content rendering
        cls._last_nav_time = time.monotonic()
        cls._nav_pending = True
        display.show_text_top(cls.get_current_title_text())

    @classmethod
    def settle_nav(cls):
        if not cls._nav_pending:
            return

        if time.monotonic() - cls._last_nav_time < 0.12:
            return

        cls._nav_pending = False
        cls._render_full_current_menu()

    @classmethod
    def _render_full_current_menu(cls):
        display.turn_off_all_dots()
        cls.current_menu.display()
        cls.current_menu.setup()
    
    @classmethod
    def toggle_nav_mode(cls, on_or_off=None):
        if cls._nav_pending:
            cls._nav_pending = False
            cls._render_full_current_menu()

        if on_or_off is None:
            cls.is_nav_mode = not cls.is_nav_mode
        elif isinstance(on_or_off, bool):
            cls.is_nav_mode = on_or_off

        display.toggle_navmode_icon(cls.is_nav_mode)

    @classmethod
    def toggle_lock_mode(cls, on_or_off=None):
        if on_or_off is None:
            cls.is_locked = not cls.is_locked
        elif isinstance(on_or_off, bool):
            cls.is_locked = on_or_off
        display.toggle_lock_icon(cls.is_locked, cls.is_nav_mode)

    @classmethod
    def show_notification(cls, msg=None):
        display.show_notification(msg)

    @classmethod
    def clear_notifications(cls):
        display.clear_notifications(cls.get_current_title_text())
    
    @classmethod
    def initialize(cls):
        cls.current_menu = cls.menus[cls.current_idx]
        menu = cls.current_menu
        menu.display()
        menu.setup()
        display.show_text_top(cls.get_current_title_text())

    @classmethod
    def get_current_title_text(cls):
        menu = cls.current_menu
        return f"{menu.menu_number}) {menu.menu_title}"
    
    def display(self):
        display_text = self.actions.get('primary_display_function', lambda: "")()
        display.show_text_middle(display_text)
    
    def setup(self):
        self.actions.get('setup_function', lambda: None)()

# ------------- Set up each menu ---------------------- #

# Play Menu
play_menu = Menu(
    "Play",
    {
        'primary_display_function': playmenu.get_playmenu_display_text,
        'setup_function': playmenu.play_menu_setup,
        'encoder_change_function': playmenu.change_and_display_midi_bank,
        'pad_held_function': playmenu.pad_held_function,
        'fn_button_press_function': loop_manager.handle_fn_press,
        'fn_button_dbl_press_function': playmenu.double_click_fn_button,
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
        'encoder_change_function': midi.next_or_prev_scale,
        'fn_button_press_function': midi.scale_fn_press_function,
        'fn_button_dbl_press_function': midi.next_or_prev_root,
        'fn_button_held_function': midi.scale_fn_held_function,
        'fn_button_held_and_encoder_change_function': midi.next_or_prev_root,
    }
)

# MIDI Settings Menu
midi_menu = Menu(
    "MIDI Settings",
    {
        'primary_display_function': settingsmenu.get_midi_settings_display_text,
        'setup_function': settingsmenu.midi_settings_menu_setup,
        'pad_held_function': settingsmenu.midi_settings_pad_held_function,
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
        'setup_function': settingsmenu.settings_menu_setup,
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
        'setup_function': presets.load_preset_setup,
    }
)

# Preset Save Menu
preset_save_menu = Menu(
    "Save Preset",
    {
        'primary_display_function': presets.get_preset_display_text,
        'encoder_change_function': presets.select_next_or_previous_preset,
        'fn_button_press_function': presets.save_preset_to_file,
    }
)