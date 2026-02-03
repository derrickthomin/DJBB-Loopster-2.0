import busio
import usb_midi
import adafruit_midi
from adafruit_midi.control_change import ControlChange
from adafruit_midi.note_off import NoteOff
from adafruit_midi.note_on import NoteOn
from adafruit_midi.pitch_bend import PitchBend
from adafruit_midi.polyphonic_key_pressure import PolyphonicKeyPressure
from adafruit_midi.channel_pressure import ChannelPressure
from adafruit_midi.start import Start
from adafruit_midi.stop import Stop
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

# Increase UART RX buffer to reduce overflow risk during dense MIDI bursts
uart = busio.UART(C.UART_MIDI_TX, C.UART_MIDI_RX, baudrate=31250, timeout=0.001, receiver_buffer_size=128)

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
        self._last_passthru_msg = None  # Filter consecutive duplicate messages
        self._cc_send_cache = {}  # Duplicate CC suppression: (cc, channel) -> last_value
        
    def get_current_scale_display_text(self):
        """Returns display text for current scale."""
        return get_scale_display_text()
    
    def get_midi_bank_idx(self):
        return s.midibank_idx

    def get_scale_bank_idx(self):
        return s.scale_idx

    def get_scale_notes_idx(self):
        return s.scalenotes_idx

    def get_pad_offset_suffix(self):
        """Return ' +', ' ++', ' +++' or '' for display."""
        if self.pad_group_offset == 0:
            return ""
        steps = self.pad_group_offset // C.PAD_OFFSET_AMOUNT
        return " " + ("+" * steps)

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

    def get_velocity_singlenote_by_idx(self, idx):
        return C.DEFAULT_SINGLENOTE_MODE_VELOCITIES[idx]
    
    def send_note_on(self, note, velocity, channel_or_pad_idx=None):
        if self.should_send("USB"):
            self.usb_port.send(NoteOn(note, velocity), channel=channel_or_pad_idx)
        
        if self.should_send("AUX"):
            self.uart_port.send(NoteOn(note, velocity), channel=channel_or_pad_idx)

    def send_note_off(self, note, channel_or_pad_idx=None):
        if self.should_send("USB"):
            self.usb_port.send(NoteOff(note, 1), channel=channel_or_pad_idx)

        if self.should_send("AUX"):
            self.uart_port.send(NoteOff(note, 1), channel=channel_or_pad_idx)
            
    def clear_all_notes(self):
        """Send All Sound Off CC message."""
        self.send_cc(120,0)

    def send_cc(self, cc, value, channel_or_pad_idx=None):
        cc = max(0, min(127, int(cc)))
        value = max(0, min(127, int(value)))
        
        # Duplicate suppression - skip if same value already sent for this CC/channel
        cache_key = (cc, channel_or_pad_idx)
        if self._cc_send_cache.get(cache_key) == value:
            return  # Skip - receiver already has this value
        self._cc_send_cache[cache_key] = value

        if self.should_send("USB"):
            self.usb_port.send(ControlChange(cc, value), channel=channel_or_pad_idx)

        if self.should_send("AUX"):
            self.uart_port.send(ControlChange(cc, value), channel=channel_or_pad_idx)
    
    def clear_cc_cache(self):
        """Clear CC send cache. Call when all loops stop for fresh start."""
        self._cc_send_cache.clear()

    def send_aftertouch(self, pressure, channel_or_pad_idx=None):
        """Send channel pressure (aftertouch) message."""
        # For polyphonic: add note param, use PolyphonicKeyPressure(note, pressure)
        pressure = max(0, min(127, int(pressure)))

        if self.should_send("USB"):
            self.usb_port.send(ChannelPressure(pressure), channel=channel_or_pad_idx)

        if self.should_send("AUX"):
            self.uart_port.send(ChannelPressure(pressure), channel=channel_or_pad_idx)

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
            return "start", None    # Treat Continue like Start for recording

        elif isinstance(msg, NoteOn):
            return("notes_on", [(msg.note, msg.velocity, 0, 0, msg.channel)])
            
        elif isinstance(msg, NoteOff):
            return("notes_off", [(msg.note, msg.velocity, 0, 0, msg.channel)])
        
        elif isinstance(msg, ControlChange):
            return("cc", [(msg.control, msg.value, msg.channel)])

        elif isinstance(msg, ChannelPressure):
            return("aftertouch", [(msg.pressure, msg.channel)]) # Channel pressure: pressure, channel (for polyphonic: add msg.note)

        if self.should_accept_clock(midi_source) and clock.is_playing:
            clock.update_clock()
            return ("clock", None)

        return (None, None)

    def _extract_raw_midi_bytes(self, msg):
        """Extract raw MIDI bytes from Adafruit message object.
        
        Converts Adafruit MIDI objects to their raw byte representation.
        Avoids object creation - just reads attributes and builds byte list.
        
        Returns: [status_byte, data1, data2] or None if unsupported message type
        
        MIDI Byte Formats:
        - NoteOn:      [0x90 | channel, note, velocity]
        - NoteOff:     [0x80 | channel, note, velocity]
        - CC:          [0xB0 | channel, control, value]
        - ChannelPressure: [0xD0 | channel, pressure]
        - PitchBend:   [0xE0 | channel, LSB, MSB] (14-bit value)
        - PolyPressure: [0xA0 | channel, note, pressure]
        """
        try:
            if isinstance(msg, NoteOn):
                return [0x90 | msg.channel, msg.note, msg.velocity]
            elif isinstance(msg, NoteOff):
                return [0x80 | msg.channel, msg.note, msg.velocity]
            elif isinstance(msg, ControlChange):
                return [0xB0 | msg.channel, msg.control, msg.value]
            elif isinstance(msg, ChannelPressure):
                return [0xD0 | msg.channel, msg.pressure]
            elif isinstance(msg, PitchBend):
                # PitchBend is 14-bit: -8192 to 8191, centered at 0
                # Convert to 0-16383 range, then split into 7-bit LSB and MSB
                value = msg.pitch_bend + 8192  # Shift to 0-16383
                return [0xE0 | msg.channel, value & 0x7F, (value >> 7) & 0x7F]
            elif isinstance(msg, PolyphonicKeyPressure):
                return [0xA0 | msg.channel, msg.note, msg.pressure]
            return None
        except Exception as e:
            if s.debug:
                print(f"[WARN] Failed to extract MIDI bytes from {type(msg).__name__}: {e}")
            return None

    def _send_raw_midi_bytes(self, raw_bytes):
        """Send raw MIDI bytes to output ports.
        
        Direct byte transmission - no object creation or serialization.
        Respects should_send() checks for USB/AUX routing.
        Uses _midi_out to access underlying transport (UART/USB).
        
        Args:
            raw_bytes: List like [status_byte, data1, data2]
        """
        try:
            if self.should_send("USB"):
                self.usb_port._midi_out.write(bytes(raw_bytes))
            if self.should_send("AUX"):
                self.uart_port._midi_out.write(bytes(raw_bytes))
        except Exception as e:
            if s.debug:
                print(f"[WARN] Failed to write raw MIDI bytes: {e}")

    def process_messages_in(self):
        """Check for and process incoming MIDI messages.
        Returns: (notes_on_list, notes_off_list, cc_list, at_list, transport_msg)
        where transport_msg is 'start', 'stop', or None
        """
        MAX_MESSAGES_PER_PORT = 16  # Safety cap to prevent main loop starvation
        
        notes_on = []
        notes_off = []
        cc_events = []
        at_events = []
        transport = None

        # Process USB messages - drain buffer with cap
        if self.should_receive("USB"):
            usb_msg_count = 0
            usb_passthru = s.passthru_mode in ("usb", "all")  # USB IN → AUX OUT
            
            for _ in range(MAX_MESSAGES_PER_PORT):
                msg = self.usb_port.receive()
                if msg is None:
                    break
                usb_msg_count += 1
                
                # USB PASSTHROUGH - forwards to AUX output only (avoids USB feedback loops)
                if usb_passthru:
                    raw_bytes = self._extract_raw_midi_bytes(msg)
                    if raw_bytes:
                        # Send to AUX output only
                        try:
                            self.uart_port._midi_out.write(bytes(raw_bytes))
                            if s.debug:
                                status = raw_bytes[0]
                                if (status & 0xF0) in (0x80, 0x90):
                                    msg_type_str = "NoteOn" if (status & 0xF0) == 0x90 else "NoteOff"
                                    print(f"[DEBUG] USB→AUX Passthru {msg_type_str}: note={raw_bytes[1]} vel={raw_bytes[2]}")
                        except Exception as e:
                            if s.debug:
                                print(f"[WARN] USB passthru failed: {e}")
                    elif isinstance(msg, Start):
                        self.uart_port.send(Start())
                    elif isinstance(msg, Stop):
                        self.uart_port.send(Stop())
                
                if not self.should_accept_channel(msg):
                    continue
                msg_type, msg_data = self.process_midi_in(msg, "USB")
                if msg_type == "notes_on":
                    notes_on.extend(msg_data)
                elif msg_type == "notes_off":
                    notes_off.extend(msg_data)
                elif msg_type == "cc":
                    cc_events.extend(msg_data)
                elif msg_type == "aftertouch":
                    at_events.extend(msg_data)
                elif msg_type in ("start", "stop"):
                    transport = msg_type
            # DEBUG: Detect buffer overflow
            if usb_msg_count >= MAX_MESSAGES_PER_PORT:
                print(f"[WARN] USB buffer hit limit ({MAX_MESSAGES_PER_PORT}), messages may be dropped!")

        # Process AUX messages - drain buffer with cap
        if self.should_receive("AUX"):
            # DEBUG: Check UART buffer status before processing
            if s.debug:
                uart_bytes_waiting = uart.in_waiting
                if uart_bytes_waiting > 96:  # 75% of 128 byte buffer
                    print(f"[WARN] UART buffer nearly full: {uart_bytes_waiting}/128 bytes")
            
            aux_passthru = s.passthru_mode in ("aux", "all")  # AUX IN → USB OUT
            aux_msg_count = 0
            aux_passthru_count = 0
            aux_filtered_count = 0
            
            for _ in range(MAX_MESSAGES_PER_PORT):
                msg = self.uart_port.receive()
                if msg is None:
                    break
                aux_msg_count += 1
                
                # PASSTHROUGH FIRST - forwards ALL channels (like hardware MIDI Thru)
                # This happens before channel filtering so multi-channel data passes through
                if aux_passthru:
                    raw_bytes = self._extract_raw_midi_bytes(msg)
                    if raw_bytes:
                        status = raw_bytes[0]
                        is_note_on = (status & 0xF0) == 0x90
                        is_note_off = (status & 0xF0) == 0x80
                        
                        # Skip consecutive duplicate messages (same bytes back-to-back)
                        if raw_bytes == self._last_passthru_msg:
                            aux_filtered_count += 1
                            # DEBUG: Log filtered messages
                            if s.debug:
                                msg_type_str = "NoteOn" if is_note_on else "NoteOff" if is_note_off else "Other"
                                print(f"[DEBUG] Passthru FILTERED duplicate: {msg_type_str} {raw_bytes}")
                            continue
                        self._last_passthru_msg = raw_bytes
                        self._send_raw_midi_bytes(raw_bytes)
                        aux_passthru_count += 1
                        # DEBUG: Log note on/off passthrough
                        if s.debug:
                            if is_note_on or is_note_off:
                                msg_type_str = "NoteOn" if is_note_on else "NoteOff"
                                print(f"[DEBUG] Passthru {msg_type_str}: note={note} vel={vel}")
                    # Handle transport messages separately (not standard channel messages)
                    elif isinstance(msg, Start):
                        self.send_start_stop(True)
                    elif isinstance(msg, Stop):
                        self.send_start_stop(False)
                
                # Channel filter - only for recording/internal processing
                if not self.should_accept_channel(msg):
                    continue
                
                # Collect for clock/transport/recording
                msg_type, msg_data = self.process_midi_in(msg, "AUX")
                if msg_type == "notes_on":
                    notes_on.extend(msg_data)
                elif msg_type == "notes_off":
                    notes_off.extend(msg_data)
                elif msg_type == "cc":
                    cc_events.extend(msg_data)
                elif msg_type == "aftertouch":
                    at_events.extend(msg_data)
                elif msg_type in ("start", "stop"):
                    transport = msg_type  # Last transport message wins
            
            # DEBUG: Detect buffer overflow and summarize
            if aux_msg_count >= MAX_MESSAGES_PER_PORT:
                print(f"[WARN] AUX buffer hit limit ({MAX_MESSAGES_PER_PORT}), messages may be dropped!")
            if s.debug and aux_msg_count > 0:
                print(f"[DEBUG] AUX: {aux_msg_count} msgs, {aux_passthru_count} passed, {aux_filtered_count} filtered")

        return (notes_on, notes_off, cc_events, at_events, transport)

    def should_accept_clock(self, midi_source):
        """Determine if clock should be accepted from this source.
        
        Uses clock_source as preference, but falls back to other port
        if preferred port can't receive input.
        """
        # If sync disabled, never accept clock
        if not s.midi_sync:
            return False
        
        # If preferred source matches and can receive, use it
        if s.clock_source == midi_source and self.should_receive(midi_source):
            return True
        
        # Fallback: if preferred source can't receive input, accept from the other port
        if s.clock_source == "USB" and not self.should_receive("USB"):
            return midi_source == "AUX" and self.should_receive("AUX")
        if s.clock_source == "AUX" and not self.should_receive("AUX"):
            return midi_source == "USB" and self.should_receive("USB")
        
        return False

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
        """Check if any MIDI passthrough is enabled"""
        return s.passthru_mode != "off"

    def change_midi_channel(self, up_or_down=True, in_or_out="out", set_channel=None, update_global_channel=True):
        """Change MIDI input/output channel configuration. Used for defaults"""
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
        """Shift 16-pad window by PAD_OFFSET_AMOUNT. Stops at bank boundaries."""
        
        amount = C.PAD_OFFSET_AMOUNT
        delta = amount if up_or_down else -amount
        new_offset = self.pad_group_offset + delta
        
        # Get current bank index
        current_bank = s.midibank_idx if s.scale_idx == 0 else s.scalenotes_idx
        max_bank = len(self.current_midibank_set) - 1
        
        if new_offset < 0:
            # Trying to go below current bank
            if current_bank == 0:
                # At bank 0, can't go lower - stay put
                return
            self.pad_group_offset = C.NUM_PADS + new_offset
            self.change_bank(False)
        elif new_offset >= C.NUM_PADS:
            # Trying to go above current bank
            if current_bank >= max_bank:
                # At max bank, can't go higher - stay put
                return
            self.pad_group_offset = new_offset - C.NUM_PADS
            self.change_bank(True)
        else:
            self.pad_group_offset = new_offset

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
        self.bank_window_start = (s.midibank_idx if s.scale_idx == 0 else s.scalenotes_idx) * C.NUM_PADS
        self.pad_group_offset = 0

midi = Midi(usb_midi, uart_midi)
