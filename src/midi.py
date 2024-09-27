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
from display import display_text_middle, display_selected_dot,pixel_set_note_on
import usb_midi
from utils import next_or_previous_index
from midiscales import get_all_scales_list, get_midi_banks_chromatic, get_scale_display_text, NUM_ROOTS
from globalstates import global_states

from settings import settings as s
import constants

NUM_PADS = 16
ENC_BUTTON_IDX = 17

uart = busio.UART(constants.UART_MIDI_TX, constants.UART_MIDI_RX, baudrate=31250,timeout=0.001)

uart_midi = adafruit_midi.MIDI(
    midi_in=uart,
    midi_out=uart,
    in_channel=s.midi_channel_out,
    out_channel=s.midi_channel_out,
    debug=False,)

usb_midi = adafruit_midi.MIDI(
    midi_in=usb_midi.ports[0],
    midi_out=usb_midi.ports[1],
    in_channel=s.midi_channel_out,
    out_channel=s.midi_channel_out,
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

def set_all_midi_velocities(val, check_default=True):
    """
    Sets all MIDI velocities to the given value for pads that are at the current default velocity.
    
    Args:
        val (int): The new MIDI velocity value.
        check_default (bool, optional): If True, only pads with the default velocity will be updated. Default is False.
    """
    for i in range(16):
        if check_default:
            if midi_velocities[i] == s.default_velocity:
                midi_velocities[i] = val
        else:
            midi_velocities[i] = val

def set_midi_velocity_by_idx(idx, vel):
    """
    Sets the MIDI velocity for a given index.
    
    Args:
        idx (int): Index of the MIDI velocity to set.
        val (int): The new MIDI velocity value.
    """
    midi_velocities[idx] = vel
    pixel_set_note_on(idx, vel)
    print_debug(f"Setting MIDI velocity: {vel}")

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

def should_send_midi(midi_type):
    """
    Determines whether or not to send MIDI based on the given MIDI type and the setup.
    
    Args:
        midi_type (str): The MIDI type, either "USB" or "AUX".
    
    Returns:
        bool: True if MIDI should be sent, False otherwise.
    """
    midi_type = midi_type.upper()
    
    if midi_type == "USB":
        return s.midi_type.upper() in ('USB', 'ALL') and s.midi_usb_io in ('both', 'out')
    if midi_type == "AUX":
        return s.midi_type.upper() in ('AUX', 'ALL') and s.midi_aux_io in ('both', 'out')
    
    return False

def should_receive_midi(midi_type):
    """
    Determines whether or not to receive MIDI based on the given MIDI type and the setup.
    
    Args:
        midi_type (str): The MIDI type, either "USB" or "AUX".
    
    Returns:
        bool: True if MIDI should be received, False otherwise.
    """
    midi_type = midi_type.upper()
    
    if midi_type == "USB":
        return s.midi_type.upper() in ('USB', 'ALL') and s.midi_usb_io in ('both', 'in')
    elif midi_type == "AUX":
        return s.midi_type.upper() in ('AUX', 'ALL') and s.midi_aux_io in ('both', 'in')
    
    return False

def send_midi_note_on(note, velocity):
    """
    Sends a MIDI note-on message with the given note and velocity.
    
    Args:
        note (int): MIDI note value (0-127).
        velocity (int): MIDI velocity value (0-127).
    """
    if should_send_midi("USB"):
        usb_midi.send(NoteOn(note, velocity))
    
    if should_send_midi("AUX"):
        uart_midi.send(NoteOn(note, velocity))

def send_cc_message(cc, val):
    """
    Sends a MIDI control change message with the given control change number and value.
    
    Args:
        cc (int): Control change number (0-127).
        val (int): Control change value (0-127).
    """
    if should_send_midi("USB"):
        usb_midi.send(ControlChange(cc, val))

    if should_receive_midi("AUX"):
        uart_midi.send(ControlChange(cc, val))

def send_midi_note_off(note):
    """
    Sends a MIDI note-off message for the given note.
    
    Args:
        note (int): MIDI note value (0-127).
    """
    if should_send_midi("USB"):
        usb_midi.send(NoteOff(note, 1))

    if should_send_midi("AUX"):
        uart_midi.send(NoteOff(note, 1))

def clear_all_notes():
    for i in range(127):
        send_midi_note_off(i)
        
def process_midi_in(msg):
    """
    Processes a MIDI message.
    
    Args:
        msg (MIDI message): The MIDI message to process.
        type (str): The type of MIDI message, either "usb" or "uart".
    """
    result = None
    if not isinstance(msg, TimingClock):
        print_debug(f"Processing MIDI In: {msg}")

    if isinstance(msg, NoteOn):
        if not clock.get_playstate():
            clock.set_play_state(True) # Ableton sends note before play sometimes.
        return((msg.note, msg.velocity, 0), ())
        
    elif isinstance(msg, NoteOff):
        return ((), (msg.note, msg.velocity, 0))

    if not s.midi_sync: # You can always record notes regardless of sync.
        return ((),())

    if isinstance(msg, TimingClock):
        clock.update_clock()

    # elif isinstance(msg, ControlChange): # Not used
    #     result = ((), ())

    elif isinstance(msg, Start):
        clock.set_play_state(True)

    elif isinstance(msg, Stop):
        clock.set_play_state(False)

    return result

def get_midi_messages_in():
    """
    Checks for MIDI messages and processes them.
    """
    output = ((), ())

    # Check for MIDI messages from the USB MIDI port
    if should_receive_midi("USB"):
        msg = usb_midi.receive()
        if msg is not None:
            output = process_midi_in(msg)

    # Check for MIDI messages from the UART MIDI port
    if should_receive_midi("AUX"):
        msg = uart_midi.receive()
        if msg is not None:
            output = process_midi_in(msg)

    return output

# ------------------ Get / Change settings ------- #
def change_midi_channel(up_or_down=True, in_or_out="out", set_channel=None):
    """
    Changes the MIDI channel for input, output

    Args:
        up_or_down (bool, optional): Determines whether to increment or decrement the MIDI channel. Defaults to True (increment).
        set_channel (int, optional): The channel to set. Defaults to None. Use to directly set channel instead of cycling.

    Returns:
        None
    """
    if set_channel is not None and in_or_out == "in":
        s.midi_channel_in = set_channel
        usb_midi.in_channel = s.midi_channel_in
        uart_midi.in_channel = s.midi_channel_in
        debug.add_debug_line("Midi Channel In changed to ", f"Channel: {s.midi_channel_in}")

    elif set_channel is not None and in_or_out == "out":
        s.midi_channel_out = set_channel
        usb_midi.out_channel = s.midi_channel_out
        uart_midi.out_channel = s.midi_channel_out
        debug.add_debug_line("Midi Channel Out changed to ", f"Channel: {s.midi_channel_out}")

    elif in_or_out == "in":
        s.midi_channel_in = next_or_previous_index(s.midi_channel_in, 16, up_or_down)
        usb_midi.in_channel = s.midi_channel_in
        uart_midi.in_channel = s.midi_channel_in
        debug.add_debug_line("Midi Channel In changed to ", f"Channel: {s.midi_channel_in}")
    else:
        s.midi_channel_out = next_or_previous_index(s.midi_channel_out, 16, up_or_down)
        usb_midi.out_channel = s.midi_channel_out
        uart_midi.out_channel = s.midi_channel_out
        debug.add_debug_line("Midi Channel Out changed to ", f"Channel: {s.midi_channel_out}")

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
    global_states.play_mode = mode

def shift_note_octave(note, up_or_down=True, num_octaves=1):
    """
    Shifts a note up or down by one octave.

    Args:
        note (tuple): A tuple containing note value, velocity, and pad index.
        up_or_down (bool, optional): Determines whether to shift the note up or down. Default is True (up).
        num_octaves (int, optional): The number of octaves to shift the note. Default is 1.

    Returns:
        tuple: The shifted note.
    """
    shift_amt = 12 * num_octaves
    note_val, velocity, pad_idx = note

    if up_or_down:
        new_note_val = note_val + shift_amt
    else:
        new_note_val = note_val - shift_amt

    if new_note_val < 0 or new_note_val > 127:
        new_note_val = note_val

    return (new_note_val, velocity, pad_idx)

def shift_all_notes_octaves(up_or_down=True, num_octaves=1):
    """
    Shifts all notes up or down by a certain number of octaves.

    Args:
        up_or_down (bool, optional): Determines whether to shift the notes up or down. Default is True (up).
        num_octaves (int, optional): The number of octaves to shift the notes. Default is 1.

    Returns:
        None
    """
    for i in range(16):
        shifted_note = shift_note_octave(s.midi_notes_default[i], up_or_down, num_octaves=num_octaves)
        if shifted_note[0] >= 0 and shifted_note[0] <= 127:
            s.midi_notes_default[i] = shifted_note

def get_current_midi_notes():
    """
    Returns the current MIDI notes assigned to pads (16)

    Returns:
        list: A list of MIDI notes.
    """
    return s.midi_notes_default
