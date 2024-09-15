from clock import clock

import adafruit_midi
from adafruit_midi.control_change import ControlChange
from adafruit_midi.note_off import NoteOff
from adafruit_midi.note_on import NoteOn
from adafruit_midi.pitch_bend import PitchBend
from adafruit_midi.start import Start
from adafruit_midi.stop import Stop
from adafruit_midi.timing_clock import TimingClock
import busio
from debug import debug, print_debug
from display import display_text_middle, display_selected_dot
import usb_midi
from utils import next_or_previous_index
from midiscales import get_all_scales_list, get_midi_banks_chromatic, get_scale_display_text, NUM_SCALES, NUM_ROOTS

from settings import settings as s
import constants

NUM_PADS = 16
ENC_BUTTON_IDX = 17

uart = busio.UART(constants.UART_MIDI_TX, constants.UART_MIDI_RX, baudrate=31250,timeout=0.001)

uart_midi = adafruit_midi.MIDI(
    midi_in=uart,
    midi_out=uart,
    in_channel=s.midi_channel,
    out_channel=s.midi_channel,
    debug=False,)

usb_midi = adafruit_midi.MIDI(
    midi_in=usb_midi.ports[0],
    midi_out=usb_midi.ports[1],
    in_channel=s.midi_channel,
    out_channel=s.midi_channel,
    debug=False)

messages = (NoteOn, 
            NoteOff, 
            PitchBend, 
            ControlChange, 
            TimingClock, 
            Start, 
            Stop,)

current_midibank_set = get_midi_banks_chromatic()
current_scale_list = []
midi_velocities = [s.default_velocity] * 16
midi_velocities_singlenote = constants.DEFAULT_SINGLENOTE_MODE_VELOCITIES
current_assignment_velocity = 120
all_scales_list = get_all_scales_list()

def get_current_scale_display_text():
    return get_scale_display_text(current_scale_list)

def get_midi_bank_idx():
    """
    Returns a string displaying the current MIDI bank information.
    
    Returns:
        str: A string containing the MIDI bank index and the note range, e.g., "Bank: 0 (C1 - G1)".
    """
    return s.midibank_idx

def get_scale_bank_idx():
    """
    Returns a string displaying the current scale bank information.
    
    Returns:
        str: A string containing the scale bank index and the note range, e.g., "Scale: 0 (C1 - G1)".
    """
    return s.scale_idx

def get_scale_notes_idx():
    """
    Returns a string displaying the current scale notes index.
    
    Returns:
        str: A string containing the scale notes index, e.g., "Scale Notes: 0".
    """
    return s.scalenotes_idx



# ------------------ MIDI / Velocity Manipulation ------------------ #
def update_global_velocity(new_velocity):
    """
    Updates the global velocity variable with the given value.

    Parameters:
    new_velocity (int): The new velocity value to be assigned.

    Returns:
    None
    """
    global current_assignment_velocity
    current_assignment_velocity = new_velocity

def get_current_assignment_velocity():
    """
    Returns the current assignment velocity.

    Returns:
    int: The current assignment velocity.
    """
    return current_assignment_velocity

def get_midi_velocity_by_idx(idx):
    """
    Returns the MIDI velocity for a given index.
    
    Args:
        idx (int): Index of the MIDI velocity to retrieve.
        
    Returns:
        int: The MIDI velocity value.
    """
    return midi_velocities[idx]

def set_midi_velocity_by_idx(idx, val):
    """
    Sets the MIDI velocity for a given index.
    
    Args:
        idx (int): Index of the MIDI velocity to set.
        val (int): The new MIDI velocity value.
    """
    midi_velocities[idx] = val
    print_debug(f"Setting MIDI velocity: {val}")

def get_midi_note_by_idx(idx):
    """
    Returns the MIDI note for a given index.
    
    Args:
        idx (int): Index of the MIDI note to retrieve.
        
    Returns:
        int: The MIDI note value.
    """
    print_debug(f"Getting MIDI note for pad index: {idx}")

    if idx > len(s.midi_notes_default) - 1:
        idx = len(s.midi_notes_default) - 1
        
    return s.midi_notes_default[idx]

def set_midi_note_by_idx(idx, val):
    """
    Sets the MIDI note for a given index.
    
    Args:
        idx (int): Index of the MIDI note to set.
        val (int): The new MIDI note value.
    """
    s.midi_notes_default[idx] = val

def get_midi_velocity_singlenote_by_idx(idx):
    """
    Returns the MIDI note velocity for a specific pad index.
    
    Args:
        idx (int): Index of the pad.
        
    Returns:
        int: The MIDI velocity value.
    """
    return midi_velocities_singlenote[idx]

