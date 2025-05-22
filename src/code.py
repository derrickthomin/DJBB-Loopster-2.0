# Standard library imports
import adafruit_ticks as ticks
import constants

# Project configuration
from utils import free_memory
from looper import setup_midi_loops, MidiLoop
free_memory()
setup_midi_loops()
from settings import settings
from debug import debug, print_debug

# Initialize inputs first (memory management)
from inputs import inputs
inputs.initialize()

# Core functionality modules
free_memory()
from chordmanager import chord_manager
free_memory()
from clock import clock
free_memory()
from midi import midi

# UI and display modules
free_memory()
from menus import Menu
from playmenu import get_midi_note_name_text
from display import display, display_manager
from pixels import pixels

# User extensions
import useraddons

# Initialize core components
pixels.clear_all()
midi.setup()
setup_midi_loops()
display.show_startup_screen()
Menu.initialize()

# Global timing variables
polling_time_prev = ticks.ticks_ms()
fast_polling_time_prev = ticks.ticks_ms()
midi_polling_time_prev = ticks.ticks_ms()
pixel_update_time_prev = ticks.ticks_ms()
clear_notifications_time_prev = ticks.ticks_ms()

# State tracking
new_notes_on = []
new_notes_off = []
last_note_event_times = {}
last_cc_event_times = {}

if debug.DEBUG_MODE:
    debug_time_prev = ticks.ticks_ms()

# -------------------- MIDI Event Handlers --------------------

def record_note_midi_messages(messages, note_type):
    """Process incoming MIDI note messages and record them if needed.
    
    Args:
        messages (list): List of (note_val, velocity, padidx) tuples
        note_type (str): Either "note_on" or "note_off"
    """
    for msg in messages:
        if not msg or len(msg) < 3:
            continue
        note_val, velocity, padidx = msg
        print_debug(f"MIDI IN: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity} padidx: {padidx}")
        
        if note_type == "notes_on":
            # pixels.encoder_button_on()
            record_midi_event(note_val, velocity, padidx, True, "all")
            print("recording note on")
        else:
            # pixels.encoder_button_off()
            record_midi_event(note_val, velocity, padidx, False, "all")
            print("recording note off")

def record_cc_messages(message_data):
    """Process and record incoming MIDI CC messages.
    
    Args:
        message_data (list): List of (cc_val, cc_value) tuples
    """
    for msg in message_data:
        if not msg or len(msg) < 2:
            continue
        cc_val, cc_value = msg
        # Flash the encoder light instead of the bottom pad
        # pixels.flash_pixel(17, duration=0.2, color=constants.CC_COLOR)
        
        if MidiLoop.current_loop.is_recording:
            MidiLoop.current_loop.add_cc(cc_val, cc_value)
        if chord_manager.is_recording:
            chord_manager.chord_loops[chord_manager.recording_pad].add_cc(cc_val, cc_value)

def record_midi_event(note_val, velocity, padidx, is_on, record):
    """Record MIDI events to active recording targets (loop and/or chord).
    
    Args:
        note_val (int): MIDI note number
        velocity (int): Note velocity
        padidx (int): Pad index
        is_on (bool): True for note-on, False for note-off
        record (str): Where to record - "loop", "chord", or "all"
    """
    if MidiLoop.current_loop.is_recording and record in ["loop", "all"]:
        MidiLoop.current_loop.add_note(note_val, velocity, padidx, is_on)
    if chord_manager.is_recording and record in ["chord", "all"]:
        chord_manager.chord_loops[chord_manager.recording_pad].add_note(note_val, velocity, padidx, is_on)

# -------------------- Event Processing --------------------

def process_notes(notes, is_on, record="all"):
    """Process a batch of note events, sending MIDI and recording if needed.
    
    Args:
        notes (list): List of (note_val, velocity, padidx) tuples
        is_on (bool): True for note-on, False for note-off 
        record (str): Recording target - "loop", "chord", "all", or False
    """
    global last_note_event_times

    if not notes:
        return
    
    now = ticks.ticks_ms()
    for note in notes:
        note_val, velocity, padidx = note
        if note_val in last_note_event_times:
            if ticks.ticks_diff(now, last_note_event_times[note_val]) < constants.MIN_TIME_BETWEEN_EVENTS:
                continue
        last_note_event_times[note_val] = now
        if is_on:
            #print(f"NOTE ON: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
            midi.send_note_on(note_val, velocity)
            pixels.set_note_on(padidx, velocity)
        else:
            #print(f"NOTE OFF: {get_midi_note_name_text(note_val)} ({note_val}) vel: {velocity}")
            midi.send_note_off(note_val)
            pixels.set_note_off(padidx)
            useraddons.handle_new_notes_off(note_val, velocity, padidx)
        if record:
            record_midi_event(note_val, velocity, padidx, is_on, record)

