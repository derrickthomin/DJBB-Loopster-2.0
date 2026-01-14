import time
import busio
from settings import settings
import constants as C
import adafruit_ssd1306
from pixels import pixels

# Display Setup
i2c = busio.I2C(C.SCL, C.SDA, frequency=400_000)
_display = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)
DOT_START_POSITIONS = [(0, 25), (0, 42), (120, 42), (125, 25)]
DOT_WIDTH = 3
DOT_HEIGHT = 3

# Page indicator settings (for settings menus)
# Aligned with middle text line 3 (same as scale screen numbers)
PAGE_INDICATOR_X = C.TEXT_PAD                               # = 7
PAGE_INDICATOR_Y = C.MIDDLE_Y_START + (2 * C.LINEHEIGHT)   # = 40

class DisplayManager():
    """Display update state manager."""
    def __init__(self):
        self.display_needs_update = True

    def check_show_display(self):
        _display.show()
        self.display_needs_update = False

display_manager = DisplayManager()

class Display:
    """OLED display content and UI manager."""

    def __init__(self):
        self.dot_states = [False] * 4           # State tracking for the 4 dot indicators
        self.notification_text = None           # Current notification text
        self.notification_on_time = 0           # Timestamp when notification appeared
        self.current_top_text = None            # Current text in top display area
        self.notification_FPS_timer = 0         # Rate limiter for notification updates

    def _set_update_flag(self, yesOrNo=True, immediate=False):
        """Mark display for update, or refresh immediately if immediate=True."""
        
        if immediate:
            _display.show()
            return
        display_manager.display_needs_update = yesOrNo
        
    def show_text_top(self, text, notification=False, force_refresh=False):
        """Display text in top area. notification=True adds underline."""
        _display.fill_rect(0, 0, C.SCREEN_W, C.TOP_HEIGHT, C.BKG_COLOR)

        if notification:
            linepad_x = 0
            _display.fill_rect(0 + linepad_x, C.TOP_HEIGHT - 1, C.SCREEN_W - (2 * linepad_x), 1, 1) 

        _display.text(text, 0 + C.PADDING, 0 + C.PADDING, C.TXT_COLOR)  
        self._set_update_flag(immediate=force_refresh)

    def show_text_middle(self, text, value_only=False, value_start_x=-1, clear_width=None):
        char_height = 8
        char_width = 6

        if value_only and isinstance(text, list):
            return

        if not isinstance(text, list):
            text = [text]
        
        if value_only and value_start_x > 0:
            # Clear width: use provided width, or calculate from text length, minimum 1 char
            width = clear_width if clear_width else max(char_width, len(text[0]) * char_width)
            _display.fill_rect(value_start_x, C.MIDDLE_Y_START, width, char_height, C.BKG_COLOR)
            _display.text(text[0], value_start_x, C.MIDDLE_Y_START, C.TXT_COLOR)

        else:
            _display.fill_rect(C.TEXT_PAD, C.MIDDLE_Y_START, 116, C.MIDDLE_HEIGHT, C.BKG_COLOR)
            if len(text) > 0:
                line_num = 0
                for text_line in text:
                    _display.text(text_line, C.TEXT_PAD, C.MIDDLE_Y_START + (line_num * C.LINEHEIGHT), C.TXT_COLOR)
                    line_num += 1

        self._set_update_flag()

    def show_page_indicator(self, current, total):
        """Show page indicator like ' 1/13' below settings text."""
        # Format: right-align numerator in 2-char space
        text = f"{current:2}/{total}"
        
        # Clear the indicator area (enough for "XX/XX" = 5 chars * 6px = 30px)
        _display.fill_rect(PAGE_INDICATOR_X, PAGE_INDICATOR_Y, 30, 8, C.BKG_COLOR)
        _display.text(text, PAGE_INDICATOR_X, PAGE_INDICATOR_Y, C.TXT_COLOR)
        self._set_update_flag()

    def display_left_dot(self, on_or_off=True):
        self.display_dot(0, on_or_off)

    def display_right_dot(self, on_or_off=True):
        self.display_dot(3, on_or_off)

    def display_dot(self, selection_pos=0, on_or_off=True):
        """Show/hide dot indicator at position (0-3 or 'L','R','LB','RB')."""

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

        # Early exit if state hasn't changed - avoids expensive I2C display updates
        if self.dot_states[selection_pos] == on_or_off:
            return

        for i in range(4):
            _display.fill_rect(DOT_START_POSITIONS[i][0], DOT_START_POSITIONS[i][1], DOT_WIDTH, DOT_HEIGHT, 0)
            self.dot_states[i] = False

        self.dot_states[selection_pos] = on_or_off

        if on_or_off:
            _display.fill_rect(DOT_START_POSITIONS[selection_pos][0], DOT_START_POSITIONS[selection_pos][1], DOT_WIDTH, DOT_HEIGHT, 1)

        self._set_update_flag()

    def turn_off_all_dots(self):
        for i in range(4):
            _display.fill_rect(DOT_START_POSITIONS[i][0], DOT_START_POSITIONS[i][1], DOT_WIDTH, DOT_HEIGHT, 0)
            self.dot_states[i] = False

        _display.fill_rect(0, C.MIDDLE_Y_START, C.TEXT_PAD, C.MIDDLE_HEIGHT, 0)
        _display.fill_rect(C.SCREEN_W - C.TEXT_PAD, C.MIDDLE_Y_START, C.TEXT_PAD, C.MIDDLE_HEIGHT, 0)
        self._set_update_flag()

    def _display_line_bottom(self):
        _display.fill_rect(0, C.BOTTOM_LINE_Y_START, C.SCREEN_W, 1, 1)
        self._set_update_flag()


    def show_text_bottom(self, text, value_only=False, start_x=-1, text_width_px=10):
        char_height = 8
        char_width = text_width_px
        bottom_y_start = 40

        if value_only and not isinstance(text, str):
            return
        
        if value_only and start_x > 0:
            _display.fill_rect(start_x, bottom_y_start, char_width, char_height, C.BKG_COLOR)
            _display.text(text, start_x, bottom_y_start, C.TXT_COLOR)

        else:
            _display.fill_rect(0, bottom_y_start, C.SCREEN_W, char_height, C.BKG_COLOR)   
            _display.text(text, 0 + C.TEXT_PAD, bottom_y_start, C.TXT_COLOR)
                
        self._set_update_flag()

    def toggle_navmode_icon(self, on_or_off):
        if on_or_off is True:
            _display.fill_rect(C.NAV_ICON_X_START, C.SCREEN_H - C.LINEHEIGHT - 2, C.NAV_MSG_WIDTH, 10, 1)
            _display.text(C.NAV_MODE_TXT, C.NAV_ICON_X_START + 4, C.SCREEN_H - C.LINEHEIGHT, 0)
            self._set_update_flag()
            pixels.encoder_button_on()

        elif on_or_off is False:
            _display.fill_rect(C.NAV_ICON_X_START, C.SCREEN_H - C.LINEHEIGHT - 2, C.NAV_MSG_WIDTH, 10, 0)
            self._set_update_flag()
            pixels.encoder_button_off()

    def toggle_lock_icon(self, on_or_off, nav_mode_on=False):
        if on_or_off is True:
            _display.fill_rect(C.NAV_ICON_X_START, C.SCREEN_H - C.LINEHEIGHT - 2, C.NAV_MSG_WIDTH, 10, 1)
            _display.text(C.ENCODER_LOCK_TXT, C.NAV_ICON_X_START + 4, C.SCREEN_H - C.LINEHEIGHT, 0)
            self._set_update_flag()
            pixels.encoder_button_on(C.ENCODER_LOCK_COLOR)

        elif on_or_off is False:
            _display.fill_rect(C.NAV_ICON_X_START, C.SCREEN_H - C.LINEHEIGHT - 2, C.NAV_MSG_WIDTH, 10, 0)
            self._set_update_flag()
            if nav_mode_on:
                pixels.encoder_button_on(C.NAV_MODE_COLOR)
                self.toggle_navmode_icon(True)
            else:
                pixels.encoder_button_off()

    def update_playmode_icon(self, playmode=None):
        if settings.performance_mode:
            return
        
        y = C.SCREEN_H - 8
        display_text = ""

        if playmode is None:
            playmode = settings.play_mode

        _display.fill_rect(C.PLAYMODE_ICON_X_START, y, 36, 25, 0)
        if playmode == "loop":
            display_text = C.LOOP_MODE_ICON
        elif playmode == "velocity":
            display_text = C.VEL_MODE_ICON
        elif playmode == "encoder":
            display_text = C.ENC_MODE_ICON

        _display.text(display_text, C.PLAYMODE_ICON_X_START, y, 1)
        self._set_update_flag()
        
    def show_notification(self, msg=None, force_display=False):
        """Show temporary notification in top bar."""
        if settings.performance_mode:
            return

        if not msg:
            return
        
        time_now = time.monotonic()

        if ((time_now - self.notification_FPS_timer) > C.NOTIFICATION_METERING_THRESH) or force_display:
            self.notification_text = msg
            self.current_top_text = msg
            self.show_text_top(msg, True, force_refresh=force_display)
            self.notification_on_time = time_now
            self.notification_FPS_timer = time_now

    def clear_notifications(self, replace_text=None):
        """Clear notification after timeout and restore replace_text."""
        if self.notification_text is None or replace_text is None:
            return

        if self.notification_text == replace_text:
            return

        if time.monotonic() - self.notification_on_time > C.NOTIFICATION_THRESH_S:
            self.notification_on_time = -1
            self.notification_text = None
            self.show_text_top(replace_text)

    def show_startup_screen(self):
        """Display welcome screen with preset loading status."""
        _display.fill(0)
        self._display_line_bottom()
        self.show_text_top("DJBB MIDI LOOPSTER", notification=False)
        self.show_text_middle(f"Loading {settings.get_startup_preset()}...")
        _display.show()
        time.sleep(0.8)

display = Display()