# Merge Plan: Create Colm Branch from Main with Colm-Customizations

**Goal:** Create a new `colm` branch starting from `main`, then implement all Colm-specific customizations.  
**Strategy:** Start fresh from main, add Colm hardware features on top.  
**Source of Truth:** Actual files from `Colm-Customization` branch (verified via `git show`)  
**Testing:** Not possible locally - this document must be thorough enough for blind implementation.

---

## Overview: What Makes Colm Different

The Colm branch adds hardware peripherals not present in the standard Loopster:
1. **Foot Pedals** - 5 pedals that trigger pads remotely, with their own NeoPixel strip that mirrors pad states
2. **Accelerometer** - MPU6050 for tilt-based CC control and arp triggering, with calibration system
3. **Glove Buttons** - Two buttons for bank switching (cycles through pedal banks 0-2)
4. **Motor Haptics** - PWM motor for tactile feedback on events

---

## Hardware Pin Assignments

| Peripheral | Pin | Board Constant | Purpose |
|------------|-----|----------------|---------|
| **Pedal 1** | GP9 | `board.GP9` | Digital input, pull-up |
| **Pedal 2** | GP0 | `board.GP0` | Digital input, pull-up |
| **Pedal 3** | GP26 (A0) | `board.A0` | Digital input, pull-up |
| **Pedal 4** | GP27 (A1) | `board.A1` | Digital input, pull-up |
| **Pedal 5** | GP22 | `board.GP22` | Digital input, pull-up |
| **Pedal NeoPixels** | GP14 | `board.GP14` | NeoPixel data out (5 LEDs) |
| **Accelerometer SCL** | GP21 | `board.GP21` | I2C clock for MPU6050 |
| **Accelerometer SDA** | GP20 | `board.GP20` | I2C data for MPU6050 |
| **Accelerometer Enable** | GP29 (A3) | `board.A3` | Switch to enable/disable accel |
| **Glove Left** | GP23 | `board.GP23` | Digital input, pull-up (bank up) |
| **Glove Right** | GP24 | `board.GP24` | Digital input, pull-up (bank down) |
| **Motor PWM** | GP28 (A2) | `board.GP28` | PWM output for haptic motor |

**⚠️ CONSTANTS FILE DISCREPANCY:** The `constants.py` file has incorrect/unused accelerometer pin definitions:
```python
ACCEL_I2C_SCL = board.GP27  # NOT USED - actual code uses GP21
ACCEL_I2C_SDA = board.GP26  # NOT USED - actual code uses GP20
```
The **actual** accelerometer I2C pins are **hardcoded in `useraddons.py`** as `busio.I2C(board.GP21, board.GP20)`. The constants should be updated to match, or the code should use the constants.

**Note:** The accelerometer I2C (GP20/GP21) is **separate** from the display I2C (GP18/GP19) to avoid bus conflicts.

---

## Files to Create (New Files)

### 1. Create `src/pedals.py`

**Purpose:** Hardware driver for 5 foot pedals that mirror pad functionality.

**EXACT Implementation from Colm branch:**

```python
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
        # NOTE: Must update this import for main branch terminology!
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
                # Has a loop but not playing - use LOOP_COLOR (was CHORD_COLOR in Colm)
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
```

**IMPORTANT CHANGES for main branch compatibility:**
- `from chordmanager import chord_manager` → `from loopmanager import loop_manager`
- `chord_manager.chord_loops` → `loop_manager.loops`
- `C.CHORD_COLOR` → `C.LOOP_COLOR` (main branch renamed this)

---

## Files to Modify

### 2. Modify `src/constants.py`

**Add these constants at the END of the file (after existing constants):**

