import constants
import looper
from display import set_blink_pixel, set_default_color, display_notification, set_blink_color
from settings import settings
from debug import print_debug
from clock import clock

pad_chords = [""] * 16 # Stores chord loop obj for pads
queued_for_playback = [False] * 16 # Play these when start midi msg
global_play_state = False
recording_pad_idx = ""
recording = False

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
    global queued_for_playback

    if pad_chords[pad_idx] == "": # No chord - start recording
        display_notification("Recording Chord")
        pad_chords[pad_idx] = looper.MidiLoop(loop_type=settings.CHORDMODE_LOOPTYPE)
        pad_chords[pad_idx].toggle_record_state()
        recording_pad_idx = pad_idx
        recording = True
        set_blink_pixel(pad_idx, True, constants.RED)
        set_default_color(pad_idx, constants.CHORD_COLOR)

    else: # Chord exists - delete it
        pad_chords[pad_idx] = ""
        queued_for_playback[pad_idx] = False
        recording = False
        display_notification(f"Chord Deleted on pad {pad_idx}")
        set_default_color(pad_idx, constants.BLACK)
        set_blink_pixel(pad_idx, False)

def chordmode_fn_press_function(action_type = "press"):
    """
    Stops the recording of a chord if one is currently being recorded.
    """
    if action_type == "release": # nothing special on release
        return
    
    global recording
        
    if recording:
        pad_chords[recording_pad_idx].toggle_record_state(False)
        pad_chords[recording_pad_idx].trim_silence()
        pad_chords[recording_pad_idx].quantize_notes()
        pad_chords[recording_pad_idx].quantize_loop()
        if pad_chords[recording_pad_idx].loop_playstate:
            set_default_color(recording_pad_idx, constants.PIXEL_LOOP_PLAYING_COLOR)
        set_blink_pixel(recording_pad_idx, False)
        recording = False

def toggle_chord_loop_type(button_idx):
    """
    Toggles between 1 shot mode and loop mode for the chord at the given index.
    
    Args:
        button_idx (int): The index of the pad to change the chord type of.
    """
    if pad_chords[button_idx] != "":
        pad_chords[button_idx].toggle_chord_loop_type()
        pad_chords[button_idx].reset_loop_notes_and_pixels()
        pad_chords[button_idx].loop_toggle_playstate(False)
        display_chord_loop_type(button_idx)

def display_chord_loop_type(idx):
    """
    Displays the loop type of the chord at the given index.
    
    Args:
        idx (int): The index of the pad to display the loop type for.
    """
    if pad_chords[idx] != "":
        chordmodetype = ""
        if pad_chords[idx].loop_type == "chord":
            chordmodetype = "1 shot"
        elif pad_chords[idx].loop_type == "chordloop":
            chordmodetype = "Loop"
        display_notification(f"Chord Type: {chordmodetype}")

def process_new_button_press(idx):
    """
    Processes a new button press event for the given index.

    Args:
        idx (int): The index of the button that was pressed.
    """
    global queued_for_playback

    if pad_chords[idx] and not recording:
        if settings.MIDI_SYNC:
            queued_for_playback[idx] = not queued_for_playback[idx]

            if not clock.play_state:
                set_blink_pixel(idx, queued_for_playback[idx], constants.PIXEL_LOOP_PLAYING_COLOR)
                return

        toggle_chord(idx)

def check_process_chord_on_queue():
    """
    Checks if there are any chords in the play queue and processes them if the clock is playing.
    """
    global global_play_state
    if clock.play_state and not global_play_state:
        global_play_state = True
        for idx, play in enumerate(queued_for_playback):
            if play:
                toggle_chord(idx)

def check_stop_all_chords():
    """
    Stops all chords from playing. Called when MIDI stop message is received.
    """
    global global_play_state
    global queued_for_playback

    if global_play_state and not clock.play_state:
        global_play_state = False
        for idx in range(16):
            if pad_chords[idx] != "":
                if queued_for_playback[idx] and pad_chords[idx].loop_playstate:
                    set_blink_pixel(idx, True, constants.PIXEL_LOOP_PLAYING_COLOR)
                else:
                    queued_for_playback[idx] = False
                pad_chords[idx].loop_toggle_playstate(False)
                pad_chords[idx].reset_loop_notes_and_pixels()
                set_default_color(idx, constants.CHORD_COLOR)


def toggle_chord(idx):
    """
    Plays the chord at the given index.
    
    Args:
        idx (int): The index of the pad to play the chord from.
    """
    if pad_chords[idx] == "":
        return  
    if pad_chords[idx].loop_type == "chordloop":
        pad_chords[idx].loop_toggle_playstate()
        pad_chords[idx].reset_loop_notes_and_pixels()
    else:
        pad_chords[idx].reset_loop()

    # Update pixel colors based on play state
    if pad_chords[idx].loop_playstate:
        set_default_color(idx, constants.PIXEL_LOOP_PLAYING_COLOR)
        set_blink_pixel(idx, False)
    else:
        set_default_color(idx, constants.CHORD_COLOR)
        set_blink_pixel(idx, False)

def get_current_chord_notes(padidx):
    """
    Retrieves the notes of the chord at the given pad index.

    Args:
        padidx (int): The index of the pad to retrieve the chord notes from.

    Returns:
        list: The list of notes in the chord. Returns an empty list if there is no chord on the pad.
    """
    if pad_chords[padidx] != "":
        return pad_chords[padidx].get_all_notes()
    return []

 