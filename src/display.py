import time
import board
import busio
import neopixel
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


# # -------------- Display Pixels Initialization ---------------
# class DisplayPixels:
#     """
#     A class to manage the neopixels on the _display.
#     """
#     def __init__(self):
#         """
#         Initialize the DisplayPixels class.
#         """
#         self.pixels_need_update = True

#         # Map pixels to buttons
#         self.pixels_mapped = [13, 14, 15, 16,
#                               9, 10, 11, 12,
#                               5, 6, 7, 8,
#                               1, 2, 3, 4, 0, 17]
#         self.pixel_blink_timer = 0
#         self.pixel_blink_states = [False] * 18
#         self.pixel_status = [False] * 18
#         self.pixels_blink_colors = [c.RED] * 18
#         self.default_colors = [c.BLACK] * 18  # Usually black, unless feature is overriding
#         self.dot_states = [False] * 4
#         self.velocity_map_colors = []*16

#     def set_note_on(self, pad_idx, velocity=120):
#         """
#         Turn on a pixel when a note is played.

#         Args:
#             pad_idx (int): Index of the pad to turn on.
#         """
#         color = self._scale_brightness(c.NOTE_COLOR, velocity / 127)
#         all_pixels[self._get_pixel(pad_idx)] = color
#         self._set_needs_update()
#         print(f"setting pixel at pad idx {pad_idx} to color {color} ON")

#     def set_note_off(self, pad_idx):
#         """
#         Turn off a pixel when a note is released.

#         Args:
#             pad_idx (int): Index of the pad to turn off.
#         """
#         self._set_needs_update()
#         if global_states.velocity_mapped is True:
#             all_pixels[self._get_pixel(pad_idx)] = self._get_velocity_map_color(pad_idx)
#         else:
#             all_pixels[self._get_pixel(pad_idx)] = self.get_default_color(pad_idx)
#         print(f"setting pixel at pad idx {pad_idx} to OFF")

#     def set_fn_button_on(self, color=c.BLUE):
#         """
#         Turn on a pixel when the function button is pressed.
#         """
#         self._set_needs_update()
#         all_pixels[0] = color

#     def set_fn_button_off(self):
#         """
#         Turn off a pixel when the function button is released.
#         """
#         self._set_needs_update()
#         all_pixels[0] = (0, 0, 0)

#     def encoder_button_on(self, color=c.NAV_MODE_COLOR):
#         """
#         Turn on a pixel when the encoder button is pressed.
#         """
#         self._set_needs_update()
#         all_pixels[17] = color

#     def encoder_button_off(self):
#         """
#         Turn off a pixel when the encoder button is released.
#         """
#         self._set_needs_update()
#         all_pixels[17] = (0, 0, 0)

#     def set_blink(self, pad_idx, on_or_off=True, color=c.RED):
#         """
#         Sets the blink state of a pixel on or off.

#         Args:
#             pad_idx (int): The index of the pixel pad.
#             on_or_off (bool, optional): The state to set the blink. Default is True.
#             color (str, optional): The color to set for the blinking pixel. Default is RED.
#         """

#         self._set_needs_update()

#         def _get_pixel_index(pad_idx):
#             """Helper function to get the pixel index."""
#             return self._get_pixel(pad_idx) if pad_idx < 16 else pad_idx

#         pixel_idx = _get_pixel_index(pad_idx)

#         if not on_or_off:
#             self.pixel_blink_states[pad_idx] = False
#             all_pixels[pixel_idx] = self.get_default_color(pad_idx)
#             self._set_needs_update()  # Ensure the pixel state is updated
#         else:
#             self.pixel_blink_states[pad_idx] = True
#             self.pixels_blink_colors[pad_idx] = color

#     def set_color(self, pad_idx, color):
#         """
#         Sets the color of a specific pixel.

#         Args:
#             pad_idx (int): The index of the pad.
#             color (str): The color to set for the pixel.
#         """
#         self._set_needs_update()
#         all_pixels[self._get_pixel(pad_idx)] = color

#     def process_blinks(self):
#         """
#         Blinks the all_pixels based on the current state of `self.pixel_blink_states`.

#         This function toggles the status of the all_pixels that are set to blink. If a pixel is set to blink, its status
#         will be toggled between ON and OFF. The status of the all_pixels is updated in the `pixel_status` list, and the
#         corresponding LED colors are set accordingly in the `all_pixels` list. The blinking interval is determined by the
#         `c.PIXEL_BLINK_TIME` constant.

#         Returns:
#             None
#         """

#         current_time = time.monotonic()
#         if True in self.pixel_blink_states and current_time - self.pixel_blink_timer > c.PIXEL_BLINK_TIME:
#             for i in range(18):
#                 if self.pixel_blink_states[i]:
#                     self._set_needs_update()
#                     self.pixel_status[i] = not self.pixel_status[i]
#                     pixel_color = self.pixels_blink_colors[i] if self.pixel_status[i] else c.BLACK
#                     all_pixels[self._get_pixel(i)] = pixel_color
            
#             self.pixel_blink_timer = current_time

#     def get_default_color(self, pad_idx):
#         """
#         Returns the default color for a given pad index.

#         Parameters:
#         pad_idx (int): The index of the pad.

#         Returns:
#         str: The default color for the pad.
#         """
#         return self.default_colors[pad_idx]

#     def set_default_color(self, pad_idx, color=""):
#         """
#         Sets the default color for a specific pad.

#         Parameters:
#         pad_idx (int): The index of the pad.
#         color (str): The color to set for the pad.
#         """

#         self._set_needs_update()
#         if color != "":
#             display_color = color

#         elif global_states.velocity_mapped is True:
#             display_color = self._get_velocity_map_color(pad_idx)

#         else:
#             display_color = c.BLACK
        
