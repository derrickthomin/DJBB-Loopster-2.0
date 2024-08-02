from settings import settings
import midi
import display
import looper
import chordmaker
import presets
import playmenu
from utils import next_or_previous_index

class Menu:
    """
    Represents a menu in the application. Use menu.menus to access a list of all menus created.

    Attributes:
        menus (list): List of all menu objects created.
        current_menu_idx (int): Index of the current menu.
        number_of_menus (int): Total number of menus.
        current_menu (Menu): Current menu object.
        menu_nav_mode (bool): True if controls change menus, False if controls change settings on current menu.
        notification_text_title (str): Temporary notification text to be displayed on the screen.
        notification_ontime (int): Timer to turn off notification after a certain time.
        cur_top_text (str): Current top text displayed on the screen.
        prev_top_text (str): Previous top text displayed on the screen.
        cur_mid_text (str): Current middle text displayed on the screen.
        prev_mid_text (str): Previous middle text displayed on the screen.

    Methods:
        __init__(self, menu_title, primary_display_function, setup_function, encoder_change_function,
                 pad_held_function, fn_button_press_function, fn_button_dbl_press_function,
                 fn_button_held_function, fn_button_held_and_btn_click_function):
            Initializes a new Menu object.

        change_menu(cls, upOrDown):
            Changes the current menu to the next or previous menu.

        toggle_nav_mode(cls, onOrOff=None):
            Toggles the menu navigation mode on or off.

        toggle_select_button_icon(cls, onOrOff):
            Toggles the select button icon on or off.

        display_notification(cls, msg=None):
            Displays a temporary notification banner on the top of the screen.

        display_clear_notifications(cls):
            Checks and clears notifications from the top bar if necessary.

        initialize(cls):
            Initializes the menu and displays the initial menu.

        get_current_title_text(cls):
            Returns the text to display on the top of the screen.

        display(self):
            Displays the menu contents.

        setup(self):
            Runs the setup function for the menu.
    """
class Menu:

    menus = []            
    current_menu_idx = settings.STARTUP_MENU_IDX 
    number_of_menus = 0    # Used in displaying which menu u are on eg. "1/4"
    current_menu = ""      # Points to current menu object
    menu_nav_mode = False  # True = controls change menus. False = controls change settings on current menu
    notification_text_title = None     # If populated, flash this on the screen temporarily
    notification_ontime = -1           # Turn off notification after so long using this timer   
    prev_top_text = ""      

    def __init__(self, menu_title, 
                 primary_display_function,
                 setup_function,
                 encoder_change_function,
                 pad_held_function, 
                 fn_button_press_function, 
                 fn_button_dbl_press_function, 
                 fn_button_held_function,
                 fn_button_held_and_btn_click_function,
                 encoder_button_press_function,
                 encoder_button_press_and_turn_function):
        
        self.menu_number = Menu.number_of_menus + 1
        self.menu_title = menu_title
        self.options = []
        self.current_option_idx = 0

        # Set up functions
        self.primary_display_function = primary_display_function
        self.setup_function = setup_function
        self.encoder_change_function = encoder_change_function
        self.pad_held_function = pad_held_function
        self.fn_button_press_function = fn_button_press_function
        self.fn_button_dbl_press_function = fn_button_dbl_press_function
        self.fn_button_held_function = fn_button_held_function
        self.fn_button_held_and_btn_click_function = fn_button_held_and_btn_click_function
        self.encoder_button_press_function = encoder_button_press_function
        self.encoder_button_press_and_turn_function = encoder_button_press_and_turn_function

        Menu.number_of_menus += 1
        Menu.menus.append(self)
    
    # Pass in boolean for which direction to go.
    @classmethod
    def change_menu(cls, upOrDown):
        Menu.current_menu_idx = next_or_previous_index(Menu.current_menu_idx, Menu.number_of_menus, upOrDown)
        Menu.current_menu = Menu.menus[Menu.current_menu_idx]
        display.display_text_top(Menu.get_current_title_text())
        Menu.current_menu.display()
        Menu.current_menu.setup()
    
    @classmethod
    def toggle_nav_mode(self,onOrOff=None):

        if onOrOff is None:
            Menu.menu_nav_mode = not Menu.menu_nav_mode
        elif onOrOff == True or onOrOff == False:
            Menu.menu_nav_mode = onOrOff
        
        display.toggle_menu_navmode_icon(Menu.menu_nav_mode)

    @classmethod       
    def toggle_select_button_icon(self,onOrOff):
        display.toggle_select_button_icon(onOrOff)

    # Function to add a temporary notification banner to top of screen
    @classmethod
    def display_notification(self, msg=None):
        display.display_notification(msg)

    # Function to check and clear notifications from top bar if necessary
    @classmethod
    def display_clear_notifications(self):
        display.display_clear_notifications(Menu.get_current_title_text())
    
    # Call once in code.py to display the initial menu
    @classmethod
    def initialize(self):
        Menu.current_menu = Menu.menus[Menu.current_menu_idx]
        menu = Menu.current_menu
        menu.display()
        display.display_text_top(Menu.get_current_title_text())

    # Returns the text to display on the top of the screen
    @classmethod
    def get_current_title_text(self):
        menu = Menu.current_menu
        disp_text = f"[{menu.menu_number}/{Menu.number_of_menus}] - {menu.menu_title}"
        return disp_text
    
    # Display menu contents, as determined by the primary_display_function set in the menu.
    def display(self):
        display_text = self.primary_display_function()
        display.display_text_middle(display_text)
    
    # Run setup function
    def setup(self):
        self.setup_function()

