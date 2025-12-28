# Standard library imports
import adafruit_ticks as ticks
import constants as C
from settings import settings as s
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

import gc
gc.collect()

# Global timing variables
polling_time_prev = ticks.ticks_ms()
fast_polling_time_prev = ticks.ticks_ms()
pixel_update_time_prev = ticks.ticks_ms()
clear_notifications_time_prev = ticks.ticks_ms()

# State tracking
new_notes_on = []
new_notes_off = []

prev_midi_sync_state = s.midi_sync
# -------------------- MIDI Event Handlers --------------------

def record_note_midi_messages(messages, note_type):
    """Record incoming MIDI note messages to active chord."""
    for msg in messages:
        if not msg or len(msg) < 4:
            continue
        
        # Handle both old format (4 elements) and new format (5 elements with channel)
        if len(msg) >= 5:
            note_val, velocity, padidx, _, midi_channel = msg
        else:
            note_val, velocity, padidx, _ = msg
            midi_channel = 0  # Default channel for legacy data

        if chord_manager.is_recording:
            padidx = chord_manager.recording_pad
        
        if note_type == "notes_on":
            record_midi_event(note_val, velocity, padidx, True, midi_channel)
        else:
            record_midi_event(note_val, velocity, padidx, False, midi_channel)

def record_cc_messages(message_data):
    """Record incoming MIDI CC messages to active chord."""
    if not chord_manager.is_recording:
        return

    for msg in message_data:
        try:
            cc_val, cc_value, midi_channel = msg
        except (TypeError, ValueError):
            continue
        
        if cc_val == 123 and cc_value == 0 and s.midi_sync:
            chord_manager.handle_fn_press()  # Special case for CC 123 (All Notes Off)

        if chord_manager.is_recording and not chord_manager.recording_is_armed:
            chord_manager.chord_loops[chord_manager.recording_pad].add_cc(cc_val, cc_value, midi_channel)

def record_aftertouch_messages(message_data):
    """Record incoming channel pressure (aftertouch) messages to active chord."""
    if not chord_manager.is_recording:
        return

    for msg in message_data:
        try:
            # Channel pressure: (pressure, channel). For polyphonic: (note, pressure, channel)
            pressure, midi_channel = msg
        except (TypeError, ValueError):
            continue
        
        if chord_manager.is_recording and not chord_manager.recording_is_armed:
            chord_manager.chord_loops[chord_manager.recording_pad].add_aftertouch(pressure, midi_channel)

def record_midi_event(note_val, velocity, padidx, is_on, midi_channel=0):
    """Record a note event to the active chord if recording."""
    if chord_manager.is_recording and not chord_manager.recording_is_armed:
        chord_manager.chord_loops[chord_manager.recording_pad].add_note(note_val, velocity, padidx, is_on, midi_channel=midi_channel)

# -------------------- Event Processing --------------------

def process_notes(notes, is_on, record=True, playback_pad_idx=None):
    """Send MIDI notes, update pixels, optionally record. playback_pad_idx for loop playback channel routing."""
    if not notes:
        return

    for note in notes:
        note_val, velocity, padidx, stored_channel = note
        
        # get midi channel
        if s.midi_channel_mode == "per_note":
            if stored_channel is not None and 0 <= stored_channel <= 15:
                output_channel = stored_channel
            else:
                output_channel = None  # Fall back to global channel
        elif s.midi_channel_mode == "per_pad":
            output_channel = playback_pad_idx if playback_pad_idx is not None else padidx
        else:
            # Global mode - use None to trigger global channel
            output_channel = None
        
        if is_on:
            midi.send_note_on(note_val, velocity, output_channel)
            pixels.set_note_on(padidx, velocity)
            useraddons.handle_new_notes_on(note_val, velocity, padidx)
        else:
            midi.send_note_off(note_val, output_channel)
            pixels.set_note_off(padidx)
            useraddons.handle_new_notes_off(note_val, velocity, padidx)
        if record:
            # For recording, use stored channel if valid, otherwise use current global output channel
            if stored_channel is not None and 0 <= stored_channel <= 15:
                midi_channel = stored_channel
            else:
                midi_channel = s.midi_channel_out
            record_midi_event(note_val, velocity, padidx, is_on, midi_channel)

