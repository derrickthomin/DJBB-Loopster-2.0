import adafruit_ticks as ticks
from settings import settings
import inputs 
from inputs import process_inputs_fast
from looper import setup_midi_loops, MidiLoop
from chordmanager import chord_manager
from menus import Menu
from debug import debug, print_debug, print_performance_data, time_function, performance_timer
from playmenu import get_midi_note_name_text
from clock import clock
from midi import setup_midi, send_midi_note_on, send_midi_note_off, process_midi_messages_in
from display import (
    pixels_process_blinks,
    pixel_set_note_on,pixel_set_note_off,
    pixel_set_encoder_button_on, pixel_set_encoder_button_off,
    clear_pixels,display_startup_screen, update_pixels,get_pixels_need_update, set_pixels_need_update, display_manager
)
import useraddons
from utils import free_memory
import constants

clear_pixels()
setup_midi()
setup_midi_loops()
display_startup_screen()
Menu.initialize()

# Timing
polling_time_prev = ticks.ticks_ms()
fast_polling_time_prev = ticks.ticks_ms()
midi_polling_time_prev = ticks.ticks_ms()
pixel_update_time_prev = ticks.ticks_ms()
clear_notifications_time_prev = ticks.ticks_ms()
all_new_notes_on = []
all_new_notes_off = []

if debug.DEBUG_MODE:
    debug_time_prev = ticks.ticks_ms()


def record_note_midi_messages(messages):
    """
    Processes a list of MIDI messages, handling note-on and note-off events.

    Args:
        messages (list of list): A list of MIDI messages, where each message is a list 
            containing three elements:
            - note_val (int): The MIDI note value.
            - velocity (int): The velocity of the note.
            - padidx (int): The index of the pad associated with the note.
    """
    for idx, msg in enumerate(messages):
        if not msg or len(msg) < 3:
            continue
        note_val, velocity, padidx = msg
        print_debug(f"MIDI IN: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity} padidx: {padidx}")
        if idx == 0:  # ON
            pixel_set_encoder_button_on()
            record_midi_event(note_val, velocity, padidx, True,"all")
        else:  # OFF
            pixel_set_encoder_button_off()
            record_midi_event(note_val, velocity, padidx, False,"all")

def record_midi_event(note_val, velocity, padidx, is_on, record):
    """
    Handles the recording of MIDI events into either a loop or a chord, 
    depending on the current recording state and the specified recording mode.

    Args:
        note_val (int): The MIDI note value of the event.
        velocity (int): The velocity of the MIDI note.
        padidx (int): The index of the pad triggering the event.
        is_on (bool): Indicates whether the note is being turned on (True) or off (False).
        record (str): Specifies the recording mode. Can be "loop", "chord", or "all".

    Behavior:
        - If the current loop is recording and `record` is "loop" or "all", 
          the MIDI event is added to the loop.
        - If the chord manager is recording and `record` is "chord" or "all", 
          the MIDI event is added to the chord associated with the recording pad index.
    """
    if MidiLoop.current_loop.is_recording and record in ["loop", "all"]:
        MidiLoop.current_loop.add_loop_note(note_val, velocity, padidx, is_on)
    if chord_manager.is_recording and record in ["chord", "all"]:
        chord_manager.pad_chords[chord_manager.recording_pad_idx].add_loop_note(note_val, velocity, padidx, is_on)
        

