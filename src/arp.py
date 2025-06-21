import random
import adafruit_ticks as ticks
from midi import midi
from utils import next_or_previous_index
from clock import clock
from settings import settings as s
import constants as C

class Arpeggiator:
    """
    Generates and manages arpeggiated notes and CC events based on configured patterns.
    """
    def __init__(self):
        self.arp_notes = []
        self.arp_ccs = []
        self.prev_arp_ccs = []
        self.prev_arp_notes = []
        self.arp_note_off_queue = []
        self.arp_play_index = 0
        self.arp_length = s.arpeggiator_length
        self.arp_cc_index = 0
        self.last_played_note = None    # Tuple: (note, velocity, padidx)
        self.last_played_cc = None      # Tuple: (CC, value)
        self.encoder_step_counter = 0   # Tracks encoder steps for timing control
        self.arp_direction = s.arpeggiator_type

    def get_arp_notes(self):
        """
        Returns the list of arpeggiated notes currently in the arpeggiator.
        
        Returns:
            list: Arpeggiator notes as (note, velocity, padidx) tuples.
        """
        return self.arp_notes

    def get_arp_type(self):
        """
        Returns the current arpeggiator pattern type.
        """
        return self.arp_direction

    def skip_this_turn(self):
        """
        Determines if the current arpeggiator step should be skipped based on encoder settings.
        
        Returns:
            bool: True if the current step should be skipped, False otherwise.
        """
        encoder_steps = s.encoder_steps_per_arpnote
        if encoder_steps <= 1:
            return False
            
        self.encoder_step_counter = (self.encoder_step_counter % encoder_steps) + 1
        return self.encoder_step_counter != encoder_steps

    def get_next_arp_events(self):
        """
        Returns the next arpeggiated note and CC tuples based on the current pattern type.
        """
        if not self.arp_notes and not self.arp_ccs:
            return None, None
            
        arp_type = s.arpeggiator_type
        
        # Notes
        note = None
        if self.arp_notes:
            current_idx = self.arp_play_index

            # Reset index if pad configuration changed
            if self.prev_arp_notes != self.arp_notes:
                self.prev_arp_notes = self.arp_notes
                current_idx = 0
                self.arp_play_index = 0
                self.encoder_step_counter = s.encoder_steps_per_arpnote

            # Always play the note at current position
            note = self.arp_notes[current_idx]
            
            next_idx = current_idx
            if arp_type in ["up", "down"]:
                next_idx = next_or_previous_index(current_idx, len(self.arp_notes), arp_type == "up", True)

            elif arp_type == "random":
                next_idx = random.randint(0, len(self.arp_notes) - 1)

            elif arp_type in ["rand oct up", "rand oct dn"]:
                next_idx = next_or_previous_index(current_idx, len(self.arp_notes), arp_type == "rand oct up", True)
                if random.randint(0, 1) == 1:
                    note = midi.shift_note_octave(self.arp_notes[current_idx], random.randint(0, 1) == 1)

            elif arp_type in ["rnd st up", "rnd st dn"]:
                direction = arp_type == "rnd st up"
                next_idx = next_or_previous_index(current_idx, len(self.arp_notes), not direction, True)
                if next_idx == 0:
                    next_idx = random.randint(0, len(self.arp_notes) - 1)

            # Schedule note-off for this note
            note_off_time = ticks.ticks_add(ticks.ticks_ms(), self._get_note_duration_ms())
            self.arp_note_off_queue.append((note, note_off_time))
            self.last_played_note = note
            self.arp_play_index = next_idx

        # CCs
        cc_event = None
        if self.arp_ccs:
            current_cc_idx = self.arp_cc_index
            
            # Reset CC index if configuration changed
            if self.prev_arp_ccs != self.arp_ccs:
                self.prev_arp_ccs = self.arp_ccs
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
        """Get the current note duration in milliseconds."""
        return int(clock.get_note_duration_seconds(s.arpeggiator_length) * C.MS_PER_SECOND)
        
    def get_off_notes(self):
        """
        Identifies notes that need to be turned off based on timing.
        """
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
        """
        Returns the last played arpeggiated note tuple.
        """
        return self.last_played_note

    def add_arp_note(self, note):
        """
        Adds a note to the arpeggiator sequence.
        """
        self.arp_notes.append(note)
        
    def add_arp_cc(self, cc):
        """
        Adds a CC event to the arpeggiator sequence.
        """
        self.arp_ccs.append(cc)

    def remove_arp_note(self, note):
        """
        Removes a note from the arpeggiator sequence.
        """
        self.arp_notes.remove(note)

    def has_ccs(self):
        """
        Checks if any CC events are in the arpeggiator.
        """
        return bool(self.arp_ccs)

    def clear_arp_notes(self):
        """
        Clears all notes and CC events from the arpeggiator.
        """
        self.arp_notes = []
        self.arp_ccs = []

    def has_events(self):
        """
        Returns True if there are any notes or CC events in the arpeggiator.
        """
        return bool(self.arp_notes) or bool(self.arp_ccs)

arpeggiator = Arpeggiator()
