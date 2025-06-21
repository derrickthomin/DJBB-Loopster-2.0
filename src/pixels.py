import time
import board
import neopixel
from settings import settings
import constants as C
import useraddons

all_pixels = neopixel.NeoPixel(board.GP15, 18, brightness=settings.led_brightness, auto_write = False)

# -------------- Memory-optimized Display Pixels ---------------
class DisplayPixels:
    """
    A memory-optimized class to manage the neopixels on the display.
    """
    def __init__(self):
        """
        Initialize the DisplayPixels class with minimal memory usage.
        """

        self.pixels_need_update = True
        self.pixel_blink_timer = 0
        
        self.pad_to_pixel_index_map = C.PAD_TO_PIXEL_IDX_MAP
        self.pixel_states = bytearray(18) # bit 0: blink state     bit 1: pixel status
        self.flashing_pixels = {}
        self.default_colors = {}
        self.blink_colors = {}
        self._velocity_map_initialized = False
        self.velocity_map_colors = []

    def set_note_on(self, pad_idx, velocity=120):
        """
        Turn on a pixel when a note is played.
        """
        color = self._scale_brightness(C.NOTE_COLOR, velocity / 127)
        all_pixels[self._get_pixel(pad_idx)] = color
        self.set_needs_update()

    def set_note_off(self, pad_idx):
        """
        Turn off a pixel when a note is released.
        """
        self.set_needs_update()
        if settings.velocity_mapped is True:
            if not self._velocity_map_initialized:
                self._initialize_velocity_map()
            all_pixels[self._get_pixel(pad_idx)] = self._get_velocity_map_color(pad_idx)
        else:
            all_pixels[self._get_pixel(pad_idx)] = self.get_default_color(pad_idx)

    def set_fn_button_on(self, color=C.BLUE):
        """Turn on function button pixel"""
        self.set_needs_update()
        all_pixels[0] = color

    def set_fn_button_off(self):
        """Turn off function button pixel"""
        self.set_needs_update()
        all_pixels[0] = (0, 0, 0)

    def encoder_button_on(self, color=C.NAV_MODE_COLOR):
        """Turn on encoder button pixel"""
        self.set_needs_update()
        all_pixels[17] = color

    def encoder_button_off(self):
        """Turn off encoder button pixel"""
        self.set_needs_update()
        all_pixels[17] = (0, 0, 0)

    def set_blink(self, pad_idx, on_or_off=True, color=C.RED):
        """
        Set a pixel to blink with memory-optimized storage
        """
        self.set_needs_update()
        pixel_idx = self._get_pixel(pad_idx) if pad_idx < 17 else pad_idx

        if not on_or_off:
            # Clear blink state
            self.pixel_states[pad_idx] &= ~0x01  # Clear bit 0
            all_pixels[pixel_idx] = self.get_default_color(pad_idx)
            if pad_idx in self.blink_colors:
                del self.blink_colors[pad_idx]  
        else:
            # Set blink state and store color only if blinking
            self.pixel_states[pad_idx] |= 0x01  # Set bit 0
            self.blink_colors[pad_idx] = color

    def set_color(self, pad_idx, color):
        """
        Sets the color of a specific pixel.
        """
        self.set_needs_update()
        all_pixels[self._get_pixel(pad_idx)] = color

    def process_blinks(self, force_update=False, blink_time=C.PIXEL_BLINK_TIME):
        """
        Process blinking pixels with memory optimization
        """
        current_time = time.monotonic()
        
        # Check if any pixel is blinking before processing
        has_blinking = False
        for i in range(18):
            if self.pixel_states[i] & 0x01:  # Check bit 0 (blink state)
                has_blinking = True
                break
                
        if has_blinking and current_time - self.pixel_blink_timer > blink_time:
            for i in range(18):
                if self.pixel_states[i] & 0x01:  # Check bit 0 (blink state)
                    self.set_needs_update()
                    # Toggle bit 1 (pixel status)
                    self.pixel_states[i] ^= 0x02
                    
                    pixel_color = self.blink_colors.get(i, C.RED) if (self.pixel_states[i] & 0x02) else C.BLACK
                    all_pixels[self._get_pixel(i)] = pixel_color

            if force_update:
                self.update()
            
            self.pixel_blink_timer = current_time

    def get_default_color(self, pad_idx):
        """
        Returns the default color for a pad with memory optimization
        """
        return self.default_colors.get(pad_idx, C.BLACK)

    def set_default_color(self, pad_idx, color=""):
        """
        Sets the default color for a pad
        """
        self.set_needs_update()
        
        if color:
            display_color = color
        elif settings.velocity_mapped:
            if not self._velocity_map_initialized:
                self._initialize_velocity_map()
            display_color = self._get_velocity_map_color(pad_idx)
        else:
            display_color = C.BLACK
        
        # Only store non-BLACK colors to save memory
        if display_color == C.BLACK:
            if pad_idx in self.default_colors:
                del self.default_colors[pad_idx]
        else:
            self.default_colors[pad_idx] = display_color

    def clear_all(self):
        """
        Set all pixels to black and free memory
        """
        for i in range(18):
            all_pixels[i] = C.BLACK
        self.default_colors.clear()
        self.blink_colors.clear()
        self.flashing_pixels.clear()
        self.pixel_states = bytearray(18)
        self.set_needs_update()

    def flash_pixel(self, pad_idx, duration, color=C.WHITE):
        """
        Flash a pixel once for a specified duration
        """
        self.flashing_pixels[pad_idx] = (time.monotonic(), duration)
        self.set_color(pad_idx, color)
        self.set_needs_update()

    def update(self):
        """
        Update pixels with memory optimization
        """
        # Process flashing pixels
        current_time = time.monotonic()
        to_remove = []
        
        for pad_idx, (start_time, duration) in self.flashing_pixels.items():
            if current_time - start_time >= duration:
                self.set_color(pad_idx, self.get_default_color(pad_idx))
                to_remove.append(pad_idx)
        
        # Remove finished flashes
        for pad_idx in to_remove:
            del self.flashing_pixels[pad_idx]
        
        # Update pixels if needed
        if self.get_update_pending_flag():
            all_pixels.show()
            self.set_needs_update(False)

    def _initialize_velocity_map(self, global_brightness_factor=0.5):
        """
        Initialize velocity map colors lazily to save memory during startup
        """
        if self._velocity_map_initialized:
            return
            
        orange = (255, 165, 0)
        red = (255, 0, 0)
        self.velocity_map_colors = []
        
        for i in range(C.NUM_PADS):
            color_factor = i / 15
            brightness_factor = ((i + 1) / 16) * global_brightness_factor
            
            interpolated_color = self._interpolate_color(orange, red, color_factor)
            final_color = self._scale_brightness(interpolated_color, brightness_factor)
            self.velocity_map_colors.append(final_color)
            
        self._velocity_map_initialized = True

    def display_velocity_map(self, on_or_off=True):
        """
        Display velocity map with memory optimization
        """
        self.set_needs_update()
        
        if on_or_off:
            if not self._velocity_map_initialized:
                self._initialize_velocity_map()
                
            for i in range(C.NUM_PADS):
                color = self.velocity_map_colors[i]
                self.set_default_color(i, color)
                all_pixels[self._get_pixel(i)] = color
        else:
            for i in range(C.NUM_PADS):
                self.set_default_color(i, C.BLACK)
                all_pixels[self._get_pixel(i)] = C.BLACK

    def get_update_pending_flag(self):
        """Get pixel update flag"""
        return self.pixels_need_update

    def set_needs_update(self, yesOrNo=True):
        """Set pixel update flag"""
        self.pixels_need_update = yesOrNo

    def _get_pixel(self, index):
        """Get mapped pixel index"""
        return self.pad_to_pixel_index_map[index]

    def _interpolate_color(self, color1, color2, factor):
        """Interpolate between two colors"""
        return tuple(int(color1[i] + (color2[i] - color1[i]) * factor) for i in range(3))

    def _get_velocity_map_color(self, pad_idx):
        """Get velocity map color with lazy initialization"""
        if not self._velocity_map_initialized:
            self._initialize_velocity_map()
        return self.velocity_map_colors[pad_idx]

    def _scale_brightness(self, color, brightness_factor):
        """Scale color brightness efficiently"""
        return tuple(int(c * brightness_factor) for c in color)

    def indicate_preset_loading(self, is_loading=True):
        """
        Indicate preset loading/saving state on FN and encoder buttons.
        
        Args:
            is_loading (bool): True for loading state, False for completion
        """
        if is_loading:
            # Start fast blinking on both FN and encoder buttons during loading
            self.set_blink(16, True, C.YELLOW)  # FN button (index 16 maps to pixel 0)
            self.set_blink(17, True, C.YELLOW)  # Encoder button (index 17 maps to pixel 17)
        else:
            # Stop blinking and do completion flash
            self.set_blink(16, False)  # Stop FN button blink
            self.set_blink(17, False)  # Stop encoder button blink
            self.flash_pixel(16, 0.8, C.GREEN)  # Longer green flash for FN button
            self.flash_pixel(17, 0.8, C.GREEN)  # Longer green flash for encoder button

pixels = DisplayPixels()