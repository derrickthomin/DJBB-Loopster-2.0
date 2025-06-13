from chordmanager import chord_manager
import constants
from display import display
from midi import midi
from debug import debug
from utils import free_memory
free_memory()
# Restore direct imports from looper
from looper import (
   set_next_or_prev_quantization,
   get_quantization_text,
   get_quantization_display_value,
   get_quantization_percent,
   set_quantization_percent,
)
from settingsmenu import set_next_arp_length, set_next_arp_type, get_arp_len_text, get_arp_type_text
from settings import settings

NUM_PADS = 16

def double_click_fn_button():
    """Toggle play modes: velocity -> encoder -> chord -> velocity"""
    
    play_mode = settings.get_play_mode()
    if play_mode == "velocity":
        play_mode = "encoder"
        display_arp_info(True)
    elif play_mode == "encoder":
        play_mode = "chord"
        display_arp_info(False)
        display_quant_info(True)
        chord_manager.update_pad_pixels()
    elif play_mode == "chord":
        play_mode = "velocity"
        display_quant_info(False)
        display_arp_info(False)
    
    settings.set_play_mode(play_mode)
    display.update_playmode_icon(play_mode)

def pad_held_function(first_pad_held_idx, button_states_array, encoder_delta):
    """Handle pad hold + encoder interaction per play mode"""
    
    play_mode = settings.get_play_mode()
    if play_mode == "encoder":  # special case - see inputs.py
        return

    # No pads were held before this one in this session.
    if first_pad_held_idx >= 0:
        if play_mode == "velocity":
            velocity = midi.get_velocity_by_idx(first_pad_held_idx)
            display.show_notification(f"velocity: {velocity}")
            return
        
        if play_mode == "chord":
            chord_manager.display_chord_loop_mode(first_pad_held_idx)
            return
        
    # Pad is held AND encoder was turned
    if abs(encoder_delta) > 0:
        pressed_pads = [idx for idx, is_pressed in enumerate(button_states_array) if is_pressed]
        
        if not pressed_pads:
            return
            
        if play_mode == "velocity":
            current_velocity = midi.get_current_assignment_velocity()
            new_velocity = max(0, min(127, current_velocity + encoder_delta))
            
            if new_velocity != current_velocity:
                midi.update_global_velocity(new_velocity)
                for pad_idx in pressed_pads:
                    midi.set_midi_velocity_by_idx(pad_idx, new_velocity)
                
                if new_velocity % 5 == 0 or new_velocity in {1, 127}:
                    display.show_notification(f"velocity: {new_velocity}")
        
        elif play_mode == "chord":
            for pad_idx in pressed_pads:
                chord_manager.change_loop_mode(pad_idx)

def change_and_display_midi_bank(up_or_down=True, display_text=True):
    """Change MIDI bank and display current index"""
    
    midi.change_bank(up_or_down)
    scale_bank = midi.get_scale_bank_idx()
    debug.add_debug_line("Midi Bank Vals", get_playmenu_display_text())
    if display_text:
        if scale_bank == 0:
            idx = midi.get_midi_bank_idx()
        else:
            idx = midi.get_scale_notes_idx()
        display.show_text_middle(str(idx), True, 38 + constants.PADDING)
        display.display_dot(0,True)

    return

def fn_button_held_function(trigger_on_release = False):
    """Handle fn button hold state with dot indicators"""
    
    if settings.get_play_mode() not in ["chord","encoder"]:
        return

    if not trigger_on_release:
        display.display_dot(1,True)
        return

    if  trigger_on_release:
        display.display_dot(1,False)
        display.display_dot(0,True)
        return

def get_midi_val_text(midi_val):
    """Return MIDI note name or 'OUT OF RANGE' for invalid values"""
    
    if midi_val < 0 or midi_val > 127:
        return "OUT OF RANGE"
    return midi_val

def get_playmenu_display_text():
    """Generate bank display text with mode-specific info"""
    
    text = []
    if midi.get_scale_bank_idx() == 0:
        text.append(f"Bank: {midi.get_midi_bank_idx()}")
    else:
        text.append(f"Bank: {midi.get_scale_notes_idx()}")
    text.append("")
    bottom_text = ""
    if settings.get_play_mode() == "chord":
        bottom_text = display_quant_info(True)
    if settings.get_play_mode() == "encoder":
        bottom_text = display_arp_info()
    text.append(bottom_text)

    display.display_dot(0,True)
    return text

def fn_button_held_and_encoder_turned_function(encoder_delta):
    """Handle fn + encoder for quantization/arp type control"""
    
    if settings.get_play_mode() not in ["chord","encoder"]:
        return
    
    if settings.get_play_mode() == "chord":
        set_next_or_prev_quantization(encoder_delta)
        val = str(get_quantization_display_value())
        display.show_text_bottom(val, True, 35, 36)

    if settings.get_play_mode() == "encoder":
        arp_direction = set_next_arp_type(encoder_delta)
        display.show_text_bottom(f"{arp_direction}", True, constants.TEXT_PAD, 80)
        return

def encoder_button_press_and_turn_function(encoder_delta):
    """Handle encoder button + turn for quantization%/arp length"""
    
    if settings.get_play_mode() not in ["chord","encoder"]:
        return
    
    display.display_dot(2,True)

    if settings.get_play_mode() == "chord":
        set_quantization_percent(encoder_delta)
        display_text = f"{get_quantization_percent(True)}%"
        display.show_text_bottom(display_text, True, 91, 25)
    
    if settings.get_play_mode() == "encoder":
        arp_length = set_next_arp_length(encoder_delta)
        display.show_text_bottom(f"{arp_length}", True, 90, 30)
        return

# def display_quantization_info(on_or_off = True):
#     """Show/hide quantization info on screen"""
    
#     if on_or_off:
#         text = (f"{get_quantization_text()}     {get_quantization_percent(True)}%")
#         display.show_text_bottom(text)
#         return text
#     else:
#         display.show_text_bottom("")
#         return ""
    
def display_quant_info(on_or_off = True):

    if on_or_off:
        left_text = get_quantization_text()
        right_text = f"{get_quantization_percent(True)}%"
        display.show_text_bottom(left_text,True, 0, 40)
        display.show_text_bottom(right_text,True, 91, 25)
        return f"{left_text}     {right_text}"
    else:
        display.show_text_bottom("")
        return ""

def display_arp_info(on_or_off = True):
    """Show/hide arpeggiator info on screen"""
    
    if on_or_off:
        left_text = get_arp_type_text()
        right_text = get_arp_len_text()
        display.show_text_bottom(left_text,True, 0, 60)
        display.show_text_bottom(right_text,True, 91, 25)
        text = (f"{get_arp_type_text()}            {get_arp_len_text()}")
        return text
    else:
        display.show_text_bottom("")
        return ""

def encoder_button_held_function(released = False): #djt flip logic
    """Handle encoder button hold state with dot indicators"""
    
    if settings.get_play_mode() not in ["chord","encoder"]:
        return
    
    if not released:
        display.display_dot(2,True)
        return
    
    if  released:
        display.display_dot(2,False)
        display.display_dot(0, True)
        return