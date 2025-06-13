from collections import OrderedDict
from settings import settings
from constants import NUM_PADS

midi_banks_chromatic = [
    [0 + i for i in range(16)],
    [4 + i for i in range(16)],
    [20 + i for i in range(16)],
    [36 + i for i in range(16)],
    [52 + i for i in range(16)],
    [68 + i for i in range(16)],
    [84 + i for i in range(16)],
    [100 + i for i in range(16)],
    [111 + i for i in range(16)]
]

scale_root_notes = [('C', 0),
                    ('Db', 1), 
                    ('D', 2), 
                    ('Eb', 3), 
                    ('E', 4), 
                    ('F', 5), 
                    ('Gb', 6), 
                    ('G', 7),
                    ('Ab', 8), 
                    ('A', 9), 
                    ('Bb', 10), 
                    ('B', 11)]


scale_intervals = OrderedDict({
    "maj": [2, 2, 1, 2, 2, 2, 1],
    "min": [2, 1, 2, 2, 1, 2, 2],
    "harm_min": [2, 1, 2, 2, 1, 3, 1],
    "mel_min": [2, 1, 2, 2, 2, 2, 1],
    "dorian": [2, 1, 2, 2, 2, 1, 2],
    "phrygian": [1, 2, 2, 2, 1, 2, 2],
    "lydian": [2, 2, 2, 1, 2, 2, 1]
})


def generate_midi_notes_in_scale(root, scale_intervals):
    """
    Generate MIDI notes in a given scale.

    Args:
        root (int): The root note of the scale.
        scale_intervals (list): A list of intervals that define the scale.

    Returns:
        list: A list of MIDI notes in the scale, split into 16-pad sets.
    """
    octave = 1  
    midi_notes = []
    cur_note = root
    
    # Add the root note first
    midi_notes.append(root)

    for scale_interval in scale_intervals:
        cur_note = cur_note + scale_interval
        midi_notes.append(cur_note)

    base_notes = midi_notes
    while cur_note < 127:
        for note in base_notes:
            cur_note = note + (12 * octave)
            if cur_note > 127:
                break
            midi_notes.append(cur_note)
        octave = octave + 1

    # Split into 16 pad sets
    midi_notes_pad_mapped = []
    numarys = round(len(midi_notes) / NUM_PADS)  # how many 16 pad banks do we need
    for i in range(numarys):
        if i == 0:
            padset = midi_notes[:NUM_PADS]
        else:
            st = i * NUM_PADS
            end = st + NUM_PADS
            padset = midi_notes[st:end]

            # Need arrays to be exactly 16. Fix if needed.
            pads_short = 16 - len(padset)
            if pads_short > 0:
                lastnote = padset[-1]
                for j in range(pads_short):
                    padset.append(lastnote)

        midi_notes_pad_mapped.append(padset)

    return midi_notes_pad_mapped

# Store scale definitions instead of pre-generated scales for lazy loading
scale_definitions = [
    ("chromatic", None),  # Special case - no intervals needed
]

# Add the scale definitions from scale_intervals
for scale_name, interval in scale_intervals.items():
    scale_definitions.append((scale_name, interval))

def get_scale_notes(scale_idx, root_idx):
    """Generate scale notes on-demand when requested."""
    if scale_idx == 0:  # Chromatic scale
        return midi_banks_chromatic
    
    # Get the scale definition
    scale_name, intervals = scale_definitions[scale_idx]
    root_note = scale_root_notes[root_idx][1]  # Get the MIDI note number
    return generate_midi_notes_in_scale(root_note, intervals)

def get_current_scale_notes():
    """Get the currently selected scale notes."""
    return get_scale_notes(settings.scale_idx, settings.rootnote_idx)

def get_scale_display_text():
    """
    Return the display text for the current scale.
    
    If the scale bank index is 0, returns chromatic scale display.
    Otherwise, constructs display text using the scale name and root note name.

    Returns:
        list: A list of strings for multi-line display text.
    """

    if settings.scale_idx == 0:  # special handling for chromatic
        disp_text = ["     Chromatic",
                     "",
                     f"        {settings.scale_idx+1}/{NUM_SCALES}"]
    else:
        scale_name = scale_definitions[settings.scale_idx][0]
        root_name = scale_root_notes[settings.rootnote_idx][0]
        disp_text = [f"     {root_name} {scale_name}",
                     "",
                     f"{settings.rootnote_idx+1}/{NUM_ROOTS}           {settings.scale_idx+1}/{NUM_SCALES}"]
    return disp_text

def get_midi_banks_chromatic():
    """Return the chromatic MIDI banks."""
    return midi_banks_chromatic

NUM_SCALES = len(scale_definitions)
NUM_ROOTS = len(scale_root_notes)