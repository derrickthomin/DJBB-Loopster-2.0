import chordmaker
import constants
from midi import get_play_mode, set_play_mode
from display import display_notification, display_text_middle, display_text_bottom,display_selected_dot, update_playmode_icon
from midi import (
    get_midi_velocity_by_idx,
    set_midi_velocity_by_idx,
    get_current_assignment_velocity,
    update_global_velocity,
    get_midi_bank_idx,
    midi_to_note,
    change_midi_bank,
    get_scale_bank_idx,
    get_scale_notes_idx,
)
from debug import debug
from looper import next_quantization,get_quantization_text, get_quantization_value, get_quantization_percent,next_quantization_percent
from settings import settings
from settingsmenu import next_arp_length, next_arp_type, get_arp_len_text, get_arp_type_text

NUM_PADS = 16

def double_click_func_btn():
    """
    Function to handle the double click event on the function button.
    It toggles between different play modes: velocity, encoder, and chord.
    """
    play_mode = get_play_mode()
    if play_mode == "velocity":
        play_mode = "encoder"
        display_arp_info(True)

    elif play_mode == "encoder":
        play_mode = "chord"
        display_arp_info(False)
        display_quantization_info(True)

    elif play_mode == "chord":
        play_mode = "velocity"
        display_quantization_info(False)
        display_arp_info(False)
    
    set_play_mode(play_mode)
    update_playmode_icon(play_mode)

    #display_notification(f"Note mode: {play_mode}")

def pad_held_function(first_pad_held_idx, button_states_array, encoder_delta):

    current_assignment_velocity = get_current_assignment_velocity()
    play_mode = get_play_mode()

    if play_mode == "encoder": # handled in inputs loop. special case.
        return 

    # No pads were held before this one in this session.
    if first_pad_held_idx >= 0:
        if play_mode == "velocity":
            current_assignment_velocity = get_midi_velocity_by_idx(first_pad_held_idx)
            display_notification(f"velocity: {get_midi_velocity_by_idx(first_pad_held_idx)}")
            return
        
        if play_mode == "chord":
            chordmaker.display_chord_loop_type(first_pad_held_idx)
            return
        
    # Pad is held AND encoder was turned
    if abs(encoder_delta) > 0:
        if play_mode == "velocity":
            current_assignment_velocity = current_assignment_velocity + encoder_delta
            current_assignment_velocity = min(current_assignment_velocity, 127)  # Make sure it's a valid MIDI velocity (0 - 127)
            current_assignment_velocity = max(current_assignment_velocity, 0)
            update_global_velocity(current_assignment_velocity)

            for pad_idx in range(NUM_PADS): # Update any pad currently pressed. Doesnt need to be "held"
                if button_states_array[pad_idx] is True:
                    set_midi_velocity_by_idx(pad_idx, current_assignment_velocity)

                    # Limit display updates
                    if current_assignment_velocity % 5 == 0 or current_assignment_velocity == 1 or current_assignment_velocity == 127: 
                        display_notification(f"velocity: {current_assignment_velocity}")
        
        if play_mode == "chord":
            print(button_states_array)
            for pad_idx in range(NUM_PADS): # Update any pad currently pressed. Doesnt need to be "held"
                if button_states_array[pad_idx] is True:
                    chordmaker.toggle_chord_loop_type(pad_idx)

def change_and_display_midi_bank(upOrDown=True, display_text=True):

    change_midi_bank(upOrDown)
    scale_bank = get_scale_bank_idx()
    debug.add_debug_line("Midi Bank Vals", get_midi_bank_display_text())
    if display_text:
        if scale_bank == 0:
            idx = get_midi_bank_idx()
        else:
            idx = get_scale_notes_idx()
        # display_text_middle(get_midi_bank_display_text())
        display_text_middle(str(idx), True, 38 + constants.PADDING)
        display_selected_dot(0,True)

    return

def fn_button_held_function(trigger_on_release = False):
    """
    Function to handle the function button being held.
    """
    if get_play_mode() not in ["chord","encoder"]:
        return

    if not trigger_on_release:
        display_selected_dot(1,True)
        return

    if  trigger_on_release:
        display_selected_dot(1,False)
        display_selected_dot(0,True)
        # display_selected_dot(0, True)
        return
    
def get_midi_note_name_text(midi_val):


# DJT - Update me to use the new settings. current stuff 
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
    text = []
    if get_scale_bank_idx() == 0:
        text.append(f"Bank: {get_midi_bank_idx()}")
    else:
        text.append(f"Bank: {get_scale_notes_idx()}")
    
    text.append("")
    # Add quantization info
    update_playmode_icon(get_play_mode())
    if get_play_mode() == "chord":
        text.append(f"{get_quantization_text()}     {get_quantization_percent(True)}%")

    if get_play_mode() == "encoder":
        display_arp_info()

    display_selected_dot(0,True)
    return text

def display_arp_info(on_or_off = True):
    if on_or_off:
        display_text_bottom(get_arp_type_text(), True, constants.TEXT_PAD, 80)
        display_text_bottom(get_arp_len_text(), True, 90, 30)
    else:
        display_text_bottom("")

def fn_button_held_and_encoder_turned_function(encoder_delta):
    """
    Function to handle the function button being held and the encoder being turned.
    
    Args:
        encoder_delta (int): The amount the encoder was turned.
    """
    if get_play_mode() not in ["chord","encoder"]:
        return
    
    if get_play_mode() == "chord":
        next_quantization(encoder_delta)
        val = str(get_quantization_value())
        display_text_bottom(val, True, 30, 30)

    if get_play_mode() == "encoder":
        arp_type = next_arp_type(encoder_delta)
        display_text_bottom(f"{arp_type}", True, constants.TEXT_PAD, 80)
        return

def encoder_button_press_and_turn_function(encoder_delta):
    """
    Function to handle the encoder button being pressed and turned.
    
    Args:
        encoder_delta (int): The amount the encoder was turned.
    """

    if get_play_mode() not in ["chord","encoder"]:
        return
    
    display_selected_dot(2,True)

    if get_play_mode() == "chord":
        next_quantization_percent(encoder_delta)
        display_text = f"{get_quantization_percent(True)}%"
        display_text_bottom(display_text, True, 90, 25)
    
    if get_play_mode() == "encoder":
        arp_length = next_arp_length(encoder_delta)
        display_text_bottom(f"{arp_length}", True, 90, 30)
        return

def display_quantization_info(on_or_off = True):
    if on_or_off:
        text = (f"{get_quantization_text()}     {get_quantization_percent(True)}%")
        display_text_bottom(text)
    else:
        display_text_bottom("")

def encoder_button_held_function(released = False): #djt flip logic
    """
    Function to handle the encoder button being held.
    """
    if get_play_mode() not in ["chord","encoder"]:
        return
    
    if not released:
        display_selected_dot(2,True)
        # display_selected_dot(0,False)
        # display_selected_dot(1,False)
        return
    
    if  released:
        display_selected_dot(2,False)
        display_selected_dot(0, True)
        return