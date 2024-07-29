from collections import OrderedDict
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
from display import display_notification, display_text_middle
import usb_midi
from utils import next_or_previous_index

from settings import settings
import constants

NUM_PADS = 16

uart = busio.UART(constants.UART_MIDI_TX, constants.UART_MIDI_RX, baudrate=31250,timeout=0.001)
midi_in_channel = settings.MIDI_CHANNEL
midi_out_channel = settings.MIDI_CHANNEL
midi_sync = settings.MIDI_SYNC_STATUS

uart_midi = adafruit_midi.MIDI(
    midi_in=uart,
    midi_out=uart,
    in_channel=midi_in_channel,
    out_channel=midi_out_channel,
    debug=False,)

usb_midi = adafruit_midi.MIDI(
    midi_in=usb_midi.ports[0],
    midi_out=usb_midi.ports[1],
    in_channel=midi_in_channel,
    out_channel=midi_out_channel,
    debug=False)

messages = (NoteOn, 
            NoteOff, 
            PitchBend, 
            ControlChange, 
            TimingClock, 
            Start, 
            Stop,)

midi_banks_chromatic = [
    [0 + i for i in range(16)],
    [4 + i for i in range(16)],
    [20 + i for i in range(16)],
    [36 + i for i in range(16)],
    [52 + i for i in range(16)],
    [68 + i for i in range(16)],
    [84 + i for i in range(16)],
    [100 + i for i in range(16)],
    [111 + i for i in range(16)]
]

current_midi_notes = settings.MIDI_NOTES_DEFAULT
midi_settings_page_indicies = settings.MIDI_SETTINGS_PAGE_INDICIES
midi_bank_idx = settings.DEFAULT_MIDIBANK_IDX
scale_bank_idx = settings.DEFAULT_SCALE_IDX        # Chromatic, maj, min, etc
scale_notes_idx = settings.DEFAULT_SCALENOTES_IDX  # Bank of notes for root/scale
rootnote_idx = settings.DEFAULT_ROOTNOTE_IDX       # C,Db,D..
midi_default_velocity = settings.DEFAULT_VELOCITY
midi_mode = settings.MIDI_TYPE                     # "usb" "aux" or "all"
play_mode = settings.STARTING_PLAYMODE             # 'standard' 'encoder' 'chord'
current_bpm = settings.DEFAULT_BPM

current_midibank_set = midi_banks_chromatic
current_scale_list = []
midi_velocities = [midi_default_velocity] * 16
midi_velocities_singlenote = constants.DEFAULT_SINGLENOTE_MODE_VELOCITIES
current_assignment_velocity = 120
midi_settings_page_index = 0

midi_settings_pages = [
    ("MIDI In Sync", midi_settings_page_indicies[0], ["On", "Off"]),
    ("BPM", midi_settings_page_indicies[1], [str(i) for i in range(60, 200)]),
    ("MIDI Type", midi_settings_page_indicies[2], ["USB", "AUX", "All"]),
    ("MIDI Channel", midi_settings_page_indicies[3], [str(i) for i in range(1, 17)]),
    ("Default Velocity", midi_settings_page_indicies[4], [str(i) for i in range(1, 127)])
]

