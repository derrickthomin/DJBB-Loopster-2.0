import random
import adafruit_ticks as ticks
from midi import midi
from utils import next_or_previous_index
from clock import clock
from settings import settings as s
import constants
from debug import print_debug

class Arpeggiator:
    """
    The Arpeggiator class represents an arpeggiator object that can generate and manipulate arpeggiated notes.

    Attributes:
        arp_notes (list): The list of arpeggiated notes.
        prev_arp_notes (list): The previous list of arpeggiated notes.
        arp_note_off_queue (list): The queue of arpeggiated notes to be turned off.
        arp_octave (int): The octave of the arpeggiator.
        arp_play_index (int): The index of the currently playing arpeggiated note.
        arp_prev_play_index (int): The index of the previously played arpeggiated note.
        arp_length (str): The length of the arpeggiator notes.
        last_played_note (tuple): The last played arpeggiated note.
        encoder_step_counter (int): The counter for encoder steps.
        arp_direction (str): The type of arpeggiator.

    Methods:
        get_arp_notes(): Returns the list of arpeggiated notes.
        get_arp_type(): Returns the type of arpeggiator.
        get_arp_octave(): Returns the octave of the arpeggiator.
        skip_this_turn(): Checks if encoder steps should be skipped.
        get_next_arp_events(): Returns the next arpeggiated note.
        get_off_notes(): Returns the arpeggiated notes that need to be turned off.
        get_previous_note(): Returns the last played arpeggiated note.
        get_arp_length(seconds=False): Returns the length of the arpeggiator notes.
        add_arp_note(): Adds an arpeggiated note to the list.
        remove_arp_note(): Removes an arpeggiated note from the list.
        clear_arp_notes(): Clears the list of arpeggiated notes.
        set_arp_type(): Sets the type of arpeggiator.
        set_arp_octave(): Sets the octave of the arpeggiator.
        set_arp_length(): Sets the length of the arpeggiator notes.
        has_events(): Checks if the arpeggiator has any notes.
    """

    def __init__(self, arp_direction="up", arp_length="1/8"):
        self.arp_notes = []
        self.arp_ccs = []

        self.prev_arp_ccs = []
        self.prev_arp_notes = []

        self.arp_note_off_queue = []
        self.arp_octave = 1

        self.arp_play_index = 0
        self.arp_prev_play_index = 0
        self.arp_length = arp_length

        self.arp_cc_index = 0
        self.arp_prev_cc_index = 0

        self.last_played_note = None   # Tuple: (note, velocity, padidx)
        self.last_played_cc = None     # Tuple: (CC, Val)
        
        self.encoder_step_counter = 0  # Tracks how many encoder steps have been skipped
        self.arp_direction = arp_direction

    def get_arp_notes(self):
        """
        Returns all arp notes.

        Returns:
            list: The list of arp notes: [(note, velocity, padidx),...]
        """
        return self.arp_notes

    def get_arp_type(self):
        """
        Returns the ARP type.

        Returns:
            str: The ARP type.
        """
        return self.arp_direction

    def skip_this_turn(self):
        """
        Checks if encoder steps should be skipped based on the ENCODER_STEPS setting.

        Returns:
            bool: True if encoder steps should be skipped, False otherwise.
        """
        encoder_steps = s.encoder_steps_per_arpnote

        if encoder_steps > 1:
            self.encoder_step_counter += 1
            if self.encoder_step_counter > encoder_steps:
                self.encoder_step_counter = 1
                return False
            return True

        return False

    def get_next_arp_events(self):
        """
        Returns the next arpeggiated note and CC value based on the arpeggiator type.
        
        Returns:
            tuple: A tuple containing (note, cc_event) where:
                   - note: The next arpeggiated note, or None if no notes are available
                   - cc_event: The next CC event (cc_num, cc_value), or None if no CCs are available
        """
        if not self.arp_notes and not self.arp_ccs:
            return None

        # Get next note (if available)
        note = None
        if self.arp_notes:
            idx = self.arp_play_index

            # Reset index if notes have changed
            if self.prev_arp_notes != self.arp_notes:
                self.prev_arp_notes = self.arp_notes  # Use copy to ensure comparison works correctly
                idx = 0
                self.encoder_step_counter = s.encoder_steps_per_arpnote  # So it fires on the first click next time

            note = self.arp_notes[idx]

            # Handle different arpeggiator types
            arp_type = s.arpeggiator_type
            if arp_type in ["up", "down"]:
                idx = next_or_previous_index(idx, len(self.arp_notes), arp_type == "up", True)
                note = self.arp_notes[idx]
            elif arp_type == "random":
                idx = random.randint(0, len(self.arp_notes) - 1)
                note = self.arp_notes[idx]
            elif arp_type in ["rand oct up", "rand oct dn"]:
                idx = next_or_previous_index(self.arp_play_index, len(self.arp_notes), arp_type == "rand oct up", True)
                if random.choice([True, False]):
                    note = midi.shift_note_octave(self.arp_notes[idx], random.choice([True, False]))
                else:
                    note = self.arp_notes[idx]
            elif arp_type in ["randstartup", "randstartdown"]:
                direction = arp_type == "randstartup"
                idx = next_or_previous_index(idx, len(self.arp_notes), not direction, True)
                if idx == 0:
                    idx = random.randint(0, len(self.arp_notes) - 1)
                note = self.arp_notes[idx]

            # Schedule note-off for this note
            note_off_time = ticks.ticks_add(ticks.ticks_ms(), int(clock.get_note_duration_seconds(self.arp_length) * 1000))
            self.arp_note_off_queue.append((note, note_off_time))
            self.last_played_note = note
            self.arp_prev_play_index = self.arp_play_index
            self.arp_play_index = idx

        # Get next CC (if available)
        cc_event = None
        if self.arp_ccs:
            cc_idx = self.arp_cc_index
            
            # Reset index if CCs have changed
            if self.prev_arp_ccs != self.arp_ccs:
                self.prev_arp_ccs = self.arp_ccs  # Use copy to ensure comparison works correctly
                cc_idx = 0
            
            cc_event = self.arp_ccs[cc_idx]
            
            # Apply the same arpeggiator type pattern to CC selection
            arp_type = s.arpeggiator_type
            if arp_type in ["up", "down"]:
                cc_idx = next_or_previous_index(cc_idx, len(self.arp_ccs), arp_type == "up", True)
                cc_event = self.arp_ccs[cc_idx]
            elif arp_type == "random":
                cc_idx = random.randint(0, len(self.arp_ccs) - 1)
                cc_event = self.arp_ccs[cc_idx]
            elif arp_type in ["randstartup", "randstartdown"]:
                direction = arp_type == "randstartup"
                cc_idx = next_or_previous_index(cc_idx, len(self.arp_ccs), not direction, True)
                if cc_idx == 0:
                    cc_idx = random.randint(0, len(self.arp_ccs) - 1)
                cc_event = self.arp_ccs[cc_idx]
            
            # Store the last played CC and update indices
            self.last_played_cc = cc_event
            self.arp_prev_cc_index = self.arp_cc_index
            self.arp_cc_index = cc_idx

        # Return both note and CC event
        return (note, cc_event)

    def get_off_notes(self):
        """
        Compares the current time to each note time in the off queue and returns the notes that need to be turned off.

        Returns:
            list: The arpeggiated notes that need to be turned off.
        """
        current_time = ticks.ticks_ms()
        off_notes = [note for note, offtime in self.arp_note_off_queue if ticks.ticks_diff(current_time, offtime) >= 0]
        self.arp_note_off_queue = [item for item in self.arp_note_off_queue if ticks.ticks_diff(current_time, item[1]) < 0]
        return off_notes

    def get_previous_note(self):
        """
        Returns the last played arpeggiated note.

        Returns:
            tuple: The last played arpeggiated note.
        """
        print_debug(f"arp_prev_play_index: {self.arp_prev_play_index} note {self.last_played_note}")
        return self.last_played_note

    def get_arp_length(self, seconds=False):
        """
        Returns the length of the arpeggiator notes.

        Args:
            seconds (bool, optional): Whether to return the length in seconds. Defaults to False.

        Returns:
            str or float: The length of the arpeggiator notes.
        """
        if seconds:
            return clock.get_note_duration_seconds(self.arp_length)
        return self.arp_length

    def add_arp_note(self, note):
        """
        Adds an arpeggiated note to the list.

        Args:
            note (tuple): The arpeggiated note to add.
        """
        self.arp_notes.append(note)

    def add_arp_cc(self,cc):
        self.arp_ccs.append(cc)

    def remove_arp_note(self, note):
        """
        Removes an arpeggiated note from the list.

        Args:
            note (tuple): The arpeggiated note to remove.
        """
        self.arp_notes.remove(note)

    def has_ccs(self):
        """
        Checks if the arpeggiator has any CC values.

        Returns:
            bool: True if the arpeggiator has CC values, False otherwise.
        """
        return bool(self.arp_ccs)

    def clear_arp_notes(self):
        """
        Clears the list of arpeggiated notes and CC values.
        """
        self.arp_notes = []
        self.arp_ccs = []

    def set_arp_type(self, arp_direction):
        """
        Sets the type of arpeggiator.

        Args:
            arp_direction (str): The type of arpeggiator.
        """
        s.arpeggiator_type = arp_direction

    def set_arp_octave(self, arp_octave):
        """
        Sets the octave of the arpeggiator.

        Args:
            arp_octave (int): The octave of the arpeggiator.
        """
        self.arp_octave = arp_octave

    def set_arp_length(self, arp_length):
        """
        Sets the length of the arpeggiator notes.

        Args:
            arp_length (str): The length of the arpeggiator notes.
        """
        if arp_length in constants.VALID_ARP_LENGTHS:
            self.arp_length = arp_length

    def has_events(self):
        """
        Checks if the arpeggiator has any notes.

        Returns:
            bool: True if the arpeggiator has notes, False otherwise.
        """
        return bool(self.arp_notes) or bool(self.arp_ccs)

# Instantiate the arpeggiator with settings
arpeggiator = Arpeggiator(arp_direction=s.arpeggiator_type, arp_length=s.arpeggiator_length)
