import random
import midi
from utils import next_or_previous_index

class Arpeggiator:
    def __init__(self):
        self.arp_notes = []
        self.prev_arp_notes = []
        self.arp_type = "up"
        self.arp_octave = 1
        self.arp_play_index = 0

    def get_arp_notes(self):
        return self.arp_notes

    def get_arp_type(self):
        return self.arp_type

    def get_arp_octave(self):
        return self.arp_octave
    
    def get_next_arp_note(self):
        
        idx = self.arp_play_index

        # Reset index if notes have changed
        if self.prev_arp_notes != self.arp_notes:
            self.prev_arp_notes = self.arp_notes
            idx = 0
            return self.arp_notes[idx]

        # Otherwise get next note in sequence
        elif self.arp_type in ["up", "down"]:
            upOrDown = False

            if self.arp_type == "up":
                upOrDown = True

            idx = next_or_previous_index(idx, len(self.arp_notes), upOrDown, True)
            self.arp_play_index = idx
            return self.arp_notes[idx]

        # elif self.arp_type == "down":
        #     idx -= 1
        #     if idx < 0:
        #         idx = len(self.arp_notes) - 1
        #         self.arp_play_index = idx
        #     return self.arp_notes[idx]

        elif self.arp_type == "random":
            idx = random.randint(0, len(self.arp_notes) - 1)
            self.arp_play_index = idx
            return self.arp_notes[idx]

        elif self.arp_type in ["randomoctaveup", "randomoctavedown"]:
            upOrDown = False
            if self.arp_type == "randomoctaveup":
                upOrDown = True
            idx = next_or_previous_index(self.arp_play_index, len(self.arp_notes), upOrDown, True)
            self.arp_play_index = idx
            # get random number between -2 and 2
            octave_direction = random.randint(0, 1)

            if random.randint(0, 1) == 0:
                return self.arp_notes[idx]
            
            note = midi.shift_note_one_octave(self.arp_notes[idx], octave_direction)
            return note
        
        elif self.arp_type == "peepee":
            pass

        # self.arp_play_index = idx
        # return self.arp_notes[idx]

    def get_previous_arp_note(self):
        pass
    
    def add_arp_note(self, note):
        self.arp_notes.append(note)
    
    def remove_arp_note(self, note):
        self.arp_notes.remove(note)
    
    def clear_arp_notes(self):
        self.arp_notes = []
        self.arp_play_index = 0
        self.prev_arp_notes = []

    # def set_arp_notes(self, arp_notes):
    #     self.arp_notes = arp_notes

    def set_arp_type(self, arp_type):
        self.arp_type = arp_type

    def set_arp_octave(self, arp_octave):
        self.arp_octave = arp_octave

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