```python
# ------ USER ADDONS ------ #
USING_FOOT_PEDALS = True
USING_GLOVE_BUTTONS = True
USING_ACCELEROMETER = True
USING_MOTOR_FEEDBACK = True


# ============================================================================
# ============================= USER ADDONS CONSTANTS =====================
# ============================================================================

# ------ ACCELEROMETER SETTINGS ------ #
# GPIO pins for accelerometer I2C (separate from display I2C)
ACCEL_I2C_SCL = board.GP27
ACCEL_I2C_SDA = board.GP26

# Accelerometer tilt-based CC numbers
ACCEL_LEFT_TILT_CC = 1          # CC number for left tilt (modulation wheel)
ACCEL_RIGHT_TILT_CC = 74        # CC number for right tilt (filter cutoff)
ACCEL_BACKWARD_TILT_CC = 7      # CC number for backward tilt (volume)
ACCEL_FORWARD_TILT_CC = 11      # CC number for forward tilt (not used - forward controls arpeggiator)

# Accelerometer processing settings
ACCEL_THRESHOLD = 1             # Threshold for CC value changes
ACCEL_SMOOTH_FACTOR = 0.8       # Smoothing factor (0-1) where 1 = no smoothing
ACCEL_UPDATE_INTERVAL = 0.05    # Time in seconds between updates

# Accelerometer switch/enable pin
ACCEL_ENABLE_PIN = board.A3     # GPIO pin for accelerometer enable switch

# Accelerometer tilt settings
ACCEL_DEADZONE_DEGREES = 10     # Deadzone in degrees to prevent accidental triggers
ACCEL_MAX_TILT_DEGREES = 90     # Maximum tilt angle for full CC range

# Accelerometer arpeggiator control settings
ACCEL_ARP_MAX_TILT_DEGREES = 90         # Maximum tilt angle for full speed
ACCEL_ARP_MIN_INTERVAL_MS = 50          # Fastest arp interval (50ms at full tilt)
ACCEL_ARP_MAX_INTERVAL_MS = 1000        # Slowest arp interval (1 second at minimal tilt)
ACCEL_ARP_AXIS = 'Y'                    # Which accelerometer axis to use ('X' or 'Y')

# ------ GLOVE BUTTON SETTINGS ------ #
GLOVE_LEFT_PIN = board.GP23
GLOVE_RIGHT_PIN = board.GP24
GLOVE_DEBOUNCE_TIME = 0.02      # 20ms debounce time

# ------ PEDAL SETTINGS ------ #
PEDAL_1_PIN = board.GP9
PEDAL_2_PIN = board.GP0
PEDAL_3_PIN = board.A0          # Analog pin used as digital
PEDAL_4_PIN = board.A1          # Analog pin used as digital
PEDAL_5_PIN = board.GP22
PEDAL_NEOPIXEL_PIN = board.GP14
PEDAL_COUNT = 5
PEDAL_BRIGHTNESS = 1

# ------ MOTOR SETTINGS ------ #
MOTOR_PWM_PIN = board.GP28      # Motor PWM pin for haptic feedback

# Motor haptic feedback settings
MOTOR_PULSE_DURATION = 0.1              # Default pulse duration in seconds
MOTOR_FREQUENCY = 500                   # PWM frequency for motor
MOTOR_MIN_THRESHOLD = 0.20              # Minimum motor intensity threshold
MOTOR_MAX_THRESHOLD = 0.85              # Maximum motor intensity threshold

# ------ ACCELEROMETER CALIBRATION SETTINGS ------ #
ACCEL_CALIBRATION_NEUTRAL_TIME = 3      # Seconds to hold neutral position
ACCEL_CALIBRATION_MOVEMENT_TIME = 20    # Seconds for movement detection
ACCEL_CALIBRATION_DISPLAY_UPDATE = 3    # Display update interval during calibration
ACCEL_DOUBLE_TOGGLE_WINDOW = 1.0        # Time window for double-toggle calibration trigger

# Accelerometer adaptive mode settings
ACCEL_MODE_HOLD_DURATION = 1.5          # Time to hold mode before switching
ACCEL_STABLE_MODE_THRESHOLD = 4         # CC change threshold in stable mode  
ACCEL_CHANGING_MODE_THRESHOLD = 1       # CC change threshold in changing mode
ACCEL_STABILITY_BUFFER_SIZE = 3         # Number of readings to check for stability
ACCEL_MAX_STABILITY_VARIATION = 4       # Max variation between readings for stability

# Debug settings
ACCEL_DEBUG_ENABLED = True              # Enable accelerometer debug output

# Default loop pad index (for accelerometer CC recording)
DEFAULT_LOOPPAD_IDX = 255               # Main branch may already have DEFAULT_LOOP_PAD_IDX
```

