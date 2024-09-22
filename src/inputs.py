from utils import free_memory
import time
import constants
import board
import digitalio
import rotaryio
import keypad
from chordmanager import chord_manager
from debug import print_debug
from menus import Menu
from display import pixel_set_fn_button_off, pixel_set_fn_button_on, pixels_set_default_color, pixel_set_color,pixels_display_velocity_map, get_default_color, set_blink_pixel
from arp import arpeggiator
from tutorial import tutorial
from playmenu import get_midi_note_name_text
from settings import settings
from looper import MidiLoop
from globalstates import global_states

from midi import (
    get_midi_velocity_by_idx,
    get_midi_note_by_idx,
    get_midi_velocity_singlenote_by_idx,
    get_play_mode,
    get_current_midi_notes,
)

pads = keypad.KeyMatrix(
    row_pins=(board.GP4, board.GP3, board.GP2, board.GP1),
    column_pins=(board.GP5, board.GP6, board.GP7, board.GP8),
    columns_to_anodes=True,
)

# Select Button and encoder setup
fn_button = digitalio.DigitalInOut(constants.SELECT_BTN)
encoder_button = digitalio.DigitalInOut(constants.ENCODER_BTN)
encoder = rotaryio.IncrementalEncoder(constants.ENCODER_DT, constants.ENCODER_CLK)
fn_button.direction = digitalio.Direction.INPUT
fn_button.pull = digitalio.Pull.UP
encoder_button.direction = digitalio.Direction.INPUT
encoder_button.pull = digitalio.Pull.UP

note_buttons = []
last_nav_check_time = 0

free_memory()
class Inputs:
    """
    Class representing the inputs of the system.

    Attributes:
        encoder_pos_now (int): The current position of the encoder.
        encoder_delta (int): The change in encoder position.
        encoder_mode_ontimes (list): List of on-times for the encoder mode.

        fn_button_starttime (float): The start time of the fn button.
        fn_button_holdtime_s (float): The hold time of the fn button.
        fn_button_held (bool): Flag indicating if the fn button is being held.
        fn_button_dbl_press (bool): Flag indicating if the fn button is double-pressed.
        fn_button_dbl_press_time (float): The time of the double press of the fn button.
        fn_button_state (bool): The state of the fn button.

        encoder_button_state (bool): The state of the encoder button.
        encoder_button_starttime (float): The start time of the encoder button.
        encoder_button_holdtime_s (float): The hold time of the encoder button.
        encoder_button_held (bool): Flag indicating if the encoder button is being held.
        encoder_button_dbl_press (bool): Flag indicating if the encoder button is double-pressed.
        encoder_button_dbl_press_time (float): The time of the double press of the encoder button.

        velocity_map_mode_midi_val (Optional[int]): The MIDI value of the single hit velocity button.

        is_any_pad_held (bool): Flag indicating if any pad is being held.
        button_states (list of bool): List of states for each button.
        button_press_start_times (list of Optional[float]): List of start times for button presses.
        button_held (list of bool): List indicating if each button is being held.
        new_press (list of bool): List indicating if a button is newly pressed.
        new_release (list of bool): List indicating if a button is newly released.
        button_holdtimes_s (list of float): List of hold times for each button.
    """

    def __init__(self):
        # self.encoder_pos_now = 0
        self.encoder_delta = 0
        # self.encoder_mode_ontimes = []

        self.fn_button_starttime = 0
        # self.fn_button_holdtime_s = 0
        self.fn_button_held = False
        self.fn_button_dbl_press = False
        self.fn_button_dbl_press_time = 0
        self.fn_button_state = False

        self.encoder_button_state = False
        self.encoder_button_starttime = 0
        # self.encoder_button_holdtime_s = 0
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
        self.new_release_from_held = [False] * 16 # Was held, now released
        self.button_holdtimes_s = [0] * 16

inputs = Inputs()

# Globals
note_states = [False] * 16
new_notes_on = []  # list of tuples: (note, velocity)
new_notes_off = []

def handle_velocity_mode(button_index):
    """Handles the logic for velocity play mode.

    Args:
        button_index (int): The index of the button pressed.
    """
    # Turn off single note mode
    if inputs.velocity_map_mode_midi_val is not None:
        inputs.velocity_map_mode_midi_val = None
        global_states.velocity_mapped = False
        pixels_display_velocity_map(False)
        Menu.display_notification("Single Note Mode: OFF")
    # Turn on single note mode
    else:
        inputs.velocity_map_mode_midi_val = get_midi_note_by_idx(button_index)
        pixels_display_velocity_map(True)
        global_states.velocity_mapped = True
        Menu.display_notification(
            f"Pads mapped to: {get_midi_note_name_text(inputs.velocity_map_mode_midi_val)}"
        )

        return
