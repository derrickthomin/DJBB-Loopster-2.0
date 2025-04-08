from utils import free_memory, show_memory
from buttons import Button  

# Standard library imports
import time
import board
import digitalio
import rotaryio
import keypad

# Project-specific imports (ordered by usage frequency or dependency)
from debug import print_debug
import constants
from settings import settings
from midi import midi
from chordmanager import chord_manager
from arp import arpeggiator
from menus import Menu
from pixels import pixels
from playmenu import get_midi_note_name_text
from looper import MidiLoop

class Inputs:
    
    def __init__(self):

        # hardware 
        self.note_buttons = []
        self.fn_button = None
        self.encoder_button = None
        self.encoder_delta = 0
        self._pads = None
        self.encoder = None
        self._encoder_button = None
        self._fn_button = None

        # state-related 
        self.velocity_map_mode_midi_val = None
        self.is_any_pad_held = False
        self.note_states = [False] * 16
        self.new_notes_on = []  # list of tuples: (note, velocity)
        self.new_notes_off = []

        # timing
        self.last_nav_check_time = 0
        self.time_since_last_check = 0
        
    def initialize(self):
        """
        Initializes the Inputs class by setting up hardware inputs and buttons.
        This should be called once at the start of the program to set up the hardware.
        """
        self.initialize_hardware_inputs()
        self.initialize_buttons()


    def initialize_hardware_inputs(self):   

        if self._pads is None: # Check if already initialized
            self._pads = keypad.KeyMatrix(
                row_pins=(board.GP4, board.GP3, board.GP2, board.GP1),
                column_pins=(board.GP5, board.GP6, board.GP7, board.GP8),
                columns_to_anodes=True,)
        
        if self._fn_button is None:
            self._fn_button = digitalio.DigitalInOut(constants.SELECT_BTN)
            self._fn_button.direction = digitalio.Direction.INPUT
            self._fn_button.pull = digitalio.Pull.UP

        if self._encoder_button is None:
            self._encoder_button = digitalio.DigitalInOut(constants.ENCODER_BTN)
            self._encoder_button.direction = digitalio.Direction.INPUT
            self._encoder_button.pull = digitalio.Pull.UP

        if self.encoder is None:
            self.encoder = rotaryio.IncrementalEncoder(constants.ENCODER_DT, constants.ENCODER_CLK)

    def initialize_buttons(self):
        self.fn_button = Button()
        self.encoder_button = Button()
        for i in range(16):
            btn = Button(pad_index=i)  # Create a button for each pad
            self.note_buttons.append(btn)
            print(btn.pad_idx, f"Initialized button for pad {i}")  # Debug statement to confirm initialization

    def get_button_states_list(self):
        """
        Returns the current states of the note buttons as a list of boolean values.
        This is useful for checking which pads are currently pressed.

        Returns:
            list: A list of boolean values representing the state of each note button.
        """
        button_states = []
        for button in self.note_buttons:
            button_states.append(button.state)
        return button_states

    def handle_velocity_mode(self,pad_idx):
        """Handles the logic for velocity play mode.

        Args:
            pad_idx (int): The index of the button pressed.
        """
        # Turn off single note mode
        if self.velocity_map_mode_midi_val is not None:
            self.velocity_map_mode_midi_val = None
            settings.velocity_mapped = False
            pixels.display_velocity_map(False)
            Menu.show_notification("Single Note Mode: OFF")
            
        # Turn on single note mode
        else:
            self.velocity_map_mode_midi_val = midi.get_midi_note_by_idx(pad_idx)
            pixels.display_velocity_map(True)
            settings.velocity_mapped = True
            Menu.show_notification(
                f"Pads mapped to: {get_midi_note_name_text(self.velocity_map_mode_midi_val)}")
            return

    def process_nav_buttons(self):
        """
        Update the navigation control states and trigger corresponding actions based on button presses and holds.
        This function manages the state and behavior of the fn button and encoder button.

        Usage:
            Call this function in a loop to continuously monitor and react to button presses and holds.

        Example:
            process_nav_buttons()
        """

        # Check for extreme latency. Just reset everything if it's too high
        # DJT - try deleting this
        self.time_since_last_check = time.monotonic() - self.last_nav_check_time
        self.last_nav_check_time = time.monotonic()

        # Update current state of fn button and encoder button
        self.fn_button.set_current_value(self._fn_button.value)
        self.encoder_button.set_current_value(self._encoder_button.value)  

        # Handle fn button release
        if self.fn_button.value and self.fn_button.state:
            self.fn_button.update_double_press() 

            if self.fn_button.is_held:
                fn_button_held_fn = Menu.current_menu.actions.get('fn_button_held_function')
                if fn_button_held_fn:
                    fn_button_held_fn(True)  # Runs once when released
            else:
                fn_button_press_fn = Menu.current_menu.actions.get('fn_button_press_function')
                if fn_button_press_fn:
                    fn_button_press_fn(action_type="release")

            self.fn_button.reset_state_and_time()  # Reset the state after handling the release
            Menu.toggle_fn_button_icon(False)
            if MidiLoop.current_loop.is_recording:
                pixels.set_fn_button_on(color=constants.RED)
                pixels.set_blink(16, True)
            elif MidiLoop.current_loop.loop_is_playing:
                pixels.set_blink(16, False)
                pixels.set_fn_button_on(color=constants.PIXEL_LOOP_PLAYING_COLOR)
            else:
                pixels.set_blink(16, False)
                pixels.set_fn_button_off()

        # Handle fn button press
        new_fn_button_press = self.fn_button.check_new_press()

        if new_fn_button_press:
            if not Menu.current_idx == 2:
                pixels.set_fn_button_on(color=constants.FN_BUTTON_COLOR)

            # Check if double press
            fn_double_press = self.fn_button.check_double_press()
            if fn_double_press:
                action_fn = Menu.current_menu.actions.get('fn_button_dbl_press_function')
                if action_fn:
                    action_fn()
                    if settings.get_play_mode() == "encoder":
                        Menu.toggle_lock_mode(True)
                    else:
                        Menu.toggle_lock_mode(False)
                print_debug("Select Button Double Press")

            # Select button single press
            else:
                self.fn_button.reset_double_press()  # Reset double press state
                action_fn = Menu.current_menu.actions.get('fn_button_press_function')
                if action_fn:
                    action_fn(action_type="press")
                
        # Handle fn button held
        fn_button_held = self.fn_button.check_if_held()
        if fn_button_held:
            if self.time_since_last_check <= 0.5: # djt - need this? 
                Menu.toggle_fn_button_icon(True)
                action_fn = Menu.current_menu.actions.get('fn_button_held_function')
                if action_fn:
                    action_fn()  # Runs once when first held
                pixels.set_fn_button_on(color=constants.PAD_HELD_COLOR)
                print_debug("Select Button Held")

        # Handle encoder button press
        encoder_button_press = self.encoder_button.check_new_press()
        if encoder_button_press:
            
            # Encoder button double press
            encoder_button_dbl_press = self.encoder_button.check_double_press()
            if encoder_button_dbl_press:
                Menu.toggle_nav_mode()  # Account for first click changing this
                Menu.toggle_lock_mode()
                print_debug("Encoder Button Double Press")
            
            # Encoder button single press
            else:
                self.encoder_button.reset_double_press()  # Reset double press state/time
                print_debug("New encoder Btn Press!!!")

        # Handle encoder button held
        encoder_button_held = self.encoder_button.check_if_held()
        if encoder_button_held:
            action_fn = Menu.current_menu.actions.get('encoder_button_held_function')
            if action_fn:
                action_fn()
            print_debug("encoder Button Held")

        # Handle encoder button release
        encoder_release = self.encoder_button.check_new_release()
        if encoder_release:
            if Menu.is_locked:
                return
            
            if not self.encoder_button.new_release_from_held:  # If not first release after hold
                Menu.toggle_nav_mode()

            else:
                action_fn = Menu.current_menu.actions.get('encoder_button_held_function')
                if action_fn:
                    action_fn(True)

    free_memory()
    show_memory("After process_nav_buttons")

    def handle_encoder_arp_mode(self, button, play_mode, pad_idx):

        if button.new_release:
            if play_mode == "encoder" and not chord_manager.chord_loops[pad_idx]:
                pixels.set_default_color(pad_idx)
                pixels.set_color(pad_idx,pixels.get_default_color(pad_idx))

            if play_mode == "encoder" and chord_manager.chord_loops[pad_idx]:
                pixels.set_default_color(pad_idx, constants.CHORD_COLOR)
                pixels.set_color(pad_idx, constants.CHORD_COLOR)
            
        if button.state:

            if play_mode == "encoder" and button.new_press:
                pixels.set_default_color(pad_idx, constants.PAD_HELD_COLOR)
                pixels.set_color(pad_idx, constants.PAD_HELD_COLOR)

            # Turn off notes - encoder ccw
            if self.encoder_delta < 0:
                note = midi.get_midi_note_by_idx(pad_idx)
                if self.velocity_map_mode_midi_val:
                    note = self.velocity_map_mode_midi_val
                for note in midi.current_notes():
                    self.new_notes_off.append((note, 0, pad_idx))

            # Turn on notes - encoder cw
            if self.encoder_delta > 0:
                note = midi.get_midi_note_by_idx(pad_idx)
                if self.velocity_map_mode_midi_val:
                    note = self.velocity_map_mode_midi_val
                velocity = midi.get_velocity_by_idx(pad_idx)

                # If chord exists, get chord notes
                if play_mode == "encoder" and chord_manager.chord_loops[pad_idx]:
                    notes = chord_manager.unique_notes(pad_idx)
                    for note in notes:
                        arpeggiator.add_arp_note(note)

                # Single Note
                else:
                    print_debug(f"adding arp single note {note}")
                    arpeggiator.add_arp_note((note, velocity, pad_idx))

    def process_inputs_slow(self):
        """
        Process inputs at a slower rate, handling encoder movements and button holds.

        This function updates the state of the encoder and buttons, processes navigation buttons,
        and triggers corresponding actions based on button presses, holds, and encoder movements.

        Usage:
            Call this function in a loop to continuously monitor and react to inputs at a slower rate.

        Example:
            process_inputs_slow()
        """

        global encoder

        hold_count = 0
        self.encoder_delta = self.encoder.position
        self.encoder.position = 0

        # Process each button (drum pad)

        for button in self.note_buttons:
            idx = button.pad_idx
            button_held = button.check_if_held()  # Check if the button is held
            if button_held:
                hold_count += 1
                if not self.is_any_pad_held:
                    self.is_any_pad_held = True
                    action_fn = Menu.current_menu.actions.get('pad_held_function')
                    if action_fn:
                        action_fn(idx, "", 0)

        # Handle encoder change if any
        if self.encoder_delta != 0:
            action_fn = Menu.current_menu.actions.get('pad_held_function')
            if action_fn:
                action_fn(-1, self.get_button_states_list(), self.encoder_delta)

        # Catch stray encoder turns meant for pads
        if hold_count == 0 and self.is_any_pad_held:
            self.is_any_pad_held = False
            self.encoder_delta = 0

        self.process_nav_buttons()

        if self.is_any_pad_held or Menu.is_locked:  # already processed in pad_held_function or locked
            return

        # Determine encoder direction
        if self.encoder_delta == 0:
            return

        encoder_direction = self.encoder_delta > 0

        # Change menu if in navigation mode
        if Menu.is_nav_mode:
            Menu.next_or_prev_menu(encoder_direction)
            return

        # Handle fn button held and encoder change
        if self.fn_button.is_held:
            action_fn = Menu.current_menu.actions.get('fn_button_held_and_encoder_change_function')
            if action_fn:
                action_fn(encoder_direction)
            return

        # Handle encoder button held and turn
        if self.encoder_button.is_held:
            encoder_button_press_and_turn_fn = Menu.current_menu.actions.get('encoder_button_press_and_turn_function')
            if encoder_button_press_and_turn_fn:
                encoder_button_press_and_turn_fn(encoder_direction)
            return

        # Handle encoder change
        action_fn = Menu.current_menu.actions.get('encoder_change_function')
        if action_fn:
            action_fn(encoder_direction)

    free_memory()
    show_memory("After process_inputs_slow")

    def process_inputs_fast(self):
        """
        Process inputs from the pads and buttons at a faster rate.

        This function updates the state of the buttons and triggers corresponding actions based on button presses
        and releases. It also handles the behavior of the fn button and encoder button in different play modes.

        Usage:
            Call this function in a loop to continuously monitor and react to button presses and releases.

        Example:
            process_inputs_fast()
        """


        #Reset states, notes
        for button in self.note_buttons:
            button.reset_actions()

        self.new_notes_on = []
        self.new_notes_off = []

        # Clear any OFF arp notes
        new_arp_off_notes = arpeggiator.get_off_notes()
        if new_arp_off_notes:
            for note in new_arp_off_notes:
                self.new_notes_off.append(note)
        
        # Update buttons, cache play_mode
        new_press_indicies = self.process_keymatrix()
        play_mode = settings.get_play_mode()

        # Handle fn button held
        if self.fn_button.is_held and len(new_press_indicies) > 0:
            for pad_idx in new_press_indicies:

                if play_mode == "velocity":
                    self.handle_velocity_mode(pad_idx)
                    
                if play_mode == "chord" and Menu.current_idx != 2: # Dont do this in looper mode
                    chord_manager.add_remove_chord(pad_idx)
                    
                self.note_buttons[pad_idx].reset_new_press()  # Reset the button's actions to avoid double processing


        # ----- Encoder / Arpeggiator Play Mode -----
        if play_mode in ["encoder", "chord"]:

            if self.encoder_delta > 0:
                if arpeggiator.skip_this_turn():
                    return
                arpeggiator.clear_arp_notes() # Reset arp notes to track if changed
            
            for button in self.note_buttons:
                pad_idx = button.pad_idx
                self.handle_encoder_arp_mode(button, play_mode, pad_idx)  

            # Add new Arp Notes
            if arpeggiator.has_notes() and self.encoder_delta > 0:
                self.encoder_delta = 0
                if not settings.arp_is_polyphonic:
                    last_note = arpeggiator.get_previous_note()
                    if last_note is not None:
                        self.new_notes_off.append(last_note)
                note = arpeggiator.get_next_arp_note()
                self.new_notes_on.append(note)
                print_debug(f"new arp note on {note}")
        
        if play_mode == "encoder":
            return

        for button in self.note_buttons:
            pad_idx = button.pad_idx

            if not button.new_press and not button.new_release:
                continue

            # ----- Handle Normal Presses -------
            if self.velocity_map_mode_midi_val is not None:
                note = self.velocity_map_mode_midi_val
                velocity = midi.get_velocity_singlenote_by_idx(pad_idx)
            else:
                note = midi.get_midi_note_by_idx(pad_idx)
                velocity = midi.get_velocity_by_idx(pad_idx)

            # New Press - Play note or chord
            if button.new_press:
                print_debug(f"new press on {pad_idx}")
                if chord_manager.chord_loops[pad_idx] and not chord_manager.is_recording:
                    chord_manager.toggle_chord_playstate(pad_idx)
                else:
                    self.new_notes_on.append((note, velocity, pad_idx))

            # New Release - Stop note or chord
            if button.new_release and not (chord_manager.chord_loops[pad_idx] and not chord_manager.is_recording):
                self.new_notes_off.append((note, 127, pad_idx))

    def process_keymatrix(self):
        new_press_indicies = []
        while True:  # Process until queue is empty
            event = self._pads.events.get()
            if not event:
                break
            pad_idx = event.key_number
            idx = self.note_buttons[pad_idx].process_keymatrix_event(event)
            if idx is not None:
                new_press_indicies.append(pad_idx)  # Changed to use pad_idx directly
                print_debug(f"Processed event for pad {pad_idx}")
        return new_press_indicies

inputs = Inputs()