**NOTE:** Main branch already has `DEFAULT_LOOP_PAD_IDX = 255` - Colm uses `DEFAULT_CHORDPAD_IDX`. Use existing constant or add alias.

---

### 3. Modify `src/settings.py`

**Add in `Settings.__init__()` after `self.arp_is_polyphonic`:**

```python
self.encoder_steps_per_arpnote = 1         # Encoder steps per arp note (higher = more turns)
```

**Exact location (find this block and add the line):**
```python
        self.arpeggiator_type = "up"
        self.arpeggiator_length = "1/8"
        self.arp_is_polyphonic = True
        self.encoder_steps_per_arpnote = 1         # ADD THIS LINE
```

---

### 4. Modify `src/settingsmenu.py`

**Update `settings_mapping` dict to include encoder_steps. Find the settings_mapping and adjust indices:**

Current main branch (approximate):
```python
settings_mapping = {
    # ... existing entries ...
    8: ("loop_type", str),
    9: ("arp_is_polyphonic", bool),
    10: ("arpeggiator_length", str),
    11: ("notes_all_at_once", bool),
    12: ("cc_stream_to_flash", bool),
}
```

**Change to (insert encoder_steps at index 9, shift others):**
```python
settings_mapping = {
    # ... existing entries ...
    8: ("loop_type", str),
    9: ("encoder_steps_per_arpnote", int),  # NEW - Colm specific
    10: ("arp_is_polyphonic", bool),        # Was 9
    11: ("arpeggiator_length", str),        # Was 10
    12: ("notes_all_at_once", bool),        # Was 11
    13: ("cc_stream_to_flash", bool),       # Was 12
}
```

**Add to `settings_pages` tuple (the display options). Find the settings_pages and add:**
```python
("encoder steps", [1, 2, 3, 4, 5, 6, 7, 8]),  # Add after loop type entry
```

---

### 5. Modify `src/arp.py`

**Add instance variable in `Arpeggiator.__init__()`:**

Find:
```python
def __init__(self):
    # Ordered list of held pads (press order preserved)
    self.held_pads = []
```

Add after existing `__init__` variables:
```python
        self.encoder_step_counter = 0   # Tracks encoder steps for timing control
```

**Add new method `skip_this_turn()` - add this method to the Arpeggiator class:**

```python
    def skip_this_turn(self):
        """
        Determines if the current arpeggiator step should be skipped based on encoder settings.
        
        Returns:
            bool: True if the current step should be skipped, False otherwise.
        """
        encoder_steps = s.encoder_steps_per_arpnote
        if encoder_steps <= 1:
            return False
            
        self.encoder_step_counter = (self.encoder_step_counter % encoder_steps) + 1
        return self.encoder_step_counter != encoder_steps
```

**Modify `get_next_arp_events()` to use skip_this_turn - find and update:**

In the existing `get_next_arp_events()` method, add check at the beginning:
```python
    def get_next_arp_events(self):
        """Returns the next arpeggiated note and CC tuples based on the current pattern type."""
        
        # Check if we should skip this step based on encoder settings
        if self.skip_this_turn():
            return None
        
        # ... rest of existing method
```

**Also reset counter when pattern changes direction. In `get_next_arp_events()`, after direction changes:**
```python
        # After "random" direction handling, reset counter:
        if s.arpeggiator_type == "random":
            self.encoder_step_counter = s.encoder_steps_per_arpnote
```

---

### 6. Modify `src/inputs.py`

**Add imports at top (after existing imports):**

