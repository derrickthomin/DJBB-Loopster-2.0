
import time
import constants

HOLD_THRESH = constants.BUTTON_HOLD_THRESH_S

class Button:
    """
    Class representing a button with a label and an action.
    """
    def __init__(self, pad_index = None):
        self.value = False 
        self.state = False
        self.pad_idx = pad_index
        self.starttime = 0
        self.dbl_press = False
        self.dbl_press_time = 0
        self.new_dbl_press = False
        
        self.is_held = False
        self.new_press = False
        self.new_release = False
        self.new_release_from_held = False
        self.held_time_s = 0
        self.new_hold = False

    def reset_actions(self):
        """
        Resets the button's action states.

        """
        self.new_press = False
        self.new_release = False
        self.new_hold = False
        self.new_release_from_held = False
        self.new_dbl_press = False

    def set_current_value(self, value: bool):
        """
        Sets the current value of the button and updates the state accordingly.
        
        Args:
            value(bool): The current state of the button (True for pressed, False for not pressed).
        """
        if self.value != value:
            self.value = value

    def update_double_press(self):
        if self.is_held:
            self.dbl_press_time = 0
        else:
            self.dbl_press_time = time.monotonic()

    def reset_new_press(self):
        self.new_press = False
    
    def reset_double_press(self):
        """
        Resets the double press state and time.
        """
        self.dbl_press = False
        self.dbl_press_time = 0
        self.new_dbl_press = False
    
    def reset_state_and_time(self):
        self.is_held = False
        self.state = False
        self.starttime = 0
    
    def process_keymatrix_event(self, event):
        """
        Processes a key matrix event to update the button's state.
        Only called when adafruit keymatrix detects a key press or release.
        
    Returns:
            int: pad_idx if this was a new press, None otherwise
        """
        if event.pressed:
            if not self.state:  # New press
                self.new_press = True
                self.starttime = time.monotonic()
                self.state = True
                print(f"Button {self.pad_idx} pressed at {self.starttime:.2f}s")  # Debug log for new press
                return self.pad_idx
            else:  
                self.new_press = False # Not a new press. Edge case. 
                return None
        else:  # Released
            if self.state:  # Was previously pressed
                self.new_release = True
                self.state = False
                self.starttime =0
                return None
            # Else: got release event but wasn't pressed (shouldn't happen)
            return None

    def check_new_press(self):
        new_press = False

        if not self.value and not self.state:
            self.state = True
            self.starttime = time.monotonic()
            self.new_press = True
            self.is_held = False
            self.dbl_press = False
            new_press = True

        return new_press

    def check_double_press(self):
        new_double_press = False

        if (self.starttime - self.dbl_press_time < constants.DBL_PRESS_THRESH_S) and not self.dbl_press:
            self.dbl_press = True
            self.dbl_press_time = 0
            self.new_dbl_press = True
            self.starttime = time.monotonic()  # Avoid erroneous button holds
            new_double_press = True
        return new_double_press
    
    def check_if_held(self):
        is_held = False

        now = time.monotonic()
        if not self.state:      # Not in a pressed state, can't be held
            self.is_held = False
            self.held_time_s = 0
            return is_held
        
        self.held_time_s = now - self.starttime  # Set held time
        if (self.state and self.held_time_s > HOLD_THRESH and not self.is_held):
            is_held = True
            self.is_held = True
            self.dbl_press = False  # Clear double press if held
            self.new_hold = True  # Mark that we have a new hold
        
        return is_held
    
    def check_new_release(self):
        new_release = False

        if self.value and self.state:
            new_release = True
            if self.is_held:
                self.dbl_press_time = 0                 # Clear double press time if released from held
                self.new_release_from_held = True         # Mark that the release was from a held state
            else:
                self.dbl_press_time = time.monotonic()  # Set the time for double press if released normally
                self.new_release_from_held = False
            self.state = False
            self.is_held = False
            self.new_release = True
            self.starttime = 0  # Reset start time

        return new_release