#         self.default_colors[pad_idx] = display_color
#         print_debug(display_color)

#     def clear_all(self):  # Turn off all pixels.
#         """
#         Set all pixels to black.
#         """
#         for i in range(18):
#             all_pixels[i] = c.BLACK

#     def update(self):
#         """
#         Update the neopixels based on their current state.
#         """
#         if self._get_needs_update():
#             all_pixels.show()
#             self._set_needs_update(False)

#     def initialize_velocity_map(self):
#         """
#         Initialize the velocity map colors.
#         """
#         self._generate_velocity_map()

#     # Internal helper methods
#     def _get_needs_update(self):
#         """
#         Returns whether the pixels need to be updated.

#         Returns:
#             bool: True if the pixels need to be updated, False otherwise.
#         """
#         return self.pixels_need_update

#     def _set_needs_update(self, yesOrNo=True):
#         """
#         Sets whether the pixels need to be updated.

#         Args:
#             yesOrNo (bool): True if the pixels need to be updated, False otherwise.
#         """
#         self.pixels_need_update = yesOrNo

#     def _get_pixel(self, index):
#         """
#         Retrieves the pixel value at the specified index.

#         Args:
#             index (int): The index of the pixel to retrieve.

#         Returns:
#             int: The pixel value at the specified index.
#         """
#         return self.pixels_mapped[index]

#     def _interpolate_color(self, color1, color2, factor):
#         """
#         Interpolates between two colors.

#         Args:
#             color1 (tuple): The starting color (R, G, B).
#             color2 (tuple): The ending color (R, G, B).
#             factor (float): The interpolation factor (0.0 to 1.0).

#         Returns:
#             tuple: The interpolated color (R, G, B).
#         """
#         return tuple(int(color1[i] + (color2[i] - color1[i]) * factor) for i in range(3))

#     def _get_velocity_map_color(self, pad_idx):
#         """
#         Returns the color for a given pad index based on the velocity map.

#         Args:
#             pad_idx (int): The index of the pad to get the color for.

#         Returns:
#             tuple: The color (R, G, B) for the pad index.
#         """
#         return self.velocity_map_colors[pad_idx]

#     def _generate_velocity_map(self, global_brightness_factor=0.5):
#         """
#         Generate a gradient from light green to orange on the neopixels with pad 0 being light green and pad 16 being orange,
#         and also transitioning from very dim to bright. Sets the default color for the pixels.

#         Args:
#             global_brightness_factor (float): The global factor by which to scale brightness (0.0 to 1.0).
#         """
#         light_green = (0, 255, 0)
#         orange = (255, 165, 0)

#         for i in range(16):
#             color_factor = i / 15  # Normalizing the index to a range of 0.0 to 1.0 for color interpolation
#             brightness_factor = ((i + 1) / 16) * global_brightness_factor  # Normalizing the index to a range of 1/16 to 1.0, then applying global brightness factor

#             interpolated_color = self._interpolate_color(light_green, orange, color_factor)
#             final_color = self._scale_brightness(interpolated_color, brightness_factor)
#             self.velocity_map_colors.append(final_color)

#     def display_velocity_map(self, on_or_off=True):
#         """
#         Display a gradient from light green to orange on the neopixels with pad 0 being light green and pad 16 being orange,
#         and also transitioning from very dim to bright. Sets the default color for the pixels.

#         Args:
#             on_or_off (bool): Whether to turn the gradient on or off.
#         """
#         self._set_needs_update()
#         if on_or_off:
#             for i in range(16):
#                 color = self.velocity_map_colors[i]
#                 self.set_default_color(i, color)
#                 all_pixels[self._get_pixel(i)] = color
#         else:
#             for i in range(16):
#                 self.set_default_color(i, c.BLACK)
#                 all_pixels[self._get_pixel(i)] = c.BLACK

#     def _scale_brightness(self, color, brightness_factor):
#         """
#         Scales the brightness of a color.

#         Args:
#             color (tuple): The color (R, G, B) to scale brightness for.
#             brightness_factor (float): The factor by which to scale brightness (0.0 to 1.0).

#         Returns:
#             tuple: The color (R, G, B) with scaled brightness.
#         """
#         return tuple(int(c * brightness_factor) for c in color)

#     def _scale_brightness_by_velocity(self, pad_idx, velocity):
#         """
#         Scales the brightness of the default color for a pad index based on the MIDI velocity value.

#         Args:
#             pad_idx (int): The index of the pad to scale the brightness for.
#             velocity (int): The MIDI velocity value (0 to 127).
#         """
#         brightness_factor = velocity / 127              # Calculate the brightness factor based on the MIDI velocity
#         default_color = self.get_default_color(pad_idx) # Get the current default color for the pad
#         dimmed_color = self._scale_brightness(default_color, brightness_factor) # Scale the default color's brightness
#         self.set_default_color(pad_idx, dimmed_color) # Set the dimmed color as the new default color for the pad
#         all_pixels[self._get_pixel(pad_idx)] = dimmed_color   # Update the actual pixel color


# pixels  = DisplayPixels() # Create an instance of the DisplayPixels class

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
        display_manager.display_needs_update = yesOrNo
        if immediate:
            _display.show()
        
    def show_text_top(self, text, notification=False):
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
        self._set_update_flag()

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
        
    def show_notification(self, msg=None):
        """
        Display a temporary notification banner at the top of the screen.

        Args:
            msg (str): Notification message to _display.
        """

        if settings.performance_mode:
            return

        if not msg:
            return

        if (time.monotonic() - self.show_notification_FPS_timer) > c.show_notification_METERING_THRESH:
            self.notification_text = msg

            if self.notification_on_time > 0:
                self.previous_top_text = self.current_top_text

            self.current_top_text = msg
            self.show_text_top(msg, True)

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
