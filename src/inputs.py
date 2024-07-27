from settings import settings
import board
import digitalio
import rotaryio
import keypad
import chordmaker
from debug import DEBUG_MODE
from midi import (get_midi_velocity_by_idx,
                       get_midi_note_by_idx,
                       get_midi_velocity_singlenote_by_idx,
                       get_midi_note_name_text,
                       get_play_mode,
                       get_current_midi_notes,
                       clear_all_notes)
from menus import Menu
from display import pixel_note_on, pixel_note_off, pixel_fn_button_off, pixel_fn_button_on, pixel_encoder_button_off, pixel_encoder_button_on, check_show_display, display_text_middle
from time import monotonic
from looper import next_quantization,get_quantization_text



FN_BUTTON_COLOR = (255, 165, 0)
pads = keypad.KeyMatrix(
    row_pins=(board.GP4, board.GP3, board.GP2, board.GP1),
    column_pins=(board.GP5, board.GP6, board.GP7, board.GP8),
    columns_to_anodes=True
)

SELECT_BTN_PIN = board.GP10
ENCODER_BTN_PIN = board.GP11
ENCODER_CLK_PIN = board.GP12
ENCODER_DT_PIN = board.GP13

select_button = digitalio.DigitalInOut(SELECT_BTN_PIN)
encoder_button = digitalio.DigitalInOut(ENCODER_BTN_PIN)
encoder = rotaryio.IncrementalEncoder(ENCODER_DT_PIN, ENCODER_CLK_PIN)

select_button.direction = digitalio.Direction.INPUT
select_button.pull = digitalio.Pull.UP
encoder_button.direction = digitalio.Direction.INPUT
encoder_button.pull = digitalio.Pull.UP

note_buttons = []

# TRACKING VARIABLES
encoder_pos_now = 0
encoder_delta = 0
select_button_starttime = 0
select_button_holdtime_s = 0
select_button_held = False
select_button_dbl_press = False
select_button_dbl_press_time = 0
select_button_state = False
encoder_button_state = False
encoder_button_starttime = 0
encoder_button_holdtime = 0
encoder_button_held = False
singlehit_velocity_btn_midi = None       # In this mode, 1 midi note is mapped to 16 diff velocities
any_pad_held = False
note_states = [False] * 16         # Keep track of if we are sending a midi note or not
button_states = [False] * 16       # Keep track of the state of the button - may not want to send MIDI on a press
button_press_start_times = [None] * 16
button_held = [False] * 16
new_press = [False] * 16           # Track when a new btn press.
new_release = [False] * 16         # and release
button_holdtimes_s = [0] * 16
encoder_mode_ontimes = []
new_notes_on = []               # Set when new midi note should send. Clear after sending. tuple: (note, velocity)
new_notes_off = []              # Set when a new note off message should go. int: midi note val


def update_nav_controls():
    """
    Update the navigation control states and trigger corresponding actions based on button presses and holds.
    This function manages the state and behavior of the select button and encoder button.

    Globals Used:
    - select_button_state: Indicates if the select button is currently pressed.
    - select_button_starttime: Timestamp when the select button is pressed.
    - select_button_holdtime_s: Threshold for considering the button press as a long hold.
    - select_button_held: Flag to indicate if the select button is being held down.
    - select_button_dbl_press: Flag to indicate if the select button is double-pressed.
    - select_button_dbl_press_time: Timestamp for the last double-press event.
    - encoder_button_state: Indicates if the encoder button is currently pressed.
    - encoder_button_starttime: Timestamp when the encoder button is pressed.
    - encoder_button_holdtime: Threshold for considering the encoder button press as a long hold.
    - encoder_button_held: Flag to indicate if the encoder button is being held down.

    Actions:
    - Handles single presses, double presses, and long holds for the select button.
    - Toggles the navigation mode when the encoder button is pressed.

    Usage:
    Call this function in a loop to continuously monitor and react to button presses and holds.

    Example:
    update_nav_controls()
    """
    global select_button_state, select_button_starttime, select_button_holdtime_s, select_button_held
    global select_button_dbl_press, select_button_dbl_press_time, encoder_button_state
    global encoder_button_starttime, encoder_button_holdtime, encoder_button_held

    if not select_button.value and not select_button_state:
        select_button_state = True
        select_button_starttime = monotonic()
        select_button_dbl_press = False
        pixel_fn_button_on()

        if (select_button_starttime - select_button_dbl_press_time < settings.DBL_PRESS_THRESH_S) and not select_button_dbl_press:
            select_button_dbl_press = True
            select_button_dbl_press_time = 0
            Menu.current_menu.fn_button_dbl_press_function()
        else:
            select_button_dbl_press = False
            select_button_dbl_press_time = 0
            if DEBUG_MODE:
                print("New Sel Btn Press!!!")
            Menu.current_menu.fn_button_press_function()

    if select_button_state and (monotonic() - select_button_starttime) > settings.BUTTON_HOLD_THRESH_S and not select_button_held:
        select_button_held = True
        select_button_dbl_press = False

        Menu.toggle_select_button_icon(True)
        Menu.current_menu.fn_button_held_function()
        pixel_fn_button_on(color=FN_BUTTON_COLOR)
        if DEBUG_MODE:
            print("Select Button Held")
        # DJT - maybe move this to the fn_button_held_function..
        # if we are in chord mode, display quantization options on the screen
        if get_play_mode() == "chord":
            display_text_middle(get_quantization_text())
                        

    if select_button.value and select_button_state:
        if select_button_held:
            Menu.current_menu.display()
            select_button_dbl_press_time = 0
        else:
            select_button_dbl_press_time = monotonic()
        
        select_button_held = False
        select_button_state = False
        # select_button_dbl_press_time = monotonic()
        select_button_starttime = 0
        pixel_fn_button_off()

        Menu.toggle_select_button_icon(False)

    if not encoder_button.value and not encoder_button_state:
        encoder_button_state = True
        Menu.toggle_nav_mode()
        encoder_button_starttime = monotonic()
        if DEBUG_MODE:
            print("New encoder Btn Press!!!")

    if encoder_button_state and (monotonic() - encoder_button_starttime) > settings.BUTTON_HOLD_THRESH_S and not encoder_button_held:
        encoder_button_held = True
        if DEBUG_MODE:
            print("encoder Button Held")

    if encoder_button.value and encoder_button_state:
        encoder_button_state = False
        encoder_button_starttime = 0
        encoder_button_held = False

