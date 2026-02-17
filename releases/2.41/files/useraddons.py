"""
Call your custom code in one of the below hooks. These hooks are called by the main program at specific times.
You can use the fast or slow hooks for general tasks, or the note and CC hooks for handling MIDI events.

Some ideas:
- Send MIDI CC messages to control external devices using your own logic
- Use the note and CC trigger hooks to implement your own MIDI effects (i.e. arpeggiators, chord generators, etc.)
- ...see useraddons_examples.py for specific examples

slow():
    - Less frequent calls for non-urgent tasks.

check_addons_fast():
    - More frequent calls for time-sensitive tasks.

handle_new_notes_on(noteval, velocity, padidx, midi_channel):
    - Triggered when a new note is played.

handle_new_notes_off(noteval, velocity, padidx, midi_channel):
    - Triggered when a note is released.

handle_new_cc(cc_num, cc_val, midi_channel):
    - Triggered when a CC message is sent.
"""

def slow():
    return

def check_addons_fast():
    return

def handle_new_notes_on(noteval, velocity, padidx, midi_channel):
    return

def handle_new_notes_off(noteval, velocity, padidx, midi_channel):
    return

def handle_new_cc(cc_num, cc_val, midi_channel):
    return