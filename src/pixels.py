import time
import board
import neopixel
from settings import settings
import constants as C
from pedals import pedals

all_pixels = neopixel.NeoPixel(board.GP15, C.NUM_PIXELS, brightness=settings.led_brightness, auto_write = False)

# -------------- Display Pixels ---------------
class DisplayPixels:
    """Neopixel manager with blink, flash, and velocity mapping."""
    def __init__(self):
        self.pixels_need_update = True
        self.pixel_blink_timer = 0
        self.blink_phase = False  # Global on/off phase for all blinks (ensures sync)
        
        self.pad_to_pixel_index_map = C.PAD_TO_PIXEL_IDX_MAP
        self.pixel_states = bytearray(C.NUM_PIXELS) # bit 0: blink state
        self.flashing_pixels = {}
        self.default_colors = {}
        self.blink_colors = {}
        self._velocity_map_initialized = False
        self.velocity_map_colors = []
        
        # Dynamic refresh rate - scales back during heavy load
        self.update_interval_ms = C.PIXEL_UPDATE_INTERVAL_MS  # Base rate (ms)
        self._consecutive_busy = 0

    def set_note_on(self, pad_idx, velocity=120):
        color = self._scale_brightness(C.NOTE_COLOR, velocity / 127)
        all_pixels[self._get_pixel(pad_idx)] = color
        if C.USING_FOOT_PEDALS:
            pedals.set_pixel_on(pad_idx, color)
        self.set_needs_update()

    def set_note_off(self, pad_idx):
        self.set_needs_update()
        if settings.velocity_mapped is True:
            if not self._velocity_map_initialized:
                self._initialize_velocity_map()
            color = self._get_velocity_map_color(pad_idx)
            all_pixels[self._get_pixel(pad_idx)] = color
        else:
            color = self.get_default_color(pad_idx)
            all_pixels[self._get_pixel(pad_idx)] = color
        if C.USING_FOOT_PEDALS:
            pedals.set_pixel_on(pad_idx, color)

    def set_fn_button_on(self, color=C.BLUE):
        if all_pixels[0] != color:
            all_pixels[0] = color
            self.set_needs_update()

    def set_fn_button_off(self):
        if all_pixels[0] != (0, 0, 0):
            all_pixels[0] = (0, 0, 0)
            self.set_needs_update()

    def encoder_button_on(self, color=C.NAV_MODE_COLOR):
        if all_pixels[C.ENC_LED_IDX] != color:
            all_pixels[C.ENC_LED_IDX] = color
            self.set_needs_update()

    def encoder_button_off(self):
        if all_pixels[C.ENC_LED_IDX] != (0, 0, 0):
            all_pixels[C.ENC_LED_IDX] = (0, 0, 0)
            self.set_needs_update()

    def set_blink(self, pad_idx, on_or_off=True, color=C.RED):
        self.set_needs_update()
        pixel_idx = self._get_pixel(pad_idx) if pad_idx < C.ENC_LED_IDX else pad_idx

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
            # Immediately sync to current global phase so all blinks are in sync
            all_pixels[pixel_idx] = color if self.blink_phase else C.BLACK

    def set_color(self, pad_idx, color):
        self.set_needs_update()
        all_pixels[self._get_pixel(pad_idx)] = color
        if C.USING_FOOT_PEDALS:
            pedals.set_pixel_on(pad_idx, color)

    def process_blinks(self, force_update=False, blink_time=C.PIXEL_BLINK_TIME):
        current_time = time.monotonic()
        
        # Check if any pixel is blinking before processing
        has_blinking = False
        for i in range(C.NUM_PIXELS):
            if self.pixel_states[i] & 0x01:  # Check bit 0 (blink state)
                has_blinking = True
                break
                
        if has_blinking and current_time - self.pixel_blink_timer > blink_time:
            # Toggle global blink phase (all blinking pixels stay in sync)
            self.blink_phase = not self.blink_phase
            
            for i in range(C.NUM_PIXELS):
                if self.pixel_states[i] & 0x01:  # Check bit 0 (blink state)
                    self.set_needs_update()
                    # Use global phase for all blinking pixels
                    pixel_color = self.blink_colors.get(i, C.RED) if self.blink_phase else C.BLACK
                    all_pixels[self._get_pixel(i)] = pixel_color
                    if C.USING_FOOT_PEDALS:
                        pedals.set_pixel_on(i, pixel_color)

            if force_update:
                self.update()
            
            self.pixel_blink_timer = current_time

    def get_default_color(self, pad_idx):
        return self.default_colors.get(pad_idx, C.BLACK)

    def set_default_color(self, pad_idx, color=""):
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
        for i in range(C.NUM_PIXELS):
            all_pixels[i] = C.BLACK
            if C.USING_FOOT_PEDALS:
                pedals.set_pixel_on(i, C.BLACK)
        self.default_colors.clear()
        self.blink_colors.clear()
        self.flashing_pixels.clear()
        self.pixel_states = bytearray(C.NUM_PIXELS)
        self.set_needs_update()

    def flash_pixel(self, pad_idx, duration, color=C.WHITE):
        # Check if already flashing with same color to avoid redundant hardware updates
        currently_flashing = pad_idx in self.flashing_pixels
        if currently_flashing:
            _, _, existing_color = self.flashing_pixels[pad_idx]
            # Same color - re-up timer but skip hardware update (no set_color, no dirty flag)
            if existing_color == color:
                self.flashing_pixels[pad_idx] = (time.monotonic(), duration, color)
                return  # Early return - no hardware update needed
        
        # New flash or different color - update both timer and hardware
        self.flashing_pixels[pad_idx] = (time.monotonic(), duration, color)
        self.set_color(pad_idx, color)
        self.set_needs_update()

    def update(self):
        # Process flashing pixels
        current_time = time.monotonic()
        to_remove = []
        
        for pad_idx, (start_time, duration, _) in self.flashing_pixels.items():
            if current_time - start_time >= duration:
                # Get the target default color
                default_color = self.get_default_color(pad_idx)
                
                # Get physical pixel index (handles encoder button mapping)
                pixel_idx = self._get_pixel(pad_idx) if pad_idx < C.ENC_LED_IDX else pad_idx
                
                # Only update if current hardware color differs from default
                # This prevents race conditions where another code path set the color
                if all_pixels[pixel_idx] != default_color:
                    self.set_color(pad_idx, default_color)
                
                to_remove.append(pad_idx)
        
        # Remove finished flashes
        for pad_idx in to_remove:
            del self.flashing_pixels[pad_idx]
        
        # Update pixels if needed
        if self.get_update_pending_flag():
            all_pixels.show()
            if C.USING_FOOT_PEDALS:
                pedals.show_pedal_pixels()
            self.set_needs_update(False)
            
            # Dynamic refresh: slow down during sustained heavy load
            self._consecutive_busy += 1
            if self._consecutive_busy > 3:
                self.update_interval_ms = min(50, self.update_interval_ms + 10)
        else:
            # No update needed - snap back to responsive rate
            self._consecutive_busy = 0
            self.update_interval_ms = C.PIXEL_UPDATE_INTERVAL_MS

    def _initialize_velocity_map(self, global_brightness_factor=0.5):
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
        return self.pixels_need_update

    def set_needs_update(self, yesOrNo=True):
        self.pixels_need_update = yesOrNo

    def _get_pixel(self, index):
        return self.pad_to_pixel_index_map[index]

    def _interpolate_color(self, color1, color2, factor):
        return tuple(int(color1[i] + (color2[i] - color1[i]) * factor) for i in range(3))

    def _get_velocity_map_color(self, pad_idx):
        if not self._velocity_map_initialized:
            self._initialize_velocity_map()
        return self.velocity_map_colors[pad_idx]

    def _scale_brightness(self, color, brightness_factor):
        return tuple(int(c * brightness_factor) for c in color)

    def indicate_preset_loading(self, is_loading=True):
        if is_loading:
            # Start fast blinking on both FN and encoder buttons during loading
            self.set_blink(C.FN_LED_IDX, True, C.YELLOW)
            self.set_blink(C.ENC_LED_IDX, True, C.YELLOW)
        else:
            # Stop blinking and do completion flash
            self.set_blink(C.FN_LED_IDX, False)
            self.set_blink(C.ENC_LED_IDX, False)
            self.flash_pixel(C.FN_LED_IDX, 0.8, C.GREEN)
            self.flash_pixel(C.ENC_LED_IDX, 0.8, C.GREEN)

pixels = DisplayPixels()