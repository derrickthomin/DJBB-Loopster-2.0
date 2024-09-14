import adafruit_ticks as ticks
from settings import settings
import inputs 
import constants
from looper import setup_midi_loops, MidiLoop
from chordmanager import chord_manager
from menus import Menu
from debug import debug, DEBUG_MODE, print_debug
from playmenu import get_midi_note_name_text
from clock import clock
from midi import setup_midi, send_midi_note_on, send_midi_note_off, get_midi_messages_in
from display import (
    check_show_display,pixels_process_blinks,
    pixel_set_note_on,pixel_set_note_off,
    pixel_set_encoder_button_on, pixel_set_encoder_button_off,
    clear_pixels,display_startup_screen,
)

clear_pixels()
setup_midi()
setup_midi_loops()
display_startup_screen()
Menu.initialize()

# Timing
polling_time_prev = ticks.ticks_ms()
if DEBUG_MODE:
    debug_time_prev = ticks.ticks_ms()

def process_midi_messages(midi_messages):
    for idx, msg in enumerate(midi_messages):
        if not msg or len(msg) < 3:
            continue
        note_val, velocity, padidx = msg
        print_debug(f"MIDI IN: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity} padidx: {padidx}")
        if idx == 0:  # ON
            pixel_set_encoder_button_on()
            record_midi_event(note_val, velocity, padidx, True)
        else:  # OFF
            pixel_set_encoder_button_off()
            record_midi_event(note_val, velocity, padidx, False)

def record_midi_event(note_val, velocity, padidx, is_on):
    if MidiLoop.current_loop.is_recording:
        MidiLoop.current_loop.add_loop_note(note_val, velocity, padidx, is_on)
    if chord_manager.is_recording:
        chord_manager.pad_chords[chord_manager.recording_pad_idx].add_loop_note(note_val, velocity, padidx, is_on)

def process_notes(notes, is_on):
    for note in notes:
        note_val, velocity, padidx = note
        if is_on:
            print_debug(f"NOTE ON: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
            send_midi_note_on(note_val, velocity)
            pixel_set_note_on(padidx)
        else:
            print_debug(f"NOTE OFF: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
            send_midi_note_off(note_val)
            pixel_set_note_off(padidx)
        record_midi_event(note_val, velocity, padidx, is_on)

# -------------------- Main loop --------------------
while True:
    # Slower input processing
    timenow = ticks.ticks_ms()
    if ticks.ticks_diff(timenow, polling_time_prev) > constants.NAV_BUTTONS_POLL_S * 1000:  # Convert seconds to milliseconds
        inputs.process_inputs_slow()
        check_show_display()
        Menu.display_clear_notifications()
        pixels_process_blinks()
        if DEBUG_MODE:
            debug.check_display_debug()
        polling_time_prev = timenow

    # Fast input processing
    inputs.process_inputs_fast()

    # Send MIDI notes off
    process_notes(inputs.new_notes_off, is_on=False)

    # Record MIDI In to loops and chords
    midi_messages = get_midi_messages_in()
    if (MidiLoop.current_loop.is_recording or chord_manager.is_recording) and midi_messages:
        process_midi_messages(midi_messages)

    # Send MIDI notes on
    process_notes(inputs.new_notes_on, is_on=True)

    # Loop Notes
    if MidiLoop.current_loop.loop_is_playing:
        new_notes = MidiLoop.current_loop.get_new_notes()
        if new_notes:
            loop_notes_on, loop_notes_off = new_notes
            process_notes(loop_notes_on, is_on=True)
            process_notes(loop_notes_off, is_on=False)

    # Chord Mode Notes
    if settings.midi_sync:
        if clock.is_playing:
            chord_manager.process_chord_on_queue()
        else:
            chord_manager.stop_all_chords()

    for chord in chord_manager.pad_chords:
        if chord == "":
            continue
        new_notes = chord.get_new_notes()  # chord is a loop object
        if new_notes:
            loop_notes_on, loop_notes_off = new_notes
            process_notes(loop_notes_on, is_on=True)
            process_notes(loop_notes_off, is_on=False)