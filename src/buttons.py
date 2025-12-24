import time
import constants as C

class Button:
    """Button state tracker: press, release, hold, double-press."""
    
    __slots__ = ('value', 'state', 'pad_idx', 'new_dbl_press', 'is_held', 
                 'new_press', 'new_release', 'new_release_from_held', 'new_hold',
                 'ignore_next_release', 'hold_thresh', 'starttime', 'dbl_press_time',
                 'held_time_s', 'label')

    def __init__(self, pad_index = None, label = None, hold_thresh = C.BUTTON_HOLD_THRESH_S):
        # States
        self.value = False 
        self.state = False
        self.pad_idx = pad_index
        self.new_dbl_press = False
        self.is_held = False
        self.new_press = False
        self.new_release = False
        self.new_release_from_held = False
        self.new_hold = False
        self.ignore_next_release = False   # Used to ignore release after hold
        
        # Timing
        self.hold_thresh = hold_thresh
        self.starttime = 0
        self.dbl_press_time = 0
        self.held_time_s = 0
        
        if label:
            self.label = label
        elif pad_index is not None:
            self.label = f"Button {pad_index}"
        else:
            self.label = "Button"

    def reset_new_press(self):
        self.new_press = False
        
    def reset_actions(self) -> None:
        self.new_press = False
        self.new_release = False
        self.new_hold = False
        self.new_release_from_held = False
        self.new_dbl_press = False

    def set_ignore_next_release(self):
        self.ignore_next_release = True

    def set_current_value(self, value):
        if self.value != value:
            self.value = value

    def update_all(self):
        """Update all button states based on current value."""
        now = time.monotonic()
        self.reset_actions()
        
        if not self.value and not self.state:     # New press
            self.state = True
            self.starttime = now
            self.new_press = True
            self.is_held = False
            self.new_dbl_press = False
            self._check_double_press()             

        if not self.value and self.state:          # Check for hold while pressed
            self.check_if_held()

        if self.value and self.state:              # New release
            self.new_release = True
            self.state = False
            if self.is_held:
                self.new_release_from_held = True
                self.dbl_press_time = 0
                self.held_time_s = 0
                self.is_held = False

            elif self.ignore_next_release:
                pass
            else:
                self.dbl_press_time = now
            self.ignore_next_release = False   # Reset ignore flag after processing

    def process_keymatrix_event(self, event):
        """Process keymatrix event. Returns pad_idx on new press, None otherwise."""
        # Pressed
        if event.pressed:
            if not self.state:
                self.new_press = True
                self.starttime = time.monotonic()
                self.state = True
                return self.pad_idx
            else:
                self.new_press = False 
                return None
        # Not Pressed
        else:
            if self.state:                       # Just released
                self.new_release = True
                self.state = False
                self.starttime = 0
                return None
            return None 
        
    def reset_double_press(self):
        self.dbl_press_time = 0
        self.new_dbl_press = False

    def _check_double_press(self):
        self.new_dbl_press = False

        if (self.starttime - self.dbl_press_time < C.DBL_PRESS_THRESH_S):
            self.new_dbl_press = True
            self.dbl_press_time = 0
            self.starttime = time.monotonic()   # Avoid erroneous button holds
            self.new_press = False
        return self.new_dbl_press

    def check_if_held(self) -> bool:
        now = time.monotonic()
        if not self.state:    
            self.is_held = False
            self.held_time_s = 0
            return False
        
        self.held_time_s = now - self.starttime
        if (self.state and self.held_time_s > self.hold_thresh and not self.is_held):
            self.is_held = True
            self.new_dbl_press = False           # Clear double press if held
            self.new_hold = True
        
        return self.is_held