```python
import useraddons
from pedals import pedals
```

**Modify `process_keymatrix()` to include pedal events:**

Find the `process_keymatrix(self)` method and **replace entirely** with:

```python
    def process_keymatrix(self):
        """Process keypad matrix events and pedal events. Returns (new_press_indices, has_releases)."""
        new_press_indices = []
        has_releases = False
        
        # Process physical keypad events first
        while True:
            event = self._pads.events.get()
            if not event:
                break
            pad_idx = event.key_number
            if event.pressed:
                self.pressed_count += 1
            else:
                self.pressed_count -= 1
                has_releases = True
            idx = self.note_buttons[pad_idx].process_keymatrix_event(event)
            if idx is not None:
                new_press_indices.append(pad_idx)

        # Process pedal events (Colm addition)
        while True:
            pedal_event = pedals.get_event()
            if not pedal_event:
                break
            pad_idx = pedal_event.key_number
            if pedal_event.pressed:
                self.pressed_count += 1
            else:
                self.pressed_count -= 1
                has_releases = True
            idx = self.note_buttons[pad_idx].process_keymatrix_event(pedal_event)
            if idx is not None:
                new_press_indices.append(pad_idx)

        return new_press_indices, has_releases
```

**Modify `process_inputs_fast()` to check accelerometer for arp triggering:**

Find the line in `process_inputs_fast()` that handles arp events (around line 320 in main):
```python
            if self.pressed_count == 0 and arpeggiator.has_events():
                arpeggiator.clear_arp_notes()
            else:
                self.play_arp_events()
```

**Change to:**
```python
            if self.pressed_count == 0 and arpeggiator.has_events():
                arpeggiator.clear_arp_notes()

            # Check encoder OR accelerometer for arp triggering
            if (self.encoder_delta > 0 or useraddons.should_trigger_accelerometer_arp()) and arpeggiator.has_events():
                self.play_arp_events()
```

**Note:** Remove the `else: self.play_arp_events()` and make it conditional on encoder OR accelerometer.

---

### 7. Modify `src/pixels.py`

**Add import at top:**
```python
from pedals import pedals
```

**Add pedal pixel mirroring to these methods (add lines with `if C.USING_FOOT_PEDALS:`):**

**In `set_note_on()`:**
```python
    def set_note_on(self, pad_idx, velocity=127):
        color = self._scale_brightness(C.NOTE_COLOR, velocity / 127)
        all_pixels[self._get_pixel(pad_idx)] = color
        if C.USING_FOOT_PEDALS:
            pedals.set_pixel_on(pad_idx, color)
        self.set_needs_update()
```

**In `set_note_off()` (at the end where color is set):**
```python
        # ... existing code that sets color ...
        all_pixels[self._get_pixel(pad_idx)] = color
        if C.USING_FOOT_PEDALS:
            pedals.set_pixel_on(pad_idx, color)
```

**In `set_blink()` both branches (blink on and blink off):**
```python
        # In the blink-off branch:
        all_pixels[pixel_idx] = color
        if C.USING_FOOT_PEDALS:
            pedals.set_pixel_on(pad_idx, color)
```

**In `set_color()`:**
```python
    def set_color(self, pad_idx, color):
        self.set_needs_update()
        all_pixels[self._get_pixel(pad_idx)] = color
        if C.USING_FOOT_PEDALS:
            pedals.set_pixel_on(pad_idx, color)
```

**In `process_blinks()` inner loop:**
```python
                    pixel_color = self.blink_colors.get(i, C.RED) if (self.pixel_states[i] & 0x02) else C.BLACK
                    all_pixels[self._get_pixel(i)] = pixel_color
                    if C.USING_FOOT_PEDALS:
                        pedals.set_pixel_on(i, pixel_color)
```

**In `clear_all()`:**
```python
        for i in range(18):
            all_pixels[i] = C.BLACK
            if C.USING_FOOT_PEDALS:
                pedals.set_pixel_on(i, C.BLACK)
```

