import random
import ticks_minimal as ticks
from clock import clock
from settings import settings as s
import constants as C

def unpack_pad_channel(packed):
    """Unpack pad index and MIDI channel from single byte."""
    pad_idx = packed & 0x0F
    midi_channel = (packed >> 4) & 0x0F
    return pad_idx, midi_channel

class Arpeggiator:
    """Reference-based arpeggiator - stores pad indices, reads notes on demand."""
    def __init__(self):
        # Ordered list of held pads (press order preserved)
        self.held_pads = []         # [3, 7, 2] = pad 3 pressed first, then 7, then 2
        
        # Track note/CC counts per pad for flat index calculation
        self.note_counts = {}       # {pad_idx: note_count}
        self.cc_counts = {}         # {pad_idx: cc_count}
        
        # Totals for flat index math
        self.total_notes = 0
        self.total_ccs = 0
        
        # Flat index across all pads
        self.note_play_index = 0
        self.cc_play_index = 0
        self._last_forward = True  # Track direction for seamless reversal
        
        # Note-off scheduling
        self.arp_note_off_queue = []    # List of tuples: (note_tuple, off_time)
        
        # Last played for monophonic mode
        self.last_played_note = None
        self.last_played_cc = None
        
        # Cached references (set on first use)
        self._loop_manager = None
        self._midi = None

    def _get_loop_manager(self):
        """Lazy import to avoid circular dependency."""
        if self._loop_manager is None:
            from loopmanager import loop_manager
            self._loop_manager = loop_manager
        return self._loop_manager

    def _get_midi(self):
        """Lazy import to avoid circular dependency."""
        if self._midi is None:
            from midi import midi
            self._midi = midi
        return self._midi

    def add_source(self, pad_idx):
        """Add pad to arp in press order. O(1) memory."""
        if pad_idx in self.held_pads:
            return
        
        loop_manager = self._get_loop_manager()
        loop = loop_manager.loops[pad_idx]
        
        if loop:
            note_count = len(loop.notes_on)
            cc_count = len(loop.cached_unique_ccs) if loop.cached_unique_ccs else 0
        else:
            note_count = 1  # Single pad note
            cc_count = 0
        
        self.held_pads.append(pad_idx)
        self.note_counts[pad_idx] = note_count
        self.cc_counts[pad_idx] = cc_count
        self.total_notes += note_count
        self.total_ccs += cc_count

    def remove_source(self, pad_idx):
        """Remove pad from arp."""
        if pad_idx not in self.held_pads:
            return
        
        self.total_notes -= self.note_counts.get(pad_idx, 0)
        self.total_ccs -= self.cc_counts.get(pad_idx, 0)
        self.held_pads.remove(pad_idx)
        self.note_counts.pop(pad_idx, None)
        self.cc_counts.pop(pad_idx, None)
        
        # Clamp indices to valid range
        if self.total_notes > 0:
            self.note_play_index %= self.total_notes
        else:
            self.note_play_index = 0
        if self.total_ccs > 0:
            self.cc_play_index %= self.total_ccs
        else:
            self.cc_play_index = 0

    def flush_playing_notes(self):
        """Return all currently-playing notes for immediate note-off. Clears the queue."""
        notes_to_off = [note_tuple for note_tuple, _ in self.arp_note_off_queue]
        self.arp_note_off_queue.clear()
        return notes_to_off

    def _get_note_at_index(self, flat_idx):
        """Get note at flat index across all held pads (pad-press order)."""
        running_count = 0
        loop_manager = self._get_loop_manager()
        
        for pad_idx in self.held_pads:
            pad_note_count = self.note_counts.get(pad_idx, 0)
            
            if flat_idx < running_count + pad_note_count:
                local_idx = flat_idx - running_count
                return self._read_note(pad_idx, local_idx, loop_manager)
            
            running_count += pad_note_count
        
        return None

    def _read_note(self, pad_idx, local_idx, loop_manager):
        """Read note directly from pad's source (no copy)."""
        midi = self._get_midi()
        loop = loop_manager.loops[pad_idx]
        
        if loop and local_idx < len(loop.notes_on):
            note = loop.notes_on.notes[local_idx]
            vel = loop.notes_on.velocities[local_idx]
            _, recorded_ch = unpack_pad_channel(loop.notes_on.packed_pad_channel[local_idx])
            
            # Use pad's channel setting with recorded channel
            midi_ch = midi.get_midi_channel_for_pad(pad_idx, recorded_ch)
            
            return (note, vel, pad_idx, midi_ch)
        else:
            # No loop - return pad's default note with pad's channel setting
            note = midi.get_midi_note_by_idx(pad_idx)
            vel = midi.get_velocity_by_idx(pad_idx)
            midi_ch = midi.get_midi_channel_for_pad(pad_idx)  # No recorded channel
            return (note, vel, pad_idx, midi_ch)

    def _get_cc_at_index(self, flat_idx):
        """Get CC at flat index across all held pads."""
        running_count = 0
        loop_manager = self._get_loop_manager()
        midi = self._get_midi()
        
        for pad_idx in self.held_pads:
            loop = loop_manager.loops[pad_idx]
            if not loop or not loop.cached_unique_ccs:
                continue
            
            pad_cc_count = len(loop.cached_unique_ccs)
            
            if flat_idx < running_count + pad_cc_count:
                local_idx = flat_idx - running_count
                cc_tuple = loop.cached_unique_ccs[local_idx]
                
                # Use pad's channel setting with recorded channel (cc_tuple[2])
                output_ch = midi.get_midi_channel_for_pad(pad_idx, cc_tuple[2])
                return (cc_tuple[0], cc_tuple[1], output_ch)
            
            running_count += pad_cc_count
        
        return None

    def get_next_arp_events(self, forward=True):
        """Returns (note_tuple, cc_tuple) for arp step.
        
        Args:
            forward: True = advance through sequence, False = step backward (polyphonic only)
        """
        if self.total_notes == 0 and self.total_ccs == 0:
            return None, None
        
        arp_type = s.arpeggiator_type
        note = None
        cc_event = None
        
        # === NOTES ===
        if self.total_notes > 0:
            # Handle direction changes to avoid repeating notes
            if not forward:
                # Backward: step back first (extra step if switching from forward)
                steps_back = 2 if self._last_forward else 1
                self.note_play_index = (self.note_play_index - steps_back) % self.total_notes
            elif not self._last_forward:
                # Switching from backward to forward: skip the just-played note
                self.note_play_index = (self.note_play_index + 1) % self.total_notes
            
            current_idx = self.note_play_index
            note = self._get_note_at_index(current_idx)
            
            # Only advance index for forward movement
            if forward:
                # Calculate next index based on arp mode
                if arp_type in ["up", "down"]:
                    step = 1 if arp_type == "up" else -1
                    next_idx = (current_idx + step) % self.total_notes
                
                elif arp_type == "random":
                    next_idx = random.randint(0, self.total_notes - 1)
                
                elif arp_type in ["rand oct up", "rand oct dn"]:
                    step = 1 if "up" in arp_type else -1
                    next_idx = (current_idx + step) % self.total_notes
                    if random.randint(0, 1) == 1 and note:
                        note = self.shift_note_octave(note, 1 if random.randint(0, 1) == 1 else -1)
                
                elif arp_type in ["rnd st up", "rnd st dn"]:
                    direction = "up" in arp_type
                    next_idx = (current_idx + (1 if direction else -1)) % self.total_notes
                    if next_idx == 0:
                        next_idx = random.randint(0, self.total_notes - 1)
                
                else:
                    next_idx = (current_idx + 1) % self.total_notes
                
                self.note_play_index = next_idx
            
            # Schedule note-off
            if note:
                note_off_time = ticks.ticks_add(ticks.ticks_ms(), self._get_note_duration_ms())
                self.arp_note_off_queue.append((note, note_off_time))
                self.last_played_note = note
        
        # === CCs ===
        if self.total_ccs > 0:
            # Handle direction changes to avoid repeating CCs
            if not forward:
                # Backward: step back first (extra step if switching from forward)
                steps_back = 2 if self._last_forward else 1
                self.cc_play_index = (self.cc_play_index - steps_back) % self.total_ccs
            elif not self._last_forward:
                # Switching from backward to forward: skip the just-played CC
                self.cc_play_index = (self.cc_play_index + 1) % self.total_ccs
            
            cc_event = self._get_cc_at_index(self.cc_play_index)
            
            # Only advance for forward movement
            if forward:
                self.cc_play_index = (self.cc_play_index + 1) % self.total_ccs
            
            self.last_played_cc = cc_event
        
        self._last_forward = forward
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

    def has_ccs(self):
        return self.total_ccs > 0

    def clear_arp_notes(self):
        """Clear all sources and reset state."""
        self.held_pads.clear()
        self.note_counts.clear()
        self.cc_counts.clear()
        self.total_notes = 0
        self.total_ccs = 0
        self.note_play_index = 0
        self.cc_play_index = 0
        self._last_forward = True
        self.arp_note_off_queue.clear()

    def has_events(self):
        return self.total_notes > 0 or self.total_ccs > 0

arpeggiator = Arpeggiator()
