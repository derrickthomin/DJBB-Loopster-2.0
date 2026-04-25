import gc
import digitalio
import time
import constants as C
import board
from pedals import pedals, update_pedal_pixels
from display import display
from settings import settings

class FakeKeypadEvent:
    def __init__(self, key_number, pressed):
        self.key_number = key_number
        self.pressed = pressed
        self.released = not pressed

glove_left = digitalio.DigitalInOut(C.GLOVE_LEFT_PIN)
glove_left.direction = digitalio.Direction.INPUT
glove_left.pull = digitalio.Pull.UP

glove_right = digitalio.DigitalInOut(C.GLOVE_RIGHT_PIN)
glove_right.direction = digitalio.Direction.INPUT
glove_right.pull = digitalio.Pull.UP

glove_left_prev = True
glove_right_prev = True
last_press_time = 0
glove_left_last_release_time = 0
glove_right_last_release_time = 0
MIN_OFF_TIME = 0.1  # 250ms minimum OFF time to prevent fabric contact bounce


def slow():
    update_pedal_pixels()

def check_addons_fast():
    check_glove_buttons()
    pedals.update()  # Update pedals and generate fake events
    accelerometer.update()

def check_glove_buttons():
    global glove_left_prev, glove_right_prev, last_press_time
    global glove_left_last_release_time, glove_right_last_release_time
    
    current_time = time.monotonic()
    glove_left_current = glove_left.value
    glove_right_current = glove_right.value

    # Track when buttons are released (transition from pressed to not pressed)
    if not glove_left_prev and glove_left_current:  # Left button was pressed, now released
        glove_left_last_release_time = current_time
    
    if not glove_right_prev and glove_right_current:  # Right button was pressed, now released
        glove_right_last_release_time = current_time

    # Check for presses with both debounce time AND minimum off time
    if current_time - last_press_time >= C.GLOVE_DEBOUNCE_TIME:
        # Left button press: was not pressed, now pressed, and has been off long enough
        if (glove_left_prev and not glove_left_current and 
            current_time - glove_left_last_release_time >= MIN_OFF_TIME):
            new_bank = min(pedals.current_bank + 1, 2)  # Go up, max at bank 2
            if new_bank != pedals.current_bank:  # Only switch if we're not at the limit
                pedals.set_pedal_bank(new_bank)
            last_press_time = current_time

        # Right button press: was not pressed, now pressed, and has been off long enough
        if (glove_right_prev and not glove_right_current and 
            current_time - glove_right_last_release_time >= MIN_OFF_TIME):
            new_bank = max(pedals.current_bank - 1, 0)  # Go down, min at bank 0
            if new_bank != pedals.current_bank:  # Only switch if we're not at the limit
                pedals.set_pedal_bank(new_bank)
            last_press_time = current_time
        
    glove_left_prev = glove_left_current
    glove_right_prev = glove_right_current

# ------- Accelerometer -------------

