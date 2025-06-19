import board
import digitalio
import rotaryio
import keypad

# Local application/library imports
from buttons import Button
import constants as C
from settings import settings
from midi import midi
from chordmanager import chord_manager
from arp import arpeggiator
from menus import Menu
from pixels import pixels

class Inputs:
        
    def __init__(self):

        # Hardware
        self.note_buttons = []
        self.fn_button = None
        self.encoder_button = None
        self.encoder_delta = 0
        self._pads = None
        self.encoder = None
        self._encoder_button = None
        self._fn_button = None

        # State
        self.single_note_mode_midi_val = None
        self.is_any_pad_held = False
        self.new_notes_on = []        
        self.new_notes_off = []
        self.recording_start_pad = None  

    def initialize(self):
        """
        Initializes the Inputs class by setting up hardware inputs and buttons.
        """
        self.initialize_hardware_inputs()
        self.initialize_buttons()

    def initialize_hardware_inputs(self):   

        # Pads
        self._pads = keypad.KeyMatrix(
            row_pins=(board.GP4, board.GP3, board.GP2, board.GP1),
            column_pins=(board.GP5, board.GP6, board.GP7, board.GP8),
            columns_to_anodes=True,)
        
        # FN Button
        self._fn_button = digitalio.DigitalInOut(C.fn_btn)
        self._fn_button.direction = digitalio.Direction.INPUT
        self._fn_button.pull = digitalio.Pull.UP

        # Encoder
        self._encoder_button = digitalio.DigitalInOut(C.ENCODER_BTN)
        self._encoder_button.direction = digitalio.Direction.INPUT
        self._encoder_button.pull = digitalio.Pull.UP
        self.encoder = rotaryio.IncrementalEncoder(C.ENCODER_DT, C.ENCODER_CLK)

    def initialize_buttons(self):
        """ Create button objects after doing the initial hardware setup. """
        self.fn_button = Button(hold_thresh=C.FN_HOLD_THRESH_S)
        self.encoder_button = Button(hold_thresh=C.ENCODER_HOLD_THRESH_S)
        for i in range(C.NUM_PADS):
            btn = Button(pad_index=i)
            self.note_buttons.append(btn)

    def call_function(self, action_key, *args, **kwargs):
        """Look up an action by key in the current menu and execute it. Returns True or False. """
        action_fn = Menu.current_menu.actions.get(action_key)
        if action_fn:
            action_fn(*args, **kwargs)
            return True
        return False

    def handle_velocity_mode(self,pad_idx):
        """Toggles velocity mode: map all pads to single note or restore normal operation. Updates pixels.

        Args:
            pad_idx (int): Pad index to use for single note mapping
        """
        # Off
        if self.single_note_mode_midi_val is not None:
            self.single_note_mode_midi_val = None
            settings.velocity_mapped = False
            pixels.display_velocity_map(False)
            chord_manager.update_pad_pixels()
            return

        # On
        else:
            self.single_note_mode_midi_val = midi.get_midi_note_by_idx(pad_idx)
            pixels.display_velocity_map(True)
            settings.velocity_mapped = True
            return

    def process_nav_buttons(self):
        """
        FN Button, Encoder Button, Button Holds
        """

        # Raw hardware values
        self.fn_button.set_current_value(self._fn_button.value)
        self.encoder_button.set_current_value(self._encoder_button.value)
        self.fn_button.update_all()
        self.encoder_button.update_all()

        # Cache essential button state values
        fn_new_release_from_held = self.fn_button.new_release_from_held
        fn_new_release = self.fn_button.new_release
        fn_new_dbl_press = self.fn_button.new_dbl_press
        fn_new_press = self.fn_button.new_press
        fn_is_held = self.fn_button.is_held
        encoder_new_release = self.encoder_button.new_release
        encoder_new_release_from_held = self.encoder_button.new_release_from_held
        encoder_new_dbl_press = self.encoder_button.new_dbl_press
        encoder_is_held = self.encoder_button.is_held
        
        # Composite conditions for readability
        fn_released = fn_new_release_from_held or fn_new_release
        fn_pressed = fn_new_dbl_press or fn_new_press

        if fn_is_held and encoder_new_release: # Up 1/4 Bank
            midi.offset_pads(True)
            pixels.encoder_button_off()
            pixels.set_fn_button_off()
            self.encoder_button.reset_double_press()  # Reset to avoid double processing
            return True

        if encoder_is_held and fn_released:    # Down 1/4 Bank
            midi.offset_pads(False)
            pixels.encoder_button_off()
            pixels.set_fn_button_off()
            self.fn_button.reset_double_press()
            return True
            
        if fn_released:
            self._handle_fn_button_release()

        if fn_pressed:
            if chord_manager.is_recording:
                chord_manager.handle_fn_press()
                Menu.next_or_prev_menu(False, 0)
                self.fn_button.set_ignore_next_release()  # Reset to avoid double processing
            else:
                self._handle_fn_button_press()
            return True

        if fn_is_held:
            self._handle_fn_button_held()

        if encoder_new_dbl_press:
            Menu.toggle_nav_mode()                   # Account for first click changing this
            Menu.toggle_lock_mode()

        if Menu.is_locked:
            return False
        
        if encoder_is_held:
            pixels.encoder_button_on(color=C.PAD_HELD_COLOR)
            self.call_function('encoder_button_held_function')

        if encoder_new_release:
            if encoder_new_release_from_held:
                if Menu.is_nav_mode:
                    pixels.encoder_button_on(color=C.NAV_MODE_COLOR)
                else:
                    pixels.encoder_button_off()
                self.call_function('encoder_button_held_function', True)
            else:
                Menu.toggle_nav_mode()
                
        return False

    def _handle_fn_button_release(self):
        """Handle fn button release:"""

        if not (self.fn_button.new_release_from_held or self.fn_button.new_release):
            return False
        if self.fn_button.new_release_from_held:
            self.call_function('fn_button_held_function', True)
        else:
            self.call_function('fn_button_press_function', action_type="release")
        pixels.set_fn_button_off()
        return True

    def _handle_fn_button_press(self):
        """
        Handle fn button press states and trigger actions.
        """
        if not (self.fn_button.new_dbl_press or self.fn_button.new_press):
            return False

        # double press
        if self.fn_button.new_dbl_press:
            action_fn_ran = self.call_function('fn_button_dbl_press_function')
            if action_fn_ran and Menu.current_idx == 0:
                Menu.toggle_lock_mode(settings.get_play_mode() == "encoder")
            return True

        # single press
        if self.fn_button.new_press:
            self.call_function('fn_button_press_function', action_type="press")
            pixels.set_fn_button_on(color=C.FN_BUTTON_COLOR)
            return True
        return False

    def _handle_fn_button_held(self):
        """
        Handle fn button held state and update visuals.
        """
        self.call_function('fn_button_held_function')
        pixels.set_fn_button_on(color=C.PAD_HELD_COLOR)

    def handle_encoder_arp_mode(self, button, play_mode, pad_idx):
        """
        Handle encoder-based arpeggiator for a specific pad.
        
        Args:
            button (Button): The button being processed
            play_mode (str): Current play mode ("encoder" or "chord")
            pad_idx (int): Index of the pad being processed
        """
        # Handle button release - update visuals
        if button.new_release and play_mode == "encoder":
            color = C.CHORD_COLOR if chord_manager.chord_loops[pad_idx] else C.BLACK
            pixels.set_default_color(pad_idx, color)
            pixels.set_color(pad_idx, color)
            
        if not button.state:
            return

        # Handle new press in encoder mode
        if play_mode == "encoder" and button.new_press:
            pixels.set_default_color(pad_idx, C.PAD_HELD_COLOR)
            pixels.set_color(pad_idx, C.PAD_HELD_COLOR)

        # Get note for this pad
        note = (self.single_note_mode_midi_val if self.single_note_mode_midi_val
               else midi.get_midi_note_by_idx(pad_idx))

        # Turn off notes on CCW encoder turn
        if self.encoder_delta < 0:
            for note in midi.current_notes():
                self.new_notes_off.append((note, 0, pad_idx, C.DEFAULT_CHORDPAD_IDX))

        # Turn on notes on CW encoder turn
        if self.encoder_delta > 0:
            if play_mode == "encoder" and chord_manager.chord_loops[pad_idx]:
                # Add chord Notes to arpeggiator
                for note in chord_manager.unique_notes(pad_idx):
                    arpeggiator.add_arp_note(note)
                for cc in chord_manager.unique_ccs(pad_idx):
                    arpeggiator.add_arp_cc(cc)
            else:
                # Add single note to arpeggiator
                velocity = midi.get_velocity_by_idx(pad_idx)
                arpeggiator.add_arp_note((note, velocity, pad_idx, C.DEFAULT_CHORDPAD_IDX))

    def process_inputs_slow(self):
        """
        Process inputs at slower rate: encoder, button holds, navigation.
        
        Handles encoder position, button hold detection, navigation buttons,
        and encoder-based menu/function navigation when not locked.
        """
        self.encoder_delta = self.encoder.position
        self.encoder.position = 0

        hold_count = self._process_button_holds()

        # Handle encoder change
        if self.encoder_delta != 0 and hold_count > 0:
            self.is_any_pad_held = True
            self.call_function('pad_held_function', -1, self.get_button_states_list(), self.encoder_delta)

        # Catch stray encoder turns meant for pads
        if hold_count == 0 and self.is_any_pad_held:
            self.is_any_pad_held = False
            self.encoder_delta = 0

        self.process_nav_buttons()

        # ---------- STOP EARLY POINT --------
        if self.is_any_pad_held or Menu.is_locked or self.encoder_delta == 0:  # already processed in pad_held_function or locked
            return False

        encoder_direction = self.encoder_delta > 0
        if Menu.is_nav_mode and not self.encoder_button.is_held and not self.fn_button.is_held:
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
        Process button inputs and handle note/chord triggering at high frequency.
        
        Handles pad matrix events, arpeggiator, and note triggering based on play mode.
        Called every main loop iteration - optimized for minimal RAM usage.
        """
        self.reset_pads_and_notes()
        self.new_notes_off.extend(arpeggiator.get_off_notes())
        new_press_indices = self.process_keymatrix()
        
        if not new_press_indices and self.encoder_delta == 0:
            has_releases = any(button.new_release for button in self.note_buttons)
            if not has_releases:
                return

        play_mode = settings.get_play_mode()
        if self.fn_button.is_held and new_press_indices:                    # FN Button Held + New Press
            self.handle_fn_button_held_fast(new_press_indices)
            return

        chord_recording = chord_manager.is_recording

        # Arp Notes
        if play_mode in ["encoder", "chord"] and Menu.current_idx != 2:  # Not in MIDI settings
            for button in self.note_buttons:
                if button.state or button.new_release: # Release resets arp notes
                    self.handle_encoder_arp_mode(button, play_mode, button.pad_idx)

            # Clear arpeggiator if no buttons are pressed
            any_buttons_pressed = any(button.state for button in self.note_buttons)
            if not any_buttons_pressed and arpeggiator.has_events():
                arpeggiator.clear_arp_notes()

            self.play_arp_events()
            
        if play_mode == "encoder":  # Midi settings
            return
            
        # Process regular note triggering
        for button in self.note_buttons:
            if not (button.new_press or button.new_release):
                continue
            
            pad_idx = button.pad_idx
            note, velocity = self.get_note_and_velocity(pad_idx)

            chord_loop = chord_manager.chord_loops[pad_idx]

            # New Press
            if button.new_press:
                if chord_loop and not chord_recording:
                    chord_manager.toggle_chord_playstate(pad_idx)
                else:
                    self.new_notes_on.append((note, velocity, pad_idx, C.DEFAULT_CHORDPAD_IDX))

            # New Release
            if button.new_release and not (chord_loop and not chord_recording) and pad_idx != self.recording_start_pad:
                self.new_notes_off.append((note, 127, pad_idx, C.DEFAULT_CHORDPAD_IDX))
            
            # Recording start - related to holding FN button and recording to one pad after another
            if pad_idx == self.recording_start_pad and (button.new_press or button.new_release):
                self.recording_start_pad = None

    def process_keymatrix(self):
        """
        Process keypad matrix events and return indices of newly pressed pads.
        
        Returns:
            list: Indices of pads that were just pressed
        """
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
        """
        Reset button states and note lists for next processing cycle.
        """
        for button in self.note_buttons:
            button.reset_actions()

        self.new_notes_on.clear()
        self.new_notes_off.clear()
    
    def handle_fn_button_held_fast(self, new_press_indicies):
        """
        Handle the fn button being held down in fast input mode. To start recording, etc.
        """
        play_mode = settings.get_play_mode()
        for pad_idx in new_press_indicies:

            if play_mode == "velocity":
                self.handle_velocity_mode(pad_idx)
                
            if play_mode == "chord": 
                self.recording_start_pad = pad_idx             
                chord_manager.add_remove_chord(pad_idx)
                if Menu.current_idx != 0:
                    Menu.next_or_prev_menu(False, 0)           # Jump to play menu
            self.note_buttons[pad_idx].reset_new_press()       # Reset the button's actions to avoid double processing

    def play_arp_events(self):
        """
        Get next arpeggiator events (notes, ccs) and add to processing queues.
        """

        arp = arpeggiator
        has_events = arp.has_events()
        
        if not (has_events or arp.has_ccs()) or self.encoder_delta <= 0:
            return
        
        # Check if we should skip this turn based on encoder steps setting
        # IMPORTANT: This must happen BEFORE get_next_arp_events() to prevent index advancement
        if arp.skip_this_turn():
            self.encoder_delta = 0  # Reset delta but don't advance indices
            return
        
        self.encoder_delta = 0
        
        # Monophonic - Turn off last note
        if has_events and not settings.arp_is_polyphonic:
            last_note = arp.get_previous_note()
            if last_note is not None:
                self.new_notes_off.append(last_note)
        
        arp_events = arp.get_next_arp_events()
        if not arp_events:
            return
            
        # Add Events to Queue
        note_event, cc_event = arp_events
        if note_event:
            self.new_notes_on.append(note_event)
            
        # Send CCs immediately
        if cc_event:
            midi.send_cc(cc_event[0], cc_event[1])

    def get_note_and_velocity(self, pad_idx):
        """
        Get the MIDI note and velocity for a given pad index.
        """
        if self.single_note_mode_midi_val is not None:
            note = self.single_note_mode_midi_val
            velocity = midi.get_velocity_singlenote_by_idx(pad_idx)
        else:
            note = midi.get_midi_note_by_idx(pad_idx)
            velocity = midi.get_velocity_by_idx(pad_idx)
        
        return note, velocity

    def get_button_states_list(self):
        """
        Return current button states as list of booleans for pad_held_function.
        """
        return [button.state for button in self.note_buttons]

inputs = Inputs()