# ------------- Functions Used by Menus --------------- #
def voidd(*args):
    return None

# ------------- Set up each menu ---------------------- #


# Use the below template to add new  menus. Use voidd function if nothing should happen.

# Template
# my_new_menu = Menu("Name of Menu",       # Title that is displayed
#   primary_display_function,              # Displays main value in middle of screen
#   setup_function,                        # run arbitrary screen setup code, if needed. NO ARGS.  
#   encoder_change_function,               # called when Encoder value changes (no other buttons held)
#   pad_held_function                      # called when pad is held.
#   fn_button_press_function,              # called when function Button pressed
#   fn_button_dbl_press_function,          # called when function btn double clicked
#   fn_button_held_function,               # called when function button is held
#   fn_button_held_and_btn_click_function) # called when fn button held, and another drumpad button is clicked


# 1) Change Midi Bank
midibank_menu = Menu("Play",
                     playmenu.get_midi_bank_display_text,
                     voidd,
                     playmenu.change_and_display_midi_bank,
                     playmenu.pad_held_function,
                     chordmaker.chordmode_fn_press_function,
                     playmenu.double_click_func_btn,
                     voidd,
                     voidd)

# 2) Change Scale
scale_menu = Menu("Scale Select",
                  midi.get_scale_display_text,
                  voidd,
                  midi.chg_scale,
                  voidd,
                  midi.chg_root,
                  midi.chg_root,
                  voidd,
                  voidd,
                  voidd,
                  voidd)

# 3) Looper Settings
looper_menu = Menu("Looper Mode",
                   looper.get_loopermode_display_text,
                   looper.update_play_rec_icons,
                   looper.encoder_chg_function,
                   voidd,
                   looper.process_select_btn_press,
                   looper.toggle_loops_playstate,
                   looper.clear_all_loops,
                   voidd,
                   voidd,
                   voidd)

# 4) MIDI Settings
midi_menu = Menu("MIDI Settings",
                 midi.get_midi_settings_display_text,
                 voidd,
                 midi.midi_settings_encoder_chg_function,
                 voidd,
                 midi.midi_settings_fn_press_function,
                 voidd,
                 voidd,
                 voidd,
                 voidd,
                 voidd)

# 5) Preset Load
preset_load_menu = Menu("Load Preset",
                 presets.get_preset_display_text,
                 voidd,
                 presets.next_or_previous_preset,
                 voidd,
                 presets.load_preset,
                 voidd,
                 voidd,
                 voidd,
                 voidd,
                 voidd)

# 6) Preset Save
preset_save_menu = Menu("Save Preset",
                 presets.get_preset_display_text,
                 voidd,
                 presets.next_or_previous_preset,
                 voidd,
                 presets.save_preset,
                 voidd,
                 voidd,
                 voidd,
                 voidd,
                 voidd)