def process_cc_events(cc_events, record=True, padchord_idx=C.DEFAULT_CHORDPAD_IDX, chord_type=None):
    """Send MIDI CCs, update pixels, optionally record. chord_type determines pixel flash duration."""
    if not cc_events:
        return
    
    # Check if this is from a oneshot loop
    is_oneshot_mode = chord_type == "oneshot"
    
    for cc_event in cc_events:
        cc_val, cc_value, stored_channel = cc_event
        
        # Determine channel routing based on mode (same delegation pattern as notes)
        # stored_channel contains the recorded MIDI channel from loop playback
        # padchord_idx is the pad playing the loop (used for per-pad mode)
        if s.midi_channel_mode == "per_note":
            # Use the stored channel from recording
            output_channel = stored_channel
        elif s.midi_channel_mode == "per_pad":
            # Use pad index, let set_active_output_midi_channel resolve to pad's channel
            output_channel = padchord_idx
        else:
            # Global mode - use None to trigger global channel
            output_channel = None
        
        midi.send_cc(cc_val, cc_value, output_channel)
        useraddons.handle_new_cc(cc_val, cc_value, output_channel if output_channel is not None else s.midi_channel_out)
        
        if padchord_idx is not None and padchord_idx != C.DEFAULT_CHORDPAD_IDX:
            if is_oneshot_mode:
                pixels.flash_pixel(padchord_idx, duration=0.1, color=C.CC_COLOR)
            else:
                pixels.flash_pixel(padchord_idx, duration=0.2, color=C.CC_COLOR)
        else: 
            if is_oneshot_mode:
                pixels.flash_pixel(C.ENC_LED_IDX, duration=0.1, color=C.CC_COLOR)
            else:
                pixels.flash_pixel(C.ENC_LED_IDX, duration=0.2, color=C.CC_COLOR)
        
        if record and chord_manager.is_recording:
            chord_manager.chord_loops[chord_manager.recording_pad].add_cc(cc_val, cc_value, stored_channel)

def process_aftertouch_events(at_events, padchord_idx=C.DEFAULT_CHORDPAD_IDX):
    """Send channel pressure (aftertouch) events during playback."""
    if not at_events:
        return
    
    for at_event in at_events:
        # Storage uses 3-tuple (cc_num=0, pressure, channel) for compat with CC format
        # For polyphonic: cc_num would be note number
        _, pressure, stored_channel = at_event
        
        # Determine channel routing based on mode (same pattern as CC)
        if s.midi_channel_mode == "per_note":
            output_channel = stored_channel
        elif s.midi_channel_mode == "per_pad":
            output_channel = padchord_idx
        else:
            output_channel = None
        
        midi.send_aftertouch(pressure, output_channel)
        
        # Visual feedback - same as CC (continuous controller)
        if padchord_idx is not None and padchord_idx != C.DEFAULT_CHORDPAD_IDX:
            pixels.flash_pixel(padchord_idx, duration=0.2, color=C.CC_COLOR)
        else:
            pixels.flash_pixel(C.ENC_LED_IDX, duration=0.2, color=C.CC_COLOR)

def process_chord_notes():
    global prev_midi_sync_state

    if s.midi_sync != prev_midi_sync_state: # If sync state just changed, stop all chords
        chord_manager.handle_midi_sync_change()
        prev_midi_sync_state = s.midi_sync
        return
    
    if s.midi_sync and clock.is_playing:
        chord_manager.process_chord_on_queue()

    for idx, chord in enumerate(chord_manager.chord_loops):
        if chord == "" or not chord.loop_is_playing:
            continue
        if s.midi_sync and not chord_manager.play_queue[idx]:
            continue
            
        chord_type = chord.loop_type
        new_chord_notes = chord.get_new_events()
        if new_chord_notes:
            chordloop_notes_on, chordloop_notes_off, new_cc_events, new_at_events = new_chord_notes
            process_notes(chordloop_notes_on, is_on=True, record=False, playback_pad_idx=idx)
            process_notes(chordloop_notes_off, is_on=False, record=False, playback_pad_idx=idx)
            process_cc_events(new_cc_events, record=False, padchord_idx=idx, chord_type=chord_type)
            process_aftertouch_events(new_at_events, padchord_idx=idx)

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
    midi_notes_on, midi_notes_off, midi_cc, midi_at, midi_transport = midi.process_messages_in()

    # 1.1 Handle MIDI passthrough visual feedback
    if midi.should_passthru_midi():
        if midi_notes_on or midi_cc or midi_at:
            pixels.flash_pixel(C.ENC_LED_IDX, duration=0.2, color=C.PASSTHRU_COLOR)
    
    # 1.2 Handle incoming MIDI messages - show activity regardless of passthru mode
    if midi_notes_on:
        pixels.flash_pixel(C.ENC_LED_IDX, duration=0.2, color=C.NOTE_COLOR)
        if chord_recording:
            record_note_midi_messages(midi_notes_on, note_type="notes_on")
    
    if midi_notes_off:
        if chord_recording:
            record_note_midi_messages(midi_notes_off, note_type="notes_off")

    if midi_cc and s.record_cc:
        pixels.flash_pixel(C.ENC_LED_IDX, duration=0.2, color=C.CC_COLOR)
        if chord_recording:
            record_cc_messages(midi_cc)

    # Aftertouch recording - always enabled (pressure data is integral to performance)
    if midi_at:
        pixels.flash_pixel(C.ENC_LED_IDX, duration=0.2, color=C.CC_COLOR)
        if chord_recording:
            record_aftertouch_messages(midi_at)

    if midi_transport == "stop" and s.midi_sync:
        chord_manager.stop_all_chords()
        # Only stop recording if actively recording, not just armed/waiting
        if chord_manager.is_recording and not chord_manager.recording_is_armed:
            chord_manager.handle_fn_press()
    
    # 2. Process User Inputs (unless MIDI start received)
    if midi_transport != "start":
        
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
        useraddons.check_addons_fast()
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

