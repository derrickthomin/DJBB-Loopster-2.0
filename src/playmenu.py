import chordmaker
from midi import get_play_mode, set_play_mode
from display import display_notification, display_text_middle, display_text_bottom
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

NUM_PADS = 16

def double_click_func_btn():
    """
    Function to handle the double click event on the function button.
    It toggles between different play modes: standard, encoder, and chord.
    """
    play_mode = get_play_mode()
    if play_mode == "standard":
        play_mode = "encoder"

    elif play_mode == "encoder":
        play_mode = "chord"

    elif play_mode == "chord":
        play_mode = "standard"
    
    set_play_mode(play_mode)
    display_notification(f"Note mode: {play_mode}")

def pad_held_function(first_pad_held_idx, button_states_array, encoder_delta):

    current_assignment_velocity = get_current_assignment_velocity()
    play_mode = get_play_mode()

    if play_mode == "encoder": # handled in inputs loop. special case.
        return 

    # No pads were held before this one in this session.
    if first_pad_held_idx >= 0:
        if play_mode == "standard":
            current_assignment_velocity = get_midi_velocity_by_idx(first_pad_held_idx)
            display_notification(f"velocity: {get_midi_velocity_by_idx(first_pad_held_idx)}")
            return 
        if play_mode == "chord":
            chordmaker.display_chord_loop_type(first_pad_held_idx)
            return
        
    # Pad is held AND encoder was turned
    if abs(encoder_delta) > 0:
        if play_mode == "standard":
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
            for pad_idx in range(NUM_PADS): # Update any pad currently pressed. Doesnt need to be "held"
                if button_states_array[pad_idx] is True:
                    chordmaker.toggle_chord_loop_type(button_states_array)

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
        display_text_middle(str(idx), True, 40)

    return

def fn_button_held_function():
    """
    Function to handle the function button being held.
    """
    if get_play_mode() == "chord":
        display_text_bottom(get_quantization_text())

def fn_button_held_and_encoder_turned_function(encoder_delta):
    """
    Function to handle the function button being held and the encoder being turned.
    
    Args:
        encoder_delta (int): The amount the encoder was turned.
    """
    if get_play_mode() == "chord":
        next_quantization(encoder_delta)
        val = str(get_quantization_value())
        display_text_bottom(val, True, 30, 30)

# DJT - Update me to use the new settings. current stuff doesnt do anything
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
    if get_scale_bank_idx() == 0:
        return f"Bank: {get_midi_bank_idx()}"
    else:
        return f"Bank: {get_scale_notes_idx()}"

def encoder_button_press_and_turn_function(encoder_delta):
    """
    Function to handle the encoder button being pressed and turned.
    
    Args:
        encoder_delta (int): The amount the encoder was turned.
    """
    if encoder_delta == 0:
        return

    next_quantization_percent(encoder_delta)
    display_text = f"{get_quantization_percent()*100}%"
    display_text_bottom(display_text, True, 80, 30)