midi_to_note = {
    0: 'C0', 1: 'C#0', 2: 'D0', 3: 'D#0', 4: 'E0', 5: 'F0', 6: 'F#0', 7: 'G0', 8: 'G#0', 9: 'A0', 10: 'A#0', 11: 'B0',
    12: 'C1', 13: 'C#1', 14: 'D1', 15: 'D#1', 16: 'E1', 17: 'F1', 18: 'F#1', 19: 'G1', 20: 'G#1', 21: 'A1', 22: 'A#1', 23: 'B1',
    24: 'C2', 25: 'C#2', 26: 'D2', 27: 'D#2', 28: 'E2', 29: 'F2', 30: 'F#2', 31: 'G2', 32: 'G#2', 33: 'A2', 34: 'A#2', 35: 'B2',
    36: 'C3', 37: 'C#3', 38: 'D3', 39: 'D#3', 40: 'E3', 41: 'F3', 42: 'F#3', 43: 'G3', 44: 'G#3', 45: 'A3', 46: 'A#3', 47: 'B3',
    48: 'C4', 49: 'C#4', 50: 'D4', 51: 'D#4', 52: 'E4', 53: 'F4', 54: 'F#4', 55: 'G4', 56: 'G#4', 57: 'A4', 58: 'A#4', 59: 'B4',
    60: 'C5', 61: 'C#5', 62: 'D5', 63: 'D#5', 64: 'E5', 65: 'F5', 66: 'F#5', 67: 'G5', 68: 'G#5', 69: 'A5', 70: 'A#5', 71: 'B5',
    72: 'C6', 73: 'C#6', 74: 'D6', 75: 'D#6', 76: 'E6', 77: 'F6', 78: 'F#6', 79: 'G6', 80: 'G#6', 81: 'A6', 82: 'A#6', 83: 'B6',
    84: 'C7', 85: 'C#7', 86: 'D7', 87: 'D#7', 88: 'E7', 89: 'F7', 90: 'F#7', 91: 'G7', 92: 'G#7', 93: 'A7', 94: 'A#7', 95: 'B7',
    96: 'C8', 97: 'C#8', 98: 'D8', 99: 'D#8', 100: 'E8', 101: 'F8', 102: 'F#8', 103: 'G8', 104: 'G#8', 105: 'A8', 106: 'A#8', 107: 'B8',
    108: 'C9', 109: 'C#9', 110: 'D9', 111: 'D#9', 112: 'E9', 113: 'F9', 114: 'F#9', 115: 'G9', 116: 'G#9', 117: 'A9', 118: 'A#9', 119: 'B9',
    120: 'C10', 121: 'C#10', 122: 'D10', 123: 'D#10', 124: 'E10', 125: 'F10', 126: 'F#10', 127: 'G10',
}

scale_root_notes_list = [('C', 0),
                        ('Db', 1), 
                        ('D', 2), 
                        ('Eb', 3), 
                        ('E', 4), 
                        ('F', 5), 
                        ('Gb', 6), 
                        ('G', 7),
                        ('Ab', 8), 
                        ('A', 9), 
                        ('Bb', 10), 
                        ('B', 11)]


scale_intervals = OrderedDict({
    "maj": [2, 2, 1, 2, 2, 2, 1],
    "min": [2, 1, 2, 2, 1,  2,2],
    "harm_min": [2, 1, 2, 2, 1, 3, 1],
    "mel_min": [2, 1, 2, 2, 2, 2, 1],
    "dorian": [2, 1, 2, 2, 2, 1, 2],
    "phrygian": [1, 2, 2, 2, 1, 2, 2],
    "lydian": [2, 2, 2, 1, 2, 2, 1]
})


def get_midi_notes_in_scale(root, scale_intervals): # Helper function to generate scale midi
    oct =1  # octave
    midi_notes = []
    cur_note = root 

    for interval in scale_intervals:
        cur_note = cur_note + interval
        midi_notes.append(cur_note)

    base_notes = midi_notes
    while cur_note < 127:
        for note in base_notes:
            cur_note = note + (12 * oct)
            if cur_note > 127:
                break
            midi_notes.append(cur_note)
        oct = oct + 1

    # Now split into 16 pad sets 
    midi_notes_pad_mapped = []
    numarys = round(len(midi_notes) / NUM_PADS)  # how many 16 pad banks do we need
    for i in range(numarys):
        if i == 0:
            padset = midi_notes[ : NUM_PADS-1]
        else:
            st = i * NUM_PADS
            end = st + NUM_PADS
            padset = midi_notes[st:end]

            # Need arrays to be exaclty 16. Fix if needed.
            pads_short = 16 - len(padset)
            if pads_short > 0:
                lastnote = padset[-1]
                for i in range(pads_short):
                    padset.append(lastnote)

        midi_notes_pad_mapped.append(padset)

    return midi_notes_pad_mapped

# Structure: all_scales list [("major", [("C", 01234...),
#                                       ("D", 01234...),..]
all_scales_list = []
chromatic_ary = ('chromatic',[('chromatic',midi_banks_chromatic)])
all_scales_list.append(chromatic_ary)

for scale_name, interval in scale_intervals.items():
    interval_ary = []
    for root_name, root in scale_root_notes_list:
        interval_ary.append((root_name,get_midi_notes_in_scale(root,interval)))
    all_scales_list.append((scale_name,interval_ary))

