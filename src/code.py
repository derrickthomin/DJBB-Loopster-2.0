# Standard library imports
import adafruit_ticks as ticks
import constants as C
from settings import settings
from inputs import inputs
inputs.initialize()
from chordmanager import chord_manager
from clock import clock
from midi import midi
from menus import Menu
from display import display, display_manager
from pixels import pixels
import useraddons

pixels.clear_all()
midi.setup()
display.show_startup_screen()
Menu.initialize()

# Global timing variables
polling_time_prev = ticks.ticks_ms()
fast_polling_time_prev = ticks.ticks_ms()
pixel_update_time_prev = ticks.ticks_ms()
clear_notifications_time_prev = ticks.ticks_ms()

# State tracking
new_notes_on = []
new_notes_off = []
last_note_event_times = {}
last_cc_event_times = {}

prev_midi_sync_state = settings.midi_sync
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
        note_val, velocity, padidx, _ = msg

        if chord_manager.is_recording:
            padidx = chord_manager.recording_pad
        
        if note_type == "notes_on":
            record_midi_event(note_val, velocity, padidx, True)

        else:
            record_midi_event(note_val, velocity, padidx, False)

def record_cc_messages(message_data):
    """Process and record incoming MIDI CC messages to active recording targets.
    
    Args:
        message_data (list): CC message tuples (cc_val, cc_value)
    """
    if not chord_manager.is_recording:
        return

    for msg in message_data:
        try:
            cc_val, cc_value, _ = msg
        except (TypeError, ValueError):
            continue
        
        if cc_val == 123 and cc_value == 0 and settings.midi_sync:
            chord_manager.handle_fn_press()  # Special case for CC 123 (All Notes Off)

        if chord_manager.is_recording:
            chord_manager.chord_loops[chord_manager.recording_pad].add_cc(cc_val, cc_value)

def record_midi_event(note_val, velocity, padidx, is_on):
    """Record MIDI events to active recording targets.
    
    Args:
        note_val (int): MIDI note number
        velocity (int): Note velocity
        padidx (int): Pad index
        is_on (bool): True for note-on, False for note-off
    """
    if chord_manager.is_recording:
        chord_manager.chord_loops[chord_manager.recording_pad].add_note(note_val, velocity, padidx, is_on)

# -------------------- Event Processing --------------------

def process_notes(notes, is_on, record=True, chord_idx=C.DEFAULT_CHORDPAD_IDX):
    """Process note events: send MIDI, update pixels, record if needed.
    
    Args:
        notes (list): Note tuples (note_val, velocity, padidx, notechord_idx)
        is_on (bool): True for note-on, False for note-off
        record (bool): True to record events, False to skip
        chord_idx (int): MIDI channel override (uses note's notechord_idx if DEFAULT_CHORDPAD_IDX)
    """
    global last_note_event_times

    if not notes:
        return
    
    use_notechord = (chord_idx == C.DEFAULT_CHORDPAD_IDX)

    now = ticks.ticks_ms()
    for note in notes:
        note_val, velocity, padidx, notechord_idx = note
        if use_notechord:
            chord_idx = notechord_idx
        
        last_note_event_times[note_val] = now
        if is_on:
            midi.send_note_on(note_val, velocity, chord_idx)
            pixels.set_note_on(padidx, velocity)
            useraddons.handle_new_notes_on(note_val, velocity, padidx)
        else:
            midi.send_note_off(note_val, chord_idx)
            pixels.set_note_off(padidx)
            useraddons.handle_new_notes_off(note_val, velocity, padidx)
        if record:
            record_midi_event(note_val, velocity, padidx, is_on)

def process_cc_events(cc_events, record=True, padchord_idx=C.DEFAULT_CHORDPAD_IDX, chord_type=None):
    """Process CC events: send MIDI, update pixels, record if needed.
    
    Args:
        cc_events (list): CC tuples (cc_val, cc_value, notechord_idx)
        record (str): True to record events, False to skip
        padchord_idx (int): Associated pad index for playback
        chord_type (str): The loop type ("oneshot", "loop", etc.) to determine pixel behavior
    """
    global last_cc_event_times

    if not cc_events:
        return
    
    # Check if this is from a oneshot loop
    is_oneshot_mode = chord_type == "oneshot"

    use_notechord = (padchord_idx == C.DEFAULT_CHORDPAD_IDX)
    chord_idx = padchord_idx
    
    now = ticks.ticks_ms()
    for cc_event in cc_events:
        cc_val, cc_value, notechord_idx = cc_event
        if use_notechord:
            chord_idx = notechord_idx
        
        last_cc_event_times[cc_val] = now
        midi.send_cc(cc_val, cc_value, chord_idx)
        useraddons.handle_new_cc(cc_val, cc_value, chord_idx)
        
        if padchord_idx is not None and padchord_idx != C.DEFAULT_CHORDPAD_IDX:
            if is_oneshot_mode:
                pixels.flash_pixel(padchord_idx, duration=0.5, color=C.CC_COLOR)
            else:
                pixels.flash_pixel(padchord_idx, duration=0.2, color=C.CC_COLOR)
        else: 
            if is_oneshot_mode:
                pixels.flash_pixel(17, duration=0.5, color=C.CC_COLOR)
            else:
                pixels.flash_pixel(17, duration=0.2, color=C.CC_COLOR)
        
        if record and chord_manager.is_recording:
            chord_manager.chord_loops[chord_manager.recording_pad].add_cc(cc_val, cc_value)

