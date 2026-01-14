import constants as C

from loopmanager import loop_manager
from display import display
from looper import (
    get_quantization_display_value,
    get_quantization_percent,
    get_quantization_text,
    set_next_or_prev_quantization,
    set_quantization_percent,
)
from midi import midi
from settings import settings
from settingsmenu import (
    get_arp_len_text,
    get_arp_type_text,
    set_next_arp_length,
    set_next_arp_type,
)

def double_click_fn_button():
    """Toggle play modes: velocity -> encoder -> loop -> velocity."""
    
    play_mode = settings.get_play_mode()
    if play_mode == "velocity":
        play_mode = "encoder"
        display_arp_info(True)

    elif play_mode == "encoder":
        play_mode = "loop"
        display_arp_info(False)
        display_quantization_info(True)
        loop_manager.update_pad_pixels()
        
    elif play_mode == "loop":
        play_mode = "velocity"
        display_quantization_info(False)
        display_arp_info(False)
    
    settings.set_play_mode(play_mode)
    display.update_playmode_icon(play_mode)

def pad_held_function(first_pad_held_idx, button_states_array, encoder_delta):
    play_mode = settings.get_play_mode()
    if play_mode == "encoder":  # special case - see inputs.py
        return

    # No pads were held before this one in this session.
    if first_pad_held_idx >= 0:
        if play_mode == "velocity":
            velocity = midi.get_velocity_by_idx(first_pad_held_idx)
            midi.update_global_velocity(velocity)
            display.show_notification(f"velocity: {velocity}")
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

                if new_velocity % C.VELOCITY_CHANGE_DISPLAY_THRESH == 0 or new_velocity in {1, 127}:
                    display.show_notification(f"velocity: {new_velocity}")
        
        elif play_mode == "loop":
            for pad_idx in pressed_pads:
                loop_manager.change_loop_mode(pad_idx, encoder_delta > 0)

def change_and_display_midi_bank(up_or_down=True, display_text=True):
    midi.change_bank(up_or_down)
    scale_bank = midi.get_scale_bank_idx()
    if display_text:
        if scale_bank == 0:
            idx = midi.get_midi_bank_idx()
        else:
            idx = midi.get_scale_notes_idx()
        offset_suffix = midi.get_pad_offset_suffix()
        # Clear 36px wide (enough for "10 +++" = 6 chars)
        display.show_text_middle(f"{idx}{offset_suffix}", True, 38 + C.PADDING, 36)
        display.display_dot(0,True)

    return

def display_bank_offset():
    """Update bank display with offset suffix. Minimal screen update."""
    scale_bank = midi.get_scale_bank_idx()
    idx = midi.get_midi_bank_idx() if scale_bank == 0 else midi.get_scale_notes_idx()
    offset_suffix = midi.get_pad_offset_suffix()
    # Clear 36px wide (enough for "10 +++" = 6 chars)
    display.show_text_middle(f"{idx}{offset_suffix}", True, 38 + C.PADDING, 36)

def fn_button_held_function(trigger_on_release = False):
    if settings.get_play_mode() not in ["loop","encoder"]:
        return

    if not trigger_on_release:
        display.display_dot(1,True)
        return

    if  trigger_on_release:
        display.display_dot(1,False)
        display.display_dot(0,True)
        return

def get_playmenu_display_text():
    text = []
    offset_suffix = midi.get_pad_offset_suffix()
    if midi.get_scale_bank_idx() == 0:
        text.append(f"Bank: {midi.get_midi_bank_idx()}{offset_suffix}")
    else:
        text.append(f"Bank: {midi.get_scale_notes_idx()}{offset_suffix}")
    text.append("")
    bottom_text = ""
    if settings.get_play_mode() == "loop":
        bottom_text = display_quantization_info(True)
    if settings.get_play_mode() == "encoder":
        bottom_text = display_arp_info()
    text.append(bottom_text)

    display.display_dot(0,True)
    display.update_playmode_icon(settings.get_play_mode())
    return text

def fn_button_held_and_encoder_turned_function(encoder_delta):
    if settings.get_play_mode() not in ["loop","encoder"]:
        return
    
    if settings.get_play_mode() == "loop":
        set_next_or_prev_quantization(encoder_delta)
        value = str(get_quantization_display_value())
        display.show_text_bottom(value, True, 35, 36)

    if settings.get_play_mode() == "encoder":
        arp_direction = set_next_arp_type(encoder_delta)
        display.show_text_bottom(f"{arp_direction}", True, C.TEXT_PAD, 80)
        return

def encoder_button_press_and_turn_function(encoder_delta):
    if settings.get_play_mode() not in ["loop","encoder"]:
        return
    
    display.display_dot(2,True)

    if settings.get_play_mode() == "loop":
        set_quantization_percent(encoder_delta)
        display_text = f"{get_quantization_percent(True)}%"
        display.show_text_bottom(display_text, True, 91, 25)
    
    if settings.get_play_mode() == "encoder":
        arp_length = set_next_arp_length(encoder_delta)
        display.show_text_bottom(f"{arp_length}", True, 90, 30)
        return
    
def display_quantization_info(on_or_off = True):
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

def encoder_button_held_function(released = False):
    if settings.get_play_mode() not in ["loop","encoder"]:
        return
    
    if not released:
        display.display_dot(2,True)
        return
    
    if  released:
        display.display_dot(2,False)
        display.display_dot(0, True)
        return