**In `update()`:**
```python
    def update(self):
        if self.get_update_pending_flag():
            all_pixels.show()
            if C.USING_FOOT_PEDALS:
                pedals.show_pedal_pixels()
            self.set_needs_update(False)
```

---

### 8. Modify `src/code.py`

**Add import:**
```python
import useraddons
```

**Add useraddons calls in main loop:**

Find the slow polling section (around line 261) and add:
```python
            useraddons.slow()
```

Find after `inputs.process_inputs_fast()` and add:
```python
        useraddons.check_addons_fast()
```

**Add accelerometer CC processing - find where CCs are processed and add:**
```python
        # Process accelerometer CC data
        process_cc_events(useraddons.get_accel_cc_data(), record=settings.record_cc)
```

---

### 9. REPLACE `src/useraddons.py`

**This is the most critical file. Replace the entire file with the Colm version.**

The file is ~700 lines. Key components:
- `FakeKeypadEvent` class (also used by glove buttons for consistency)
- Glove button handling with:
  - Debounce timing
  - Directional haptic patterns (up=gentler/longer, down=stronger/shorter)
  - Bank limits (0-2)
  - Minimum off-time to prevent fabric contact bounce
- `MotorController` class for PWM haptic feedback:
  - `pulse_from_cc(cc_value)` - intensity based on CC value
  - `pulse(intensity, duration)` - direct control
  - `update_pulse_timing()` - called in main loop to end pulses
- `AccelerometerController` class with:
  - MPU6050 I2C initialization
  - Enable switch with double-toggle calibration trigger
  - Tilt-to-CC conversion for left/right/backward directions
  - Forward tilt for arp triggering (variable speed based on tilt angle)
  - Calibration system with display feedback (3-phase: neutral, movement, complete)
  - Adaptive smoothing modes (STABLE vs CHANGING)
  - Cached readings for arp checks
- Global instances: `motor_controller`, `accelerometer`
- Hook functions: `slow()`, `check_addons_fast()`, `handle_new_notes_on/off()`, `handle_new_cc()`
- Helper functions: 
  - `should_trigger_accelerometer_arp()` 
  - `get_accel_cc_data()`
  - `trigger_motor_pulse_manual(cc_value)`
  - `force_accelerometer_calibration()`

**To extract the full file:**
```bash
git show Colm-Customization:src/useraddons.py > src/useraddons.py
```

**Then update these references in the file:**
- `from chordmanager import chord_manager` → remove if present (not used in useraddons)
- Any `chord_` references → `loop_` equivalents
- `C.DEFAULT_CHORDPAD_IDX` → `C.DEFAULT_LOOP_PAD_IDX`

**Key haptic constants defined at top of file (preserve these):**
```python
GLOVE_HAPTIC_ENABLED = True
ACCEL_HAPTIC_ENABLED = False    # Disabled by default, can be noisy
GLOVE_HAPTIC_UP_INTENSITY = 0.7
GLOVE_HAPTIC_UP_DURATION = 0.25
GLOVE_HAPTIC_DOWN_INTENSITY = 0.9
GLOVE_HAPTIC_DOWN_DURATION = 0.1
MIN_OFF_TIME = 0.1  # Fabric bounce prevention
```

---

## Terminology Translation Guide

| Colm Branch | Main Branch |
|-------------|-------------|
| `chordmanager` | `loopmanager` |
| `chord_manager` | `loop_manager` |
| `chord_loops` | `loops` |
| `ChordManager` | `LoopManager` |
| `toggle_chord_playstate()` | `toggle_loop_playstate()` |
| `CHORD_COLOR` | `LOOP_COLOR` |
| `CHD_MODE_ICON` | `LOOP_MODE_ICON` |
| `DEFAULT_CHORDPAD_IDX` | `DEFAULT_LOOP_PAD_IDX` |
| `chordmode_looptype` | `loop_type` |

---

## Integration Verification Checklist

After implementing all changes, verify:

