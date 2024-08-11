import constants
import looper
from display import set_blink_pixel, set_default_color, display_notification, set_blink_color
from settings import settings
from debug import print_debug
from clock import clock

pad_chords = [""] * 16 # Stores chord loop obj for pads
play_on_queue = [False] * 16 # Play these when start midi msg
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

    # No chord - start recording
    if pad_chords[pad_idx] == "":
        display_notification("Recording Chord")
        pad_chords[pad_idx] = looper.MidiLoop(loop_type=settings.CHORDMODE_DEFAULT_LOOPTYPE)
        pad_chords[pad_idx].toggle_record_state()
        recording_pad_idx = pad_idx
        recording = True
        set_blink_pixel(pad_idx, True, constants.RED)
        set_default_color(pad_idx, constants.CHORD_COLOR)

    # Chord exists - delete it
    else:
        pad_chords[pad_idx] = ""
        recording = False
        display_notification(f"Chord Deleted on pad {pad_idx}")
        set_default_color(pad_idx, constants.BLACK)
        set_blink_pixel(pad_idx, False)

def chordmode_fn_press_function():
    """
    Stops the recording of a chord if one is currently being recorded.
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
    global play_on_queue

    if pad_chords[idx] and not recording:
        if settings.MIDI_SYNC_STATUS_STATUS:
            play_on_queue[idx] = not play_on_queue[idx]

        if not clock.play_state:
            set_blink_pixel(idx, play_on_queue[idx], constants.PIXEL_LOOP_PLAYING_COLOR)
            return

        toggle_chord(idx)

def check_process_chord_on_queue():
    """
    Checks if there are any chords in the play queue and processes them if the clock is playing.
    """
    global global_play_state
    if clock.play_state and not global_play_state:
        global_play_state = True
        for idx, play in enumerate(play_on_queue):
            if play:
                toggle_chord(idx)

def check_stop_all_chords():
    """
    Stops all chords from playing. Called when MIDI stop message is received.
    """
    global global_play_state
    global play_on_queue

    if global_play_state and not clock.play_state:
        global_play_state = False
        for idx in range(16):
            if pad_chords[idx] != "":
                print(f"play_on_queue: {play_on_queue[idx]}")
                print(f"loop_playstate: {pad_chords[idx].loop_playstate}")
                if play_on_queue[idx] and pad_chords[idx].loop_playstate:
                    set_blink_pixel(idx, True, constants.PIXEL_LOOP_PLAYING_COLOR)
                else:
                    play_on_queue[idx] = False
                pad_chords[idx].loop_toggle_playstate(False)
                pad_chords[idx].reset_loop_notes_and_pixels()
                set_default_color(idx, constants.CHORD_COLOR)


def toggle_chord(idx):
    """
    Plays the chord at the given index.
    
    Args:
        idx (int): The index of the pad to play the chord from.
    """
    if pad_chords[idx].loop_type == "chordloop":
        # Toggle play state and reset loop notes and pixels for chord loop
        pad_chords[idx].loop_toggle_playstate()
        pad_chords[idx].reset_loop_notes_and_pixels()
    else:
        # Reset loop for one-shot chord
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

 