def check_inputs_slow():
    global button_states, button_press_start_times, button_held, button_holdtimes_s
    global encoder_pos_now, encoder_delta, any_pad_held, current_assignment_velocity

    hold_count = 0
    encoder_delta = encoder.position
    encoder.position = 0

    for button_index in range(16):
        delta_used = False

        if button_states[button_index]:
            button_holdtimes_s[button_index] = monotonic() - button_press_start_times[button_index]
            if button_holdtimes_s[button_index] > settings.BUTTON_HOLD_THRESH_S and not button_held[button_index]:
                button_held[button_index] = True
                if DEBUG_MODE:
                    print(f"holding {button_index}")
        else:
            button_held[button_index] = False
            button_holdtimes_s[button_index] = 0

        if button_states[button_index]:
            hold_count += 1
            if not any_pad_held:
                any_pad_held = True
                delta_used = Menu.current_menu.pad_held_function(button_index, encoder_delta, True)
            else:
                delta_used = Menu.current_menu.pad_held_function(button_index, encoder_delta, False)

        if delta_used:
            encoder_delta = 0

    if hold_count == 0 and any_pad_held:
        any_pad_held = False
        encoder_delta = 0

    update_nav_controls()

    if any_pad_held:
        return

    enc_direction = None
    if encoder_delta > 0:
        enc_direction = True
    elif encoder_delta < 0:
        enc_direction = False

    if enc_direction is None:
        return

    if Menu.menu_nav_mode:
        Menu.change_menu(enc_direction)
        return
    
    elif select_button_held and get_play_mode() == "chord":
        if enc_direction:
            next_quantization()
        else:
            next_quantization(False)
        display_text_middle(get_quantization_text())

    else:
        Menu.current_menu.encoder_change_function(enc_direction)

def check_inputs_fast():
    global new_press, new_release, button_press_start_times, button_states

    for button_index in range(16):
        new_press[button_index] = False
        new_release[button_index] = False

    event = pads.events.get()
    if event:
        pad = event.key_number
        if event.pressed and not button_states[pad]:
            new_press[pad] = True
            button_press_start_times[pad] = monotonic()
            button_states[pad] = True
        elif not event.pressed and button_states[pad]:
            new_release[pad] = True
            button_states[pad] = False
            button_press_start_times[pad] = 0

def process_inputs_fast():
    global new_press, new_release, new_notes_on, new_notes_off, singlehit_velocity_btn_midi
    global encoder_mode_ontimes, any_pad_held, encoder_delta

    new_notes_on = []
    new_notes_off = []

    if select_button_held:
        for button_index in range(16):
            if new_press[button_index] and get_play_mode() != "chord":
                if singlehit_velocity_btn_midi is not None:
                    singlehit_velocity_btn_midi = None
                    Menu.display_notification("Single Note Mode: OFF")
                else:
                    singlehit_velocity_btn_midi = get_midi_note_by_idx(button_index)
                    Menu.display_notification(f"Pads mapped to: {get_midi_note_name_text(singlehit_velocity_btn_midi)}")
                
            if new_press[button_index] and get_play_mode() == "chord":
                chordmaker.add_remove_chord(button_index)

        return

    if encoder_button_held:
        clear_all_notes()
        return

    if get_play_mode() == "encoder" and any_pad_held:
        for button_index in range(16):
            if button_states[button_index]:
                if encoder_delta < 0:
                    note = get_midi_note_by_idx(button_index)
                    if singlehit_velocity_btn_midi:
                        note = singlehit_velocity_btn_midi
                    for note in get_current_midi_notes():
                        new_notes_off.append((note, 0, button_index))

                if encoder_delta > 0:
                    note = get_midi_note_by_idx(button_index)
                    if singlehit_velocity_btn_midi:
                        note = singlehit_velocity_btn_midi
                    velocity = get_midi_velocity_by_idx(button_index)
                    new_notes_off.append((note, 0, button_index))
                    new_notes_on.append((note, velocity, button_index))

    for button_index in range(16):
        if not (new_press[button_index] or new_release[button_index]):
            continue

        note = None
        velocity = None

        if singlehit_velocity_btn_midi is not None:
            note = singlehit_velocity_btn_midi
            velocity = get_midi_velocity_singlenote_by_idx(button_index)
        else:
            note = get_midi_note_by_idx(button_index)
            velocity = get_midi_velocity_by_idx(button_index)

        if new_press[button_index]:
            if DEBUG_MODE:
                print(f"new press on {button_index}")
            if chordmaker.current_chord_notes[button_index] and not chordmaker.recording:
                chordmaker.current_chord_notes[button_index].loop_toggle_playstate(True)
                # chordmaker.current_chord_notes[button_index].reset_loop()
            else:
                new_notes_on.append((note, velocity, button_index))

        if new_release[button_index]:
            if chordmaker.current_chord_notes[button_index] and not chordmaker.recording:
                pass
            else:
                new_notes_off.append((note, 127, button_index))