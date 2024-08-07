import random
import midi
from utils import next_or_previous_index
from clock import clock
import time

ARP_LENGTHS = ["1", "1/2", "1/4", "1/8", "1/16", "1/32", "1/64"]

class Arpeggiator:
    def __init__(self):
        self.arp_notes = []
        self.prev_arp_notes = []
        self.arp_note_off_queue = []
        self.arp_type = "up"
        self.arp_octave = 1
        self.arp_play_index = 0
        self.arp_length_idx = 2
        self.arp_length = "1/4" # 1, 1/2, 1/4, 1/8, 1/16, 1/32, 1/64,
        self.monophonic = True # If true, cut off previous note when new note is played
        self.last_played_note = () # (note, velocity, padidx)
        self.encoder_turns_per_step = 1 # if 1, new note every click. If 2, every other click, etc.
        self.encoder_step_counter = 0

    def get_arp_notes(self):
        return self.arp_notes

    def get_arp_type(self):
        return self.arp_type

    def get_arp_octave(self):
        return self.arp_octave 
    
    def skip_this_turn(self):
        # Skip encoder steps if needed.
        if self.encoder_turns_per_step > 1:
            self.encoder_step_counter += 1
            if self.encoder_step_counter > self.encoder_turns_per_step:
                self.encoder_step_counter = 1
                return False
            return True
        return False
    
    def get_next_arp_note(self):
        
        idx = self.arp_play_index
        note = ()

        # Reset index if notes have changed
        if self.prev_arp_notes != self.arp_notes:
            self.prev_arp_notes = self.arp_notes
            idx = 0
            self.encoder_step_counter = self.encoder_turns_per_step # So it fires on the first click next time
            note = self.arp_notes[idx]

        if self.arp_type in ["up", "down"]:
            upOrDown = False

            if self.arp_type == "up":
                upOrDown = True

            idx = next_or_previous_index(idx, len(self.arp_notes), upOrDown, True)
            note = self.arp_notes[idx]

        elif self.arp_type == "random":
            idx = random.randint(0, len(self.arp_notes) - 1)
            note = self.arp_notes[idx]

        elif self.arp_type in ["randomoctaveup", "randomoctavedown"]:
            upOrDown = False
            if self.arp_type == "randomoctaveup":
                upOrDown = True
            idx = next_or_previous_index(self.arp_play_index, len(self.arp_notes), upOrDown, True)
            # get random number between -2 and 2
            octave_direction = random.randint(0, 1)

            if random.randint(0, 1) == 0:
                note = self.arp_notes[idx]
            else:
                note = midi.shift_note_one_octave(self.arp_notes[idx], octave_direction)
        
        elif self.arp_type == "peepee":
            pass

        # Add note off to queue. Off queue has format [(note,time)] where note is the regular tuple of (note, velocity, padidx) and time is when to turn it off
        # time is calculated by adding the current time to the length of the note
        note_off_time = time.monotonic() + clock.get_note_time(self.arp_length)
        self.arp_note_off_queue.append((note, note_off_time))
        self.last_played_note = note
        self.arp_play_index = idx
        return note
    
    # Compare current time to each note time in off queue. Return notes in a list that need to be turned off.
    def get_off_notes(self):
        off_notes = []
        for idx, (note, offtime) in enumerate(self.arp_note_off_queue):
            if offtime < time.monotonic():
                off_notes.append(note)
                self.arp_note_off_queue.pop(idx)
        return off_notes


    def get_previous_arp_note(self):
        return self.last_played_note
    
    def get_arp_length(self, seconds=False):
        if seconds:
            return clock.get_note_time(self.arp_length)
        return self.arp_length
    
    def add_arp_note(self, note):
        print(f"adding note {note}")
        self.arp_notes.append(note)
    
    def remove_arp_note(self, note):
        self.arp_notes.remove(note)
    
    def clear_arp_notes(self):
        self.arp_notes = []

    def set_arp_type(self, arp_type):
        self.arp_type = arp_type

    def set_arp_octave(self, arp_octave):
        self.arp_octave = arp_octave
    
    def set_arp_length(self, arp_length):
        valid_lengths = ["1", "1/2", "1/4", "1/8", "1/16", "1/32", "1/64"]
        if arp_length in valid_lengths:
            self.arp_length = arp_length
            return
    
    def set_next_or_previous_arp_length(self, upOrDown):
        idx = ARP_LENGTHS.index(self.arp_length)
        idx = next_or_previous_index(idx, len(ARP_LENGTHS), upOrDown, True)
        self.arp_length = ARP_LENGTHS[idx]

    def has_arp_notes(self):
        return bool(self.arp_notes)


arpeggiator = Arpeggiator()
# # Up / Down / Random / Reverse / poopoo / peepee
# def change_arp_type():
#     pass

# def get_next_arp_note():
#     pass

# def get_previous_arp_note():
#     pass

# # Recalculates based on buttons / notes available
# def update_arp_notes():
#     pass