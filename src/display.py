import time
import busio
from settings import settings
import constants as c 
import adafruit_ssd1306
from pixels import pixels
from debug import print_debug

# Display Setup
i2c = busio.I2C(c.SCL, c.SDA, frequency=400_000)
_display = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)
DOT_START_POSITIONS = [(0, 25), (0, 42), (120, 42), (125, 25)]
DOT_WIDTH = 3
DOT_HEIGHT = 3

class DisplayManager():
    # Handles display update state management
    def __init__(self):
        self.display_needs_update = True

    def check_show_display(self):
        """
        Updates the display if changes are pending.
        """
        _display.show()
        self.display_needs_update = False

display_manager = DisplayManager()

class Display:
    # Manages OLED display content and UI elements

    def __init__(self):
        self.dot_states = [False] * 4           # State tracking for the 4 dot indicators
        self.notification_text = None           # Current notification text
        self.notification_on_time = 0           # Timestamp when notification appeared
        self.current_top_text = None            # Current text in top display area
        self.previous_top_text = None           # Previous text in top display area
        self.notification_FPS_timer = 0         # Rate limiter for notification updates

    def _set_update_flag(self, yesOrNo=True, immediate=False):
        """
        Marks display for update or refreshes immediately.
        
        Args:
            yesOrNo: Whether to set update flag
            immediate: Whether to refresh display immediately
        """
        
        if immediate:
            _display.show()
            return
        display_manager.display_needs_update = yesOrNo
        
    def show_text_top(self, text, notification=False, force_refresh=False):
        """
        Displays text in the top screen area.
        
        Args:
            text: Text to display
            notification: Whether to show as temporary notification
            force_refresh: Whether to update display immediately
        """
        _display.fill_rect(0, 0, c.SCREEN_W, c.TOP_HEIGHT, c.BKG_COLOR)

        if notification:
            linepad_x = 0
            _display.fill_rect(0 + linepad_x, c.TOP_HEIGHT - 1, c.SCREEN_W - (2 * linepad_x), 1, 1) 

        _display.text(text, 0 + c.PADDING, 0 + c.PADDING, c.TXT_COLOR)  
        self._set_update_flag(immediate=force_refresh)

    def show_text_middle(self, text, value_only=False, value_start_x=-1):
        """
        Displays text in the middle screen area.
        
        Args:
            text: Text or list of text lines to display
            value_only: Whether to update just a value field
            value_start_x: X-position for value display
        """
        char_height = 8
        char_width = 6

        if value_only and isinstance(text, list):
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
        Shows or hides the left dot indicator.
        """
        self.display_dot(0, on_or_off)

    def display_right_dot(self, on_or_off=True):
        """
        Shows or hides the right dot indicator.
        """
        self.display_dot(3, on_or_off)

    def display_dot(self, selection_pos=0, on_or_off=True):
        """
        Shows or hides a specific dot indicator.
        
        Args:
            selection_pos: Position index or name ("L", "R", "LB", "RB")
            on_or_off: Whether to show or hide the dot
        """

        if selection_pos not in (0, 1, 2, 3, "L", "R", "LB", "RB"):
            return
        
        if selection_pos == "L":
            selection_pos = 0
        elif selection_pos == "R":
            selection_pos = 1
        elif selection_pos == "LB":
            selection_pos = 2
        elif selection_pos == "RB":
            selection_pos = 3

        for i in range(4):
            _display.fill_rect(DOT_START_POSITIONS[i][0], DOT_START_POSITIONS[i][1], DOT_WIDTH, DOT_HEIGHT, 0)
            self.dot_states[i] = False

        self.dot_states[selection_pos] = on_or_off

        if on_or_off:
            _display.fill_rect(DOT_START_POSITIONS[selection_pos][0], DOT_START_POSITIONS[selection_pos][1], DOT_WIDTH, DOT_HEIGHT, 1)

        self._set_update_flag()

    def turn_off_all_dots(self):
        """
        Clears all dot indicators and side margins.
        """
        for i in range(4):
            _display.fill_rect(DOT_START_POSITIONS[i][0], DOT_START_POSITIONS[i][1], DOT_WIDTH, DOT_HEIGHT, 0)
            self.dot_states[i] = False

        _display.fill_rect(0, c.MIDDLE_Y_START, c.TEXT_PAD, c.MIDDLE_HEIGHT, 0)
        _display.fill_rect(c.SCREEN_W - c.TEXT_PAD, c.MIDDLE_Y_START, c.TEXT_PAD, c.MIDDLE_HEIGHT, 0)
        self._set_update_flag()

    def _display_line_bottom(self):
        """
        Draws the horizontal line at the bottom of the screen.
        """
        _display.fill_rect(0, c.BOTTOM_LINE_Y_START, c.SCREEN_W, 1, 1)
        self._set_update_flag()


    def show_text_bottom(self, text, value_only=False, start_x=-1, text_width_px=10):
        """
        Displays text in the bottom screen area.
        
        Args:
            text: Text to display
            value_only: Whether to update just a value field
            start_x: X-position for value display
            text_width_px: Width of characters in pixels
        """
        char_height = 8
        char_width = text_width_px
        bottom_y_start = 40

        if value_only and not isinstance(text, str):
            print("ERROR: must be string")
            return
        
        if value_only and start_x > 0:
            _display.fill_rect(start_x, bottom_y_start, char_width, char_height, c.BKG_COLOR)
            _display.text(text, start_x, bottom_y_start, c.TXT_COLOR)

        else:
            _display.fill_rect(0, bottom_y_start, c.SCREEN_W, char_height, c.BKG_COLOR)   
            _display.text(text, 0 + c.TEXT_PAD, bottom_y_start, c.TXT_COLOR)
                
        self._set_update_flag()

    def toggle_navmode_icon(self, on_or_off):
        """
        Shows or hides the navigation mode indicator.
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
        Shows or hides the encoder lock indicator.
        
        Args:
            on_or_off: Whether to show or hide the lock icon
            nav_mode_on: Whether navigation mode is active
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
        Updates the play mode indicator based on current mode.
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
        Shows a temporary notification message in the top bar.
        
        Args:
            msg: Notification text to display
            force_display: Whether to bypass rate limiting
        """

        if settings.performance_mode:
            return

        if not msg:
            return

        if ((time.monotonic() - self.notification_FPS_timer) > c.show_notification_METERING_THRESH) or force_display:
            self.notification_text = msg

            if self.notification_on_time > 0:
                self.previous_top_text = self.current_top_text

            self.current_top_text = msg
            self.show_text_top(msg, True)

            self.notification_on_time = time.monotonic()

            self.notification_FPS_timer = time.monotonic()

    def clear_notifications(self, replace_text=None):
        """
        Removes notifications after timeout period and restores normal text.
        
        Args:
            replace_text: Text to show after notification is cleared
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
        Displays the welcome screen with preset loading status.
        """
        _display.fill(0)
        self._display_line_bottom()
        self.show_text_top("DJBB MIDI LOOPSTER", notification=False)
        self.show_text_middle(f"Loading {settings.get_startup_preset()}...")
        _display.show()
        time.sleep(0.8)

display = Display()