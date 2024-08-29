import time
from settings import settings
import inputs 
import constants
from looper import setup_midi_loops, MidiLoop
import chordmaker
from menus import Menu
from debug import debug, DEBUG_MODE, print_debug
from playmenu import get_midi_note_name_text
from clock import clock

from midi import (
    setup_midi,
    send_midi_note_on,
    send_midi_note_off,
    get_midi_messages_in
)
from display import (
    check_show_display,
    blink_pixels,
    pixel_note_on,
    pixel_note_off,
    pixel_encoder_button_on,
    pixel_encoder_button_off
)

setup_midi()
setup_midi_loops()
Menu.initialize()

# Timing
polling_time_prev = time.monotonic()
if DEBUG_MODE:
    debug_time_prev = time.monotonic()

# -------------------- Main loop --------------------

while True:

    # Slower input processing
    timenow = time.monotonic()
    if (timenow - polling_time_prev) > constants.NAV_BUTTONS_POLL_S:
        inputs.process_inputs_slow() 
        check_show_display()
        Menu.display_clear_notifications()
        blink_pixels()
        if DEBUG_MODE:
            debug.check_display_debug()

    # Fast input processing
    inputs.process_inputs_fast()

    # Send MIDI notes off
    for note in inputs.new_notes_off:
        note_val, velocity, padidx = note
        print_debug(f"NOTE OFF: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
        send_midi_note_off(note_val)
        pixel_note_off(padidx)

        # Record to loops and chords
        if MidiLoop.current_loop_obj.loop_record_state:
            MidiLoop.current_loop_obj.add_loop_note(note_val, velocity, padidx, False)
        if chordmaker.recording:
            chordmaker.pad_chords[chordmaker.recording_pad_idx].add_loop_note(note_val, velocity, padidx, False)

    # Record MIDI In to loops and chords
    midi_messages = get_midi_messages_in()
    if MidiLoop.current_loop_obj.loop_record_state or chordmaker.recording:
        for idx, msg in enumerate(midi_messages): # ON or OFF
            if len(msg) == 0:
                continue
            note_val, velocity, padidx = msg
            print_debug(f"MIDI IN: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity} padidx: {padidx}")
            if idx == 0: # ON
                pixel_encoder_button_on()
                if MidiLoop.current_loop_obj.loop_record_state:
                    MidiLoop.current_loop_obj.add_loop_note(note_val, velocity, padidx, True)
                if chordmaker.recording:
                    chordmaker.pad_chords[chordmaker.recording_pad_idx].add_loop_note(note_val, velocity, padidx, True)
            else: # OFF
                pixel_encoder_button_off()
                if MidiLoop.current_loop_obj.loop_record_state:
                    MidiLoop.current_loop_obj.add_loop_note(note_val, velocity, padidx, False)
                if chordmaker.recording:
                    chordmaker.pad_chords[chordmaker.recording_pad_idx].add_loop_note(note_val, velocity, padidx, False)


    # Send MIDI notes on
    for note in inputs.new_notes_on:
        debug.performance_timer("main loop notes on")
        note_val, velocity, padidx = note
        print_debug(f"NOTE ON: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
        send_midi_note_on(note_val, velocity)
        pixel_note_on(padidx)

        # Record to loops and chords
        if MidiLoop.current_loop_obj.loop_record_state:
            MidiLoop.current_loop_obj.add_loop_note(note_val, velocity, padidx, True)
        if chordmaker.recording:
            chordmaker.pad_chords[chordmaker.recording_pad_idx].add_loop_note(note_val, velocity, padidx, True)
        debug.performance_timer("main loop notes on")

    # Loop Notes
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
 
    # Chord Mode Notes
    if settings.MIDI_SYNC:
        if clock.play_state:
            chordmaker.check_process_chord_on_queue()
        else:
            chordmaker.check_stop_all_chords()

    for chord in chordmaker.pad_chords:
        if chord == "":
            continue
        new_notes = chord.get_new_notes() # chord is a loop object
        if new_notes:
            loop_notes_on, loop_notes_off = new_notes
            for note_val, velocity, padidx in loop_notes_on:
                send_midi_note_on(note_val, velocity)
                pixel_note_on(padidx)

                # Add note to current loop if recording
                if MidiLoop.current_loop_obj.loop_record_state:
                    MidiLoop.current_loop_obj.add_loop_note(note_val, velocity, padidx, True)

            for note_val, velocity, padidx in loop_notes_off:
                send_midi_note_off(note_val)
                pixel_note_off(padidx)
                if MidiLoop.current_loop_obj.loop_record_state:
                    MidiLoop.current_loop_obj.add_loop_note(note_val, velocity, padidx, False)
 