class AccelerometerController:
    
    def __init__(self):
        
        self.enable_switch = digitalio.DigitalInOut(C.ACCEL_ENABLE_PIN)
        self.enable_switch.direction = digitalio.Direction.INPUT
        self.enable_switch.pull = digitalio.Pull.UP
        
        # Calibration tracking - triggered by double-toggle pattern
        self.calibrated = False
        self.previous_enabled_state = False
        
        # Double-toggle calibration trigger (ultra-simple approach)
        self.last_on_transition_time = 0
        self.transition_window = C.ACCEL_DOUBLE_TOGGLE_WINDOW  # Use constant from config
        
        self.prev_left_tilt = 0
        self.prev_right_tilt = 0  
        self.prev_backward_tilt = 0
        self.prev_forward_tilt = 0  # Add forward tilt tracking
        self.last_left_cc_val = 0
        self.last_right_cc_val = 0
        self.last_backward_cc_val = 0
        self.last_forward_cc_val = 0  # Add forward tilt CC tracking
        self.last_update_time = 0
        
        self.recent_left_cc = [0, 0, 0]
        self.recent_right_cc = [0, 0, 0]
        self.recent_backward_cc = [0, 0, 0]
        self.recent_forward_cc = [0, 0, 0]  # Add forward tilt stability tracking
        
        self.left_mode = "STABLE"
        self.right_mode = "STABLE"
        self.backward_mode = "STABLE"
        self.forward_mode = "STABLE"  # Add forward tilt adaptive mode
        self.left_mode_switch_time = 0
        self.right_mode_switch_time = 0
        self.backward_mode_switch_time = 0
        self.forward_mode_switch_time = 0  # Add forward tilt mode timing
        self.mode_hold_duration = C.ACCEL_MODE_HOLD_DURATION
        
        self.x_baseline = 0
        self.y_baseline = 0
        self.x_max = 90
        self.x_min = -90
        self.y_max = 90
        self.y_min = -90
        
        self.threshold = C.ACCEL_THRESHOLD
        self.smooth_factor = C.ACCEL_SMOOTH_FACTOR
        self.update_interval = C.ACCEL_UPDATE_INTERVAL
        self.debug = C.ACCEL_DEBUG_ENABLED
        
        self.cc_data = []
        
        self.arp_last_trigger_time = 0
        self.arp_current_interval_ms = None
        self.arp_locked_interval_ms = None  # Interval locked for current cycle
        self.cached_accel_reading = None
        
        try:
            import busio  # Import only when needed
            from mpu6050_minimal import MPU6050  # Minimal driver (~10KB savings vs adafruit_mpu6050)
            self.i2c = busio.I2C(board.GP21, board.GP20)
            self.mpu = MPU6050(self.i2c)
            self.has_accelerometer = True
            if self.debug:
                print("MPU6050 accelerometer initialized (minimal driver)")
        except (OSError, ValueError, RuntimeError) as e:
            self.has_accelerometer = False
            print(f"Error initializing accelerometer: {e}")
    
    def is_enabled(self):
        return not self.enable_switch.value

    def _is_readings_stable(self, new_cc_val, recent_values):
        recent_values.append(new_cc_val)
        if len(recent_values) > C.ACCEL_STABILITY_BUFFER_SIZE:
            recent_values.pop(0)
        
        if len(recent_values) < C.ACCEL_STABILITY_BUFFER_SIZE:
            return False
            
        min_val = min(recent_values)
        max_val = max(recent_values)
        return (max_val - min_val) <= C.ACCEL_MAX_STABILITY_VARIATION

    def _update_adaptive_mode(self, readings_are_stable_now, current_mode, mode_switch_time, current_time):
        if current_mode == "STABLE":
            if not readings_are_stable_now:
                return "CHANGING", 0
            else:
                return "STABLE", 0
                
        else:
            if readings_are_stable_now:
                if mode_switch_time == 0:
                    return "CHANGING", current_time
                elif current_time - mode_switch_time >= self.mode_hold_duration:
                    return "STABLE", 0
                else:
                    return "CHANGING", mode_switch_time
            else:
                return "CHANGING", 0

    def update(self):
        if not self.has_accelerometer:
            return
        
        # Check for enable switch state change
        current_enabled_state = self.is_enabled()
        
        # Detect OFF->ON transition for double-toggle calibration trigger
        if current_enabled_state and not self.previous_enabled_state:
            # Memory debug on enable
            gc.collect()
            if settings.debug:
                print("ACCEL ON - mem:", gc.mem_free())
            
            cal_time = time.monotonic()
            
            # Check if this is the second OFF->ON within the time window
            if (self.last_on_transition_time > 0 and 
                cal_time - self.last_on_transition_time <= self.transition_window):
                
                if self.debug:
                    print("Double-toggle detected! Starting calibration...")
                self.calibrate()
                self.last_on_transition_time = 0  # Reset after triggering
            else:
                # Record this as the first transition
                self.last_on_transition_time = cal_time
                if self.debug:
                    print("First toggle detected - toggle again within 1 second to calibrate")
        
        # Detect ON->OFF transition
        if not current_enabled_state and self.previous_enabled_state:
            gc.collect()
            if settings.debug:
                print("ACCEL OFF - mem:", gc.mem_free())
        
        # Update previous state
        self.previous_enabled_state = current_enabled_state
        
        if not current_enabled_state:
            return
        
        # Check timing - only process at update_interval rate
        current_time = time.monotonic()
        if current_time - self.last_update_time < self.update_interval:
            return
        
        self.last_update_time = current_time
        
        # Force gc at start of actual processing to prevent accumulation
        gc.collect()
        
        try:
            accel = self.mpu.acceleration
            
            self.cached_accel_reading = accel
            
            x_tilt_degrees = (accel[0] / 9.8) * 90
            y_tilt_degrees = (accel[1] / 9.8) * 90
            
            left_tilt = 0
            right_tilt = 0
            backward_tilt = 0
            forward_tilt = 0  # Add forward tilt calculation
            
            # Check if we have valid calibration data, otherwise use constants as fallback
            if self.has_valid_calibration_data():
                # Use calibrated values for left tilt (negative X direction)
                if x_tilt_degrees < (self.x_baseline - C.ACCEL_DEADZONE_DEGREES):
                    effective_tilt = abs(x_tilt_degrees - self.x_baseline) - C.ACCEL_DEADZONE_DEGREES
                    max_effective_tilt = abs(self.x_min - self.x_baseline) - C.ACCEL_DEADZONE_DEGREES
                    if max_effective_tilt > 0:
                        tilt_ratio = min(effective_tilt / max_effective_tilt, 1.0)
                        left_tilt = int(1 + (tilt_ratio * 126))
                
                # Use calibrated values for right tilt (positive X direction)  
                elif x_tilt_degrees > (self.x_baseline + C.ACCEL_DEADZONE_DEGREES):
                    effective_tilt = x_tilt_degrees - self.x_baseline - C.ACCEL_DEADZONE_DEGREES
                    max_effective_tilt = self.x_max - self.x_baseline - C.ACCEL_DEADZONE_DEGREES
                    if max_effective_tilt > 0:
                        tilt_ratio = min(effective_tilt / max_effective_tilt, 1.0)
                        right_tilt = int(1 + (tilt_ratio * 126))
                
                # Use calibrated values for backward tilt (negative Y direction) - CC message
                if y_tilt_degrees < (self.y_baseline - C.ACCEL_DEADZONE_DEGREES):
                    effective_tilt = abs(y_tilt_degrees - self.y_baseline) - C.ACCEL_DEADZONE_DEGREES
                    max_effective_tilt = abs(self.y_min - self.y_baseline) - C.ACCEL_DEADZONE_DEGREES
                    if max_effective_tilt > 0:
                        tilt_ratio = min(effective_tilt / max_effective_tilt, 1.0)
                        backward_tilt = int(1 + (tilt_ratio * 126))
                
                # Use calibrated values for forward tilt (positive Y direction) - Arp control only, no CC
                elif y_tilt_degrees > (self.y_baseline + C.ACCEL_DEADZONE_DEGREES):
                    effective_tilt = y_tilt_degrees - self.y_baseline - C.ACCEL_DEADZONE_DEGREES
                    max_effective_tilt = self.y_max - self.y_baseline - C.ACCEL_DEADZONE_DEGREES
                    if max_effective_tilt > 0:
                        tilt_ratio = min(effective_tilt / max_effective_tilt, 1.0)
                        forward_tilt = int(1 + (tilt_ratio * 126))  # Calculate for motor feedback, arp handled separately
            else:
                # Fallback to original constants-based calculation
                if x_tilt_degrees < -C.ACCEL_DEADZONE_DEGREES:
                    effective_tilt = abs(x_tilt_degrees) - C.ACCEL_DEADZONE_DEGREES
                    max_effective_tilt = C.ACCEL_MAX_TILT_DEGREES - C.ACCEL_DEADZONE_DEGREES
                    tilt_ratio = min(effective_tilt / max_effective_tilt, 1.0)
                    left_tilt = int(1 + (tilt_ratio * 126))
                
                elif x_tilt_degrees > C.ACCEL_DEADZONE_DEGREES:
                    effective_tilt = x_tilt_degrees - C.ACCEL_DEADZONE_DEGREES
                    max_effective_tilt = C.ACCEL_MAX_TILT_DEGREES - C.ACCEL_DEADZONE_DEGREES
                    tilt_ratio = min(effective_tilt / max_effective_tilt, 1.0)
                    right_tilt = int(1 + (tilt_ratio * 126))
                
                if y_tilt_degrees < -C.ACCEL_DEADZONE_DEGREES:
                    effective_tilt = abs(y_tilt_degrees) - C.ACCEL_DEADZONE_DEGREES
                    max_effective_tilt = C.ACCEL_MAX_TILT_DEGREES - C.ACCEL_DEADZONE_DEGREES
                    tilt_ratio = min(effective_tilt / max_effective_tilt, 1.0)
                    backward_tilt = int(1 + (tilt_ratio * 126))
                
                elif y_tilt_degrees > C.ACCEL_DEADZONE_DEGREES:
                    effective_tilt = y_tilt_degrees - C.ACCEL_DEADZONE_DEGREES
                    max_effective_tilt = C.ACCEL_MAX_TILT_DEGREES - C.ACCEL_DEADZONE_DEGREES
                    tilt_ratio = min(effective_tilt / max_effective_tilt, 1.0)
                    forward_tilt = int(1 + (tilt_ratio * 126))
            
            self.prev_left_tilt = (self.smooth_factor * left_tilt) + ((1 - self.smooth_factor) * self.prev_left_tilt)
            self.prev_right_tilt = (self.smooth_factor * right_tilt) + ((1 - self.smooth_factor) * self.prev_right_tilt)
            self.prev_backward_tilt = (self.smooth_factor * backward_tilt) + ((1 - self.smooth_factor) * self.prev_backward_tilt)
            self.prev_forward_tilt = (self.smooth_factor * forward_tilt) + ((1 - self.smooth_factor) * self.prev_forward_tilt)
            
            left_cc_val = int(self.prev_left_tilt)
            right_cc_val = int(self.prev_right_tilt)
            backward_cc_val = int(self.prev_backward_tilt)
            forward_cc_val = int(self.prev_forward_tilt)  # Forward tilt used for arp control
            
            self.cc_data.clear()
            
            # Process Left Tilt CC
            left_stable = self._is_readings_stable(left_cc_val, self.recent_left_cc)
            self.left_mode, self.left_mode_switch_time = self._update_adaptive_mode(
                left_stable, self.left_mode, self.left_mode_switch_time, current_time)
            left_threshold = C.ACCEL_STABLE_MODE_THRESHOLD if self.left_mode == "STABLE" else C.ACCEL_CHANGING_MODE_THRESHOLD
            
            if abs(left_cc_val - self.last_left_cc_val) >= left_threshold:
                if left_cc_val > 0:
                    self.cc_data.append((C.ACCEL_LEFT_TILT_CC, left_cc_val, None))
                    if self.debug:
                        print(f"Left tilt CC{C.ACCEL_LEFT_TILT_CC}: {left_cc_val} (mode: {self.left_mode}, thresh: {left_threshold})")
                self.last_left_cc_val = left_cc_val

            # Process Right Tilt CC
            right_stable = self._is_readings_stable(right_cc_val, self.recent_right_cc)
            self.right_mode, self.right_mode_switch_time = self._update_adaptive_mode(
                right_stable, self.right_mode, self.right_mode_switch_time, current_time)
            right_threshold = C.ACCEL_STABLE_MODE_THRESHOLD if self.right_mode == "STABLE" else C.ACCEL_CHANGING_MODE_THRESHOLD
            
            if abs(right_cc_val - self.last_right_cc_val) >= right_threshold:
                if right_cc_val > 0:
                    self.cc_data.append((C.ACCEL_RIGHT_TILT_CC, right_cc_val, None))
                    if self.debug:
                        print(f"Right tilt CC{C.ACCEL_RIGHT_TILT_CC}: {right_cc_val} (mode: {self.right_mode}, thresh: {right_threshold})")
                self.last_right_cc_val = right_cc_val

            # Process Backward Tilt CC
            backward_stable = self._is_readings_stable(backward_cc_val, self.recent_backward_cc)
            self.backward_mode, self.backward_mode_switch_time = self._update_adaptive_mode(
                backward_stable, self.backward_mode, self.backward_mode_switch_time, current_time)
            backward_threshold = C.ACCEL_STABLE_MODE_THRESHOLD if self.backward_mode == "STABLE" else C.ACCEL_CHANGING_MODE_THRESHOLD
            
            if abs(backward_cc_val - self.last_backward_cc_val) >= backward_threshold:
                if backward_cc_val > 0:
                    self.cc_data.append((C.ACCEL_BACKWARD_TILT_CC, backward_cc_val, None))
                    if self.debug:
                        print(f"Backward tilt CC{C.ACCEL_BACKWARD_TILT_CC}: {backward_cc_val} (mode: {self.backward_mode}, thresh: {backward_threshold})")
                self.last_backward_cc_val = backward_cc_val

            # Process Forward Tilt - for arp control (no CC sent)
            forward_stable = self._is_readings_stable(forward_cc_val, self.recent_forward_cc)
            self.forward_mode, self.forward_mode_switch_time = self._update_adaptive_mode(
                forward_stable, self.forward_mode, self.forward_mode_switch_time, current_time)
            forward_threshold = C.ACCEL_STABLE_MODE_THRESHOLD if self.forward_mode == "STABLE" else C.ACCEL_CHANGING_MODE_THRESHOLD
            
            if abs(forward_cc_val - self.last_forward_cc_val) >= forward_threshold:
                if forward_cc_val > 0:
                    if self.debug:
                        print(f"Forward tilt (arp control): {forward_cc_val} (mode: {self.forward_mode}, thresh: {forward_threshold})")
                self.last_forward_cc_val = forward_cc_val

        except OSError as e:
            if self.debug:
                print(f"Error reading accelerometer: {e}")
            return
    
    def calibrate(self, neutral_time=None, calibration_time=None):
        if not self.has_accelerometer:
            print("Error: No accelerometer available for calibration")
            return
        
        # Use constants for timing
        neutral_time = neutral_time or C.ACCEL_CALIBRATION_NEUTRAL_TIME
        calibration_time = calibration_time or C.ACCEL_CALIBRATION_MOVEMENT_TIME
        
        print("Starting accelerometer calibration with display feedback...")
        
        start_time = time.monotonic()
        last_display_update = 0
        display_update_interval = C.ACCEL_CALIBRATION_DISPLAY_UPDATE  # Use constant for display updates
        
        # Phase 1: Neutral position
        print(f"Phase 1: Neutral position for {neutral_time} seconds...")
        neutral_end_time = start_time + neutral_time
        temp_x_baseline = 0
        temp_y_baseline = 0
        
        while time.monotonic() < neutral_end_time:
            current_time = time.monotonic()
            
            # Update display every 3 seconds or immediately on first iteration
            if current_time - last_display_update >= display_update_interval or last_display_update == 0:
                remaining = max(1, int(neutral_end_time - current_time))
                
                # Get current reading for live baseline display
                try:
                    accel = self.mpu.acceleration
                    temp_x_baseline = (accel[0] / 9.8) * 90
                    temp_y_baseline = (accel[1] / 9.8) * 90
                except OSError:
                    pass
                
                self._show_calibration_phase_1(remaining, temp_x_baseline, temp_y_baseline)
                last_display_update = current_time
            
            time.sleep(0.01)  # Short sleep to prevent CPU spinning
        
        # Capture final neutral position
        try:
            accel = self.mpu.acceleration
            self.x_baseline = (accel[0] / 9.8) * 90
            self.y_baseline = (accel[1] / 9.8) * 90
            print(f"Neutral position recorded: X={self.x_baseline:.1f}°, Y={self.y_baseline:.1f}°")
        except OSError as e:
            print(f"Error reading accelerometer during baseline: {e}")
            self._restore_menu_display()
            return
        
        # Initialize min/max values to baseline
        self.x_max = self.x_baseline
        self.x_min = self.x_baseline
        self.y_max = self.y_baseline
        self.y_min = self.y_baseline
        
        # Phase 2: Movement collection
        print(f"Phase 2: Movement detection for {calibration_time} seconds...")
        movement_end_time = neutral_end_time + calibration_time
        last_display_update = 0  # Reset for phase 2
        
        while time.monotonic() < movement_end_time:
            current_time = time.monotonic()
            
            # Collect accelerometer data continuously
            try:
                accel = self.mpu.acceleration
                x_degrees = (accel[0] / 9.8) * 90
                y_degrees = (accel[1] / 9.8) * 90
                
                # Gradual update filtering - reject impossible values and sudden spikes
                # Only update if reasonable (not > 90° and not too far from previous)
                if abs(x_degrees) <= 90 and abs(x_degrees - self.x_max) <= 10:
                    if x_degrees > self.x_max:
                        self.x_max = x_degrees
                        
                if abs(x_degrees) <= 90 and abs(x_degrees - self.x_min) <= 10:
                    if x_degrees < self.x_min:
                        self.x_min = x_degrees
                        
                if abs(y_degrees) <= 90 and abs(y_degrees - self.y_max) <= 10:
                    if y_degrees > self.y_max:
                        self.y_max = y_degrees
                        
                if abs(y_degrees) <= 90 and abs(y_degrees - self.y_min) <= 10:
                    if y_degrees < self.y_min:
                        self.y_min = y_degrees
                    
            except OSError:
                pass  # Continue if sensor read fails
            
            # Update display every 3 seconds
            if current_time - last_display_update >= display_update_interval or last_display_update == 0:
                remaining = max(1, int(movement_end_time - current_time))
                self._show_calibration_phase_2(remaining, self.x_min, self.x_max, self.y_min, self.y_max)
                last_display_update = current_time
            
            time.sleep(0.01)  # Short sleep for continuous data collection
        
        # Phase 3: Completion display
        print("Calibration complete!")
        print(f"Final values - X: {self.x_min:.1f}° to {self.x_max:.1f}°, Y: {self.y_min:.1f}° to {self.y_max:.1f}°")
        print(f"Baseline - X: {self.x_baseline:.1f}°, Y: {self.y_baseline:.1f}°")
        
        self._show_calibration_complete(self.x_min, self.x_max, self.y_min, self.y_max)
        time.sleep(2)  # Show completion for 2 seconds
        
        # Mark as calibrated
        self.calibrated = True
        
        # Restore menu display
        self._restore_menu_display()
    
    def force_calibration(self):
        if self.debug:
            print("Forcing accelerometer calibration...")
        self.calibrated = False
        self.last_on_transition_time = 0  # Reset transition tracking
        self.calibrate()
    
    def is_calibrated(self):
        return self.calibrated
    
    def has_valid_calibration_data(self):
        return (self.calibrated and 
                self.x_max != self.x_min and 
                self.y_max != self.y_min and
                abs(self.x_max - self.x_min) > C.ACCEL_DEADZONE_DEGREES * 2 and
                abs(self.y_max - self.y_min) > C.ACCEL_DEADZONE_DEGREES * 2)

    def _show_calibration_phase_1(self, seconds_left, x_baseline=0, y_baseline=0):
        display.show_text_top(f"Accel Cal ({seconds_left}s)", notification=True)
        display.show_text_middle([
            "Keep device FLAT",
            "and STEADY", 
            f"Base: X={x_baseline:.0f} Y={y_baseline:.0f}"
        ])
        display.show_text_bottom("Neutralizing...")
        from display import display_manager
        display_manager.check_show_display()

    def _show_calibration_phase_2(self, seconds_left, x_min, x_max, y_min, y_max):
        x_range = abs(x_max - x_min)
        y_range = abs(y_max - y_min)
        
        display.show_text_top(f"Accel Cal ({seconds_left}s)", notification=True)
        display.show_text_middle([
            "TILT ALL DIRECTIONS",
            f"X: {x_min:.0f} to {x_max:.0f} ({x_range:.0f})",
            ""
        ])
        display.show_text_bottom(f"Y: {y_min:.0f} to {y_max:.0f} ({y_range:.0f})")
        from display import display_manager
        display_manager.check_show_display()

    def _show_calibration_complete(self, x_min, x_max, y_min, y_max):
        x_range = abs(x_max - x_min)
        y_range = abs(y_max - y_min)
        
        display.show_text_top("Cal Complete!", notification=True)
        display.show_text_middle([
            "Final ranges:",
            f"X: {x_range:.0f} range",
            f"Y: {y_range:.0f} range"
        ])
        display.show_text_bottom("Returning to menu...")
        from display import display_manager
        display_manager.check_show_display()

    def _restore_menu_display(self):
        try:
            from menus import Menu
            Menu.current_menu.display()  # Refresh menu content
            display.show_text_top(Menu.get_current_title_text())  # Restore menu title
            from display import display_manager
            display_manager.check_show_display()
        except ImportError:
            # Fallback if Menu import fails
            print("Could not restore menu display - Menu import failed")
            display.show_text_top("DJBB MIDI LOOPSTER")
            display.show_text_middle("Ready")
            from display import display_manager
            display_manager.check_show_display()

    def get_cc_data(self):
        # Return the list directly and let caller consume it before next update
        # Avoids memory allocation from copy()
        data = self.cc_data
        self.cc_data = []  # Create new empty list for next cycle
        return data
    
    def should_trigger_arp_note(self):
        if not self.has_accelerometer:
            return False
            
        if self.cached_accel_reading is None:
            return False
        
        # Must be enabled
        if not self.is_enabled():
            return False
        
        try:
            # Forward tilt uses positive Y axis specifically
            tilt_value = self.cached_accel_reading[1]
            tilt_degrees = (tilt_value / 9.8) * 90
            
            # Only trigger arp on forward tilt (positive Y values relative to baseline)
            # Use calibrated baseline if available
            if self.has_valid_calibration_data():
                baseline = self.y_baseline
                max_tilt = self.y_max
                
                # Check if we're within the deadzone from baseline (forward direction only)
                if tilt_degrees <= (baseline + C.ACCEL_DEADZONE_DEGREES):
                    # Reset timer when returning to deadzone
                    self.arp_current_interval_ms = None
                    self.arp_locked_interval_ms = None
                    self.arp_last_trigger_time = 0
                    return False
                
                # Calculate effective tilt using calibrated values
                effective_tilt = tilt_degrees - baseline - C.ACCEL_DEADZONE_DEGREES
                max_effective_tilt = max_tilt - baseline - C.ACCEL_DEADZONE_DEGREES
                
                if max_effective_tilt <= 0:
                    self.arp_current_interval_ms = None
                    self.arp_locked_interval_ms = None
                    self.arp_last_trigger_time = 0
                    return False
                    
                tilt_ratio = min(effective_tilt / max_effective_tilt, 1.0)
            else:
                # Fallback: without calibration, forward tilt is positive degrees from zero
                if tilt_degrees < C.ACCEL_DEADZONE_DEGREES:
                    # Reset timer when returning to deadzone
                    self.arp_current_interval_ms = None
                    self.arp_locked_interval_ms = None
                    self.arp_last_trigger_time = 0
                    return False
                
                effective_tilt = tilt_degrees - C.ACCEL_DEADZONE_DEGREES
                max_effective_tilt = C.ACCEL_ARP_MAX_TILT_DEGREES - C.ACCEL_DEADZONE_DEGREES
                tilt_ratio = min(effective_tilt / max_effective_tilt, 1.0)
            
            # Calculate the current interval based on tilt
            interval_range = C.ACCEL_ARP_MAX_INTERVAL_MS - C.ACCEL_ARP_MIN_INTERVAL_MS
            self.arp_current_interval_ms = C.ACCEL_ARP_MAX_INTERVAL_MS - (tilt_ratio * interval_range)
            
            current_time_ms = time.monotonic() * 1000
            
            # First time entering tilt zone - start timer but don't play immediately
            if self.arp_last_trigger_time == 0:
                self.arp_locked_interval_ms = self.arp_current_interval_ms
                self.arp_last_trigger_time = current_time_ms
                #print("ARP: Start timer, interval=", int(self.arp_locked_interval_ms), "ratio=", round(tilt_ratio, 2))
                return False  # Don't play immediately, wait for timer
                
            time_since_last = current_time_ms - self.arp_last_trigger_time
            
            # Use the locked interval for timing (prevents mid-cycle changes)
            if time_since_last >= self.arp_locked_interval_ms:
                # Lock in the new interval for the next cycle
                self.arp_locked_interval_ms = self.arp_current_interval_ms
                self.arp_last_trigger_time = current_time_ms
                #print("ARP TRIGGER!")
                return True
            
            return False
            
        except Exception as e:
            if self.debug:
                print(f"Error in accelerometer arp control: {e}")
            self.arp_current_interval_ms = None
            return False

accelerometer = AccelerometerController()

def should_trigger_accelerometer_arp():
    return accelerometer.should_trigger_arp_note()

def update_accelerometer():
    accelerometer.update()

accel_cc_data = []

def get_accel_cc_data():
    global accel_cc_data
    accel_cc_data = accelerometer.get_cc_data()
    return accel_cc_data

def force_accelerometer_calibration():
    accelerometer.force_calibration()

def handle_new_notes_on(noteval, velocity, padidx, midi_channel):
    return

def handle_new_notes_off(noteval, velocity, padidx, midi_channel):
    return

def handle_new_cc(cc_num, cc_val, midi_channel):
    return