NUM_SCALES = len(all_scales_list)
NUM_ROOTS = len(scale_root_notes_list)

# ------------------ Menu / Display Functions ------------------ #
def double_click_func_btn():
    """
    Function to handle the double click event on the function button.
    It toggles between different play modes: standard, encoder, and chord.
    """
    if play_mode == "standard":
        set_play_mode("encoder")
    elif play_mode == "encoder":
        set_play_mode("chord")
    elif play_mode == "chord":
        set_play_mode("standard")
    
    display_notification(f"Note mode: {play_mode}")

def pad_held_function(first_pad_held_idx, button_states_array, encoder_delta):
    """
    Update the velocity of a MIDI pad based on the encoder delta.

    Args:
        pad_idx (int): The index of the MIDI pad.
        encoder_delta (int): The change in value of the encoder.
        first_pad_held (bool): Indicates if any pads were held before this one in the session.

    Returns:
        bool: True if the encoder delta was used, False otherwise.
    """

    global current_assignment_velocity

    if play_mode == "encoder":
        return 
    
    # No pads were held before this one in this session
    if first_pad_held_idx >= 0:
        current_assignment_velocity = get_midi_velocity_by_idx(first_pad_held_idx)
        display_notification(f"velocity: {get_midi_velocity_by_idx(first_pad_held_idx)}")
        return 

    if abs(encoder_delta) > 0:
        current_assignment_velocity = current_assignment_velocity + encoder_delta
        current_assignment_velocity = min(current_assignment_velocity, 127)  # Make sure it's a valid MIDI velocity (0 - 127)
        current_assignment_velocity = max(current_assignment_velocity, 0)
        
        for pad_idx in range(NUM_PADS): # Update any pad currently pressed. Doesnt need to be "held"
            if button_states_array[pad_idx] is True:
                set_midi_velocity_by_idx(pad_idx, current_assignment_velocity)

        # Limit display updates
        if current_assignment_velocity % 5 == 0 or current_assignment_velocity == 1 or current_assignment_velocity == 127: 
            display_notification(f"velocity: {current_assignment_velocity}")


def midi_settings_fn_press_function():
    """
    Function to handle the press event for the MIDI settings page.

    This function increments the `midi_settings_page_index` variable by 1 and wraps around to 0 if it exceeds the length of `midi_settings_pages` list.
    It then calls the `display_text_middle` function with the result of `get_midi_settings_display_text` as the argument.

    Parameters:
    None

    Returns:
    None
    """
    global midi_settings_page_index

    midi_settings_page_index = next_or_previous_index(midi_settings_page_index, len(midi_settings_pages), True)
    display_text_middle(get_midi_settings_display_text())

# DJT - Update me to use the new settings. current stuff doesnt do anything
def midi_settings_encoder_chg_function(upOrDown=True):
    """
    Function to handle changes in MIDI settings based on encoder input.

    Parameters:
    - upOrDown (bool): Indicates whether the encoder input is moving up or down. Default is True (up).

    Global Variables:
    - midi_settings_page_index (int): Current index of the MIDI settings page.
    - midi_settings_pages (list): List of tuples containing the name, index, and options for each MIDI settings page.
    - midi_in_channel (int): MIDI input channel.
    - midi_out_channel (int): MIDI output channel.
    - midi_sync (bool): Indicates whether MIDI sync is enabled.
    - midi_type (str): MIDI type (usb, aux, all).
    - midi_default_velocity (int): Default MIDI velocity.
    - midi_velocities (list): List of MIDI velocities for each channel.
    - current_bpm (int): Current BPM value.
    - midi_settings_page_indicies (list): List of indices for each MIDI settings page.

    Returns:
    - None
    """

    global midi_settings_page_index
    global midi_settings_pages
    global midi_in_channel
    global midi_out_channel
    global midi_sync
    global midi_type
    global midi_default_velocity
    global midi_velocities
    global current_bpm
    global midi_settings_page_indicies

    name, idx, options = midi_settings_pages[midi_settings_page_index]

    idx = next_or_previous_index(idx, len(options), upOrDown)

    midi_settings_pages[midi_settings_page_index] = (name, idx, options)
    midi_settings_page_indicies[midi_settings_page_index] = idx

    # 0 - midi in sync
    if midi_settings_page_index == 0:
        if options[idx] == "On":
            midi_sync = True
        else:
            midi_sync = False

    # 1 - default bpm
    if midi_settings_page_index == 1:
        current_bpm = int(options[idx])
        if not midi_sync:
            clock.update_all_note_timings(60 / current_bpm)
        
    # 2 - midi type (usb, aux, all)
    if midi_settings_page_index == 2:
        midi_type = options[idx]
    
    # 3 - midi channel
    # djt split in and out
    if midi_settings_page_index == 3:
        midi_in_channel = int(options[idx])
        midi_out_channel = int(options[idx])

    # 4 - default velocity
    if midi_settings_page_index == 4:
        midi_velocities = [midi_default_velocity] * 16 
        midi_default_velocity = int(options[idx])
        for i in range(16):
            set_midi_velocity_by_idx(i,midi_default_velocity)

    display_text_middle(get_midi_settings_display_text())

