# Standard library imports
import adafruit_ticks as ticks
import constants
from inputs import inputs # THIS IS THE MEM ISSUE
inputs.initialize() # Initialize inputs before importing other modules to avoid memory issues

# Project configuration
from utils import free_memory
from settings import settings
from debug import debug, print_debug

# Core functionality modules
free_memory()
from looper import setup_midi_loops, MidiLoop
free_memory()
from chordmanager import chord_manager
free_memory()
from clock import clock
free_memory()
from midi import midi

# UI and input handling
# from inputs import inputs, initialize_hardware_inputs # THIS IS THE MEM ISSUE
free_memory()
from menus import Menu
from playmenu import get_midi_note_name_text
from display import display, display_manager
from pixels import pixels

# User extensions
import useraddons
pixels.clear_all()
midi.setup()
setup_midi_loops()
display.show_startup_screen()
Menu.initialize()

# Timing
polling_time_prev = ticks.ticks_ms()
fast_polling_time_prev = ticks.ticks_ms()
midi_polling_time_prev = ticks.ticks_ms()
pixel_update_time_prev = ticks.ticks_ms()
clear_notifications_time_prev = ticks.ticks_ms()
new_notes_on = []
new_notes_off = []

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
            pixels.encoder_button_on()
            record_midi_event(note_val, velocity, padidx, True,"all")
        else:  # OFF
            pixels.encoder_button_off()
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
    """
    if MidiLoop.current_loop.is_recording and record in ["loop", "all"]:
        MidiLoop.current_loop.add_note(note_val, velocity, padidx, is_on)
    if chord_manager.is_recording and record in ["chord", "all"]:
        chord_manager.chord_loops[chord_manager.recording_pad].add_note(note_val, velocity, padidx, is_on)
        

def process_notes(notes, is_on, record="all"): # record = "loop", "chord", "all", False
    """
    Processes a list of MIDI notes, handling note-on and note-off events, 
    updating visual feedback, and optionally recording the events.

    Args:
        notes (list): Each tuple contains (note_val, velocity, padidx).
        is_on (bool): A flag indicating whether the notes are being turned on or off
        record (str or bool, optional): "loop", "chord", "all", False. Defaults to "all".

    Returns:
        None
    """
    if not notes:
        return
    
    for note in notes:
        note_val, velocity, padidx = note
        if is_on:
            print(f"NOTE ON: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
            midi.send_note_on(note_val, velocity)
            pixels.set_note_on(padidx, velocity)
        else:
            print(f"NOTE OFF: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
            midi.send_note_off(note_val)
            pixels.set_note_off(padidx)
            useraddons.handle_new_notes_off(note_val, velocity, padidx)
        if record:
            record_midi_event(note_val, velocity, padidx, is_on, record)

def process_chord_notes():
    # Start chords that are queued (blinking green)
    if settings.midi_sync:
        if clock.is_playing:
            chord_manager.process_chord_on_queue()

    # 5) Get all new chord notes from all chords
    for idx, chord in enumerate(chord_manager.chord_loops):
        if chord == "":
            continue

        # No sync
        if not settings.midi_sync:
            new_chord_notes = chord.get_new_notes()  # chord is a loop object
            if new_chord_notes:
                chordloop_notes_on, chordloop_notes_off = new_chord_notes
                process_notes(chordloop_notes_on, is_on=True, record=False)   # dont record into self
                process_notes(chordloop_notes_off, is_on=False, record=False) # djt change back to loop eventually

        # Midi sync
        else:
            if chord_manager.play_queue[idx] is False:
                continue

            new_chord_notes = chord.get_new_notes()  # chord is a loop object
            if new_chord_notes:
                chordloop_notes_on, chordloop_notes_off = new_chord_notes
                process_notes(chordloop_notes_on, is_on=True, record="loop") # dont record into self
                process_notes(chordloop_notes_off, is_on=False, record="loop") # djt change back to loop eventually

# -------------------- Main loop --------------------
while True:
    timenow = ticks.ticks_ms()

    # 0) Reset new notes
    new_notes_on.clear()
    new_notes_off.clear()
    is_anything_recording = MidiLoop.current_loop.is_recording or chord_manager.is_recording

    # 1) MIDI Input, Clock updates
    clock.reset_new_tick_flag()
    incoming_midi = midi.process_messages_in()
    
    if incoming_midi and incoming_midi != "start" and is_anything_recording: # We have MIDI input and we are recording
        record_note_midi_messages(incoming_midi)

    midi_polling_time_prev = timenow
    if incoming_midi == "stop":
        chord_manager.stop_all_chords() 
        MidiLoop.current_loop.clear_notes_and_pixels()
    
    # 2) Process Inputs unless new MIDI start message
    if not incoming_midi == "start":

        # 2.1) Slow input processing
        if ticks.ticks_diff(timenow, polling_time_prev) > constants.NAV_BUTTONS_POLL_S * 1000:  # Convert seconds to milliseconds
            inputs.process_inputs_slow()

            if display_manager.display_needs_update:
                display_manager.check_show_display()

            if ticks.ticks_diff(timenow, clear_notifications_time_prev) > 1000:
                clear_notifications_time_prev = timenow
                Menu.clear_notifications()

            pixels.process_blinks()
            debug.display_info()
            polling_time_prev = timenow
            useraddons.slow()

        # 2.2) Fast input processing    
        inputs.process_inputs_fast() # DJT - !!! useraddons???
        new_notes_off.extend(inputs.new_notes_off)
        new_notes_on.extend(inputs.new_notes_on)

    # 3) Loop - Get notes
    if MidiLoop.current_loop.loop_is_playing:
        new_notes = MidiLoop.current_loop.get_new_notes()
        if new_notes:
            loop_notes_on, loop_notes_off = new_notes
            process_notes(loop_notes_on, is_on=True, record=False) # dont record to self
            process_notes(loop_notes_off, is_on=False, record=False)

    # 4) Chord - Get notes
    process_chord_notes()

    # 5) Send MIDI - Process all notes
    if new_notes_on or new_notes_off:
        process_notes(new_notes_on, is_on=True, record="all")
        process_notes(new_notes_off, is_on=False, record="all")

    # 6) Update pixels
    if ticks.ticks_diff(timenow, pixel_update_time_prev) > 10:
        pixels.update()
        pixel_update_time_prev = timenow
