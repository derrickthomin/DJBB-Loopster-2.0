from utils import free_memory, show_memory

# Standard library imports
import time
import board
import digitalio
import rotaryio
import keypad

# Project-specific imports (ordered by usage frequency or dependency)
from debug import print_debug
from globalstates import global_states
import constants
from settings import settings
from midi import (
    get_velocity_by_idx,
    get_midi_note_by_idx,
    get_velocity_singlenote_by_idx,
    get_play_mode,
    get_current_midi_notes,
)
from chordmanager import chord_manager
from arp import arpeggiator
from menus import Menu
from pixels import pixels
from playmenu import get_midi_note_name_text
from looper import MidiLoop

note_buttons = []
last_nav_check_time = 0

pads = None  # Initialize as None, to be initialized later
fn_button = None
encoder_button = None
encoder = None

def initialize_hardware_inputs():
    global pads, fn_button, encoder_button, encoder # Declare globals to modify them

    if pads is None: # Check if already initialized
        pads = keypad.KeyMatrix(
            row_pins=(board.GP4, board.GP3, board.GP2, board.GP1),
            column_pins=(board.GP5, board.GP6, board.GP7, board.GP8),
            columns_to_anodes=True,
        )
    
    if fn_button is None:
        fn_button = digitalio.DigitalInOut(constants.SELECT_BTN)
        fn_button.direction = digitalio.Direction.INPUT
        fn_button.pull = digitalio.Pull.UP

    if encoder_button is None:
        encoder_button = digitalio.DigitalInOut(constants.ENCODER_BTN)
        encoder_button.direction = digitalio.Direction.INPUT
        encoder_button.pull = digitalio.Pull.UP

    if encoder is None:
        encoder = rotaryio.IncrementalEncoder(constants.ENCODER_DT, constants.ENCODER_CLK)


