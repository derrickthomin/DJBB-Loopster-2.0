from looper import MidiLoop
from midi import get_play_mode, set_play_mode
from display import display_notification, display_text_middle
from midi import (
    get_midi_velocity_by_idx,
    set_midi_velocity_by_idx,
    get_current_assignment_velocity,
    update_global_velocity,
    get_midi_bank_idx,
    midi_to_note,
    change_midi_bank
)
from debug import debug

NUM_PADS = 16

def double_click_func_btn():
    """
    Function to handle the double click event on the function button.
    It toggles between different play modes: standard, encoder, and chord.
    """
    play_mode = get_play_mode()
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

    current_assignment_velocity = get_current_assignment_velocity()
    play_mode = get_play_mode()
    if play_mode == "encoder": # handled in inputs loop. special case.
        return 
    
    if play_mode == "chord":  # update chord loop mode
        return
    
    if play_mode == "standard": # Update velocity

        # No pads were held before this one in this session. Use it to get velocity in standard mode.
        if first_pad_held_idx >= 0:
            current_assignment_velocity = get_midi_velocity_by_idx(first_pad_held_idx)
            display_notification(f"velocity: {get_midi_velocity_by_idx(first_pad_held_idx)}")
            return 

        if abs(encoder_delta) > 0:
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

def change_and_display_midi_bank(upOrDown=True, display_text=True):

    change_midi_bank(upOrDown)

    debug.add_debug_line("Midi Bank Vals", get_midi_bank_display_text())
    if display_text:
        display_text_middle(get_midi_bank_display_text())

    return

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
    return f"Bank: {get_midi_bank_idx()}"