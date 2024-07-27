from settings import settings
import time
import inputs
from looper import setup_midi_loops, MidiLoop
import chordmaker
from menus import Menu
from debug import debug, DEBUG_MODE
from midi import (
    setup_midi,
    get_midi_note_name_text,
    send_midi_note_on,
    send_midi_note_off,
    get_midi_messages_in
)
from display import check_show_display,blink_pixels,pixel_note_on,pixel_note_off


# Initialize MIDI and other components
setup_midi()
setup_midi_loops()
Menu.initialize()


# Initialize time variables
polling_time_prev = time.monotonic()
if DEBUG_MODE:
    debug_time_prev = time.monotonic()

# Main loop
while True:

    # Timing compensation for MIDI in primarily
    timenow = time.monotonic()

    # Polling for navigation buttons
    if (timenow - polling_time_prev) > settings.NAV_BUTTONS_POLL_S:
        inputs.check_inputs_slow()  # Update screen, button holds
        check_show_display()
        Menu.display_clear_notifications()
        if DEBUG_MODE:
            debug.check_display_debug()

    # Fast input processing
    inputs.check_inputs_fast()
    inputs.process_inputs_fast()
    get_midi_messages_in()     # Updates timings for midi IN
    blink_pixels() #djt meter this

    # Send MIDI notes off 
    for note in inputs.new_notes_off:
        note_val, velocity, padidx = note
        if DEBUG_MODE:
            print(
                f"sending MIDI OFF val: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}"
            )
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
        if DEBUG_MODE:
            print(
                f"sending MIDI ON val: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}"
            )
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
                if MidiLoop.current_loop_obj.loop_record_state:
                    MidiLoop.current_loop_obj.add_loop_note(note_val, velocity, padidx, True)
    
            for note_val,velocity,padidx in loop_notes_off:
                send_midi_note_off(note_val) 
                pixel_note_off(padidx)
                if MidiLoop.current_loop_obj.loop_record_state:
                    MidiLoop.current_loop_obj.add_loop_note(note_val, velocity, padidx, False)
 
