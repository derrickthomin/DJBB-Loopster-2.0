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
from midi import setup_midi, send_midi_note_on, send_midi_note_off, get_midi_messages_in
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
all_notes_on = []
all_notes_off = []

if debug.DEBUG_MODE:
    debug_time_prev = ticks.ticks_ms()


def process_midi_messages(midi_messages):
    for idx, msg in enumerate(midi_messages):
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
    if MidiLoop.current_loop.is_recording and record in ["loop", "all"]:
        MidiLoop.current_loop.add_loop_note(note_val, velocity, padidx, is_on)
    if chord_manager.is_recording and record in ["chord", "all"]:
        chord_manager.pad_chords[chord_manager.recording_pad_idx].add_loop_note(note_val, velocity, padidx, is_on)
        

def process_notes(notes, is_on, record="all"): # record = "loop", "chord", "all", False
    if not notes:
        return
    for note in notes:
        note_val, velocity, padidx = note
        if is_on:
            print_debug(f"NOTE ON: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
            send_midi_note_on(note_val, velocity)
            pixel_set_note_on(padidx, velocity)
        else:
            print_debug(f"NOTE OFF: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
            send_midi_note_off(note_val)
            pixel_set_note_off(padidx)
            useraddons.handle_new_notes_off(note_val, velocity, padidx)
        if record:
            record_midi_event(note_val, velocity, padidx, is_on, record)

# -------------------- Main loop --------------------
while True:
    # Slower input processing
    timenow = ticks.ticks_ms()

    # Get MIDI in, update clock
    clock.reset_new_tick_flag()
    midi_messages = get_midi_messages_in()
    if (MidiLoop.current_loop.is_recording or chord_manager.is_recording) and midi_messages and midi_messages != "start":
        process_midi_messages(midi_messages)
    midi_polling_time_prev = timenow
    
    # skip this cycle if we got a start message - priority to MIDI
    if not midi_messages == "start":

        if ticks.ticks_diff(timenow, polling_time_prev) > constants.NAV_BUTTONS_POLL_S * 1000 * 3:  # Convert seconds to milliseconds
            # performance_timer.start("process_inputs_slow")
            inputs.process_inputs_slow()
            # performance_timer.stop("process_inputs_slow")

            # performance_timer.start("check_show_display")
            if display_manager.display_needs_update:
                display_manager.check_show_display()
            # performance_timer.stop("check_show_display")

            if ticks.ticks_diff(timenow, clear_notifications_time_prev) > 1000:
                clear_notifications_time_prev = timenow
                # performance_timer.start("Menu.display_clear_notifications")
                Menu.display_clear_notifications()
                # performance_timer.stop("Menu.display_clear_notifications")

            # performance_timer.start("pixels_process_blinks")
            pixels_process_blinks()
            # performance_timer.stop("pixels_process_blinks")

            # performance_timer.start("debug.check_display_debug")
            debug.check_display_debug()
            # performance_timer.stop("debug.check_display_debug")

            polling_time_prev = timenow

            # performance_timer.start("useraddons.check_addons_slow")
            useraddons.check_addons_slow()
            # performance_timer.stop("useraddons.check_addons_slow")

        # Fast input processing
        if ticks.ticks_diff(timenow, fast_polling_time_prev) > 15:  # Convert seconds to milliseconds
            # performance_timer.start("process_inputs_fast")
            process_inputs_fast()
            # performance_timer.stop("process_inputs_fast")
            # performance_timer.start("process_inputs_combined")
            # process_inputs_combined_metered()
            # performance_timer.stop("process_inputs_combined")
            fast_polling_time_prev = timenow

        # Temporary data structures for notes
        all_notes_on.clear()
        all_notes_off.clear()

        # Collect notes to be processed
        all_notes_off.extend(inputs.new_notes_off)
        all_notes_on.extend(inputs.new_notes_on)

    # Loop Notes
    if MidiLoop.current_loop.loop_is_playing:
        # performance_timer.start("MidiLoop.current_loop.get_new_notes")
        new_notes = MidiLoop.current_loop.get_new_notes()
        # performance_timer.stop("MidiLoop.current_loop.get_new_notes")
        if new_notes:
            loop_notes_on, loop_notes_off = new_notes
            all_notes_on.extend(loop_notes_on)
            all_notes_off.extend(loop_notes_off)

    # Chord Mode Notes
    if settings.midi_sync:
        if clock.is_playing:
            # performance_timer.start("chord_manager.process_chord_on_queue")
            chord_manager.process_chord_on_queue()
            # performance_timer.stop("chord_manager.process_chord_on_queue")
        else:
            # performance_timer.start("chord_manager.stop_all_chords")
            chord_manager.stop_all_chords()
            # performance_timer.stop("chord_manager.stop_all_chords")

    for chord in chord_manager.pad_chords:
        if chord == "":
            continue
        # performance_timer.start("chord.get_new_notes")
        new_notes = chord.get_new_notes()  # chord is a loop object
        # performance_timer.stop("chord.get_new_notes")
        if new_notes:
            loop_notes_on, loop_notes_off = new_notes
            all_notes_on.extend(loop_notes_on)
            all_notes_off.extend(loop_notes_off)

    # Process all collected notes if there are any
    if all_notes_on or all_notes_off:
        # performance_timer.start("process_notes_on")
        process_notes(all_notes_on, is_on=True)
        # performance_timer.stop("process_notes_on")

        # performance_timer.start("process_notes_off")
        process_notes(all_notes_off, is_on=False)
        # performance_timer.stop("process_notes_off")

    if ticks.ticks_diff(timenow, pixel_update_time_prev) > 20:
        # performance_timer.start("update_pixels")
        update_pixels()
        # performance_timer.stop("update_pixels")
        pixel_update_time_prev = timenow

    # Print performance data
    # performance_timer.update()
    #free_memory()