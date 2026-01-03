import random
import adafruit_ticks as ticks
from utils import next_or_previous_index
from clock import clock
from settings import settings as s
import constants as C

class Arpeggiator:
    """Arpeggiator with pattern types and note scheduling."""
    def __init__(self):
        self.arp_notes = []             # (note, velocity, padidx, midi_channel)
        self.arp_ccs = []               # (cc_num, cc_value, midi_channel)
        self.arp_note_off_queue = []    # List of tuples: (note_tuple, off_time)
        self.arp_play_index = 0
        self.arp_length = s.arpeggiator_length
        self.arp_cc_index = 0
        self.last_played_note = None    # Tuple: (note, velocity, padidx, midi_channel)
        self.last_played_cc = None      # Tuple: (cc_num, cc_value, midi_channel)
        self.arp_direction = s.arpeggiator_type

    def get_arp_notes(self):
        return self.arp_notes

    def get_arp_type(self):
        return self.arp_direction

    def get_next_arp_events(self):
        """Returns (note_tuple, cc_tuple) for next arp step."""
        if not self.arp_notes and not self.arp_ccs:
            return None, None
            
        arp_type = s.arpeggiator_type
        
        # Notes
        note = None
        if self.arp_notes:
            current_idx = self.arp_play_index
            
            # Ensure index is valid (may have been invalidated by note removal)
            if current_idx >= len(self.arp_notes):
                current_idx = 0
                self.arp_play_index = 0

            # Always play the note at current position
            # Format: (note, velocity, padidx, midi_channel)
            note = self.arp_notes[current_idx]
            
            next_idx = current_idx
            if arp_type in ["up", "down"]:
                next_idx = next_or_previous_index(current_idx, len(self.arp_notes), arp_type == "up", True)

            elif arp_type == "random":
                next_idx = random.randint(0, len(self.arp_notes) - 1)

            elif arp_type in ["rand oct up", "rand oct dn"]:
                next_idx = next_or_previous_index(current_idx, len(self.arp_notes), arp_type == "rand oct up", True)
                if random.randint(0, 1) == 1:
                    note = self.shift_note_octave(note, 1 if random.randint(0, 1) == 1 else -1)

            elif arp_type in ["rnd st up", "rnd st dn"]:
                direction = arp_type == "rnd st up"
                next_idx = next_or_previous_index(current_idx, len(self.arp_notes), not direction, True)
                if next_idx == 0:
                    next_idx = random.randint(0, len(self.arp_notes) - 1)

            # Schedule note-off for this note (store full note tuple for channel info)
            note_off_time = ticks.ticks_add(ticks.ticks_ms(), self._get_note_duration_ms())
            self.arp_note_off_queue.append((note, note_off_time))
            self.last_played_note = note
            self.arp_play_index = next_idx

        # CCs
        cc_event = None
        if self.arp_ccs:
            current_cc_idx = self.arp_cc_index
            
            # Ensure index is valid (may have been invalidated by CC removal)
            if current_cc_idx >= len(self.arp_ccs):
                current_cc_idx = 0
                self.arp_cc_index = 0
            
            cc_event = self.arp_ccs[current_cc_idx]

            next_cc_idx = current_cc_idx
            if arp_type in ["up", "down"]:
                next_cc_idx = next_or_previous_index(current_cc_idx, len(self.arp_ccs), arp_type == "up", True)

            elif arp_type == "random":
                next_cc_idx = random.randint(0, len(self.arp_ccs) - 1)

            elif arp_type in ["rand oct up", "rand oct dn"]:
                next_cc_idx = next_or_previous_index(current_cc_idx, len(self.arp_ccs), arp_type == "rand oct up", True)

            elif arp_type in ["randstartup", "randstartdown"]:
                direction = arp_type == "randstartup"
                next_cc_idx = next_or_previous_index(current_cc_idx, len(self.arp_ccs), not direction, True)
                if next_cc_idx == 0:
                    next_cc_idx = random.randint(0, len(self.arp_ccs) - 1)

            self.last_played_cc = cc_event
            self.arp_cc_index = next_cc_idx

        return note, cc_event

    def _get_note_duration_ms(self):
        return int(clock.get_note_duration_seconds(s.arpeggiator_length) * C.MS_PER_SECOND)

    def shift_note_octave(self, note_tuple, num_octaves=1):
        """Shift note by octave(s). Use negative num_octaves to shift down."""
        shift_amt = 12 * num_octaves
        note_val, velocity, pad_idx, midi_channel = note_tuple

        new_note_val = note_val + shift_amt

        if new_note_val < 0 or new_note_val > 127:
            new_note_val = note_val

        return (new_note_val, velocity, pad_idx, midi_channel)
        
    def get_off_notes(self):
        """Returns notes whose duration has expired."""
        current_time = ticks.ticks_ms()
        off_notes = []
        remaining_queue = []
        
        for note, off_time in self.arp_note_off_queue:
            if ticks.ticks_diff(current_time, off_time) >= 0:
                off_notes.append(note)
            else:
                remaining_queue.append((note, off_time))
        
        self.arp_note_off_queue = remaining_queue
        return off_notes

    def get_previous_note(self):
        return self.last_played_note

    def add_arp_note(self, note):
        # Only add if not already present (prevent duplicates)
        if note not in self.arp_notes:
            self.arp_notes.append(note)
        
    def add_arp_cc(self, cc):
        # Only add if not already present (prevent duplicates)
        if cc not in self.arp_ccs:
            self.arp_ccs.append(cc)

    def remove_arp_note(self, note):
        """Remove note from arp, clamp index if needed."""
        try:
            self.arp_notes.remove(note)
            # Clamp play index to valid range after removal
            if len(self.arp_notes) > 0:
                self.arp_play_index = self.arp_play_index % len(self.arp_notes)
            else:
                self.arp_play_index = 0
        except ValueError:
            pass  # Note not in list, ignore
    
    def remove_arp_cc(self, cc):
        """Remove CC from arp, clamp index if needed."""
        try:
            self.arp_ccs.remove(cc)
            # Clamp CC index to valid range after removal
            if len(self.arp_ccs) > 0:
                self.arp_cc_index = self.arp_cc_index % len(self.arp_ccs)
            else:
                self.arp_cc_index = 0
        except ValueError:
            pass  # CC not in list, ignore

    def has_ccs(self):
        return bool(self.arp_ccs)

    def clear_arp_notes(self):
        self.arp_notes = []
        self.arp_ccs = []

    def has_events(self):
        return bool(self.arp_notes) or bool(self.arp_ccs)

arpeggiator = Arpeggiator()
