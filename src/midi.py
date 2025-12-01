import busio
import usb_midi

import adafruit_midi
from adafruit_midi.control_change import ControlChange
from adafruit_midi.note_off import NoteOff
from adafruit_midi.note_on import NoteOn
from adafruit_midi.pitch_bend import PitchBend
from adafruit_midi.start import Start
from adafruit_midi.stop import Stop
from adafruit_midi.timing_clock import TimingClock
from adafruit_midi.midi_continue import Continue

import constants as C

# Local module imports
from clock import clock
from display import display
from midiscales import (
    get_scale_notes,
    get_scale_display_text,
    get_midi_banks_chromatic,
    NUM_ROOTS,
    NUM_SCALES,
)
from pixels import pixels
from settings import settings as s
from utils import next_or_previous_index

uart = busio.UART(C.UART_MIDI_TX, C.UART_MIDI_RX, baudrate=31250,timeout=0.001)

uart_midi = adafruit_midi.MIDI(
    midi_in=uart,
    midi_out=uart,
    in_channel=None,
    out_channel=s.midi_channel_out,
    debug=False,)

usb_midi = adafruit_midi.MIDI(
    midi_in=usb_midi.ports[0],
    midi_out=usb_midi.ports[1],
    in_channel=None if s.midi_channel_in == -1 else s.midi_channel_in,
    out_channel=s.midi_channel_out,
    debug=False)

