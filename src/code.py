from settings import settings
import constants
import time
import inputs
from looper import setup_midi_loops, MidiLoop
import chordmaker
from menus import Menu
from debug import debug, DEBUG_MODE, print_debug
from midi import (
    setup_midi,
    get_midi_note_name_text,
    send_midi_note_on,
    send_midi_note_off,
    get_midi_messages_in
)
from display import check_show_display,blink_pixels,pixel_note_on,pixel_note_off

setup_midi()
setup_midi_loops()
Menu.initialize()

# Timing
polling_time_prev = time.monotonic()
if DEBUG_MODE:
    debug_time_prev = time.monotonic()

# -------------------- Main loop --------------------

while True:

    # Slow input processing. navigation, etc.
    timenow = time.monotonic()
    if (timenow - polling_time_prev) > constants.NAV_BUTTONS_POLL_S:
        inputs.process_inputs_slow()  # Update screen, button holds
        check_show_display()
        Menu.display_clear_notifications()
        if DEBUG_MODE:
            debug.check_display_debug()

    # Fast input processing
    inputs.process_inputs_fast()
    external_midinotes = get_midi_messages_in()     # Updates timings, gets notes, etc.
    external_midinotes_on = external_midinotes[0]
    external_midinotes_off = external_midinotes[1]
    if len(external_midinotes_on)>1:
        print(f"External MIDI notes on: {external_midinotes_on}")
    if len(external_midinotes_off)>1:
        print(f"External MIDI notes off: {external_midinotes_off}")

    blink_pixels()             #djt meter this

    # Send MIDI notes off 
    for note in inputs.new_notes_off:
        note_val, velocity, padidx = note
        print_debug(f"NOTE OFF: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
        send_midi_note_off(note_val)
        pixel_note_off(padidx)

        # Add note to current loop or chord if recording
        if MidiLoop.current_loop_obj.loop_record_state:
            MidiLoop.current_loop_obj.add_loop_note(note_val, velocity, padidx, False)
        if chordmaker.recording:
            chordmaker.current_chord_notes[chordmaker.recording_pad_idx].add_loop_note(note_val, velocity, padidx, False)

    # Send MIDI notes on
    for note in inputs.new_notes_on:
        note_val, velocity, padidx = note
        print_debug(f"NOTE ON: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
        send_midi_note_on(note_val, velocity)
        pixel_note_on(padidx)

        # Add note to current loop or chord if recording
        if MidiLoop.current_loop_obj.loop_record_state:
            MidiLoop.current_loop_obj.add_loop_note(note_val, velocity, padidx, True)
        if chordmaker.recording:
            chordmaker.current_chord_notes[chordmaker.recording_pad_idx].add_loop_note(note_val, velocity, padidx, True)

    # Handle loop notes if playing
    if MidiLoop.current_loop_obj.loop_playstate:
        new_notes = MidiLoop.current_loop_obj.get_new_notes()
        if new_notes:
            loop_notes_on, loop_notes_off = new_notes
            for note in loop_notes_on:
                send_midi_note_on(note[0], note[1])
                pixel_note_on(note[2])
            for note in loop_notes_off:
                send_midi_note_off(note[0])
                pixel_note_off(note[2])
 
    # Chord Mode loops
    for chord in chordmaker.current_chord_notes:
        if chord == "":
            continue
        new_notes = chord.get_new_notes() # chord is a loop object
        if new_notes:
            loop_notes_on, loop_notes_off = new_notes
            for note_val,velocity,padidx in loop_notes_on:
                send_midi_note_on(note_val, velocity)
                pixel_note_on(padidx)

                # Add note to current loop if recording
                if MidiLoop.current_loop_obj.loop_record_state:
                    MidiLoop.current_loop_obj.add_loop_note(note_val, velocity, padidx, True)
    
            for note_val,velocity,padidx in loop_notes_off:
                send_midi_note_off(note_val) 
                pixel_note_off(padidx)
                if MidiLoop.current_loop_obj.loop_record_state:
                    MidiLoop.current_loop_obj.add_loop_note(note_val, velocity, padidx, False)
 