def process_chord_notes():
    """Process notes from chord loops, handling MIDI sync and non-sync modes.
    """
    global prev_midi_sync_state

    if settings.midi_sync != prev_midi_sync_state: # If sync state just changed, stop all chords
        chord_manager.handle_midi_sync_change()
        prev_midi_sync_state = settings.midi_sync
        return
    
    if settings.midi_sync and clock.is_playing:
        chord_manager.process_chord_on_queue()

    for idx, chord in enumerate(chord_manager.chord_loops):
        if chord == "" or not chord.loop_is_playing:
            continue
        if settings.midi_sync and not chord_manager.play_queue[idx]:
            continue
            
        chord_type = chord.loop_type
        new_chord_notes = chord.get_new_notes()
        if new_chord_notes:
            chordloop_notes_on, chordloop_notes_off, new_cc_events = new_chord_notes
            process_notes(chordloop_notes_on, is_on=True, record=False, chord_idx=idx)
            process_notes(chordloop_notes_off, is_on=False, record=False, chord_idx=idx)
            process_cc_events(new_cc_events, record=False, padchord_idx=idx, chord_type=chord_type)

# -------------------- Main Loop --------------------
chord_manager.initialize()
chord_manager.update_pad_pixels()

while True:
    # Reset 
    timenow = ticks.ticks_ms()
    new_notes_on.clear()
    new_notes_off.clear()
    chord_recording = chord_manager.is_recording

    # 1. Process MIDI Input & Clock updates
    clock.reset_new_tick_flag()
    midi_in_type, midi_in_data = midi.process_messages_in()

    # 1.1 Handle MIDI passthrough
    if midi.should_passthru_midi():
        if midi_in_type == "notes_on":
            process_notes(midi_in_data, is_on=True, record=False)
            pixels.flash_pixel(17, duration=0.2, color=C.PASSTHRU_COLOR) 
            
        elif midi_in_type == "notes_off":
            process_notes(midi_in_data, is_on=False, record=False)
            
        elif midi_in_type == "cc":
            process_cc_events(midi_in_data, record=False)
            pixels.flash_pixel(17, duration=0.2, color=C.PASSTHRU_COLOR)
            
        elif midi_in_type == "start":
            midi.send_start_stop(True)
                
        elif midi_in_type == "stop":
            midi.send_start_stop(False)
    
    # 1.2 Handle incoming MIDI messages
    if midi_in_type in ["notes_on","notes_off"]:
        if midi_in_type == "notes_on":
            pixels.flash_pixel(17, duration=0.2, color=C.NOTE_COLOR)

        if chord_recording:
            record_note_midi_messages(midi_in_data, note_type=midi_in_type)

    if midi_in_type == "cc" and settings.record_cc:
        pixels.flash_pixel(17, duration=0.2, color=C.CC_COLOR)

        if chord_recording:
            record_cc_messages(midi_in_data)

    if midi_in_type == "stop" and settings.midi_sync:
        chord_manager.stop_all_chords()
        chord_manager.handle_fn_press() # Stop recording if active
    
    # 2. Process User Inputs (unless MIDI start received)
    if not midi_in_type == "start":
        
        # 2.1 Slow input processing (navigation, display, notifications)
        if ticks.ticks_diff(timenow, polling_time_prev) > C.NAV_BUTTONS_POLL_S * 1000:
            inputs.process_inputs_slow()

            if display_manager.display_needs_update:
                display_manager.check_show_display()

            if ticks.ticks_diff(timenow, clear_notifications_time_prev) > 1000:
                clear_notifications_time_prev = timenow
                Menu.clear_notifications()

            pixels.process_blinks()
            polling_time_prev = timenow
            useraddons.slow()
            chord_manager.check_event_limits()

        # 2.2 Fast input processing
        inputs.process_inputs_fast()
        new_notes_off.extend(inputs.new_notes_off)
        new_notes_on.extend(inputs.new_notes_on)

    # 4. Process Chord Loop Notes
    process_chord_notes()

    # 5. Process New Notes
    if new_notes_on or new_notes_off:
        process_notes(new_notes_on, is_on=True, record=True)
        process_notes(new_notes_off, is_on=False, record=True)

    # 6. Update Visual Feedback
    if ticks.ticks_diff(timenow, pixel_update_time_prev) > 10:
        pixels.update()
        pixel_update_time_prev = timenow

