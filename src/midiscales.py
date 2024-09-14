from collections import OrderedDict
from settings import settings

NUM_PADS = 16

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

midi_to_note = {
    0: 'C0', 1: 'C#0', 2: 'D0', 3: 'D#0', 4: 'E0', 5: 'F0', 6: 'F#0', 7: 'G0', 8: 'G#0', 9: 'A0', 10: 'A#0', 11: 'B0',
    12: 'C1', 13: 'C#1', 14: 'D1', 15: 'D#1', 16: 'E1', 17: 'F1', 18: 'F#1', 19: 'G1', 20: 'G#1', 21: 'A1', 22: 'A#1', 23: 'B1',
    24: 'C2', 25: 'C#2', 26: 'D2', 27: 'D#2', 28: 'E2', 29: 'F2', 30: 'F#2', 31: 'G2', 32: 'G#2', 33: 'A2', 34: 'A#2', 35: 'B2',
    36: 'C3', 37: 'C#3', 38: 'D3', 39: 'D#3', 40: 'E3', 41: 'F3', 42: 'F#3', 43: 'G3', 44: 'G#3', 45: 'A3', 46: 'A#3', 47: 'B3',
    48: 'C4', 49: 'C#4', 50: 'D4', 51: 'D#4', 52: 'E4', 53: 'F4', 54: 'F#4', 55: 'G4', 56: 'G#4', 57: 'A4', 58: 'A#4', 59: 'B4',
    60: 'C5', 61: 'C#5', 62: 'D5', 63: 'D#5', 64: 'E5', 65: 'F5', 66: 'F#5', 67: 'G5', 68: 'G#5', 69: 'A5', 70: 'A#5', 71: 'B5',
    72: 'C6', 73: 'C#6', 74: 'D6', 75: 'D#6', 76: 'E6', 77: 'F6', 78: 'F#6', 79: 'G6', 80: 'G#6', 81: 'A6', 82: 'A#6', 83: 'B6',
    84: 'C7', 85: 'C#7', 86: 'D7', 87: 'D#7', 88: 'E7', 89: 'F7', 90: 'F#7', 91: 'G7', 92: 'G#7', 93: 'A7', 94: 'A#7', 95: 'B7',
    96: 'C8', 97: 'C#8', 98: 'D8', 99: 'D#8', 100: 'E8', 101: 'F8', 102: 'F#8', 103: 'G8', 104: 'G#8', 105: 'A8', 106: 'A#8', 107: 'B8',
    108: 'C9', 109: 'C#9', 110: 'D9', 111: 'D#9', 112: 'E9', 113: 'F9', 114: 'F#9', 115: 'G9', 116: 'G#9', 117: 'A9', 118: 'A#9', 119: 'B9',
    120: 'C10', 121: 'C#10', 122: 'D10', 123: 'D#10', 124: 'E10', 125: 'F10', 126: 'F#10', 127: 'G10',
}

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
    "min": [2, 1, 2, 2, 1,  2,2],
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
    octave = 1  # octave
    midi_notes = []
    cur_note = root

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
            padset = midi_notes[:NUM_PADS-1]
        else:
            st = i * NUM_PADS
            end = st + NUM_PADS
            padset = midi_notes[st:end]

            # Need arrays to be exactly 16. Fix if needed.
            pads_short = 16 - len(padset)
            if pads_short > 0:
                lastnote = padset[-1]
                for i in range(pads_short):
                    padset.append(lastnote)

        midi_notes_pad_mapped.append(padset)

    return midi_notes_pad_mapped

# Structure: all_scales list [("major", [("C", 01234...),
#                                       ("D", 01234...),..]
all_scales_list = []
chromatic_ary = ('chromatic',[('chromatic',midi_banks_chromatic)])
all_scales_list.append(chromatic_ary)

for scale_name, interval in scale_intervals.items():
    interval_ary = []
    for root_name, root in scale_root_notes:
        interval_ary.append((root_name,generate_midi_notes_in_scale(root,interval)))
    all_scales_list.append((scale_name,interval_ary))

# ------------------- Public Functions -------------------

def get_all_scales_list():
    return all_scales_list

def get_midi_banks_chromatic():
    return midi_banks_chromatic

def get_scale_display_text(current_scale_list):
    """
    If the scale bank index is 0, it returns "Scale: Chromatic".
    Otherwise, it constructs the display text using the scale name and root note name.

    Returns:
        disp_text (str or list): The display text for the current scale.
    """

    if settings.SCALE_IDX == 0: #special handling for chromatic
        disp_text = ["     Chromatic",
            "",
            f"        {settings.SCALE_IDX+1}/{NUM_SCALES}"]
    else:
        scale_name = all_scales_list[settings.SCALE_IDX][0]
        root_name = current_scale_list[settings.ROOTNOTE_IDX][0]
        disp_text = [f"     {root_name} {scale_name}",
                    "",
                    f"{settings.ROOTNOTE_IDX+1}/{NUM_ROOTS}           {settings.SCALE_IDX+1}/{NUM_SCALES}"]
    return disp_text


NUM_SCALES = len(all_scales_list)
NUM_ROOTS = len(scale_root_notes)