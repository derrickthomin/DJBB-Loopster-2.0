import looper
from display import set_blink_pixel, set_default_color, display_notification
from settings import settings
from debug import print_debug

pad_chords = [""] * 16 # Stores chord loop obj for pads
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
    global pad_chords
    global recording_pad_idx
    global recording 

    # No chord - start recording
    if pad_chords[pad_idx] == "":
        display_notification(f"Recording Chord")
        pad_chords[pad_idx] = looper.MidiLoop(loop_type=settings.CHORDMODE_DEFAULT_LOOPTYPE)
        pad_chords[pad_idx].toggle_record_state()
        recording_pad_idx = pad_idx
        recording = True
        set_blink_pixel(pad_idx)
        set_default_color(pad_idx, CHORD_COLOR)

    # Chord exists - delete it
    else:
        pad_chords[pad_idx] = ""
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
        pad_chords[recording_pad_idx].toggle_record_state(False)
        pad_chords[recording_pad_idx].trim_silence()
        pad_chords[recording_pad_idx].quantize_notes()
        pad_chords[recording_pad_idx].quantize_loop()
        # print("--- Chord recorded ----- )")
        # print(pad_chords[recording_pad_idx].total_loop_time())

        recording = False

def toggle_chord_loop_type(button_idx):
    """
    Toggles between 1 shot mode, and loop mode.
    - Toggle: press pad to play the chord one time
    - Loop: press pad to play the loop until pad pressed again
    
    Args:
        pad_idx (int): The index of the pad to change the chord type of.
    """
    #global pad_chords

    if pad_chords[button_idx] != "":
        print(f"toggle_chord_loop_type: {button_idx}")
        pad_chords[button_idx].toggle_chord_loop_type()
        pad_chords[button_idx].reset_loop_notes_and_pixels()
        pad_chords[button_idx].loop_toggle_playstate(False)
        display_chord_loop_type(button_idx)

def display_chord_loop_type(idx):
    
    if pad_chords[idx] != "":
        chordmodetype = ""
        if pad_chords[idx].loop_type == "chord":
            chordmodetype = "1 shot"
        elif pad_chords[idx].loop_type == "chordloop":
            chordmodetype = "Loop"
        display_notification(f"Chord Type: {chordmodetype}")

# returns the notes of the 
def get_current_chord_notes(padidx):
    if pad_chords[padidx] != "":
        return pad_chords[padidx].get_all_notes()
    return []
 