def process_notes(notes, is_on, record="all"): # record = "loop", "chord", "all", False
    """
    Processes a list of MIDI notes, handling note-on and note-off events, 
    updating visual feedback, and optionally recording the events.

    Args:
        notes (list): A list of tuples representing MIDI notes. Each tuple 
                        contains (note_val, velocity, padidx), where:
                        - note_val (int): The MIDI note value.
                        - velocity (int): The velocity of the note.
                        - padidx (int): The index of the pad associated with the note.
        is_on (bool): A flag indicating whether the notes are being turned on 
                        (True) or off (False).
        record (str or bool, optional): Specifies whether and how to record the 
                        MIDI events. Possible values:
                        - "loop": Record the notes into global loop if it is recording.
                        - "chord": Record the notes into chord if recording.
                        - "all": Record all notes.
                        - False: Do not record the notes.
                        Defaults to "all".

    Returns:
        None
    """
    if not notes:
        return
    for note in notes:
        note_val, velocity, padidx = note
        if is_on:
            print(f"NOTE ON: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
            send_midi_note_on(note_val, velocity)
            pixel_set_note_on(padidx, velocity)
        else:
            print(f"NOTE OFF: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
            send_midi_note_off(note_val)
            pixel_set_note_off(padidx)
            useraddons.handle_new_notes_off(note_val, velocity, padidx)
        if record:
            record_midi_event(note_val, velocity, padidx, is_on, record)

# -------------------- Main loop --------------------
while True:
    timenow = ticks.ticks_ms()

    # 0) Reset new notes
    all_new_notes_on.clear()
    all_new_notes_off.clear()
    is_anything_recording = MidiLoop.current_loop.is_recording or chord_manager.is_recording

    # 1) MIDI Input, Clock updates
    clock.reset_new_tick_flag()
    incoming_midi = process_midi_messages_in()
    
    if incoming_midi and incoming_midi != "start" and is_anything_recording: # We have MIDI input and we are recording
        record_note_midi_messages(incoming_midi)

    midi_polling_time_prev = timenow
    if incoming_midi == "stop":
        chord_manager.stop_all_chords() 
        MidiLoop.current_loop.clear_loop_notes_and_pixels()
    
    # 2) Process Inputs unless new MIDI start message
    if not incoming_midi == "start":

        # 2.1) Slow input processing
        if ticks.ticks_diff(timenow, polling_time_prev) > constants.NAV_BUTTONS_POLL_S * 1000:  # Convert seconds to milliseconds
            inputs.process_inputs_slow()

            if display_manager.display_needs_update:
                display_manager.check_show_display()

            if ticks.ticks_diff(timenow, clear_notifications_time_prev) > 1000:
                clear_notifications_time_prev = timenow
                Menu.display_clear_notifications()

            pixels_process_blinks()
            debug.check_display_debug()
            polling_time_prev = timenow
            useraddons.check_addons_slow()

        # 2.2) Fast input processing
        process_inputs_fast()

        all_new_notes_off.extend(inputs.new_notes_off)
        all_new_notes_on.extend(inputs.new_notes_on)

    # 3) Get new loop notes
    if MidiLoop.current_loop.loop_is_playing:
        new_notes = MidiLoop.current_loop.get_new_notes()
        if new_notes:
            loop_notes_on, loop_notes_off = new_notes
            process_notes(loop_notes_on, is_on=True, record=False) # dont record to self
            process_notes(loop_notes_off, is_on=False, record=False)

    # 4) Start chords that are queued (blinking green)
    if settings.midi_sync:
        if clock.is_playing:
            chord_manager.process_chord_on_queue()
        # else:
        #     chord_manager.stop_all_chords()  #djt - maaybe do this elsewher.. not a bunch of times here.

    # 5) Get all new chord notes from all chords
    for idx, chord in enumerate(chord_manager.pad_chords):
        if chord == "":
            continue

        # No sync
        if not settings.midi_sync:
            new_notes = chord.get_new_notes()  # chord is a loop object
            if new_notes:
                loop_notes_on, loop_notes_off = new_notes
                process_notes(loop_notes_on, is_on=True, record=False) # dont record into self
                process_notes(loop_notes_off, is_on=False, record=False) # djt change back to loop eventually

        # Midi sync
        else:
            if chord_manager.chord_playback_queue[idx] is False:
                continue
        
            new_notes = chord.get_new_notes()  # chord is a loop object
            if new_notes:
                loop_notes_on, loop_notes_off = new_notes
                process_notes(loop_notes_on, is_on=True, record=False) # dont record into self
                process_notes(loop_notes_off, is_on=False, record=False) # djt change back to loop eventually

    # 6) Process all notes
    if all_new_notes_on or all_new_notes_off:
        process_notes(all_new_notes_on, is_on=True, record="all")
        process_notes(all_new_notes_off, is_on=False, record="all")

    # 7) Update pixels
    if ticks.ticks_diff(timenow, pixel_update_time_prev) > 10:
        update_pixels()
        pixel_update_time_prev = timenow