class Inputs:
    
    def __init__(self):
        free_memory()
        show_memory("Before init in inputs_new.py")
        self.encoder_delta = 0

        self.fn_button_starttime = 0
        self.fn_button_held = False
        self.fn_button_dbl_press = False
        self.fn_button_dbl_press_time = 0
        self.fn_button_state = False

        self.encoder_button_state = False
        self.encoder_button_starttime = 0
        self.encoder_button_held = False
        self.encoder_button_dbl_press = False
        self.encoder_button_dbl_press_time = 0

        self.velocity_map_mode_midi_val = None

        self.is_any_pad_held = False
        self.button_states = [False] * 16
        self.button_press_start_times = [None] * 16
        self.button_held = [False] * 16
        self.new_press = [False] * 16
        self.new_release = [False] * 16
        self.new_release_from_held = [False] * 16
        self.button_holdtimes_s = [0] * 16
 
        self.note_states = [False] * 16
        self.new_notes_on = []  # list of tuples: (note, velocity)
        self.new_notes_off = []

        free_memory()
        show_memory("After init in inputs_new.py")

    def handle_velocity_mode(self,pad_idx):
        """Handles the logic for velocity play mode.

        Args:
            pad_idx (int): The index of the button pressed.
        """
        # Turn off single note mode
        if self.velocity_map_mode_midi_val is not None:
            self.velocity_map_mode_midi_val = None
            global_states.velocity_mapped = False
            pixels.display_velocity_map(False)
            Menu.show_notification("Single Note Mode: OFF")

        # Turn on single note mode
        else:
            self.velocity_map_mode_midi_val = get_midi_note_by_idx(pad_idx)
            pixels.display_velocity_map(True)
            global_states.velocity_mapped = True
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
        
        global fn_button, encoder_button, last_nav_check_time

        # Check for extreme latency. Just reset everything if it's too high
        time_since_last_check = time.monotonic() - last_nav_check_time
        last_nav_check_time = time.monotonic()

        # Handle fn button release
        if fn_button.value and self.fn_button_state:
            if self.fn_button_held:
                self.fn_button_dbl_press_time = 0
            else:
                self.fn_button_dbl_press_time = time.monotonic()

            if self.fn_button_held:
                fn_button_held_fn = Menu.current_menu.actions.get('fn_button_held_function')
                if fn_button_held_fn:
                    fn_button_held_fn(True)  # Runs once when released
            else:
                fn_button_press_fn = Menu.current_menu.actions.get('fn_button_press_function')
                if fn_button_press_fn:
                    fn_button_press_fn(action_type="release")

            self.fn_button_held = False
            self.fn_button_state = False
            self.fn_button_starttime = 0
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
        if not self.fn_button_state and not fn_button.value:
            self.fn_button_state = True
            self.fn_button_starttime = time.monotonic()
            self.fn_button_held = False
            self.fn_button_dbl_press = False
            if not Menu.current_idx == 2:
                pixels.set_fn_button_on(color=constants.FN_BUTTON_COLOR)

            # Select button double press
            if (self.fn_button_starttime - self.fn_button_dbl_press_time
                < constants.DBL_PRESS_THRESH_S) and not self.fn_button_dbl_press:
                self.fn_button_dbl_press = True
                self.fn_button_dbl_press_time = 0
                fn_button_dbl_press_fn = Menu.current_menu.actions.get('fn_button_dbl_press_function')
                if fn_button_dbl_press_fn:
                    fn_button_dbl_press_fn()
                    if get_play_mode() == "encoder":
                        Menu.toggle_lock_mode(True)
                    else:
                        Menu.toggle_lock_mode(False)
                self.fn_button_starttime = time.monotonic()  # Avoid erroneous button holds
                print_debug("Select Button Double Press")

            # Select button single press
            else:
                self.fn_button_dbl_press = False
                self.fn_button_dbl_press_time = 0
                print_debug("New Sel Btn Press")
                fn_button_press_fn = Menu.current_menu.actions.get('fn_button_press_function')
                if fn_button_press_fn:
                    fn_button_press_fn(action_type="press")

        # Handle fn button held
        if (self.fn_button_state and
            (time.monotonic() - self.fn_button_starttime) > constants.BUTTON_HOLD_THRESH_S and
            not self.fn_button_held):
            if time_since_last_check <= 0.5:
                self.fn_button_held = True
                self.fn_button_dbl_press = False
                Menu.toggle_fn_button_icon(True)
                fn_button_held_fn = Menu.current_menu.actions.get('fn_button_held_function')
                if fn_button_held_fn:
                    fn_button_held_fn()  # Runs once when first held
                pixels.set_fn_button_on(color=constants.PAD_HELD_COLOR)
                print_debug("Select Button Held")

        # Handle encoder button press
        if not self.encoder_button_state and not encoder_button.value:
            self.encoder_button_state = True
            self.encoder_button_starttime = time.monotonic()
            self.encoder_button_held = False
            self.encoder_button_dbl_press = False
            
            # Encoder button double press
            if (self.encoder_button_starttime - self.encoder_button_dbl_press_time
                < constants.DBL_PRESS_THRESH_S) and not self.encoder_button_dbl_press:
                self.encoder_button_dbl_press_time = 0
                self.encoder_button_dbl_press = True
                Menu.toggle_nav_mode()  # Account for first click changing this
                Menu.toggle_lock_mode()
                self.encoder_button_starttime = time.monotonic()  # Avoid erroneous button holds
                print_debug("Encoder Button Double Press")
            
            # Encoder button single press
            else:
                self.fn_button_dbl_press = False
                self.encoder_button_dbl_press_time = 0
                print_debug("New encoder Btn Press!!!")

        # Handle encoder button held
        if (self.encoder_button_state and
            (time.monotonic() - self.encoder_button_starttime) > constants.BUTTON_HOLD_THRESH_S and
            not self.encoder_button_held):
            self.encoder_button_held = True
            encoder_button_held_fn = Menu.current_menu.actions.get('encoder_button_held_function')
            if encoder_button_held_fn:
                encoder_button_held_fn()
            print_debug("encoder Button Held")

        # Handle encoder button release
        if encoder_button.value and self.encoder_button_state:
            if self.encoder_button_held:
                self.encoder_button_dbl_press_time = 0
            else:
                self.encoder_button_dbl_press_time = time.monotonic()
            
            self.encoder_button_state = False
            self.encoder_button_starttime = 0

            if Menu.is_locked:
                return
            
            if not self.encoder_button_held:  # If not first release after hold
                Menu.toggle_nav_mode()
            else:
                encoder_button_held_fn = Menu.current_menu.actions.get('encoder_button_held_function')
                if encoder_button_held_fn:
                    encoder_button_held_fn(True)
            self.encoder_button_held = False

    free_memory()
    show_memory("After process_nav_buttons")


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
        self.encoder_delta = encoder.position
        encoder.position = 0

        # Process each button (drum pad)
        for pad_idx in range(16):
            if self.button_states[pad_idx]:
                self.button_holdtimes_s[pad_idx] = (
                    time.monotonic() - self.button_press_start_times[pad_idx]
                )
                if (self.button_holdtimes_s[pad_idx] > constants.BUTTON_HOLD_THRESH_S
                    and not self.button_held[pad_idx]):
                    self.button_held[pad_idx] = True
                    # set_default_color(pad_idx, constants.PAD_HELD_COLOR)
                    # set_color(pad_idx, constants.PAD_HELD_COLOR)
                    print_debug(f"holding {pad_idx}")
            else:
                self.button_held[pad_idx] = False
                self.button_holdtimes_s[pad_idx] = 0
                # set_default_color(pad_idx, constants.BLACK)
                # set_color(pad_idx, constants.BLACK)

            if self.button_held[pad_idx]:
                hold_count += 1
                if not self.is_any_pad_held:
                    self.is_any_pad_held = True
                    pad_held_fn = Menu.current_menu.actions.get('pad_held_function')
                    if pad_held_fn:
                        pad_held_fn(pad_idx, "", 0)

        # Handle encoder delta if any
        if self.encoder_delta != 0:
            pad_held_fn = Menu.current_menu.actions.get('pad_held_function')
            if pad_held_fn:
                pad_held_fn(-1, self.button_states, self.encoder_delta)

        # Catch stray encoder turns meant for pads
        if hold_count == 0 and self.is_any_pad_held:
            self.is_any_pad_held = False
            self.encoder_delta = 0

        self.process_nav_buttons()

        if self.is_any_pad_held or Menu.is_locked:  # already processed in pad_held_function or locked
            return

        # Determine encoder direction
        encoder_direction = None
        if self.encoder_delta > 0:
            encoder_direction = True
        elif self.encoder_delta < 0:
            encoder_direction = False

        if encoder_direction is None:
            return

        # Change menu if in navigation mode
        if Menu.is_nav_mode:
            Menu.next_or_prev_menu(encoder_direction)
            return

        # Handle fn button held and encoder change
        if self.fn_button_held:
            fn_button_held_and_encoder_change_fn = Menu.current_menu.actions.get('fn_button_held_and_encoder_change_function')
            if fn_button_held_and_encoder_change_fn:
                fn_button_held_and_encoder_change_fn(encoder_direction)
            return

        # Handle encoder button held and turn
        if self.encoder_button_held:
            encoder_button_press_and_turn_fn = Menu.current_menu.actions.get('encoder_button_press_and_turn_function')
            if encoder_button_press_and_turn_fn:
                encoder_button_press_and_turn_fn(encoder_direction)
            return

        # Handle encoder change
        encoder_change_fn = Menu.current_menu.actions.get('encoder_change_function')
        if encoder_change_fn:
            encoder_change_fn(encoder_direction)

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


        # Reset new press and release states for all buttons
        for pad_idx in range(16):
            self.new_press[pad_idx] = False
            self.new_release[pad_idx] = False
            self.new_release_from_held[pad_idx] = False

        # Process pad events
        event = pads.events.get()
        if event:
            pad = event.key_number
            if event.pressed and not self.button_states[pad]:
                self.new_press[pad] = True
                self.button_press_start_times[pad] = time.monotonic()
                self.button_states[pad] = True

            elif not event.pressed and self.button_states[pad]:
                self.new_release[pad] = True
                self.button_states[pad] = False
                self.button_press_start_times[pad] = 0

        self.new_notes_on = []
        self.new_notes_off = []

        # Clear any OFF arp notes
        new_arp_off_notes = arpeggiator.get_off_notes()
        if new_arp_off_notes:
            for note in new_arp_off_notes:
                self.new_notes_off.append(note)

        # Handle fn button held
        if self.fn_button_held:
            for pad_idx in range(16):
                if not self.new_press[pad_idx]:
                    continue

                play_mode = get_play_mode()

                if play_mode == "velocity":
                    self.handle_velocity_mode(pad_idx)
                    self.new_press[pad_idx] = False
                    return
                    
                if play_mode == "chord" and Menu.current_idx != 2: # Dont do this in looper mode
                    chord_manager.add_remove_chord(pad_idx)
                    self.new_press[pad_idx] = False
                    return

        # Handle encoder play mode
        if get_play_mode() in ["encoder", "chord"]:
            # Reset arp notes to track if changed
            if self.encoder_delta > 0:
                if arpeggiator.skip_this_turn():
                    return
                arpeggiator.clear_arp_notes()

            for pad_idx in range(16):
                if self.new_release[pad_idx]:
                    if get_play_mode() == "encoder" and not chord_manager.chord_loops[pad_idx]:
                        pixels.set_default_color(pad_idx)
                        pixels.set_color(pad_idx,pixels.get_default_color(pad_idx))
                    if get_play_mode() == "encoder" and chord_manager.chord_loops[pad_idx]:
                        pixels.set_default_color(pad_idx, constants.CHORD_COLOR)
                        pixels.set_color(pad_idx, constants.CHORD_COLOR)
                    
                if self.button_states[pad_idx]:

                    if get_play_mode() == "encoder" and self.new_press[pad_idx]:
                        pixels.set_default_color(pad_idx, constants.PAD_HELD_COLOR)
                        pixels.set_color(pad_idx, constants.PAD_HELD_COLOR)

                    # Turn off notes - encoder ccw
                    if self.encoder_delta < 0:
                        note = get_midi_note_by_idx(pad_idx)
                        if self.velocity_map_mode_midi_val:
                            note = self.velocity_map_mode_midi_val
                        for note in get_current_midi_notes():
                            self.new_notes_off.append((note, 0, pad_idx))

                    # Turn on notes - encoder cw
                    if self.encoder_delta > 0:
                        note = get_midi_note_by_idx(pad_idx)
                        if self.velocity_map_mode_midi_val:
                            note = self.velocity_map_mode_midi_val
                        velocity = get_velocity_by_idx(pad_idx)

                        # If chord exists, get chord notes
                        if get_play_mode() == "encoder" and chord_manager.chord_loops[pad_idx]:
                            notes = chord_manager.unique_notes(pad_idx)
                            for note in notes:
                                arpeggiator.add_arp_note(note)

                        # Single Note
                        else:
                            print_debug(f"adding arp single note {note}")
                            arpeggiator.add_arp_note((note, velocity, pad_idx))

            # Arpeggiator
            if arpeggiator.has_notes() and self.encoder_delta > 0:
                self.encoder_delta = 0
                if not settings.arp_is_polyphonic:
                    last_note = arpeggiator.get_previous_note()
                    if last_note is not None:
                        self.new_notes_off.append(last_note)
                note = arpeggiator.get_next_arp_note()
                self.new_notes_on.append(note)
                print_debug(f"new note on {note}")
            
            if get_play_mode() == "encoder":
                return

        # Get new midi on/off notes
        for pad_idx in range(16):
            if not (self.new_press[pad_idx] or self.new_release[pad_idx]):
                continue

            # Set up Note and Velocity
            if self.velocity_map_mode_midi_val is not None:
                note = self.velocity_map_mode_midi_val
                velocity = get_velocity_singlenote_by_idx(pad_idx)
            else:
                note = get_midi_note_by_idx(pad_idx)
                velocity = get_velocity_by_idx(pad_idx)

            # New Press - Play note or chord
            if self.new_press[pad_idx]:
                print_debug(f"new press on {pad_idx}")

                if chord_manager.chord_loops[pad_idx] and not chord_manager.is_recording:
                    chord_manager.toggle_chord_playstate(pad_idx)
                else:
                    self.new_notes_on.append((note, velocity, pad_idx))

            # New Release - Stop note or chord
            if self.new_release[pad_idx]:
                if chord_manager.chord_loops[pad_idx] and not chord_manager.is_recording:
                    pass
                else:
                    self.new_notes_off.append((note, 127, pad_idx))

    def process_keymatrix(self):
        # Process pad events
        event = pads.events.get()
        if event:
            pad = event.key_number
            if event.pressed and not self.button_states[pad]:
                self.new_press[pad] = True
                self.button_press_start_times[pad] = time.monotonic()
                self.button_states[pad] = True

            elif not event.pressed and self.button_states[pad]:
                self.new_release[pad] = True
                self.button_states[pad] = False
                self.button_press_start_times[pad] = 0

inputs = Inputs()