def process_nav_buttons():
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
    if fn_button.value and inputs.fn_button_state:
        if inputs.fn_button_held:
            inputs.fn_button_dbl_press_time = 0
        else:
            inputs.fn_button_dbl_press_time = time.monotonic()

        if inputs.fn_button_held:
            fn_button_held_fn = Menu.current_menu.actions.get('fn_button_held_function')
            if fn_button_held_fn:
                fn_button_held_fn(True)  # Runs once when released
        else:
            fn_button_press_fn = Menu.current_menu.actions.get('fn_button_press_function')
            if fn_button_press_fn:
                fn_button_press_fn(action_type="release")

        inputs.fn_button_held = False
        inputs.fn_button_state = False
        inputs.fn_button_starttime = 0
        Menu.toggle_fn_button_icon(False)
        if MidiLoop.current_loop.is_recording:
            pixel_set_fn_button_on(color=constants.RED)
            set_blink_pixel(16, True)
        elif MidiLoop.current_loop.loop_is_playing:
            set_blink_pixel(16, False)
            pixel_set_fn_button_on(color=constants.PIXEL_LOOP_PLAYING_COLOR)
        else:
            set_blink_pixel(16, False)
            pixel_set_fn_button_off()

    # Handle fn button press
    if not inputs.fn_button_state and not fn_button.value:
        inputs.fn_button_state = True
        inputs.fn_button_starttime = time.monotonic()
        inputs.fn_button_held = False
        inputs.fn_button_dbl_press = False
        if not Menu.current_menu_idx == 2:
            pixel_set_fn_button_on(color=constants.FN_BUTTON_COLOR)

        # Select button double press
        if (inputs.fn_button_starttime - inputs.fn_button_dbl_press_time
            < constants.DBL_PRESS_THRESH_S) and not inputs.fn_button_dbl_press:
            inputs.fn_button_dbl_press = True
            inputs.fn_button_dbl_press_time = 0
            fn_button_dbl_press_fn = Menu.current_menu.actions.get('fn_button_dbl_press_function')
            if fn_button_dbl_press_fn:
                fn_button_dbl_press_fn()
                if get_play_mode() == "encoder":
                    Menu.toggle_lock_mode(True)
                else:
                    Menu.toggle_lock_mode(False)
            inputs.fn_button_starttime = time.monotonic()  # Avoid erroneous button holds
            print_debug("Select Button Double Press")

        # Select button single press
        else:
            inputs.fn_button_dbl_press = False
            inputs.fn_button_dbl_press_time = 0
            print_debug("New Sel Btn Press")
            fn_button_press_fn = Menu.current_menu.actions.get('fn_button_press_function')
            if fn_button_press_fn:
                fn_button_press_fn(action_type="press")

    # Handle fn button held
    if (inputs.fn_button_state and
        (time.monotonic() - inputs.fn_button_starttime) > constants.BUTTON_HOLD_THRESH_S and
        not inputs.fn_button_held):
        if time_since_last_check <= 0.5:
            inputs.fn_button_held = True
            inputs.fn_button_dbl_press = False
            Menu.toggle_fn_button_icon(True)
            fn_button_held_fn = Menu.current_menu.actions.get('fn_button_held_function')
            if fn_button_held_fn:
                fn_button_held_fn()  # Runs once when first held
            pixel_set_fn_button_on(color=constants.PAD_HELD_COLOR)
            print_debug("Select Button Held")

    # Handle encoder button press
    if not inputs.encoder_button_state and not encoder_button.value:
        inputs.encoder_button_state = True
        inputs.encoder_button_starttime = time.monotonic()
        inputs.encoder_button_held = False
        inputs.encoder_button_dbl_press = False
        
        # Encoder button double press
        if (inputs.encoder_button_starttime - inputs.encoder_button_dbl_press_time
            < constants.DBL_PRESS_THRESH_S) and not inputs.encoder_button_dbl_press:
            inputs.encoder_button_dbl_press_time = 0
            inputs.encoder_button_dbl_press = True
            Menu.toggle_nav_mode()  # Account for first click changing this
            Menu.toggle_lock_mode()
            inputs.encoder_button_starttime = time.monotonic()  # Avoid erroneous button holds
            print_debug("Encoder Button Double Press")
        
        # Encoder button single press
        else:
            inputs.fn_button_dbl_press = False
            inputs.encoder_button_dbl_press_time = 0
            print_debug("New encoder Btn Press!!!")

    # Handle encoder button held
    if (inputs.encoder_button_state and
        (time.monotonic() - inputs.encoder_button_starttime) > constants.BUTTON_HOLD_THRESH_S and
        not inputs.encoder_button_held):
        inputs.encoder_button_held = True
        encoder_button_held_fn = Menu.current_menu.actions.get('encoder_button_held_function')
        if encoder_button_held_fn:
            encoder_button_held_fn()
        print_debug("encoder Button Held")

    # Handle encoder button release
    if encoder_button.value and inputs.encoder_button_state:
        if inputs.encoder_button_held:
            inputs.encoder_button_dbl_press_time = 0
        else:
            inputs.encoder_button_dbl_press_time = time.monotonic()
        
        inputs.encoder_button_state = False
        inputs.encoder_button_starttime = 0

        if Menu.is_locked:
            return
        
        if not inputs.encoder_button_held:  # If not first release after hold
            Menu.toggle_nav_mode()
        else:
            encoder_button_held_fn = Menu.current_menu.actions.get('encoder_button_held_function')
            if encoder_button_held_fn:
                encoder_button_held_fn(True)
        inputs.encoder_button_held = False

