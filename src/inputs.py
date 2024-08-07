import time
import constants
import board
import digitalio
import rotaryio
import keypad
import chordmaker
from debug import print_debug
from midi import (
    get_midi_velocity_by_idx,
    get_midi_note_by_idx,
    get_midi_velocity_singlenote_by_idx,
    get_play_mode,
    get_current_midi_notes,
)
from menus import Menu
from display import pixel_fn_button_off, pixel_fn_button_on
from arp import arpeggiator
from tutorial import display_tutorial
from playmenu import get_midi_note_name_text

pads = keypad.KeyMatrix(
    row_pins=(board.GP4, board.GP3, board.GP2, board.GP1),
    column_pins=(board.GP5, board.GP6, board.GP7, board.GP8),
    columns_to_anodes=True,
)

# Select Button and encoder setup
select_button = digitalio.DigitalInOut(constants.SELECT_BTN)
encoder_button = digitalio.DigitalInOut(constants.ENCODER_BTN)
encoder = rotaryio.IncrementalEncoder(constants.ENCODER_DT, constants.ENCODER_CLK)
select_button.direction = digitalio.Direction.INPUT
select_button.pull = digitalio.Pull.UP
encoder_button.direction = digitalio.Direction.INPUT
encoder_button.pull = digitalio.Pull.UP

note_buttons = []
last_nav_check_time = 0

# Show tutorial if select button held on boot
# djt make a way to run this on first startup
if not select_button.value:
    time.sleep(0.2)
    if not select_button.value:
        display_tutorial()


class Inputs:
    """
    Class representing the inputs of the system.

    Attributes:
        encoder_pos_now (int): The current position of the encoder.
        encoder_delta (int): The change in encoder position.
        encoder_mode_ontimes (list): List of on-times for the encoder mode.

        select_button_starttime (int): The start time of the select button.
        select_button_holdtime_s (int): The hold time of the select button.
        select_button_held (bool): Flag indicating if the select button is being held.
        select_button_dbl_press (bool): Flag indicating if the select button is double-pressed.
        select_button_dbl_press_time (int): The time of the double press of the select button.
        select_button_state (bool): The state of the select button.

        encoder_button_state (bool): The state of the encoder button.
        encoder_button_starttime (int): The start time of the encoder button.
        encoder_button_holdtime (int): The hold time of the encoder button.
        encoder_button_held (bool): Flag indicating if the encoder button is being held.

        singlehit_velocity_btn_midi (None): The MIDI value of the single hit velocity button.

        any_pad_held (bool): Flag indicating if any pad is being held.
        button_states (list): List of states for each button.
        button_press_start_times (list): List of start times for button presses.
        button_held (list): List indicating if each button is being held.
        new_press (list): List indicating if a button is newly pressed.
        new_release (list): List indicating if a button is newly released.
        button_holdtimes_s (list): List of hold times for each button.
    """

    def __init__(self):
        self.encoder_pos_now = 0
        self.encoder_delta = 0
        self.encoder_mode_ontimes = []

        self.select_button_starttime = 0
        self.select_button_holdtime_s = 0
        self.select_button_held = False
        self.select_button_dbl_press = False
        self.select_button_dbl_press_time = 0
        self.select_button_state = False

        self.encoder_button_state = False
        self.encoder_button_starttime = 0
        self.encoder_button_holdtime = 0
        self.encoder_button_held = False

        self.singlehit_velocity_btn_midi = None

        self.any_pad_held = False
        self.button_states = [False] * 16
        self.button_press_start_times = [None] * 16
        self.button_held = [False] * 16
        self.new_press = [False] * 16
        self.new_release = [False] * 16
        self.button_holdtimes_s = [0] * 16


inpts = Inputs()

# Globals
note_states = [False] * 16
new_notes_on = []  # list of tuples: (note, velocity)
new_notes_off = []