def get_midi_settings_display_text():

    """
    Returns a string of text displaying the current MIDI settings.
    
    Returns:
        str: A string containing the current MIDI settings.
    """
    name, idx, options = midi_settings_pages[midi_settings_page_index]
    disp_text = f"{name}: {options[idx]}"
    return disp_text

def get_scale_display_text():
    """
    Returns the display text for the current scale.

    If the scale bank index is 0, it returns "Scale: Chromatic".
    Otherwise, it constructs the display text using the scale name and root note name.

    Returns:
        disp_text (str or list): The display text for the current scale.
    """
    if scale_bank_idx == 0: #special handling for chromatic
        disp_text = "Scale: Chromatic"
    else:
        scale_name = all_scales_list[scale_bank_idx][0]
        root_name = current_scale_list[rootnote_idx][0]
        disp_text = [f"Scale: {root_name} {scale_name}",
                    "",
                    f"       {rootnote_idx+1}/{NUM_ROOTS}     {scale_bank_idx+1}/{NUM_SCALES}",]
    return disp_text

def get_midi_note_name_text(midi_val):
    """
    Returns the MIDI note name as text based on the provided MIDI value.
    
    Args:
        midi_val (int): MIDI value (0-127) to get the note name for.
        
    Returns:
        str: The MIDI note name as text, e.g., "C4" or "OUT OF RANGE" if out of MIDI range.
    """
    if midi_val < 0 or midi_val > 127:
        return "OUT OF RANGE"
    else:
        return midi_to_note[midi_val]

def get_midi_bank_display_text():
    """
    Returns a string displaying the current MIDI bank information.
    
    Returns:
        str: A string containing the MIDI bank index and the note range, e.g., "Bank: 0 (C1 - G1)".
    """
    if scale_bank_idx == 0:
        disp_text = f"Bank: {midi_bank_idx}"
    else:
        disp_text = f"Bank: {scale_notes_idx}"
    return disp_text

# Get a string of text corresponding to the note range of the current MIDI bank
def get_currentbank_noterange():
    """
    Returns a string of text representing the note range of the current MIDI bank.
    
    Returns:
        str: A string describing the note range, e.g., "C#1 - G1".
    """
    first = midi_to_note[current_midi_notes[0]]
    last = midi_to_note[current_midi_notes[-1]]
    text = f"{first} - {last}"
    return text

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

def get_current_midi_notes():
    return current_midi_notes

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

    if idx > len(current_midi_notes) - 1:
        idx = len(current_midi_notes) - 1
        
    return current_midi_notes[idx]

def set_midi_note_by_idx(idx, val):
    """
    Sets the MIDI note for a given index.
    
    Args:
        idx (int): Index of the MIDI note to set.
        val (int): The new MIDI note value.
    """
    current_midi_notes[idx] = val

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
    if settings.MIDI_TYPE.upper() in ('USB', 'ALL'):
        usb_midi.send(NoteOn(note, velocity))
    
    if settings.MIDI_TYPE.upper() in ('AUX', 'ALL'):
        uart_midi.send(NoteOn(note, velocity))