free_memory()

def process_inputs_slow():
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
    inputs.encoder_delta = encoder.position
    encoder.position = 0

    # Process each button (drum pad)
    for button_index in range(16):
        if inputs.button_states[button_index]:
            inputs.button_holdtimes_s[button_index] = (
                time.monotonic() - inputs.button_press_start_times[button_index]
            )
            if (inputs.button_holdtimes_s[button_index] > constants.BUTTON_HOLD_THRESH_S
                and not inputs.button_held[button_index]):
                inputs.button_held[button_index] = True
                # pixels_set_default_color(button_index, constants.PAD_HELD_COLOR)
                # pixel_set_color(button_index, constants.PAD_HELD_COLOR)
                print_debug(f"holding {button_index}")
        else:
            inputs.button_held[button_index] = False
            inputs.button_holdtimes_s[button_index] = 0
            # pixels_set_default_color(button_index, constants.BLACK)
            # pixel_set_color(button_index, constants.BLACK)

        if inputs.button_held[button_index]:
            hold_count += 1
            if not inputs.is_any_pad_held:
                inputs.is_any_pad_held = True
                pad_held_fn = Menu.current_menu.actions.get('pad_held_function')
                if pad_held_fn:
                    pad_held_fn(button_index, "", 0)

    # Handle encoder delta if any
    if inputs.encoder_delta != 0:
        pad_held_fn = Menu.current_menu.actions.get('pad_held_function')
        if pad_held_fn:
            pad_held_fn(-1, inputs.button_states, inputs.encoder_delta)

    # Catch stray encoder turns meant for pads
    if hold_count == 0 and inputs.is_any_pad_held:
        inputs.is_any_pad_held = False
        inputs.encoder_delta = 0

    process_nav_buttons()

    if inputs.is_any_pad_held or Menu.is_locked:  # already processed in pad_held_function or locked
        return

    # Determine encoder direction
    encoder_direction = None
    if inputs.encoder_delta > 0:
        encoder_direction = True
    elif inputs.encoder_delta < 0:
        encoder_direction = False

    if encoder_direction is None:
        return

    # Change menu if in navigation mode
    if Menu.is_nav_mode:
        Menu.next_or_prev_menu(encoder_direction)
        return

    # Handle fn button held and encoder change
    if inputs.fn_button_held:
        fn_button_held_and_encoder_change_fn = Menu.current_menu.actions.get('fn_button_held_and_encoder_change_function')
        if fn_button_held_and_encoder_change_fn:
            fn_button_held_and_encoder_change_fn(encoder_direction)
        return

    # Handle encoder button held and turn
    if inputs.encoder_button_held:
        encoder_button_press_and_turn_fn = Menu.current_menu.actions.get('encoder_button_press_and_turn_function')
        if encoder_button_press_and_turn_fn:
            encoder_button_press_and_turn_fn(encoder_direction)
        return

    # Handle encoder change
    encoder_change_fn = Menu.current_menu.actions.get('encoder_change_function')
    if encoder_change_fn:
        encoder_change_fn(encoder_direction)