def process_nav_buttons():
    """
    Update the navigation control states and trigger corresponding actions based on button presses and holds.
    This function manages the state and behavior of the select button and encoder button.

    Usage:
    Call this function in a loop to continuously monitor and react to button presses and holds.

    Example:
    process_nav_buttons()
    """

    global select_button, encoder_button, last_nav_check_time

    # Check for extreme latency. Just reset everything if it's too high
    time_since_last_check = time.monotonic() - last_nav_check_time
    last_nav_check_time = time.monotonic()

    # Select Button released
    if select_button.value and inpts.select_button_state:
        if inpts.select_button_held:
            # Menu.current_menu.display()
            inpts.select_button_dbl_press_time = 0
        else:
            inpts.select_button_dbl_press_time = time.monotonic()

        if inpts.select_button_held:
            Menu.current_menu.fn_button_held_function(True)  # Runs once when released

        inpts.select_button_held = False
        inpts.select_button_state = False
        inpts.select_button_starttime = 0
        pixel_fn_button_off()
        Menu.toggle_select_button_icon(False)

    if not inpts.select_button_state and not select_button.value:
        inpts.select_button_state = True
        inpts.select_button_starttime = time.monotonic()
        inpts.select_button_held = False
        inpts.select_button_dbl_press = False
        pixel_fn_button_on()

        # Select button double press
        if (
            inpts.select_button_starttime - inpts.select_button_dbl_press_time
            < constants.DBL_PRESS_THRESH_S
        ) and not inpts.select_button_dbl_press:
            inpts.select_button_dbl_press = True
            inpts.select_button_dbl_press_time = 0
            Menu.current_menu.fn_button_dbl_press_function()
            inpts.select_button_starttime = (
                time.monotonic()
            )  # dont want erroneous button holds
            print_debug("Select Button Double Press")

        # Select button single press
        else:
            inpts.select_button_dbl_press = False
            inpts.select_button_dbl_press_time = 0
            print_debug("New Sel Btn Press")
            Menu.current_menu.fn_button_press_function()

    # Select button held
    if (
        inpts.select_button_state
        and (time.monotonic() - inpts.select_button_starttime)
        > constants.BUTTON_HOLD_THRESH_S
        and not inpts.select_button_held
    ):
        if time_since_last_check > 0.5:
            pass
        else:
            inpts.select_button_held = True
            inpts.select_button_dbl_press = False
            Menu.toggle_select_button_icon(True)
            Menu.current_menu.fn_button_held_function()  # Runs once when first held
            pixel_fn_button_on(color=constants.FN_BUTTON_COLOR)
            print_debug("Select Button Held")

            # if get_play_mode() == "chord":
            #     display_text_middle(get_quantization_text())

    # Encoder button pressed
    if not inpts.encoder_button_state and not encoder_button.value:
        inpts.encoder_button_state = True
        # Menu.toggle_nav_mode()
        inpts.encoder_button_starttime = time.monotonic()
        print_debug("New encoder Btn Press!!!")

    # Encoder button held
    if (
        inpts.encoder_button_state
        and (time.monotonic() - inpts.encoder_button_starttime)
        > constants.BUTTON_HOLD_THRESH_S
        and not inpts.encoder_button_held
    ):
        inpts.encoder_button_held = True
        Menu.current_menu.encoder_button_held_function()
        print_debug("encoder Button Held")

    # Encoder button released
    if encoder_button.value and inpts.encoder_button_state:
        inpts.encoder_button_state = False
        inpts.encoder_button_starttime = 0
        if not inpts.encoder_button_held:
            Menu.toggle_nav_mode()
        else:
            Menu.current_menu.encoder_button_held_function(True)
        inpts.encoder_button_held = False


def process_inputs_slow():
    global encoder

    hold_count = 0
    inpts.encoder_delta = encoder.position
    encoder.position = 0

    for button_index in range(16):

        # Drum pad button held
        if inpts.button_states[button_index]:
            inpts.button_holdtimes_s[button_index] = (
                time.monotonic() - inpts.button_press_start_times[button_index]
            )
            if (
                inpts.button_holdtimes_s[button_index] > constants.BUTTON_HOLD_THRESH_S
                and not inpts.button_held[button_index]
            ):
                inpts.button_held[button_index] = True
                print_debug(f"holding {button_index}")
        else:
            inpts.button_held[button_index] = False
            inpts.button_holdtimes_s[button_index] = 0

        if inpts.button_held[button_index]:
            hold_count += 1
            if not inpts.any_pad_held:
                inpts.any_pad_held = True
                Menu.current_menu.pad_held_function(button_index, "", 0)

    if inpts.encoder_delta != 0:
        Menu.current_menu.pad_held_function(
            -1, inpts.button_states, inpts.encoder_delta
        )

    if hold_count == 0 and inpts.any_pad_held:
        inpts.any_pad_held = False
        inpts.encoder_delta = 0

    process_nav_buttons()

    if inpts.any_pad_held:
        return

    enc_direction = None
    if inpts.encoder_delta > 0:
        enc_direction = True

    if inpts.encoder_delta < 0:
        enc_direction = False

    if enc_direction is None:
        return

    if Menu.menu_nav_mode:
        Menu.change_menu(enc_direction)
        return

    if inpts.select_button_held:
        Menu.current_menu.fn_button_held_and_encoder_change_function(enc_direction)
        return

    if inpts.encoder_button_held:
        Menu.current_menu.encoder_button_press_and_turn_function(enc_direction)
        return

    Menu.current_menu.encoder_change_function(enc_direction)