def send_midi_note_off(note):
    """
    Sends a MIDI note-off message for the given note.
    
    Args:
        note (int): MIDI note value (0-127).
    """
    if settings.MIDI_TYPE.upper() in ('USB', 'ALL'):
        usb_midi.send(NoteOff(note, 1))

    if settings.MIDI_TYPE.upper() in ('AUX', 'ALL'):
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

    if isinstance(msg, NoteOn):
        #djt - add to note on queue
        print(msg)
        pass

    if isinstance(msg, NoteOff):
        print(msg)
        #djt - add to note off queue
        #djt - record if needed
        pass

    if isinstance(msg, ControlChange):
        #djt - not sure what to do with this yet..
        pass
    
    if isinstance(msg, TimingClock):
        clock.update_clock()

def get_midi_messages_in():
    """
    Checks for MIDI messages and processes them.
    """
    # Check for MIDI messages from the USB MIDI port
    msg = usb_midi.receive()
    if msg is not None:
        process_midi_in(msg,midi_type="usb")

    # Check for MIDI messages from the UART MIDI port
    msg = uart_midi.receive()
    if msg is not None:
        process_midi_in(msg,midi_type="uart")

# ------------------ Get / Change settings ------- #
def change_midi_channel(upOrDown=True):
    """
    Changes the MIDI channel for both input and output.

    Args:
        upOrDown (bool, optional): Determines whether to increment or decrement the MIDI channel. Defaults to True (increment).

    Returns:
        None
    """
    global midi_in_channel
    global midi_out_channel

    midi_in_channel = next_or_previous_index(midi_in_channel, 16, upOrDown)
    midi_out_channel = next_or_previous_index(midi_out_channel, 16, upOrDown)

    usb_midi.in_channel = midi_in_channel
    usb_midi.out_channel = midi_out_channel
    uart_midi.in_channel = midi_in_channel
    uart_midi.out_channel = midi_out_channel
    debug.add_debug_line("Midi Channel",f"Channel: {midi_in_channel}")

def chg_scale(upOrDown=True, display_text=True):
    """
    Change the current scale used in the MIDI loopster.

    Parameters:
    - upOrDown (bool): Determines whether to change to the next scale (True) or the previous scale (False). Default is True.
    - display_text (bool): Determines whether to display the updated scale text. Default is True.

    Returns:
    None
    """
    global scale_bank_idx
    global rootnote_idx
    global scale_notes_idx
    global current_scale_list
    global current_midi_notes

    scale_bank_idx = next_or_previous_index(scale_bank_idx, len(all_scales_list), upOrDown)

    current_scale_list = all_scales_list[scale_bank_idx][1]  # maj, min, etc. item 0 is the name.
    if scale_bank_idx == 0:  
        current_midi_notes = current_scale_list[0][1][midi_bank_idx] # special handling for chromatic.
    else:
        current_midi_notes = current_scale_list[rootnote_idx][1][scale_notes_idx]  # item 0 is c,d,etc.
    if display_text:
        display_text_middle(get_scale_display_text())
    print_debug(f"current midi notes: {current_midi_notes}")
    debug.add_debug_line("Current Scale", get_scale_display_text())

def chg_root(upOrDown=True, display_text=True):
    """
    Change the root note of the current scale.

    Args:
        upOrDown (bool, optional): Determines whether to change the root note up or down. Defaults to True.
        display_text (bool, optional): Determines whether to display the updated scale text. Defaults to True.
    """
    global scale_bank_idx
    global rootnote_idx
    global midi_bank_idx
    global scale_notes_idx
    global current_midi_notes

    if scale_bank_idx == 0: # doesn't make sense for chromatic.
        return

    rootnote_idx = next_or_previous_index(rootnote_idx, NUM_ROOTS, upOrDown)

    current_midi_notes = current_scale_list[rootnote_idx][1][scale_notes_idx] # item 0 is c,d,etc.
    print_debug(f"current midi notes: {current_midi_notes}")
    debug.add_debug_line("Current Scale", get_scale_display_text())
    if display_text:
        display_text_middle(get_scale_display_text())

