import digitalio
import time
from buttons import Button
import neopixel
import constants as C

"""Pedal control functionality for DJBB MIDI Loopster 2.0"""

class FakeKeypadEvent:
    """A fake keypad event that mimics CircuitPython's keypad event structure"""
    def __init__(self, key_number, pressed):
        self.key_number = key_number
        self.pressed = pressed
        self.released = not pressed

class Pedals:
    def __init__(self):
        self.pixels = neopixel.NeoPixel(C.PEDAL_NEOPIXEL_PIN, C.PEDAL_COUNT, brightness=C.PEDAL_BRIGHTNESS, auto_write=False)
        self.pixels.fill((0, 0, 0))
        self._pedal_1 = digitalio.DigitalInOut(C.PEDAL_1_PIN)
        self._pedal_1.direction = digitalio.Direction.INPUT
        self._pedal_1.pull = digitalio.Pull.UP

        self._pedal_2 = digitalio.DigitalInOut(C.PEDAL_2_PIN)
        self._pedal_2.direction = digitalio.Direction.INPUT
        self._pedal_2.pull = digitalio.Pull.UP

        self._pedal_3 = digitalio.DigitalInOut(C.PEDAL_3_PIN)
        self._pedal_3.direction = digitalio.Direction.INPUT
        self._pedal_3.pull = digitalio.Pull.UP
        
        self._pedal_4 = digitalio.DigitalInOut(C.PEDAL_4_PIN)
        self._pedal_4.direction = digitalio.Direction.INPUT
        self._pedal_4.pull = digitalio.Pull.UP
        
        self._pedal_5 = digitalio.DigitalInOut(C.PEDAL_5_PIN)
        self._pedal_5.direction = digitalio.Direction.INPUT
        self._pedal_5.pull = digitalio.Pull.UP

        self.pedal_1 = Button(pad_index=0,label="Pedal 1")
        self.pedal_2 = Button(pad_index=1,label="Pedal 2")
        self.pedal_3 = Button(pad_index=2,label="Pedal 3")
        self.pedal_4 = Button(pad_index=3,label="Pedal 4")
        self.pedal_5 = Button(pad_index=4,label="Pedal 5")
        self.pedals = [self.pedal_1, self.pedal_2, self.pedal_3, self.pedal_4, self.pedal_5]

        self.pixels_need_update = True

        # Event queue for fake keypad events
        self.event_queue = []
        
        # Bank state variables
        self.current_bank = 0  # 0, 1, or 2 for banks 0-2
        self.bank_offset = 0   # Calculated offset: bank * 5

    def update(self):
        """Update the state of all pedals and generate fake keypad events"""
        self.pedal_1.set_current_value(self._pedal_1.value)
        self.pedal_2.set_current_value(self._pedal_2.value)
        self.pedal_3.set_current_value(self._pedal_3.value)
        self.pedal_4.set_current_value(self._pedal_4.value)
        self.pedal_5.set_current_value(self._pedal_5.value)
        
        for i, pedal in enumerate(self.pedals):
            # Store previous state before updating
            prev_state = pedal.state
            pedal.update_all()
            
            # Generate fake events for state changes
            if not prev_state and pedal.state:  # New press
                fake_event = FakeKeypadEvent(key_number=pedal.pad_idx, pressed=True)
                self.event_queue.append(fake_event)
            elif prev_state and not pedal.state:  # New release
                fake_event = FakeKeypadEvent(key_number=pedal.pad_idx, pressed=False)
                self.event_queue.append(fake_event)
    
    def show_pedal_pixels(self):
        """Update the pedal pixels based on the current pedal states"""
        if self.pixels_need_update:
            self.pixels.show()
            self.pixels_need_update = False

    def set_pixel_on(self, loopster_pad_idx, color=C.NOTE_COLOR):
        """Set the pixel color for a pedal based on loopster pad index"""
        pedal_pixel_idx = self.get_pedal_pixel_index(loopster_pad_idx)
        if pedal_pixel_idx is not None:
            self.pixels[pedal_pixel_idx] = color
            self.pixels_need_update = True

    def set_pixel_off(self, loopster_pad_idx):
        """Turn off the pixel for a pedal based on loopster pad index"""
        pedal_pixel_idx = self.get_pedal_pixel_index(loopster_pad_idx)
        if pedal_pixel_idx is not None:
            self.pixels[pedal_pixel_idx] = (0, 0, 0)
            self.pixels_need_update = True
    
    def reset_pedals(self):
        """Reset the pedal states and pixel colors"""
        for pedal in self.pedals:
            pedal.reset_actions()

    def get_event(self):
        """Get the next event from the pedal event queue, returns None if empty"""
        if self.event_queue:
            return self.event_queue.pop(0)
        return None

    def set_pedal_bank(self, bank_idx):
        """Switch to a different pedal bank (0-2)"""
        if 0 <= bank_idx <= 2:
            self.current_bank = bank_idx
            self.bank_offset = bank_idx * 5
            # Update all pedal button pad_indices
            for i, pedal in enumerate(self.pedals):
                pedal.pad_idx = self.bank_offset + i
            
            # Immediately reflect the state of loops in the new bank
            self._update_pixels_for_current_bank()
            
            print(f"Switched to pedal bank {bank_idx} (pads {self.bank_offset}-{self.bank_offset+4})")

    def get_pedal_pixel_index(self, loopster_pad_idx):
        """Convert loopster pad index to local pedal pixel index (0-4)"""
        if self.bank_offset <= loopster_pad_idx < self.bank_offset + 5:
            return loopster_pad_idx - self.bank_offset
        return None  # This pad doesn't correspond to any pedal

    def _update_pixels_for_current_bank(self):
        """Update pedal pixels to reflect current state of loops in this bank"""
        # Late import to avoid circular dependency
        from loopmanager import loop_manager
        
        # For each pedal in current bank, check if corresponding loop is playing
        for i in range(5):
            loopster_pad_idx = self.bank_offset + i
            # Check if there's a loop at this pad index and if it's playing
            if (loopster_pad_idx < len(loop_manager.loops) and 
                loop_manager.loops[loopster_pad_idx] != "" and 
                loop_manager.loops[loopster_pad_idx].loop_is_playing):
                self.pixels[i] = C.PIXEL_LOOP_PLAYING_COLOR
            elif (loopster_pad_idx < len(loop_manager.loops) and 
                  loop_manager.loops[loopster_pad_idx] != ""):
                # Has a loop but not playing - use LOOP_COLOR
                self.pixels[i] = C.LOOP_COLOR
            else:
                # No loop
                self.pixels[i] = (0, 0, 0)
        self.pixels_need_update = True

# Create the global pedals instance
pedals = Pedals()

def update_pedal_pixels():
    """Update the pedal pixels based on the current pedal states"""
    if pedals.pixels_need_update:
        pedals.show_pedal_pixels()