### Pedals
- [ ] Pressing pedal triggers same action as pressing corresponding pad
- [ ] Pedal LEDs mirror pad state (playing = green, stopped with loop = purple, no loop = off)
- [ ] Bank switching via glove buttons works (left glove = bank up, right glove = bank down)
- [ ] Pedal pixels update when switching banks
- [ ] Hold mode works with pedals
- [ ] Pedal banks cycle 0→1→2 (left glove) and 2→1→0 (right glove)

### Accelerometer
- [ ] Tilting left sends CC 1 (mod wheel)
- [ ] Tilting right sends CC 74 (filter cutoff)
- [ ] Tilting backward sends CC 7 (volume)
- [ ] Tilting forward triggers arp notes (no CC sent)
- [ ] Enable switch (board.A3) toggles accelerometer on/off
- [ ] Double-toggle of enable switch triggers calibration
- [ ] Calibration displays properly on screen (3 phases)
- [ ] Deadzone prevents accidental triggers near neutral

### Motor Haptics
- [ ] Motor pulses on bank change (up=gentle/long, down=strong/short)
- [ ] Motor pulses on tilt (only if `ACCEL_HAPTIC_ENABLED = True`)
- [ ] Pulse intensity scales with CC value

### Arp Integration
- [ ] `encoder_steps_per_arpnote` throttles encoder arp speed
- [ ] Accelerometer forward tilt triggers arp at variable speed based on tilt angle
- [ ] Setting appears in settings menu
- [ ] Arp only triggers when pads are held (encoder mode)

---

## Files Summary

| File | Action | Lines Changed |
|------|--------|---------------|
| `pedals.py` | CREATE | ~130 lines (new file) |
| `constants.py` | MODIFY | Add ~60 lines at end |
| `settings.py` | MODIFY | Add 1 line |
| `settingsmenu.py` | MODIFY | Add entry, shift indices |
| `arp.py` | MODIFY | Add ~15 lines |
| `inputs.py` | MODIFY | Add imports, modify 2 methods |
| `pixels.py` | MODIFY | Add ~15 conditional lines |
| `code.py` | MODIFY | Add ~5 lines |
| `useraddons.py` | REPLACE | ~700 lines |

---

## Extraction Commands

To get exact files from Colm branch:
```bash
cd "/path/to/Code - Production"

# Get full files
git show Colm-Customization:src/pedals.py > /tmp/colm_pedals.py
git show Colm-Customization:src/useraddons.py > /tmp/colm_useraddons.py
git show Colm-Customization:src/constants.py > /tmp/colm_constants.py

# Compare specific files
git diff main Colm-Customization -- src/inputs.py
git diff main Colm-Customization -- src/pixels.py
git diff main Colm-Customization -- src/arp.py
git diff main Colm-Customization -- src/settings.py
git diff main Colm-Customization -- src/settingsmenu.py
git diff main Colm-Customization -- src/code.py
```

---

## Critical Notes for Implementation

1. **Circular Import Risk**: `pedals.py` imports from `loopmanager` inside `_update_pixels_for_current_bank()` - keep this as a late import to avoid circular dependency.

2. **Pedal Pixel Synchronization**: Every place in `pixels.py` that changes a pixel must also call the corresponding pedal pixel method, guarded by `if C.USING_FOOT_PEDALS:`.

3. **Accelerometer I2C is SEPARATE**: Uses GP26/GP27 (board.A0/A1 area), NOT the display I2C (GP18/GP19). This is intentional to avoid bus conflicts.

4. **Enable Switch Logic**: The accelerometer enable switch is active-low (pull-up, value=False when pressed/enabled). The `is_enabled()` method returns `not self.enable_switch.value`.

5. **useraddons.py Import Order**: Must import `pedals` before using it in glove button functions. The import is at module level.

6. **Settings Menu Index Shift**: Adding `encoder_steps_per_arpnote` at index 9 shifts ALL subsequent indices. The `settings_menu_option_indices` array in Settings may need its length adjusted.