def send_midi_note_on(note, velocity):
    """
    Sends a MIDI note-on message with the given note and velocity.
    
    Args:
        note (int): MIDI note value (0-127).
        velocity (int): MIDI velocity value (0-127).
    """
    if s.midi_type.upper() in ('USB', 'ALL'):
        usb_midi.send(NoteOn(note, velocity))
    
    if s.midi_type.upper() in ('AUX', 'ALL'):
        uart_midi.send(NoteOn(note, velocity))

def send_midi_note_off(note):
    """
    Sends a MIDI note-off message for the given note.
    
    Args:
        note (int): MIDI note value (0-127).
    """
    if s.midi_type.upper() in ('USB', 'ALL'):
        usb_midi.send(NoteOff(note, 1))

    if s.midi_type.upper() in ('AUX', 'ALL'):
        uart_midi.send(NoteOff(note, 1))

def clear_all_notes():
    for i in range(127):
        send_midi_note_off(i)
        
def process_midi_in(msg,midi_type="usb"):
    """
    Processes a MIDI message.
    
    Args:
        msg (MIDI message): The MIDI message to process.
        type (str): The type of MIDI message, either "usb" or "uart".
    """
    result = None
    if not isinstance(msg, TimingClock):
        print(f"Processing MIDI In: {msg}")
        
    if isinstance(msg, NoteOn):
        result = ((msg.note, msg.velocity, 0), ())
        if not clock.get_playstate():
            clock.set_play_state(True) # Ableton sends note before play sometimes.
        
    elif isinstance(msg, NoteOff):
        result = ((), (msg.note, msg.velocity, 0))

    # elif isinstance(msg, ControlChange):
    #     result = ((), ())

    elif isinstance(msg, TimingClock):
        clock.update_clock()
        # result = ((), ())

    elif isinstance(msg, Start):
        clock.set_play_state(True)
        # result = ((), ())

    elif isinstance(msg, Stop):
        clock.set_play_state(False)
        # result = ((), ())

    return result

def get_midi_messages_in():
    """
    Checks for MIDI messages and processes them.
    """
    if not s.midi_sync:
        return ((),())
    
    # Check for MIDI messages from the USB MIDI port
    msg = usb_midi.receive()
    output = ((),())
    if msg is not None:
        output = process_midi_in(msg,midi_type="usb")

    # Check for MIDI messages from the UART MIDI port
    msg = uart_midi.receive()
    if msg is not None:
        output = process_midi_in(msg,midi_type="uart")

    return output

# ------------------ Get / Change settings ------- #
def change_midi_channel(up_or_down=True):
    """
    Changes the MIDI channel for both input and output.

    Args:
        up_or_down (bool, optional): Determines whether to increment or decrement the MIDI channel. Defaults to True (increment).

    Returns:
        None
    """
    s.midi_channel = next_or_previous_index(s.midi_channel, 16, up_or_down)
    s.midi_channel = next_or_previous_index(s.midi_channel, 16, up_or_down)

    usb_midi.in_channel = s.midi_channel
    usb_midi.out_channel = s.midi_channel
    uart_midi.in_channel = s.midi_channel
    uart_midi.out_channel = s.midi_channel
    debug.add_debug_line("Midi Channel", f"Channel: {s.midi_channel}")

def next_or_prev_scale(up_or_down=True, display_text=True):
    """
    Change the current scale used in the MIDI loopster.

    Args:
        up_or_down (bool, optional): Determines whether to change to the next scale (True) or the previous scale (False). Default is True.
        display_text (bool, optional): Determines whether to display the updated scale text. Default is True.

    Returns:
        None
    """
    global current_scale_list

    s.scale_idx = next_or_previous_index(s.scale_idx, len(all_scales_list), up_or_down)

    current_scale_list = all_scales_list[s.scale_idx][1]  # maj, min, etc. item 0 is the name.
    if s.scale_idx == 0:
        s.midi_notes_default = current_scale_list[0][1][s.midibank_idx]  # special handling for chromatic.
    else:
        s.midi_notes_default = current_scale_list[s.rootnote_idx][1][s.scalenotes_idx]  # item 0 is c,d,etc.
    if display_text:
        display_text_middle(get_scale_display_text(current_scale_list))
        # display_selected_dot("R", True)
    print_debug(f"current midi notes: {s.midi_notes_default}")
    debug.add_debug_line("Current Scale", get_scale_display_text(current_scale_list))

def next_or_prev_root(up_or_down=True, display_text=True):
    """
    Change the root note of the current scale.

    Args:
        up_or_down (bool, optional): Determines whether to change the root note up or down. Defaults to True.
        display_text (bool, optional): Determines whether to display the updated scale text. Defaults to True.

    Returns:
        None
    """
    if s.scale_idx == 0:  # doesn't make sense for chromatic.
        return

    s.rootnote_idx = next_or_previous_index(s.rootnote_idx, NUM_ROOTS, up_or_down)

    s.midi_notes_default = current_scale_list[s.rootnote_idx][1][s.scalenotes_idx]  # item 0 is c,d,etc.
    print_debug(f"current midi notes: {s.midi_notes_default}")
    debug.add_debug_line("Current Scale", get_scale_display_text(current_scale_list))
    if display_text:
        display_text_middle(get_scale_display_text(current_scale_list))

