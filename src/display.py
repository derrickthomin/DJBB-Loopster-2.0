import time
import busio
from settings import settings
import constants as c 
import adafruit_ssd1306
from pixels import pixels
from debug import print_debug
from utils import free_memory, show_memory


# Display Setup
i2c     = busio.I2C(c.SCL, c.SDA, frequency=400_000)
_display = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)


# Dots
dot_start_positions = [(0, 25), (0, 42), (120, 42), (125, 25)]
DOT_WIDTH = 3
DOT_HEIGHT = 3

show_memory("Before display init")
free_memory()
show_memory("After display init")

class DisplayManager():
    """
    A class to manage the display and neopixels.
    """

    def __init__(self):
        self.display_needs_update = True

    def check_show_display(self):
        """
        Checks if the display needs to be updated and shows it if necessary.
        """
        _display.show()
        self.display_needs_update = False

display_manager = DisplayManager()

# ------ Display Class ---------
class Display:
    """
    A class to encapsulate display functionalities.
    """

    def __init__(self):
        self.dot_states = [False] * 4
        self.notification_text = None
        self.notification_on_time = 0
        self.current_top_text = None
        self.previous_top_text = None
        self.show_notification_FPS_timer = 0
        self.show_notification_most_recent = ""

    def _set_update_flag(self, yesOrNo=True, immediate=False):
        """
        Sets the display update flag.

        Args:
            yesOrNo (bool, optional): Flag indicating whether the display needs to be updated. Defaults to True.
            immediate (bool, optional): Flag indicating whether the display update should happen immediately. Defaults to False.
        Returns:
            None
        """
        
        if immediate:
            _display.show()
            return
        display_manager.display_needs_update = yesOrNo

    def show_text_top(self, text, notification=False, force_refresh=False):
        """
        Display text on the top part of the screen. If it's a notification, the text will be displayed only temporarily.

        Args:
            text (str): Text to _display.
            notification (bool, optional): Indicates if it's a notification. Defaults to False.
        """
        _display.fill_rect(0, 0, c.SCREEN_W, c.TOP_HEIGHT, c.BKG_COLOR)

        if notification:
            linepad_x = 0
            _display.fill_rect(0 + linepad_x, c.TOP_HEIGHT - 1, c.SCREEN_W - (2 * linepad_x), 1, 1) 

        _display.text(text, 0 + c.PADDING, 0 + c.PADDING, c.TXT_COLOR)  
        self._set_update_flag(immediate=force_refresh)

    def show_text_middle(self, text, value_only=False, value_start_x=-1):
        """
        Display text in the middle part of the screen.

        Args:
            text (str or list): Text or list of text lines to _display.
            value_only (bool, optional): Indicates if only a value should be displayed. Defaults to False.
            value_start_x (int, optional): The starting x position for the value. Defaults to -1.

        Returns:
            None
        """
        char_height = 8
        char_width = 6

        if value_only and isinstance(text, list):
            print_debug("ERROR: show_text_middle - value_only is True, but text is a list")
            return

        if not isinstance(text, list):
            text = [text]
        
        if value_only and value_start_x > 0:
            _display.fill_rect(value_start_x, c.MIDDLE_Y_START, char_width, char_height, c.BKG_COLOR)
            _display.text(text[0], value_start_x, c.MIDDLE_Y_START, c.TXT_COLOR)

        else:
            _display.fill_rect(c.TEXT_PAD, c.MIDDLE_Y_START, 116, c.MIDDLE_HEIGHT, c.BKG_COLOR)
            if len(text) > 0:
                line_num = 0
                for text_line in text:
                    _display.text(text_line, c.TEXT_PAD, c.MIDDLE_Y_START + (line_num * c.LINEHEIGHT), c.TXT_COLOR)
                    line_num += 1

        self._set_update_flag()

    def display_left_dot(self, on_or_off=True):
        """
        Display the left dot on the screen.

        Args:
            on_or_off (bool): Indicates whether to turn the dot on or off.
        """
        self.display_dot(0, on_or_off)

    def display_right_dot(self, on_or_off=True):
        """
        Display the right dot on the screen.

        Args:
            on_or_off (bool): Indicates whether to turn the dot on or off.
        """
        self.display_dot(3, on_or_off)

    def display_dot(self, selection_pos=0, on_or_off=True):
        """
        Displays a selected dot on the _display.

        Args:
            selection_pos (str) L, R, LB, RB
            on_or_off (bool): Determines whether the dot should be turned on or off.

        Returns:
            None
        """

        if selection_pos not in (0, 1, 2, 3, "L", "R", "LB", "RB"):
            print_debug("ERROR: display_dot- invalid selection_pos")
            return
        
        if selection_pos == "L":
            selection_pos = 0
        elif selection_pos == "R":
            selection_pos = 1
        elif selection_pos == "LB":
            selection_pos = 2
        elif selection_pos == "RB":
            selection_pos = 3

        # First turn off all dots
        for i in range(4):
            _display.fill_rect(dot_start_positions[i][0], dot_start_positions[i][1], DOT_WIDTH, DOT_HEIGHT, 0)
            self.dot_states[i] = False

        self.dot_states[selection_pos] = on_or_off

        if on_or_off:
            _display.fill_rect(dot_start_positions[selection_pos][0], dot_start_positions[selection_pos][1], DOT_WIDTH, DOT_HEIGHT, 1)

        self._set_update_flag()

    def turn_off_all_dots(self):
        """
        Turns off all the dots on the _display.

        Returns:
            None
        """
        for i in range(4):
            _display.fill_rect(dot_start_positions[i][0], dot_start_positions[i][1], DOT_WIDTH, DOT_HEIGHT, 0)
            self.dot_states[i] = False

        # Also clear all pixels on left side and right side of screen. TEXT_PAD is the width
        _display.fill_rect(0, c.MIDDLE_Y_START, c.TEXT_PAD, c.MIDDLE_HEIGHT, 0)
        _display.fill_rect(c.SCREEN_W - c.TEXT_PAD, c.MIDDLE_Y_START, c.TEXT_PAD, c.MIDDLE_HEIGHT, 0)
        self._set_update_flag()

    def toggle_fn_button_icon(self, on_or_off=False):
        """
        Toggle the fn button icon on the screen.

        Args:
            on_or_off (bool, optional): Indicates whether to turn the icon on or off. Defaults to False.

        Returns:
            None
        """
        if settings.performance_mode or c.LOOPSTER_VERSION == 2: # Dont need this in V2.. LED is on the button
            return
        
        start_x = c.FN_BTN_ICON_X_START
        start_y = c.BOTTOM_Y_START
        icon_width = 32
        icon_height = 18
        pad = 2
        _display.fill_rect(start_x - pad, start_y - pad, icon_width, icon_height, 0) 
        if on_or_off: 
            _display.text(c.SEL_ICON_TXT, start_x, start_y, 1)
        self._set_update_flag()

    def _display_line_bottom(self):
        """
        Display a line at the bottom of the screen.
        """
        _display.fill_rect(0, c.BOTTOM_LINE_Y_START, c.SCREEN_W, 1, 1)
        self._set_update_flag()

    def toggle_recording_icon(self, on_or_off=False):
        """
        Toggle the recording icon on the screen.

        Args:
            on_or_off (bool, optional): Indicates whether to turn the icon on or off. Defaults to False.
        """
        if settings.performance_mode:
            return

        height = 10
        width = 18
        start_y = c.SCREEN_H - height

        if on_or_off is True:
            _display.fill_rect(0, start_y, width, height, 1)
            _display.text(c.RECORDING_ICON, 0, start_y, 0)
            self._set_update_flag()

        if on_or_off is False:
            _display.fill_rect(0, start_y, width, height, 0)
            self._set_update_flag()

    def show_text_bottom(self, text, value_only=False, start_x=-1, text_width_px=10):
        """
        Display text in the bottom part of the screen.

        Args:
            text (str or list): Text or list of text lines to _display.
            value_only (bool, optional): Indicates if only a value should be displayed. Defaults to False.
            value_start_x (int, optional): The starting x position for the value. Defaults to -1.
            text_width_px (int, optional): The width of each character in pixels. Defaults to 10.
        """
        char_height = 8
        char_width = text_width_px
        bottom_y_start = 40

        if value_only and not isinstance(text, str):
            print_debug("ERROR: must be string")
            return
        
        if value_only and start_x > 0:
            _display.fill_rect(start_x, bottom_y_start, char_width, char_height, c.BKG_COLOR)
            _display.text(text, start_x, bottom_y_start, c.TXT_COLOR)

        else:
            _display.fill_rect(0, bottom_y_start, c.SCREEN_W, char_height, c.BKG_COLOR)   
            _display.text(text, 0 + c.TEXT_PAD, bottom_y_start, c.TXT_COLOR)
                
        self._set_update_flag()

    def toggle_play_icon(self, on_or_off=False):
        """
        Toggle the play icon on the screen.

        Args:
            on_or_off (bool, optional): Indicates whether to turn the icon on or off. Defaults to False.
        """
        if settings.performance_mode:
            return

        height = 10
        width = 18
        start_y = c.SCREEN_H - 23

        if on_or_off is True:
            _display.fill_rect(0, start_y, width, height, 0)
            _display.text(c.PLAY_ICON, 0, start_y, 1)

        if on_or_off is False:
            _display.fill_rect(0, start_y, width, height, 0)

    def toggle_navmode_icon(self, on_or_off):
        """
        Toggle the navigation mode icon on the screen.

        Args:
            on_or_off (bool): Indicates whether to turn the icon on or off.

        Returns:
            None
        """
        if on_or_off is True:
            _display.fill_rect(c.NAV_ICON_X_START, c.SCREEN_H - c.LINEHEIGHT - 2, c.NAV_MSG_WIDTH, 10, 1)
            _display.text(c.NAV_MODE_TXT, c.NAV_ICON_X_START + 4, c.SCREEN_H - c.LINEHEIGHT, 0)
            self._set_update_flag()
            pixels.encoder_button_on()

        elif on_or_off is False:
            _display.fill_rect(c.NAV_ICON_X_START, c.SCREEN_H - c.LINEHEIGHT - 2, c.NAV_MSG_WIDTH, 10, 0)
            self._set_update_flag()
            pixels.encoder_button_off()

    def toggle_lock_icon(self, on_or_off, nav_mode_on=False):
        """
        Toggle the lock icon on the screen.

        Args:
            on_or_off (bool): Indicates whether to turn the icon on or off.
            nav_mode_on (bool, optional): Indicates whether the navigation mode is on. Defaults to False.

        Returns:
            None
        """
        if on_or_off is True:
            _display.fill_rect(c.NAV_ICON_X_START, c.SCREEN_H - c.LINEHEIGHT - 2, c.NAV_MSG_WIDTH, 10, 1)
            _display.text(c.ENCODER_LOCK_TXT, c.NAV_ICON_X_START + 4, c.SCREEN_H - c.LINEHEIGHT, 0)
            self._set_update_flag()
            pixels.encoder_button_on(c.ENCODER_LOCK_COLOR)

        elif on_or_off is False:
            _display.fill_rect(c.NAV_ICON_X_START, c.SCREEN_H - c.LINEHEIGHT - 2, c.NAV_MSG_WIDTH, 10, 0)
            self._set_update_flag()
            if nav_mode_on:
                pixels.encoder_button_on(c.NAV_MODE_COLOR)
                self.toggle_navmode_icon(True)
            else:
                pixels.encoder_button_off()

    def update_playmode_icon(self, playmode):
        """
        Update the playmode icon on the screen.

        Args:
            playmode (str): The playmode to _display.

        Returns:
            None
        """
        if settings.performance_mode:
            return
        
        y = c.SCREEN_H - 8
        display_text = ""

        _display.fill_rect(c.PLAYMODE_ICON_X_START, y, 25, 25, 0)
        if playmode == "chord":
            display_text = c.CHD_MODE_ICON
        elif playmode == "velocity":
            display_text = c.VEL_MODE_ICON
        elif playmode == "encoder":
            display_text = c.ENC_MODE_ICON

        _display.text(display_text, c.PLAYMODE_ICON_X_START, y, 1)
        self._set_update_flag()
        
    def show_notification(self, msg=None, force_display=False):
        """
        Display a temporary notification banner at the top of the screen.

        Args:
            msg (str): Notification message to _display.
        """

        if settings.performance_mode:
            return

        if not msg:
            return

        if ((time.monotonic() - self.show_notification_FPS_timer) > c.show_notification_METERING_THRESH) or force_display:
            self.notification_text = msg

            if self.notification_on_time > 0:
                self.previous_top_text = self.current_top_text

            self.current_top_text = msg
            self.show_text_top(msg, True, True)

            self.notification_on_time = time.monotonic()

            self.show_notification_FPS_timer = time.monotonic()

    def clear_notifications(self, replace_text=None):
        """
        Check and clear notifications from the top bar if necessary.

        Args:
            replace_text (str, optional): Text to replace the notification with. Defaults to None.
        """

        if self.notification_text is None or replace_text is None:
            return

        if self.notification_text == replace_text:
            return

        if time.monotonic() - self.notification_on_time > c.NOTIFICATION_THRESH_S:
            self.notification_on_time = -1
            self.notification_text = None
            self.show_text_top(replace_text)

    def show_startup_screen(self):
        """
        Display the startup screen.
        """
        _display.fill(0)
        self._display_line_bottom()
        self.show_text_top("DJBB MIDI LOOPSTER", notification=False)
        self.show_text_middle(f"Loading {settings.get_startup_preset()}...")
        _display.show()
        time.sleep(0.8)

display = Display()         # Create an instance of the Display class
