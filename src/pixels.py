import time
import board
import neopixel
from settings import settings
import constants as c
from debug import print_debug

#all_pixels = neopixel.NeoPixel(board.GP9, 18, brightness=settings.led_pixel_brightness) # V1
all_pixels = neopixel.NeoPixel(board.GP15, 18, brightness=settings.led_pixel_brightness, auto_write = False) #V2

# -------------- Display Pixels Initialization ---------------
class DisplayPixels:
    """
    A class to manage the neopixels on the _display.
    """
    def __init__(self):
        """
        Initialize the DisplayPixels class.
        """
        self.pixels_need_update = True

        # Map pixels to buttons
        self.pixels_mapped = [13, 14, 15, 16,
                              9, 10, 11, 12,
                              5, 6, 7, 8,
                              1, 2, 3, 4, 0, 17]
        self.pixel_blink_timer = 0
        self.pixel_blink_states = [False] * 18
        self.pixel_status = [False] * 18
        self.pixels_blink_colors = [c.RED] * 18
        self.default_colors = [c.BLACK] * 18  # Usually black, unless feature is overriding
        self.dot_states = [False] * 4
        self.velocity_map_colors = []*16

    def set_note_on(self, pad_idx, velocity=120):
        """
        Turn on a pixel when a note is played.

        Args:
            pad_idx (int): Index of the pad to turn on.
        """
        color = self._scale_brightness(c.NOTE_COLOR, velocity / 127)
        all_pixels[self._get_pixel(pad_idx)] = color
        self._set_needs_update()
        print(f"setting pixel at pad idx {pad_idx} to color {color} ON")

    def set_note_off(self, pad_idx):
        """
        Turn off a pixel when a note is released.

        Args:
            pad_idx (int): Index of the pad to turn off.
        """
        self._set_needs_update()
        if settings.velocity_mapped is True:
            all_pixels[self._get_pixel(pad_idx)] = self._get_velocity_map_color(pad_idx)
        else:
            all_pixels[self._get_pixel(pad_idx)] = self.get_default_color(pad_idx)
        print(f"setting pixel at pad idx {pad_idx} to OFF")

    def set_fn_button_on(self, color=c.BLUE):
        """
        Turn on a pixel when the function button is pressed.
        """
        self._set_needs_update()
        all_pixels[0] = color

    def set_fn_button_off(self):
        """
        Turn off a pixel when the function button is released.
        """
        self._set_needs_update()
        all_pixels[0] = (0, 0, 0)

    def encoder_button_on(self, color=c.NAV_MODE_COLOR):
        """
        Turn on a pixel when the encoder button is pressed.
        """
        self._set_needs_update()
        all_pixels[17] = color

    def encoder_button_off(self):
        """
        Turn off a pixel when the encoder button is released.
        """
        self._set_needs_update()
        all_pixels[17] = (0, 0, 0)

    def set_blink(self, pad_idx, on_or_off=True, color=c.RED):
        """
        Sets the blink state of a pixel on or off.

        Args:
            pad_idx (int): The index of the pixel pad.
            on_or_off (bool, optional): The state to set the blink. Default is True.
            color (str, optional): The color to set for the blinking pixel. Default is RED.
        """

        self._set_needs_update()

        def _get_pixel_index(pad_idx):
            """Helper function to get the pixel index."""
            return self._get_pixel(pad_idx) if pad_idx < 16 else pad_idx

        pixel_idx = _get_pixel_index(pad_idx)

        if not on_or_off:
            self.pixel_blink_states[pad_idx] = False
            all_pixels[pixel_idx] = self.get_default_color(pad_idx)
            self._set_needs_update()  # Ensure the pixel state is updated
        else:
            self.pixel_blink_states[pad_idx] = True
            self.pixels_blink_colors[pad_idx] = color

    def set_color(self, pad_idx, color):
        """
        Sets the color of a specific pixel.

        Args:
            pad_idx (int): The index of the pad.
            color (str): The color to set for the pixel.
        """
        self._set_needs_update()
        all_pixels[self._get_pixel(pad_idx)] = color

    def process_blinks(self):
        """
        Blinks the all_pixels based on the current state of `self.pixel_blink_states`.

        This function toggles the status of the all_pixels that are set to blink. If a pixel is set to blink, its status
        will be toggled between ON and OFF. The status of the all_pixels is updated in the `pixel_status` list, and the
        corresponding LED colors are set accordingly in the `all_pixels` list. The blinking interval is determined by the
        `c.PIXEL_BLINK_TIME` constant.

        Returns:
            None
        """

        current_time = time.monotonic()
        if True in self.pixel_blink_states and current_time - self.pixel_blink_timer > c.PIXEL_BLINK_TIME:
            for i in range(18):
                if self.pixel_blink_states[i]:
                    self._set_needs_update()
                    self.pixel_status[i] = not self.pixel_status[i]
                    pixel_color = self.pixels_blink_colors[i] if self.pixel_status[i] else c.BLACK
                    all_pixels[self._get_pixel(i)] = pixel_color
            
            self.pixel_blink_timer = current_time

    def get_default_color(self, pad_idx):
        """
        Returns the default color for a given pad index.

        Parameters:
        pad_idx (int): The index of the pad.

        Returns:
        str: The default color for the pad.
        """
        return self.default_colors[pad_idx]

    def set_default_color(self, pad_idx, color=""):
        """
        Sets the default color for a specific pad.

        Parameters:
        pad_idx (int): The index of the pad.
        color (str): The color to set for the pad.
        """

        self._set_needs_update()
        if color != "":
            display_color = color

        elif settings.velocity_mapped is True:
            display_color = self._get_velocity_map_color(pad_idx)

        else:
            display_color = c.BLACK
        
        self.default_colors[pad_idx] = display_color
        print_debug(display_color)

    def clear_all(self):  # Turn off all pixels.
        """
        Set all pixels to black.
        """
        for i in range(18):
            all_pixels[i] = c.BLACK

    def update(self):
        """
        Update the neopixels based on their current state.
        """
        if self._get_needs_update():
            all_pixels.show()
            self._set_needs_update(False)

    def initialize_velocity_map(self):
        """
        Initialize the velocity map colors.
        """
        self._generate_velocity_map()

    # Internal helper methods
    def _get_needs_update(self):
        """
        Returns whether the pixels need to be updated.

        Returns:
            bool: True if the pixels need to be updated, False otherwise.
        """
        return self.pixels_need_update

    def _set_needs_update(self, yesOrNo=True):
        """
        Sets whether the pixels need to be updated.

        Args:
            yesOrNo (bool): True if the pixels need to be updated, False otherwise.
        """
        self.pixels_need_update = yesOrNo

    def _get_pixel(self, index):
        """
        Retrieves the pixel value at the specified index.

        Args:
            index (int): The index of the pixel to retrieve.

        Returns:
            int: The pixel value at the specified index.
        """
        return self.pixels_mapped[index]

    def _interpolate_color(self, color1, color2, factor):
        """
        Interpolates between two colors.

        Args:
            color1 (tuple): The starting color (R, G, B).
            color2 (tuple): The ending color (R, G, B).
            factor (float): The interpolation factor (0.0 to 1.0).

        Returns:
            tuple: The interpolated color (R, G, B).
        """
        return tuple(int(color1[i] + (color2[i] - color1[i]) * factor) for i in range(3))

    def _get_velocity_map_color(self, pad_idx):
        """
        Returns the color for a given pad index based on the velocity map.

        Args:
            pad_idx (int): The index of the pad to get the color for.

        Returns:
            tuple: The color (R, G, B) for the pad index.
        """
        return self.velocity_map_colors[pad_idx]

    def _generate_velocity_map(self, global_brightness_factor=0.5):
        """
        Generate a gradient from light green to orange on the neopixels with pad 0 being light green and pad 16 being orange,
        and also transitioning from very dim to bright. Sets the default color for the pixels.

        Args:
            global_brightness_factor (float): The global factor by which to scale brightness (0.0 to 1.0).
        """
        light_green = (0, 255, 0)
        orange = (255, 165, 0)

        for i in range(16):
            color_factor = i / 15  # Normalizing the index to a range of 0.0 to 1.0 for color interpolation
            brightness_factor = ((i + 1) / 16) * global_brightness_factor  # Normalizing the index to a range of 1/16 to 1.0, then applying global brightness factor

            interpolated_color = self._interpolate_color(light_green, orange, color_factor)
            final_color = self._scale_brightness(interpolated_color, brightness_factor)
            self.velocity_map_colors.append(final_color)

    def display_velocity_map(self, on_or_off=True):
        """
        Display a gradient from light green to orange on the neopixels with pad 0 being light green and pad 16 being orange,
        and also transitioning from very dim to bright. Sets the default color for the pixels.

        Args:
            on_or_off (bool): Whether to turn the gradient on or off.
        """
        self._set_needs_update()
        if on_or_off:
            for i in range(16):
                color = self.velocity_map_colors[i]
                self.set_default_color(i, color)
                all_pixels[self._get_pixel(i)] = color
        else:
            for i in range(16):
                self.set_default_color(i, c.BLACK)
                all_pixels[self._get_pixel(i)] = c.BLACK

    def _scale_brightness(self, color, brightness_factor):
        """
        Scales the brightness of a color.

        Args:
            color (tuple): The color (R, G, B) to scale brightness for.
            brightness_factor (float): The factor by which to scale brightness (0.0 to 1.0).

        Returns:
            tuple: The color (R, G, B) with scaled brightness.
        """
        return tuple(int(c * brightness_factor) for c in color)

    def _scale_brightness_by_velocity(self, pad_idx, velocity):
        """
        Scales the brightness of the default color for a pad index based on the MIDI velocity value.

        Args:
            pad_idx (int): The index of the pad to scale the brightness for.
            velocity (int): The MIDI velocity value (0 to 127).
        """
        brightness_factor = velocity / 127              # Calculate the brightness factor based on the MIDI velocity
        default_color = self.get_default_color(pad_idx) # Get the current default color for the pad
        dimmed_color = self._scale_brightness(default_color, brightness_factor) # Scale the default color's brightness
        self.set_default_color(pad_idx, dimmed_color) # Set the dimmed color as the new default color for the pad
        all_pixels[self._get_pixel(pad_idx)] = dimmed_color   # Update the actual pixel color


pixels  = DisplayPixels() # Create an instance of the DisplayPixels class