def scale_fn_press_function(action_type):
    """
    Handle the function press action for changing the scale.

    Args:
        action_type (str): The type of action performed. Should be "release".

    Returns:
        None
    """
    if action_type not in ["release"]:
        return
    
    next_or_prev_root(up_or_down=True, display_text=True)

def scale_fn_held_function(trigger_on_release=False):
    """
    Handle the function held action for changing the scale.

    Args:
        trigger_on_release (bool, optional): Whether to trigger the action on release. Defaults to False.

    Returns:
        None
    """
    if not trigger_on_release:
        display_selected_dot(0, True)
        return

    if trigger_on_release:
        display_selected_dot(0, False)
        display_selected_dot(3, True)
        return

def scale_setup_function():
    """
    Setup the scale selection function.

    Returns:
        None
    """
    display_selected_dot(3, True)

def next_or_prev_midi_bank(up_or_down=True):
    """
    Change the MIDI bank index and update the current MIDI notes.

    Args:
        up_or_down (bool, optional): Determines whether to move the MIDI bank index up or down. Defaults to True.

    Returns:
        None
    """
    global current_midibank_set

    # Chromatic mode    
    if s.scale_idx == 0:
        current_midibank_set = current_scale_list[0][1]  # chromatic is special
        s.midibank_idx = next_or_previous_index(s.midibank_idx, len(current_midibank_set), up_or_down)
        clear_all_notes()
        s.midi_notes_default = current_midibank_set[s.midibank_idx]

    # Scale Mode
    else:
        current_midibank_set = current_scale_list[s.rootnote_idx][1]
        s.scalenotes_idx = next_or_previous_index(s.scalenotes_idx, len(current_midibank_set), up_or_down)
        clear_all_notes()
        s.midi_notes_default = current_midibank_set[s.scalenotes_idx] 

    return

def chg_midi_mode(nextOrPrev=1):
    """
    Changes the MIDI mode to the next or previous mode.
    
    Args:
        nextOrPrev (int, optional): 1 for the next mode, 0 for the previous mode. Default is 1 (next).
    
    Returns:
        None
    """
    if nextOrPrev:
        if s.midi_type == "usb":
            s.midi_type = "aux"
        elif s.midi_type == "aux":
            s.midi_type = "all"
        elif s.midi_type == "all":
            s.midi_type = "usb"
    
    if not nextOrPrev:
        if s.midi_type == "usb":
            s.midi_type = "all"
        elif s.midi_type == "aux":
            s.midi_type = "usb"
        elif s.midi_type == "all":
            s.midi_type = "aux"

def setup_midi():
    """
    Sets up the MIDI configuration for the application.

    This function initializes the global variables `current_scale_list`, `s.midi_notes_default`, and `current_midibank_set`.
    It assigns the appropriate values based on the default settings.

    Returns:
        None
    """
    global current_scale_list
    global current_midibank_set

    current_scale_list = all_scales_list[s.scale_idx][1]

    if s.scale_idx == 0:  # special handling for chromatic.
        print("chromatic timeeee")
        current_midibank_set = current_scale_list[0][1]
        s.midi_notes_default = current_midibank_set[s.midibank_idx]
    else:
        current_midibank_set = current_scale_list[s.rootnote_idx][1]
        s.midi_notes_default = current_scale_list[s.rootnote_idx][1][s.scalenotes_idx]  # item 0 is c,d,etc.

def get_play_mode():
    """
    Returns the current play mode.

    Returns:
        str: The current play mode.
    """
    return s.playmode

def set_play_mode(mode):
    """
    Sets the play mode for the MIDI loopster.

    Args:
        mode (str): The play mode to set.

    Returns:
        None
    """
    s.playmode = mode

def shift_note_one_octave(note, up_or_down=True):
    """
    Shifts a note up or down by one octave.

    Args:
        note (tuple): A tuple containing note value, velocity, and pad index.
        up_or_down (bool, optional): Determines whether to shift the note up or down. Default is True (up).

    Returns:
        tuple: The shifted note.
    """
    note_val, velocity, pad_idx = note

    if up_or_down:
        new_note_val = note_val + 12
    else:
        new_note_val = note_val - 12

    if new_note_val < 0 or new_note_val > 127:
        new_note_val = note_val

    return (new_note_val, velocity, pad_idx)

def get_current_midi_notes():
    """
    Returns the current MIDI notes for the loopster.

    Returns:
        list: A list of MIDI notes.
    """
    return s.midi_notes_default