def chg_midi_bank(upOrDown=True, display_text=True):
    """
    Change the MIDI bank index and update the current MIDI notes.

    Args:
        upOrDown (bool, optional): Determines whether to move the MIDI bank index up or down. Defaults to True.
        display_text (bool, optional): Determines whether to display the MIDI bank text. Defaults to True.

    Returns:
        None
    """
    global midi_bank_idx
    global current_midi_notes
    global current_midibank_set
    global scale_notes_idx

    # Chromatic mode    
    if scale_bank_idx == 0:
        current_midibank_set = current_scale_list[0][1] # chromatic is special
        midi_bank_idx = next_or_previous_index(midi_bank_idx, len(current_midibank_set), upOrDown)
        clear_all_notes()
        current_midi_notes = current_midibank_set[midi_bank_idx]

    # Scale Mode
    else:
        current_midibank_set = current_scale_list[rootnote_idx][1]
        scale_notes_idx = next_or_previous_index(scale_notes_idx, len(current_midibank_set), upOrDown)
        clear_all_notes()
        current_midi_notes = current_midibank_set[scale_notes_idx] 

    debug.add_debug_line("Midi Bank Vals", get_midi_bank_display_text())
    if display_text:
        display_text_middle(get_midi_bank_display_text())

    return

def chg_midi_mode(nextOrPrev=1):
    """
    Changes the MIDI mode to the next or previous mode.
    
    Args:
        nextOrPrev (bool): True for the next mode, False for the previous mode.
    """
    global midi_mode

    if nextOrPrev:
        if midi_mode == "usb":
            midi_mode = "aux"
        elif midi_mode == "aux":
            midi_mode = "all"
        elif midi_mode == "all":
            midi_mode = "usb"
    
    if not nextOrPrev:
        if midi_mode == "usb":
            midi_mode = "all"
        elif midi_mode == "aux":
            midi_mode = "usb"
        elif midi_mode == "all":
            midi_mode = "aux"

def setup_midi():
    """
    Sets up the MIDI configuration for the application.

    This function initializes the global variables `current_scale_list`, `current_midi_notes`, and `current_midibank_set`.
    It assigns the appropriate values based on the default settings.

    Returns:
        None
    """
    global current_scale_list
    global current_midi_notes
    global current_midibank_set

    current_scale_list = all_scales_list[settings.DEFAULT_SCALEBANK_IDX][1]

    if settings.DEFAULT_SCALEBANK_IDX == 0: #special handling for chromatic.
        current_midibank_set = current_scale_list[0][1]
        current_midi_notes = current_midibank_set[settings.DEFAULT_MIDIBANK_IDX]

    else:
        current_midibank_set = current_scale_list[settings.DEFAULT_ROOTNOTE_IDX][1]
        current_midi_notes = current_scale_list[settings.DEFAULT_ROOTNOTE_IDX][1][settings.DEFAULT_SCALENOTES_IDX] # item 0 is c,d,etc.

def get_play_mode():
    """
    Returns the current play mode.

    Returns:
        str: The current play mode.
    """
    return play_mode

def set_play_mode(mode):
    """
    Sets the play mode for the MIDI loopster.

    Parameters:
    mode (str): The play mode to set.

    Returns:
    None
    """
    global play_mode
    play_mode = mode

def save_midi_settings():
    """
    Saves the MIDI settings to the settings module.

    This function updates the MIDI settings in the settings module with the current values of the MIDI variables.

    Parameters:
    None

    Returns:
    None
    """
    settings.MIDI_CHANNEL = midi_in_channel
    settings.MIDI_SYNC_STATUS = midi_sync
    settings.MIDI_TYPE = midi_mode
    settings.DEFAULT_VELOCITY = midi_default_velocity
    settings.DEFAULT_BPM = current_bpm
    settings.MIDI_NOTES_DEFAULT = current_midi_notes
    settings.MIDI_TYPE = midi_mode
    settings.DEFAULT_MIDIBANK_IDX = midi_bank_idx
    settings.DEFAULT_SCALEBANK_IDX = scale_bank_idx
    settings.DEFAULT_SCALE_IDX = scale_bank_idx
    settings.DEFAULT_SCALENOTES_IDX = scale_notes_idx
    settings.DEFAULT_ROOTNOTE_IDX = rootnote_idx
    settings.MIDI_NOTES_DEFAULT = get_current_midi_notes()
    settings.MIDI_SETTINGS_PAGE_INDICIES = midi_settings_page_indicies
