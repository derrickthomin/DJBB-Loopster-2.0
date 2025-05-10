from utils import free_memory, show_memory
from buttons import Button

# Standard library imports
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
        self.encoder_button = Button(hold_thresh=constants.ENCODER_HOLD_THRESH_S)
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
    
    def call_function(self, action_key, *args, **kwargs):
        """Look up an action by key in the current menu and execute it if available.
        
        Returns True if an action was found and called, otherwise False.
        """
        action_fn = Menu.current_menu.actions.get(action_key)
        if action_fn:
            action_fn(*args, **kwargs)
            return True
        return False

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
        Process navigation button states and trigger corresponding actions.
        Handles fn button and encoder button press/hold/release states.
        Updates display icons and LEDs based on button states.
        """

        # Update button states from hardware
        self.fn_button.set_current_value(self._fn_button.value)
        self.encoder_button.set_current_value(self._encoder_button.value)
        self.fn_button.update_all()
        self.encoder_button.update_all()

        # Handle all button states before acting on any of them
        fn_released = self.fn_button.new_release_from_held or self.fn_button.new_release
        fn_pressed = self.fn_button.new_dbl_press or self.fn_button.new_press
        fn_held = self.fn_button.is_held
        
        encoder_released = self.encoder_button.new_release
        encoder_released_from_held = self.encoder_button.new_release_from_held
        encoder_dbl_pressed = self.encoder_button.new_dbl_press
        encoder_held = self.encoder_button.is_held

        # Process FN Button Actions

        # Special cases for going up and down 1/4 bank - immediate return
        if fn_held and encoder_released:
            midi.offset_pads(True)
            pixels.encoder_button_off()
            pixels.set_fn_button_off()
            return True

        if encoder_held and fn_released:
            midi.offset_pads(False)
            pixels.encoder_button_off()
            pixels.set_fn_button_off()
            return True
            
        if fn_released:
            self._handle_fn_button_release()

        if fn_pressed:
            self._handle_fn_button_press()  # Also handles double press
            
        if fn_held:
            self._handle_fn_button_held()

        # Process Encoder Button Actions
        if encoder_dbl_pressed:
            Menu.toggle_nav_mode()  # Account for first click changing this
            Menu.toggle_lock_mode()

        if Menu.is_locked:
            return False
        
        if encoder_held:
            self.call_function('encoder_button_held_function')

        if encoder_released:
            if encoder_released_from_held:
                self.call_function('encoder_button_held_function', True)
            else:
                Menu.toggle_nav_mode()
                
        return False

    def _handle_fn_button_release(self):
        """Handle fn button release states and update visuals."""
        if not (self.fn_button.new_release_from_held or self.fn_button.new_release):
            return False
        print("fn button released")
        # Handle release from held state
        if self.fn_button.new_release_from_held:
            self.call_function('fn_button_held_function', True)
        else:
            self.call_function('fn_button_press_function', action_type="release")

        # Update visuals
        Menu.toggle_fn_button_icon(False)
        
        # Import MidiLoop only when needed
        from looper import MidiLoop
        
        if MidiLoop.current_loop.is_recording:
            pixels.set_fn_button_on(color=constants.RED)
            pixels.set_blink(16, True)
        elif MidiLoop.current_loop.loop_is_playing:
            pixels.set_blink(16, False)
            pixels.set_fn_button_on(color=constants.PIXEL_LOOP_PLAYING_COLOR)
        else:
            pixels.set_blink(16, False)
            pixels.set_fn_button_off()
        
        return True

    def _handle_fn_button_press(self):
        """Handle fn button press states and trigger actions."""
        if not (self.fn_button.new_dbl_press or self.fn_button.new_press):
            return False
        
        from looper import MidiLoop
        
        # If anything is recording, intercept the fn button press
        if chord_manager.is_recording:
            chord_manager.handle_fn_press()
            return True
        
        if MidiLoop.current_loop.is_recording:
            MidiLoop.current_loop.toggle_record_state()
            return True

        # Handle double press
        if self.fn_button.new_dbl_press:
            action_fn_ran = self.call_function('fn_button_dbl_press_function')
            if action_fn_ran:
                Menu.toggle_lock_mode(settings.get_play_mode() == "encoder")
            return True

        # Handle single press
        if self.fn_button.new_press:
            self.call_function('fn_button_press_function', action_type="press")
            if Menu.current_idx != 2:
                pixels.set_fn_button_on(color=constants.FN_BUTTON_COLOR)
            return True

        return False

    def _handle_fn_button_held(self):
        """Handle fn button held state and update visuals."""
        Menu.toggle_fn_button_icon(True)
        self.call_function('fn_button_held_function')
        pixels.set_fn_button_on(color=constants.PAD_HELD_COLOR)

    free_memory()
    show_memory("After process_nav_buttons")

    def handle_encoder_arp_mode(self, button, play_mode, pad_idx):
        """
        Handles encoder-based arpeggiator functionality for a specific pad button.
        
        Args:
            button (Button): The button being processed
            play_mode (str): Current play mode ("encoder" or "chord")
            pad_idx (int): Index of the pad being processed
        """
        # Handle button release - update visuals
        if button.new_release and play_mode == "encoder":
            color = constants.CHORD_COLOR if chord_manager.chord_loops[pad_idx] else pixels.get_default_color(pad_idx)
            pixels.set_default_color(pad_idx, color)
            pixels.set_color(pad_idx, color)
            
        if not button.state:
            return

        # Handle new press in encoder mode
        if play_mode == "encoder" and button.new_press:
            pixels.set_default_color(pad_idx, constants.PAD_HELD_COLOR)
            pixels.set_color(pad_idx, constants.PAD_HELD_COLOR)

        # Get note for this pad
        note = (self.velocity_map_mode_midi_val if self.velocity_map_mode_midi_val 
               else midi.get_midi_note_by_idx(pad_idx))

        # Turn off notes on CCW encoder turn
        if self.encoder_delta < 0:
            for note in midi.current_notes():
                self.new_notes_off.append((note, 0, pad_idx))

        # Turn on notes on CW encoder turn
        if self.encoder_delta > 0:
            if play_mode == "encoder" and chord_manager.chord_loops[pad_idx]:
                # Add chord notes to arpeggiator
                for note in chord_manager.unique_notes(pad_idx):
                    arpeggiator.add_arp_note(note)

                for cc in chord_manager.unique_ccs(pad_idx):
                    arpeggiator.add_arp_cc(cc)
            else:
                # Add single note to arpeggiator
                velocity = midi.get_velocity_by_idx(pad_idx)
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

        hold_count = 0
        update_midtext = False
        self.encoder_delta = self.encoder.position
        self.encoder.position = 0

        hold_count = self._process_button_holds()
        # Check for new holds
        # for button in self.note_buttons:
        #     idx = button.pad_idx
        #     button_held = button.check_if_held()  # Check if the button is held
        #     if button_held:
        #         hold_count += 1
        #         if not self.is_any_pad_held:
        #             self.is_any_pad_held = True
        #             self.call_function('pad_held_function', idx, "", 0)

        # Handle encoder change
        if self.encoder_delta != 0:
            self.call_function('pad_held_function', -1, self.get_button_states_list(), self.encoder_delta)

        # Catch stray encoder turns meant for pads
        if hold_count == 0 and self.is_any_pad_held:
            self.is_any_pad_held = False
            self.encoder_delta = 0

        update_midtext = self.process_nav_buttons()

        # ---------- STOP EARLY POINT --------
        if self.is_any_pad_held or Menu.is_locked or self.encoder_delta == 0:  # already processed in pad_held_function or locked
            return False

        encoder_direction = self.encoder_delta > 0
        if Menu.is_nav_mode:
            Menu.next_or_prev_menu(encoder_direction)
            return False
        
        if self.fn_button.is_held:
            self.call_function('fn_button_held_and_encoder_change_function', encoder_direction)
            return False

        if self.encoder_button.is_held:
            self.call_function('encoder_button_press_and_turn_function', encoder_direction)
            return False

        # Default
        self.call_function('encoder_change_function', encoder_direction)

    free_memory()
    show_memory("After process_inputs_slow")

    def _process_button_holds(self):
        hold_count = 0
        for button in self.note_buttons:
            idx = button.pad_idx
            button_held = button.check_if_held()  # Check if the button is held
            if button_held:
                hold_count += 1
                if not self.is_any_pad_held:
                    self.is_any_pad_held = True
                    self.call_function('pad_held_function', idx, "", 0)
        return hold_count

    def process_inputs_fast(self):
        """
        Process button inputs and handle note/chord triggering based on current play mode.
        Runs at a higher frequency than process_inputs_slow.
        """
        # Reset states and process matrix events
        self.reset_pads_and_notes()
        self.new_notes_off.extend(arpeggiator.get_off_notes())
        new_press_indices = self.process_keymatrix()
        play_mode = settings.get_play_mode()

        # Handle fn button special cases
        if self.fn_button.is_held and new_press_indices:
            self.handle_fn_button_held_fast(new_press_indices)
            return

        # Handle encoder/arpeggiator modes
        if play_mode in ["encoder", "chord"]:
            if self.encoder_delta > 0 and not arpeggiator.skip_this_turn():
                arpeggiator.clear_arp_notes()
            
            # Only process buttons that are pressed/held or just released
            for button in self.note_buttons:
                if button.state or button.new_release:
                    self.handle_encoder_arp_mode(button, play_mode, button.pad_idx)

            self.play_arp_events()
            
            if play_mode == "encoder":
                return

        # Process regular note triggering
        for button in self.note_buttons:
            if not (button.new_press or button.new_release):
                continue
            
            pad_idx = button.pad_idx
            note, velocity = self.get_note_and_velocity(pad_idx)

            # Handle press - either trigger chord or note
            if button.new_press:
                print_debug(f"new press on {pad_idx}")
                if chord_manager.chord_loops[pad_idx] and not chord_manager.is_recording:
                    chord_manager.toggle_chord_playstate(pad_idx)
                else:
                    self.new_notes_on.append((note, velocity, pad_idx))

            # Handle release - stop note unless it's a non-recording chord
            if button.new_release and not (chord_manager.chord_loops[pad_idx] 
                                         and not chord_manager.is_recording):
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

        return new_press_indicies

    def reset_pads_and_notes(self):
        #Reset states, new notes
        for button in self.note_buttons:
            button.reset_actions()

        self.new_notes_on = []
        self.new_notes_off = []
    
    def handle_fn_button_held_fast(self, new_press_indicies):
        """
        Handle the fn button being held down in fast input mode.
        
        This function is called when the fn button is held down and processes the action
        associated with the current menu's 'fn_button_held_function'.
        
        Usage:
            Call this function when the fn button is held down to trigger the corresponding action.

        Example:
            handle_fn_button_held_fast()
        """
        play_mode = settings.get_play_mode()
        for pad_idx in new_press_indicies:

            if play_mode == "velocity":
                self.handle_velocity_mode(pad_idx)
                
            if play_mode == "chord" and Menu.current_idx != 2: # Dont do this in looper mode
                chord_manager.add_remove_chord(pad_idx)
                
            self.note_buttons[pad_idx].reset_new_press()  # Reset the button's actions to avoid double processing

    def play_arp_events(self):
        """
        Gets the next arpeggiator note and CC values, and adds them to the appropriate queues for processing.
        This method handles both MIDI notes and CC events from the arpeggiator.
        """
        if not (arpeggiator.has_events() or arpeggiator.has_ccs()) or self.encoder_delta <= 0:
            return
        
        self.encoder_delta = 0
        
        # Handle note transitions if we have notes and aren't in polyphonic mode
        if arpeggiator.has_events() and not settings.arp_is_polyphonic:
            last_note = arpeggiator.get_previous_note()
            if last_note is not None:
                self.new_notes_off.append(last_note)
        
        # Get next note and CC value
        result = arpeggiator.get_next_arp_events()
        if not result:
            return
            
        note, cc_event = result
        
        # Add note to the notes_on queue if available
        if note:
            self.new_notes_on.append(note)
            print_debug(f"new arp note on {note}")
            
        # Add CC event to the CC queue if available
        if cc_event:
            # Send directly to MIDI handler
            midi.send_cc(cc_event[0], cc_event[1])
            print_debug(f"new arp CC: {cc_event[0]}={cc_event[1]}")

    def get_note_and_velocity(self, pad_idx):
            
        if self.velocity_map_mode_midi_val is not None:
            note = self.velocity_map_mode_midi_val
            velocity = midi.get_velocity_singlenote_by_idx(pad_idx)
        else:
            note = midi.get_midi_note_by_idx(pad_idx)
            velocity = midi.get_velocity_by_idx(pad_idx)
        
        return note, velocity

inputs = Inputs()