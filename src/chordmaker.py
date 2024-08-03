import looper
from display import set_blink_pixel, set_default_color, display_notification
from settings import settings

current_chord_notes = [""] * 16 # Stores chord loop obj for pads
recording_pad_idx = ""
recording = False

CHORD_COLOR = (20, 0, 20)
BLACK = (0, 0, 0)

def add_remove_chord(pad_idx):
    """
    This function either starts recording a chord if there is no chord on the pad at the given index,
    or deletes the chord if one exists.
    
    Args:
        pad_idx (int): The index of the pad to add or remove a chord from.
    """
    global current_chord_notes
    global recording_pad_idx
    global recording 

    # No chord - start recording
    if current_chord_notes[pad_idx] == "":
        display_notification(f"Recording Chord")
        current_chord_notes[pad_idx] = looper.MidiLoop(loop_type=settings.CHORDMODE_DEFAULT_LOOPTYPE)
        current_chord_notes[pad_idx].toggle_record_state()
        recording_pad_idx = pad_idx
        recording = True
        set_blink_pixel(pad_idx)
        set_default_color(pad_idx, CHORD_COLOR)

    # Chord exists - delete it
    else:
        current_chord_notes[pad_idx] = ""
        recording = False
        display_notification(f"Chrd Deleted on pd {pad_idx}")
        set_default_color(pad_idx, BLACK)
        set_blink_pixel(pad_idx, False)

def chordmode_fn_press_function():
    """
    This function stops the recording of a chord if one is currently being recorded.
    """
    global recording
        
    if recording:
        set_blink_pixel(recording_pad_idx, False)
        current_chord_notes[recording_pad_idx].toggle_record_state(False) 
        current_chord_notes[recording_pad_idx].trim_silence()
        current_chord_notes[recording_pad_idx].quantize_notes()
        current_chord_notes[recording_pad_idx].quantize_loop()

        recording = False

def toggle_chord_loop_type(button_ary):
    """
    Toggles between 1 shot mode, and loop mode.
    - Toggle: press pad to play the chord one time
    - Loop: press pad to play the loop until pad pressed again
    
    Args:
        pad_idx (int): The index of the pad to change the chord type of.
    """
    global current_chord_notes

    if not button_ary:
        return

    for idx, button in enumerate(button_ary):
        if button and current_chord_notes[idx] != "":
            current_chord_notes[idx].toggle_chord_loop_type()
            chordmodetype = ""
            if current_chord_notes[idx].loop_type == "chord":
                chordmodetype = "1 shot"
            elif current_chord_notes[idx].loop_type == "chordloop":
                chordmodetype = "Loop"

            display_notification(f"Chord Type: {chordmodetype}")

def display_chord_loop_type(padidx):
    
    if current_chord_notes[padidx] != "":
        display_notification(f"Chord Type: {current_chord_notes[padidx].loop_type}")