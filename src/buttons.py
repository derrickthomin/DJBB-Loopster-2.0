import time
from debug import print_debug
import constants

HOLD_THRESH = constants.BUTTON_HOLD_THRESH_S

class Button:
    """
    A class representing a physical button with state tracking capabilities.
    
    This class tracks various button states including:
    - Basic press/release state
    - Hold detection
    - Double-press detection
    - Duration tracking
    
    The button can be used either with direct value setting or through keymatrix events.
    
    Attributes:
        value (bool): Raw input value from hardware
        state (bool): Current logical state of the button
        pad_idx (Optional[int]): Index of the pad this button represents
        label (str): Human-readable identifier for the button
        starttime (float): Timestamp when button was last pressed
        dbl_press_time (float): Timestamp of last registered double press
        new_dbl_press (bool): Flag indicating a new double press was detected
        is_held (bool): Whether button is currently being held
        new_press (bool): Flag indicating a new press was detected
        new_release (bool): Flag indicating a new release was detected
        new_release_from_held (bool): Flag indicating release from held state
        held_time_s (float): Duration button has been held
        new_hold (bool): Flag indicating hold threshold just reached
    """

    def __init__(self, pad_index = None, label = None):
        """
        Initialize a new Button instance.
        
        Args:
            pad_index: Optional index identifying this button's position in a pad matrix
            label: Optional human-readable name for this button
        """
        # Core state
        self.value = False 
        self.state = False
        self.pad_idx = pad_index
        
        # Timing
        self.starttime = 0
        self.dbl_press_time = 0
        self.held_time_s = 0
        
        # State flags
        self.new_dbl_press = False
        self.is_held = False
        self.new_press = False
        self.new_release = False
        self.new_release_from_held = False
        self.new_hold = False

        # Set label based on provided args
        if label:
            self.label = label
        elif pad_index is not None:
            self.label = f"Button {pad_index}"
        else:
            self.label = "Button"

    def reset_new_press(self):
        """Reset the new press flag to its default state."""
        self.new_press = False
        
    def reset_actions(self) -> None:
        """Reset all action flags to their default state."""
        self.new_press = False
        self.new_release = False
        self.new_hold = False
        self.new_release_from_held = False
        self.new_dbl_press = False

    def set_current_value(self, value: bool) -> None:
        """
        Set the current hardware value of the button.
        
        Args:
            value: True if button is physically pressed, False otherwise
        """
        if self.value != value:
            self.value = value

    def update_all(self) -> None:
        """
        Update all button states based on current conditions.
        
        This method should be called regularly to:
        - Detect new presses and releases
        - Update hold status and timing
        - Check for double-press conditions
        """
        now = time.monotonic()
        self.reset_actions()
        
        if not self.value and not self.state:    # New press
            self.state = True
            self.starttime = now
            self.new_press = True
            self.is_held = False
            self.new_dbl_press = False
            print_debug(f"{self.label} - New Press")
            self._check_double_press()             

        if not self.value and self.state:         # Check for hold while pressed
            self.check_if_held()

        if self.value and self.state:             # New release
            self.new_release = True
            self.state = False
            if self.is_held:
                self.new_release_from_held = True
                self.dbl_press_time = 0
                print_debug(f"{self.label} - New Release from Held. Holdtime was {self.held_time_s:.2f}s")
                self.held_time_s = 0
                self.is_held = False
            else:
                self.dbl_press_time = now
                print_debug(f"{self.label} - New Release")

    def process_keymatrix_event(self, event):
        """
        Process a keymatrix event and update button state accordingly.
        
        Args:
            event: A keymatrix event object containing pressed state
            
        Returns:
            int: The pad_idx if this was a new press, None otherwise
        """
        if event.pressed:
            if not self.state:  # New press
                self.new_press = True
                self.starttime = time.monotonic()
                self.state = True
                print(f"Button {self.pad_idx} pressed at {self.starttime:.2f}s")
                return self.pad_idx
            else:  
                self.new_press = False  # Not a new press (edge case)
                return None
        else:  # Released
            if self.state:  # Was previously pressed
                self.new_release = True
                self.state = False
                self.starttime = 0
                return None
            return None  # Release when not pressed (shouldn't happen)

    def _check_double_press(self) -> bool:
        """
        Check if current press qualifies as a double-press.
        
        Returns:
            bool: True if a double-press was detected
        """
        self.new_dbl_press = False

        if (self.starttime - self.dbl_press_time < constants.DBL_PRESS_THRESH_S):
            self.new_dbl_press = True
            self.dbl_press_time = 0
            self.starttime = time.monotonic()  # Avoid erroneous button holds
            self.new_press = False
            print_debug(f"{self.label} - New Double Press")
        return self.new_dbl_press

    def check_if_held(self) -> bool:
        """
        Check if button has been held long enough to trigger hold state.
        
        Returns:
            bool: True if button is currently held
        """
        now = time.monotonic()
        if not self.state:      # Not in a pressed state, can't be held
            self.is_held = False
            self.held_time_s = 0
            return False
        
        self.held_time_s = now - self.starttime
        if (self.state and self.held_time_s > HOLD_THRESH and not self.is_held):
            self.is_held = True
            self.new_dbl_press = False  # Clear double press if held
            self.new_hold = True
            print_debug(f"{self.label} - New Hold")
        
        return self.is_held