def process_cc_events(cc_events, record="all", pad_idx=None):
    """Process CC events, sending MIDI and recording if needed.
    
    Args:
        cc_events (list): List of (cc_val, cc_value) tuples
        record (str): Recording target - "loop","chord", "all", or False
        pad_idx (int, optional): The pad index associated with this CC event during playback
    """
    global last_cc_event_times

    if not cc_events:
        return
    
    now = ticks.ticks_ms()
    for cc_event in cc_events:
        cc_val, cc_value = cc_event
        if cc_val in last_cc_event_times:
            if ticks.ticks_diff(now, last_cc_event_times[cc_val]) < constants.MIN_TIME_BETWEEN_EVENTS:
                continue
        last_cc_event_times[cc_val] = now
        print_debug(f"CC: {cc_val} value: {cc_value}")
        midi.send_cc(cc_val, cc_value)
        
        # For playback of CC events, show them on the associated pad if available
        if pad_idx is not None:
            pixels.flash_pixel(pad_idx, duration=0.2, color=constants.CC_COLOR)
        else:
            # For newly recorded CC events, show on encoder light
            pixels.flash_pixel(17, duration=0.2, color=constants.CC_COLOR)
        
        if record and record != "false":
            if MidiLoop.current_loop.is_recording and record in ["loop", "all"]:
                MidiLoop.current_loop.add_cc(cc_val, cc_value)
            if chord_manager.is_recording and record in ["chord", "all"]:
                chord_manager.chord_loops[chord_manager.recording_pad].add_cc(cc_val, cc_value)

def process_chord_notes():
    """Process notes from chord loops, handling both MIDI sync and non-sync modes."""
    # Start chords that are queued when using MIDI sync
    if settings.midi_sync and clock.is_playing:
        chord_manager.process_chord_on_queue()

    # Process notes from all active chord loops
    for idx, chord in enumerate(chord_manager.chord_loops):
        if chord == "" or not chord.loop_is_playing:
            continue

        # Handle non-MIDI sync mode
        if not settings.midi_sync:
            new_chord_notes = chord.get_new_notes()
            if new_chord_notes:
                chordloop_notes_on, chordloop_notes_off, new_cc_events = new_chord_notes
                process_notes(chordloop_notes_on, is_on=True, record=False)
                process_notes(chordloop_notes_off, is_on=False, record=False)
                # Pass the pad index to process_cc_events for proper visualization
                process_cc_events(new_cc_events, record=False, pad_idx=idx)
        
        # Handle MIDI sync mode
        else:
            if not chord_manager.play_queue[idx]:
                continue
            
            new_chord_notes = chord.get_new_notes()
            if new_chord_notes:
                chordloop_notes_on, chordloop_notes_off, new_cc_events = new_chord_notes
                process_notes(chordloop_notes_on, is_on=True, record="loop")
                process_notes(chordloop_notes_off, is_on=False, record="loop")
                # Pass the pad index to process_cc_events for proper visualization
                process_cc_events(new_cc_events, record="loop", pad_idx=idx)

# -------------------- Main Loop --------------------
while True:
    timenow = ticks.ticks_ms()

    # Reset state
    new_notes_on.clear()
    new_notes_off.clear()
    is_anything_recording = MidiLoop.current_loop.is_recording or chord_manager.is_recording

    # 1. Process MIDI Input & Clock updates
    clock.reset_new_tick_flag()
    midi_in_type, midi_in_data = midi.process_messages_in()
    
    # Handle MIDI passthrough
    if midi.should_passthru_midi():
        if midi_in_type == "notes_on":
            process_notes(midi_in_data, is_on=True, record=False)
            pixels.flash_pixel(17, duration=0.2, color=constants.PASSTHRU_COLOR)
            
        elif midi_in_type == "notes_off":
            process_notes(midi_in_data, is_on=False, record=False)
            
        elif midi_in_type == "cc":
            process_cc_events(midi_in_data, record=False)
            pixels.flash_pixel(17, duration=0.2, color=constants.PASSTHRU_COLOR)
            
        elif midi_in_type == "start":
            midi.send_start_stop(True)
                
        elif midi_in_type == "stop":
            midi.send_start_stop(False)
    
    # Handle incoming MIDI messages
    if midi_in_type in ["notes_on","notes_off"]:
        if midi_in_type == "notes_on":
            pixels.flash_pixel(17, duration=0.2, color=constants.NOTE_COLOR)

        if is_anything_recording:
            record_note_midi_messages(midi_in_data, note_type=midi_in_type)

    if midi_in_type == "cc" and settings.record_cc:
        pixels.flash_pixel(17, duration=0.2, color=constants.CC_COLOR)

        if is_anything_recording:
            record_cc_messages(midi_in_data)

    midi_polling_time_prev = timenow
    if midi_in_type == "stop":
        chord_manager.stop_all_chords() 
        MidiLoop.current_loop.clear_notes_and_pixels()
    
    # 2. Process User Inputs (unless MIDI start received)
    if not midi_in_type == "start":
        # 2.1 Slow input processing (navigation, display, notifications)
        if ticks.ticks_diff(timenow, polling_time_prev) > constants.NAV_BUTTONS_POLL_S * 1000:
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
            chord_manager.check_event_limits()

        # 2.2 Fast input processing
        inputs.process_inputs_fast()
        new_notes_off.extend(inputs.new_notes_off)
        new_notes_on.extend(inputs.new_notes_on)

    # 3. Process Loop Notes
    if MidiLoop.current_loop.loop_is_playing:
        new_notes = MidiLoop.current_loop.get_new_notes()
        if new_notes:
            loop_notes_on, loop_notes_off, new_cc_events = new_notes
            process_notes(loop_notes_on, is_on=True, record=False)
            process_notes(loop_notes_off, is_on=False, record=False)
            process_cc_events(new_cc_events, record=False)

    # 4. Process Chord Notes
    process_chord_notes()

    # 5. Process New Notes
    if new_notes_on or new_notes_off:
        process_notes(new_notes_on, is_on=True, record="all")
        process_notes(new_notes_off, is_on=False, record="all")

    # 6. Update Visual Feedback
    if ticks.ticks_diff(timenow, pixel_update_time_prev) > 10:
        pixels.update()
        pixel_update_time_prev = timenow
