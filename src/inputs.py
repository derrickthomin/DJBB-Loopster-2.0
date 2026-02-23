import board
import digitalio
import rotaryio
import keypad

# Local application/library imports
from buttons import Button
import constants as C
from settings import settings
from midi import midi
from loopmanager import loop_manager
from arp import arpeggiator
from menus import Menu
import playmenu
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
        self.pressed_count = 0  # Track number of currently pressed buttons

    def initialize(self):
        self.initialize_hardware_inputs()
        self.initialize_buttons()

    def initialize_hardware_inputs(self):

        # Pads
        self._pads = keypad.KeyMatrix(
            row_pins=(board.GP4, board.GP3, board.GP2, board.GP1),
            column_pins=(board.GP5, board.GP6, board.GP7, board.GP8),
            columns_to_anodes=True,)
        
        # FN Button
        self._fn_button = digitalio.DigitalInOut(C.FN_BTN)
        self._fn_button.direction = digitalio.Direction.INPUT
        self._fn_button.pull = digitalio.Pull.UP

        # Encoder
        self._encoder_button = digitalio.DigitalInOut(C.ENCODER_BTN)
        self._encoder_button.direction = digitalio.Direction.INPUT
        self._encoder_button.pull = digitalio.Pull.UP
        self.encoder = rotaryio.IncrementalEncoder(C.ENCODER_DT, C.ENCODER_CLK)

    def initialize_buttons(self):
        self.fn_button = Button(hold_thresh=C.FN_HOLD_THRESH_S)
        self.encoder_button = Button(hold_thresh=C.ENCODER_HOLD_THRESH_S)
        for i in range(C.NUM_PADS):
            btn = Button(pad_index=i)
            self.note_buttons.append(btn)

    def call_function(self, action_key, *args, **kwargs):
        action_fn = Menu.current_menu.actions.get(action_key)
        if action_fn:
            action_fn(*args, **kwargs)
            return True
        return False

    def handle_velocity_mode(self,pad_idx):
        """Toggle single-note velocity mode."""
        # Off
        if self.single_note_mode_midi_val is not None:
            self.single_note_mode_midi_val = None
            settings.velocity_mapped = False
            pixels.display_velocity_map(False)
            loop_manager.update_pad_pixels()
            return

        # On
        else:
            self.single_note_mode_midi_val = midi.get_midi_note_by_idx(pad_idx)
            pixels.display_velocity_map(True)
            settings.velocity_mapped = True
            return

    def process_nav_buttons(self):
        """Process FN button, encoder button, and holds."""
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
        fn_is_down = self.fn_button.state              # Currently pressed (no hold delay)
        encoder_new_release = self.encoder_button.new_release
        encoder_new_release_from_held = self.encoder_button.new_release_from_held
        encoder_new_dbl_press = self.encoder_button.new_dbl_press
        encoder_is_held = self.encoder_button.is_held
        encoder_is_down = self.encoder_button.state    # Currently pressed (no hold delay)
        
        # Composite conditions for readability
        fn_released = fn_new_release_from_held or fn_new_release
        fn_pressed = fn_new_dbl_press or fn_new_press

        if fn_is_down and encoder_new_release:       # Up 1/4 Bank (instant, no hold needed)
            midi.offset_pads(True)
            if Menu.current_idx == C.MENU_PLAY and settings.get_play_mode() == "loop":
                playmenu.display_bank_offset()
            pixels.encoder_button_off()
            pixels.set_fn_button_off()
            self.encoder_button.reset_double_press()  # Prevent double processing
            return True

        if encoder_is_down and fn_released:           # Down 1/4 Bank (instant, no hold needed)
            midi.offset_pads(False)
            if Menu.current_idx == C.MENU_PLAY and settings.get_play_mode() == "loop":
                playmenu.display_bank_offset()
            pixels.encoder_button_off()
            pixels.set_fn_button_off()
            self.fn_button.reset_double_press()
            self.encoder_button.set_ignore_next_release()  # Prevent nav mode toggle on release
            return True

        if encoder_is_down and fn_new_dbl_press:      # Prevent FN double-click when encoder down
            self.fn_button.reset_double_press()
            return True
            
        if fn_released:
            self._handle_fn_button_release()

        if fn_pressed:
            if loop_manager.is_recording:
                loop_manager.handle_fn_press()
                self.fn_button.set_ignore_next_release()  # Prevent double processing
            else:
                self._handle_fn_button_press()
            return True

        if fn_is_held:
            self._handle_fn_button_held()

        if encoder_new_dbl_press:
            Menu.toggle_nav_mode()                        # Account for first click changing this
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
        if not (self.fn_button.new_release_from_held or self.fn_button.new_release):
            return False
        if self.fn_button.new_release_from_held:
            self.call_function('fn_button_held_function', True)
        else:
            self.call_function('fn_button_press_function', action_type="release")
        pixels.set_fn_button_off()
        return True

    def _handle_fn_button_press(self):
        if not (self.fn_button.new_dbl_press or self.fn_button.new_press):
            return False

        # double press
        if self.fn_button.new_dbl_press:
            action_fn_ran = self.call_function('fn_button_dbl_press_function')
            if action_fn_ran and Menu.current_idx == C.MENU_PLAY:
                Menu.toggle_lock_mode(settings.get_play_mode() == "encoder")
            return True

        # single press
        if self.fn_button.new_press:
            self.call_function('fn_button_press_function', action_type="press")
            pixels.set_fn_button_on(color=C.FN_BUTTON_COLOR)
            return True
        return False

    def _handle_fn_button_held(self):
        self.call_function('fn_button_held_function')
        pixels.set_fn_button_on(color=C.PAD_HELD_COLOR)

    def handle_encoder_arp_mode(self, button, play_mode, pad_idx):
        """Handle encoder-based arpeggiator for a pad."""
        has_loop = bool(loop_manager.loops[pad_idx])
        
        # Handle button release - remove pad from arp
        if button.new_release:
            if play_mode == "encoder":
                color = C.LOOP_COLOR if has_loop else C.BLACK
                pixels.set_default_color(pad_idx, color)
                pixels.set_color(pad_idx, color)
            
            arpeggiator.remove_source(pad_idx)
            return
            
        if not button.state:
            return

        # Handle new press - add pad to arp
        if button.new_press:
            if play_mode == "encoder":
                pixels.set_default_color(pad_idx, C.PAD_HELD_COLOR)
                pixels.set_color(pad_idx, C.PAD_HELD_COLOR)
            
            arpeggiator.add_source(pad_idx)

    def process_inputs_slow(self):
        """Process encoder, button holds, and navigation."""
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

        # Return early if we can
        if self.is_any_pad_held or self.encoder_delta == 0:  # already processed in pad_held_function
            return

        # Lock only blocks bare encoder turns (allows arp changes with FN/encoder button held)
        if Menu.is_locked and not self.fn_button.is_held and not self.encoder_button.is_held:
            return

        encoder_direction = self.encoder_delta > 0
        if Menu.is_nav_mode and not self.encoder_button.is_held and not self.fn_button.is_held:
            Menu.next_or_prev_menu(encoder_direction)
            return
        
        if self.fn_button.is_held:
            self.call_function('fn_button_held_and_encoder_change_function', encoder_direction)
            return

        if self.encoder_button.is_held:
            self.call_function('encoder_button_press_and_turn_function', encoder_direction)
            return

        # Default
        self.call_function('encoder_change_function', encoder_direction)

    def _process_button_holds(self):
        hold_count = 0
        pressed_count = 0  # Reconciliation sync
        for button in self.note_buttons:
            if button.state:
                pressed_count += 1
            idx = button.pad_idx
            button_held = button.check_if_held()  # Check if the button is held
            if button_held:
                hold_count += 1
                if not self.is_any_pad_held:
                    self.is_any_pad_held = True
                    self.call_function('pad_held_function', idx, "", 0)
        self.pressed_count = pressed_count  # Sync point
        return hold_count

    def process_inputs_fast(self):
        """Process pad matrix, arpeggiator, and note triggering."""
        self.reset_pads_and_notes()
        self.new_notes_off.extend(arpeggiator.get_off_notes())
        new_press_indices, has_releases = self.process_keymatrix()
        
        if not new_press_indices and self.encoder_delta == 0:
            if not has_releases:
                return

        play_mode = settings.get_play_mode()
        if self.fn_button.is_held and new_press_indices:
            self.handle_fn_button_held_fast(new_press_indices)
            return

        loop_recording = loop_manager.is_recording
        loops = loop_manager.loops  # Cache reference

        # Arp Notes
        if play_mode == "encoder" and Menu.current_idx != C.MENU_MIDI:
            for button in self.note_buttons:
                if button.state or button.new_release:
                    self.handle_encoder_arp_mode(button, play_mode, button.pad_idx)

            if self.pressed_count == 0 and arpeggiator.has_events():
                arpeggiator.clear_arp_notes()
            else:
                self.play_arp_events()
            
        if play_mode == "encoder":  # If encoder mode, skip regular note processing
            return
            
        # Process regular note triggering
        for button in self.note_buttons:
            if not (button.new_press or button.new_release):
                continue
            
            pad_idx = button.pad_idx
            note, velocity = self.get_note_and_velocity(pad_idx)
            loop = loops[pad_idx]

            # New Press
            if button.new_press:
                if loop and not loop_recording:
                    # Hold mode: force play on press
                    if loop.loop_type == "hold":
                        loop_manager.toggle_loop_playstate(pad_idx, force_play=True)
                    else:
                        loop_manager.toggle_loop_playstate(pad_idx)
                else:
                    # Use current output channel for live input notes
                    midi_channel = settings.midi_channel_out
                    self.new_notes_on.append((note, velocity, pad_idx, midi_channel))

            # New Release
            if button.new_release:
                # Hold mode: force stop on release
                if loop and not loop_recording and loop.loop_type == "hold":
                    loop_manager.toggle_loop_playstate(pad_idx, force_stop=True)
                elif not (loop and not loop_recording) and pad_idx != self.recording_start_pad:
                    midi_channel = settings.midi_channel_out
                    self.new_notes_off.append((note, 127, pad_idx, midi_channel))
            
            # Recording start - related to holding FN button and recording to one pad after another
            if pad_idx == self.recording_start_pad and (button.new_press or button.new_release):
                self.recording_start_pad = None

    def process_keymatrix(self):
        """Process keypad matrix events. Returns (new_press_indices, has_releases)."""
        new_press_indices = []
        has_releases = False
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

        return new_press_indices, has_releases

    def reset_pads_and_notes(self):
        for button in self.note_buttons:
            button.reset_actions()

        self.new_notes_on.clear()
        self.new_notes_off.clear()
    
    def handle_fn_button_held_fast(self, new_press_indices):
        play_mode = settings.get_play_mode()
        for pad_idx in new_press_indices:

            if play_mode == "velocity":
                self.handle_velocity_mode(pad_idx)
                
            if play_mode == "loop": 
                self.recording_start_pad = pad_idx             
                loop_manager.add_remove_loop(pad_idx)
                if Menu.current_idx != C.MENU_PLAY:
                    Menu.next_or_prev_menu(False, C.MENU_PLAY)           # Jump to play menu
            self.note_buttons[pad_idx].reset_new_press()       # Reset the button's actions to avoid double processing

    def play_arp_events(self, from_accelerometer=False):
        arp = arpeggiator
        has_events = arp.has_events()
        
        if not (has_events or arp.has_ccs()):
            return
        
        # Encoder mode requires encoder movement, unless triggered by accelerometer
        if not from_accelerometer and self.encoder_delta == 0:
            return
        
        # Determine direction - backward only works in polyphonic mode
        forward = self.encoder_delta > 0
        if not forward and not settings.arp_is_polyphonic:
            self.encoder_delta = 0
            return  # CCW does nothing in monophonic mode
        
        self.encoder_delta = 0
        
        # Monophonic - Turn off last note
        if has_events and not settings.arp_is_polyphonic:
            last_note = arp.get_previous_note()
            if last_note is not None:
                self.new_notes_off.append(last_note)
        
        arp_events = arp.get_next_arp_events(forward)
        if not arp_events:
            return
            
        # Add Events to Queue
        note_event, cc_event = arp_events
        if note_event:
            self.new_notes_on.append(note_event)
            
        # Send CCs immediately - channel was computed at add time
        if cc_event:
            cc_num, cc_val, midi_channel = cc_event
            midi.send_cc(cc_num, cc_val, midi_channel)

    def get_note_and_velocity(self, pad_idx):
        if self.single_note_mode_midi_val is not None:
            note = self.single_note_mode_midi_val
            velocity = midi.get_velocity_singlenote_by_idx(pad_idx)
        else:
            note = midi.get_midi_note_by_idx(pad_idx)
            velocity = midi.get_velocity_by_idx(pad_idx)
        
        return note, velocity

    def get_button_states_list(self):
        return [button.state for button in self.note_buttons]

inputs = Inputs()