def process_inputs_fast():
    """
    Process inputs from the pads and buttons at a faster rate.

    This function updates the state of the buttons and triggers corresponding actions based on button presses
    and releases. It also handles the behavior of the fn button and encoder button in different play modes.

    Usage:
        Call this function in a loop to continuously monitor and react to button presses and releases.

    Example:
        process_inputs_fast()
    """

    global new_notes_on, new_notes_off

    # Reset new press and release states for all buttons
    for button_index in range(16):
        inputs.new_press[button_index] = False
        inputs.new_release[button_index] = False
        inputs.new_release_from_held[button_index] = False

    # Process pad events
    event = pads.events.get()
    if event:
        pad = event.key_number
        if event.pressed and not inputs.button_states[pad]:
            inputs.new_press[pad] = True
            inputs.button_press_start_times[pad] = time.monotonic()
            inputs.button_states[pad] = True

        elif not event.pressed and inputs.button_states[pad]:
            inputs.new_release[pad] = True
            inputs.button_states[pad] = False
            inputs.button_press_start_times[pad] = 0

    new_notes_on = []
    new_notes_off = []

    # Clear any OFF arp notes
    new_arp_off_notes = arpeggiator.get_off_notes()
    if new_arp_off_notes:
        for note in new_arp_off_notes:
            new_notes_off.append(note)

    # Handle fn button held
    if inputs.fn_button_held:
        for button_index in range(16):
            if not inputs.new_press[button_index]:
                continue

            play_mode = get_play_mode()

            if play_mode == "velocity":
                handle_velocity_mode(button_index)
                inputs.new_press[button_index] = False
                return
                
            if play_mode == "chord" and Menu.current_menu_idx != 2: # Dont do this in looper mode
                chord_manager.add_remove_chord(button_index)
                inputs.new_press[button_index] = False
                return

    # Handle encoder play mode
    if get_play_mode() in ["encoder", "chord"]:
        # Reset arp notes to track if changed
        if inputs.encoder_delta > 0:
            if arpeggiator.skip_this_turn():
                return
            arpeggiator.clear_arp_notes()

        for button_index in range(16):
            if inputs.new_release[button_index]:
                if get_play_mode() == "encoder" and not chord_manager.pad_chords[button_index]:
                    pixels_set_default_color(button_index)
                    pixel_set_color(button_index,get_default_color(button_index))
                if get_play_mode() == "encoder" and chord_manager.pad_chords[button_index]:
                    pixels_set_default_color(button_index, constants.CHORD_COLOR)
                    pixel_set_color(button_index, constants.CHORD_COLOR)
                
            if inputs.button_states[button_index]:

                if get_play_mode() == "encoder" and inputs.new_press[button_index]:
                    pixels_set_default_color(button_index, constants.PAD_HELD_COLOR)
                    pixel_set_color(button_index, constants.PAD_HELD_COLOR)

                # Turn off notes - encoder ccw
                if inputs.encoder_delta < 0:
                    note = get_midi_note_by_idx(button_index)
                    if inputs.velocity_map_mode_midi_val:
                        note = inputs.velocity_map_mode_midi_val
                    for note in get_current_midi_notes():
                        new_notes_off.append((note, 0, button_index))

                # Turn on notes - encoder cw
                if inputs.encoder_delta > 0:
                    note = get_midi_note_by_idx(button_index)
                    if inputs.velocity_map_mode_midi_val:
                        note = inputs.velocity_map_mode_midi_val
                    velocity = get_midi_velocity_by_idx(button_index)

                    # If chord exists, get chord notes
                    if get_play_mode() == "encoder" and chord_manager.pad_chords[button_index]:
                        notes = chord_manager.get_chord_notes(button_index)
                        for note in notes:
                            arpeggiator.add_arp_note(note)

                    # Single Note
                    else:
                        print(f"adding arp single note {note}")
                        arpeggiator.add_arp_note((note, velocity, button_index))

        # Arpeggiator
        if arpeggiator.has_arp_notes() and inputs.encoder_delta > 0:
            inputs.encoder_delta = 0
            if not settings.arp_is_polyphonic:
                last_note = arpeggiator.get_previous_arp_note()
                if last_note is not None:
                    new_notes_off.append(last_note)
            note = arpeggiator.get_next_arp_note()
            new_notes_on.append(note)
            print(f"new note on {note}")
        
        if get_play_mode() == "encoder":
            return

    # Get new midi on/off notes
    for button_index in range(16):
        if not (inputs.new_press[button_index] or inputs.new_release[button_index]):
            continue

        # Set up Note and Velocity
        if inputs.velocity_map_mode_midi_val is not None:
            note = inputs.velocity_map_mode_midi_val
            velocity = get_midi_velocity_singlenote_by_idx(button_index)
        else:
            note = get_midi_note_by_idx(button_index)
            velocity = get_midi_velocity_by_idx(button_index)

        # New Press - Play note or chord
        if inputs.new_press[button_index]:
            print_debug(f"new press on {button_index}")

            if chord_manager.pad_chords[button_index] and not chord_manager.is_recording:
                chord_manager.toggle_chord_by_index(button_index)
            else:
                new_notes_on.append((note, velocity, button_index))

        # New Release - Stop note or chord
        if inputs.new_release[button_index]:
            if chord_manager.pad_chords[button_index] and not chord_manager.is_recording:
                pass
            else:
                new_notes_off.append((note, 127, button_index))