class Midi:
    """MIDI I/O and scale/bank management."""
    def __init__(self, usb_midi_port=None, uart_midi_port=None):
        self.usb_port = usb_midi_port
        self.uart_port = uart_midi_port

        self.current_midibank_set = get_midi_banks_chromatic()
        self.midi_velocities = [s.default_velocity] * 16
        self.current_assignment_velocity = 120
        self.current_assignment_channel = None

        self.full_scale_notes = []       
        self.bank_window_start = 0       
        self.pad_group_offset = 0

        self.clock_source = None
        
    def get_current_scale_display_text(self):
        """Returns display text for current scale."""
        return get_scale_display_text()
    
    def get_midi_bank_idx(self):
        return s.midibank_idx

    def get_scale_bank_idx(self):
        return s.scale_idx

    def get_scale_notes_idx(self):
        return s.scalenotes_idx

    def update_global_velocity(self,new_velocity):
        self.current_assignment_velocity = new_velocity

    def get_current_assignment_velocity(self):
        return self.current_assignment_velocity

    def get_velocity_by_idx(self,idx):
        return self.midi_velocities[idx]

    def set_all_midi_velocities(self, value, check_default=True):
        
        for i in range(16):
            if check_default:
                if self.midi_velocities[i] == s.default_velocity:
                    self.midi_velocities[i] = value
            else:
                self.midi_velocities[i] = value

    def set_midi_velocity_by_idx(self, idx, vel):
        if not (0 <= idx < 16):
            raise ValueError(f"Pad index {idx} out of range (0-15)")
        
        if not (0 <= vel <= 127):
            raise ValueError(f"MIDI velocity {vel} out of range (0-127)")
        
        self.midi_velocities[idx] = vel
        pixels.set_note_on(idx, vel)

    def shift_note_octave(self, note, up_or_down=True, num_octaves=1):
        """Shift note by octave(s)."""
        shift_amt = 12 * num_octaves
        note_val, velocity, pad_idx, chordpad_idx = note

        if up_or_down:
            new_note_val = note_val + shift_amt
        else:
            new_note_val = note_val - shift_amt

        if new_note_val < 0 or new_note_val > 127:
            new_note_val = note_val

        return (new_note_val, velocity, pad_idx, chordpad_idx)

    def current_notes(self):
        """Return current 16 MIDI notes."""
        notes = []
        for i in range(C.NUM_PADS):
            notes.append(self.get_midi_note_by_idx(i))
        return notes
    
    def get_midi_note_by_idx(self, idx):
        """Return MIDI note for pad index."""
        if not (0 <= idx < C.NUM_PADS):
            raise ValueError(f"Pad index {idx} out of range (0-{C.NUM_PADS-1})")
        
        if not self.full_scale_notes:
            raise RuntimeError("MIDI scale not initialized - call setup() first")
        
        base = self.bank_window_start + self.pad_group_offset + idx
        abs_idx = min(max(base, 0), len(self.full_scale_notes) - 1)
        return self.full_scale_notes[abs_idx]

    def set_midi_note_by_idx(self,idx, value):
        s.midi_notes_default[idx] = value

    def get_velocity_singlenote_by_idx(self, idx):
        return C.DEFAULT_SINGLENOTE_MODE_VELOCITIES[idx]
    
    def send_note_on(self, note, velocity, channel_or_pad_idx=None):
        self.set_active_output_midi_channel(channel_or_pad_idx)
        if self.should_send("USB"):
            self.usb_port.send(NoteOn(note, velocity))
        
        if self.should_send("AUX"):
            self.uart_port.send(NoteOn(note, velocity))

    def send_note_off(self, note, channel_or_pad_idx=None):
        self.set_active_output_midi_channel(channel_or_pad_idx)
        if self.should_send("USB"):
            self.usb_port.send(NoteOff(note, 1))

        if self.should_send("AUX"):
            self.uart_port.send(NoteOff(note, 1))
            
    def clear_all_notes(self):
        """Send All Sound Off CC message."""
        self.send_cc(120,0)

    def send_cc(self, cc, value, channel_or_pad_idx=None):
        cc = max(0, min(127, int(cc)))
        value = max(0, min(127, int(value)))

        self.set_active_output_midi_channel(channel_or_pad_idx)
        if self.should_send("USB"):
            self.usb_port.send(ControlChange(cc, value))

        if self.should_send("AUX"):
            self.uart_port.send(ControlChange(cc, value))

    def send_start_stop(self, start):
        if self.should_send("USB"):
            if start:
                self.usb_port.send(Start())
            else:
                self.usb_port.send(Stop())

        if self.should_send("AUX"):
            if start:
                self.uart_port.send(Start())
            else:
                self.uart_port.send(Stop())

    def should_send(self, midi_type):
        """Check if MIDI should be sent on specified type."""
        midi_type = midi_type.upper()
        
        if midi_type == "USB":
            return s.midi_type.upper() in ('USB', 'ALL') and s.midi_usb_io in ('both', 'out')
        if midi_type == "AUX":
            return s.midi_type.upper() in ('AUX', 'ALL') and s.midi_aux_io in ('both', 'out')
        
        return False

    def should_receive(self, midi_type):
        """Check if MIDI should be received on specified type."""
        midi_type = midi_type.upper()
        
        if midi_type == "USB":
            return s.midi_type.upper() in ('USB', 'ALL') and s.midi_usb_io in ('both', 'in')
        elif midi_type == "AUX":
            return s.midi_type.upper() in ('AUX', 'ALL') and s.midi_aux_io in ('both', 'in')
        
        return False
    
    def process_midi_in(self, msg, midi_source):
        """Process incoming MIDI message, return (type, data) or (None, None)"""
        
        if isinstance(msg, Start):
            clock.start_clock()
            return "start", None

        elif isinstance(msg, Stop):
            clock.stop_clock()
            return "stop", None

        elif isinstance(msg, Continue):
            clock.continue_clock()  # Resume without resetting tick count
            return "start", None  # Treat Continue like Start for recording

        elif isinstance(msg, NoteOn):
            # Include the source MIDI channel in the note data
            return("notes_on", [(msg.note, msg.velocity, 0, 0, msg.channel)])
            
        elif isinstance(msg, NoteOff):
            # Include the source MIDI channel in the note data
            return("notes_off", [(msg.note, msg.velocity, 0, 0, msg.channel)])
        
        elif isinstance(msg, ControlChange):
            # Include the source MIDI channel in the CC data
            return("cc", [(msg.control, msg.value, msg.channel)])

        if not s.midi_sync:
            return (None, None)
        
        if self.should_send_clock(midi_source) and clock.is_playing:
            clock.update_clock()
            return ("clock", None)

        return (None, None)

    def process_messages_in(self):
        """Check for and process incoming MIDI messages"""
        
        output = (None, None)

        if self.should_receive("USB"):
            msg = self.usb_port.receive()
            if msg is not None and self.should_accept_channel(msg):
                output = self.process_midi_in(msg, "USB")

        if self.should_receive("AUX"):
            msg = self.uart_port.receive()
            if msg is not None and self.should_accept_channel(msg):
                aux_output = self.process_midi_in(msg, "AUX")
                # Preserve transport messages from either source - don't let clock/notes overwrite them
                if aux_output[0] in ("start", "stop") or output[0] not in ("start", "stop"):
                    output = aux_output

        return output

    def should_send_clock(self, midi_source):
        """Determine if clock should be sent from this source"""
        
        if s.clock_source == "AUTO":
            if self.clock_source is None:
                self.clock_source = midi_source
        else:
            self.clock_source = s.clock_source
        
        return self.clock_source == midi_source

    def should_accept_channel(self, msg):
        """Check if message should be accepted based on channel filtering"""
        # Always accept non-channel messages (Start, Stop, Clock)
        if not hasattr(msg, 'channel'):
            return True
            
        # If "ALL" channels mode is enabled (-1), accept all channels
        if s.midi_channel_in == -1:
            return True
            
        # Otherwise filter by the configured input channel
        return msg.channel == s.midi_channel_in
    
    def should_passthru_midi(self):
        """Check if MIDI passthrough is enabled for AUX"""
        
        return s.midi_passthru and self.should_receive("AUX")

    def toggle_passthru(self):
        """Toggle MIDI passthrough on/off"""
        
        s.midi_passthru = not s.midi_passthru
        return s.midi_passthru

    def change_midi_channel(self, up_or_down=True, in_or_out="out", set_channel=None, update_global_channel=True):
        """Change MIDI channel for input or output"""
        
        new_chan = None
        if set_channel is not None:
            new_chan = set_channel

        else:
            if in_or_out == "in":
                # Handle ALL (-1) + channels 0-15 = 17 total options
                current_pos = s.midi_channel_in + 1  # Convert -1->0, 0->1, ..., 15->16
                new_pos = next_or_previous_index(current_pos, 17, up_or_down)
                new_chan = new_pos - 1  # Convert back: 0->-1, 1->0, ..., 16->15
            if in_or_out == "out":
                new_chan = next_or_previous_index(s.midi_channel_out, 16, up_or_down)

        if in_or_out == "in":
            # MIDI library uses None for "accept all channels", not -1
            midi_lib_channel = None if new_chan == -1 else new_chan
            self.usb_port.in_channel = midi_lib_channel
            self.uart_port.in_channel = midi_lib_channel
            if update_global_channel:
                s.midi_channel_in = new_chan

        if in_or_out == "out":
            self.usb_port.out_channel = new_chan
            self.uart_port.out_channel = new_chan
            s.midi_channel_current = new_chan
            if update_global_channel:
                s.midi_channel_out = new_chan
           
    def set_midi_channel_for_pad(self, pad_idx, channel):
        """Set MIDI channel for specific pad"""
        
        if not (0 <= pad_idx < 16):
            raise ValueError(f"Pad index {pad_idx} out of range (0-15)")
        
        if not (0 <= channel < 16):
            raise ValueError(f"MIDI channel {channel} out of range (0-15)")
        
        s.midi_channel_pad_mapping[pad_idx] = channel
    
    def get_midi_channel_for_pad(self, pad_idx):
        """Return MIDI channel for pad or global if unset"""
        
        # Validate pad index
        if pad_idx is None or not (0 <= pad_idx < 16):
            return s.midi_channel_out
            
        pad_channel = s.midi_channel_pad_mapping[pad_idx]
        if pad_channel is None or not (0 <= pad_channel <= 15):
            return s.midi_channel_out
        return pad_channel
    
    def set_active_output_midi_channel(self, channel_or_pad_idx): 
        """Update MIDI channel based on channel mode settings"""
        
        # Determine the target channel based on channel mode
        if s.midi_channel_mode == "per_note":
            # In per-note mode, channel_or_pad_idx is the stored MIDI channel
            if channel_or_pad_idx is not None and 0 <= channel_or_pad_idx <= 15:
                new_channel = channel_or_pad_idx
            else:
                new_channel = s.midi_channel_out  # Fallback to global
        elif s.midi_channel_mode == "per_pad":
            # In per-pad mode, use pad-specific channel mapping
            if channel_or_pad_idx is not None and 0 <= channel_or_pad_idx < 16:
                new_channel = self.get_midi_channel_for_pad(channel_or_pad_idx)
            else:
                new_channel = s.midi_channel_out
        else:  # "global" mode
            new_channel = s.midi_channel_out
        
        # Final validation - ensure channel is always in valid range
        if new_channel is None or not (0 <= new_channel <= 15):
            new_channel = s.midi_channel_out
            
        # Ensure s.midi_channel_out itself is valid
        if not (0 <= new_channel <= 15):
            new_channel = 0  # Ultimate fallback
        
        if new_channel != s.midi_channel_current:
            self.change_midi_channel(set_channel=new_channel, in_or_out="out", update_global_channel=False)

    def next_or_prev_scale(self, up_or_down=True, display_text=True):
        """Change current scale and update MIDI note mappings"""
        
        s.scale_idx = next_or_previous_index(s.scale_idx, NUM_SCALES, up_or_down)
        current_scale_notes = get_scale_notes(s.scale_idx, s.rootnote_idx)
        
        if s.scale_idx == 0:
            s.midi_notes_default = current_scale_notes[s.midibank_idx]
            self.current_midibank_set = current_scale_notes
        else:
            s.midi_notes_default = current_scale_notes[s.scalenotes_idx]
            self.current_midibank_set = current_scale_notes
        
        self.full_scale_notes = []
        for padset in self.current_midibank_set:
            self.full_scale_notes.extend(padset)
        self.bank_window_start = (s.midibank_idx if s.scale_idx==0 else s.scalenotes_idx) * C.NUM_PADS

        if display_text:
            display.show_text_middle(get_scale_display_text())
        
    def next_or_prev_root(self, up_or_down=True, display_text=True):
        """Change root note of current scale"""
        
        if s.scale_idx == 0:
            return

        s.rootnote_idx = next_or_previous_index(s.rootnote_idx, NUM_ROOTS, up_or_down)

        current_scale_notes = get_scale_notes(s.scale_idx, s.rootnote_idx)
        s.midi_notes_default = current_scale_notes[s.scalenotes_idx]

        self.current_midibank_set = current_scale_notes
        self.full_scale_notes = []
        for padset in self.current_midibank_set:
            self.full_scale_notes.extend(padset)
        self.bank_window_start = s.scalenotes_idx * C.NUM_PADS

        if display_text:
            display.show_text_middle(get_scale_display_text())

    def scale_fn_press_function(self, action_type):
        """Handle function press for root note change"""
        
        if action_type not in ["release"]:
            return
        
        self.next_or_prev_root(up_or_down=True, display_text=True)

    def scale_fn_held_function(self, trigger_on_release=False):
        """Handle function hold for scale with dot indicators"""
        
        if not trigger_on_release:
            display.display_dot(0, True)
            return

        if trigger_on_release:
            display.display_dot(0, False)
            display.display_dot(3, True)
            return

    def scale_setup_function(self):
        """Setup scale selection display"""
        
        display.display_dot(3, True)

    def change_bank(self, up_or_down=True):
        """Change MIDI bank index and update notes"""
        
        if s.scale_idx == 0:
            s.midibank_idx = next_or_previous_index(s.midibank_idx, len(self.current_midibank_set), up_or_down, False)
            self.bank_window_start = s.midibank_idx * C.NUM_PADS
        else:
            s.scalenotes_idx = next_or_previous_index(s.scalenotes_idx, len(self.current_midibank_set), up_or_down, False)
            self.bank_window_start = s.scalenotes_idx * C.NUM_PADS
        self.clear_all_notes()

    def offset_pads(self, up_or_down=True):
        """Shift 16-pad window by PAD_OFFSET_AMOUNT"""
        
        amount = C.PAD_OFFSET_AMOUNT
        delta = amount if up_or_down else -amount
        new_offset = self.pad_group_offset + delta
        if new_offset < 0:
            self.pad_group_offset = C.NUM_PADS + new_offset
            self.change_bank(False)
        elif new_offset >= C.NUM_PADS:
            self.pad_group_offset = new_offset - C.NUM_PADS
            self.change_bank(True)
        else:
            self.pad_group_offset = new_offset

    def change_mode(self, up_or_down=True):
        """Cycle through MIDI modes: usb, aux, all"""
        
        if up_or_down:
            if s.midi_type == "usb":
                s.midi_type = "aux"
            elif s.midi_type == "aux":
                s.midi_type = "all"
            elif s.midi_type == "all":
                s.midi_type = "usb"
        else:
            if s.midi_type == "usb":
                s.midi_type = "all"
            elif s.midi_type == "aux":
                s.midi_type = "usb"
            elif s.midi_type == "all":
                s.midi_type = "aux"

    def setup(self):
        """Initialize MIDI configuration and note mappings"""
        
        current_scale_notes = get_scale_notes(s.scale_idx, s.rootnote_idx)
        if s.scale_idx == 0:
            self.current_midibank_set = current_scale_notes
            s.midi_notes_default = self.current_midibank_set[s.midibank_idx]
        else:
            self.current_midibank_set = current_scale_notes
            s.midi_notes_default = current_scale_notes[s.scalenotes_idx]

        self.full_scale_notes = []
        for padset in self.current_midibank_set:
            self.full_scale_notes.extend(padset)
        self.bank_window_start = s.midibank_idx * C.NUM_PADS
        self.pad_group_offset = 0

midi = Midi(usb_midi, uart_midi)