def process_inputs_fast():
    global new_notes_on, new_notes_off

    for button_index in range(16):
        inpts.new_press[button_index] = False
        inpts.new_release[button_index] = False

    event = pads.events.get()
    if event:
        pad = event.key_number
        if event.pressed and not inpts.button_states[pad]:
            inpts.new_press[pad] = True
            inpts.button_press_start_times[pad] = time.monotonic()
            inpts.button_states[pad] = True
        elif not event.pressed and inpts.button_states[pad]:
            inpts.new_release[pad] = True
            inpts.button_states[pad] = False
            inpts.button_press_start_times[pad] = 0

    new_notes_on = []
    new_notes_off = []

    # Clear any arp notes that are due to be off. Put this here so we dont get hanging notes when changing modes, etc.
    new_arp_off_notes = arpeggiator.get_off_notes()
    for note in new_arp_off_notes:
        new_notes_off.append(note)

    # Select button is held
    if inpts.select_button_held:
        for button_index in range(16):
            if inpts.new_press[button_index] and get_play_mode() == "velocity":
                if (
                    inpts.singlehit_velocity_btn_midi is not None
                ):  # Turn off single note mode
                    inpts.singlehit_velocity_btn_midi = None
                    Menu.display_notification("Single Note Mode: OFF")
                else:
                    inpts.singlehit_velocity_btn_midi = get_midi_note_by_idx(
                        button_index
                    )  # Turn on single note mode
                    Menu.display_notification(
                        f"Pads mapped to: {get_midi_note_name_text(inpts.singlehit_velocity_btn_midi)}"
                    )

            if inpts.new_press[button_index]:
                chordmaker.add_remove_chord(button_index)

        return

    # Encoder play mode
    if get_play_mode() == "encoder":

        if not True in inpts.button_states:  # nothing is pressed.
            return

        # Reset arp notes to track if changed.
        if inpts.encoder_delta > 0:
            if arpeggiator.skip_this_turn():
                return
            arpeggiator.clear_arp_notes()

        for button_index in range(16):
            if inpts.button_states[button_index]:

                # Turn off notes if encoder is turned ccw
                if inpts.encoder_delta < 0:
                    note = get_midi_note_by_idx(button_index)
                    if inpts.singlehit_velocity_btn_midi:
                        note = inpts.singlehit_velocity_btn_midi
                    for note in get_current_midi_notes():
                        new_notes_off.append((note, 0, button_index))

                # Turn on notes if encoder is turned cw
                if inpts.encoder_delta > 0:
                    note = get_midi_note_by_idx(button_index)
                    if inpts.singlehit_velocity_btn_midi:
                        note = inpts.singlehit_velocity_btn_midi
                    velocity = get_midi_velocity_by_idx(button_index)

                    # If chord exists, then get chord notes instead of just pad note
                    if chordmaker.pad_chords[button_index]:
                        print(chordmaker.pad_chords)
                        notes = chordmaker.get_current_chord_notes(button_index)
                        for note in notes:
                            arpeggiator.add_arp_note(note)

                    # Otherwise just get the pad note
                    else:
                        print(f"adding arp single note {note}")
                        arpeggiator.add_arp_note((note, velocity, button_index))

        if arpeggiator.has_arp_notes() and inpts.encoder_delta > 0:
            note = arpeggiator.get_next_arp_note()
            if arpeggiator.monophonic:
                new_notes_off.append(arpeggiator.get_previous_arp_note())
            # new_notes_off.append(note)
            new_notes_on.append(note)
        return

    # Get new midi on/off notes
    for button_index in range(16):
        if not (inpts.new_press[button_index] or inpts.new_release[button_index]):
            continue

        note = None
        velocity = None

        # Get note and velocity data
        if inpts.singlehit_velocity_btn_midi is not None:
            note = inpts.singlehit_velocity_btn_midi
            velocity = get_midi_velocity_singlenote_by_idx(button_index)
        else:
            note = get_midi_note_by_idx(button_index)
            velocity = get_midi_velocity_by_idx(button_index)

        # Toggle loop playstate if chord exists and mode is chordloop
        if inpts.new_press[button_index]:
            print_debug(f"new press on {button_index}")
            if chordmaker.pad_chords[button_index] and not chordmaker.recording:
                if chordmaker.pad_chords[button_index].loop_type == "chordloop":
                    chordmaker.pad_chords[button_index].loop_toggle_playstate()
                    chordmaker.pad_chords[button_index].reset_loop_notes_and_pixels()
                else:
                    chordmaker.pad_chords[button_index].reset_loop()
            else:
                new_notes_on.append((note, velocity, button_index))

        if inpts.new_release[button_index]:
            if chordmaker.pad_chords[button_index] and not chordmaker.recording:
                pass
            else:
                new_notes_off.append((note, 127, button_index))
