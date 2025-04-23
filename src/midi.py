# Adafruit Library
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

# Local module imports
from clock import clock
from debug import debug, print_debug
from display import display
from pixels import pixels
from utils import next_or_previous_index
from midiscales import get_all_scales_list, get_midi_banks_chromatic, get_scale_display_text, NUM_ROOTS
from settings import settings as s
import constants

NUM_PADS = 16
ENC_BUTTON_IDX = 17

uart = busio.UART(constants.UART_MIDI_TX, constants.UART_MIDI_RX, baudrate=31250,timeout=0.001)

uart_midi = adafruit_midi.MIDI(
    midi_in=uart,
    midi_out=uart,
    in_channel=None,
    out_channel=s.midi_channel_out,
    debug=False,)

usb_midi = adafruit_midi.MIDI(
    midi_in=usb_midi.ports[0],
    midi_out=usb_midi.ports[1],
    in_channel=s.midi_channel_out,
    out_channel=s.midi_channel_out,
    debug=False)

class Midi:
    """
    Midi class to handle MIDI input and output.
    """

    def __init__(self, usb_midi=None, uart_midi=None):

        self.usb_port = usb_midi
        self.uart_port = uart_midi
        self.messages = (NoteOn,
                    NoteOff,
                    PitchBend,
                    ControlChange,
                    TimingClock,
                    Start,
                    Stop,)

        self.current_midibank_set = get_midi_banks_chromatic()
        self.current_scale_list = []
        self.midi_velocities = [s.default_velocity] * 16
        self.midi_velocities_singlenote = constants.DEFAULT_SINGLENOTE_MODE_VELOCITIES
        self.current_assignment_velocity = 120
        self.all_scales_list = get_all_scales_list()
        self.last_midi_in_check = 0

    def get_current_scale_display_text(self):
        return get_scale_display_text(self.current_scale_list)
    
    # ------------------ Get / Set / Manipulate MIDI ------------------ #

    def get_midi_bank_idx(self):
        """ 
        Returns:
            str: A string containing the MIDI bank index and the note range, e.g., "Bank: 0 (C1 - G1)".
        """
        return s.midibank_idx

    def get_scale_bank_idx(self):
        """
        Returns:
            str: A string containing the scale bank index and the note range, e.g., "Scale: 0 (C1 - G1)".
        """
        return s.scale_idx

    def get_scale_notes_idx(self):
        """
        Returns:
            str: A string containing the scale notes index, e.g., "Scale Notes: 0".
        """
        return s.scalenotes_idx

    def update_global_velocity(self,new_velocity):
        """
        Updates the global velocity variable with the given value.

        Parameters:
        new_velocity (int): The new velocity value to be assigned.

        Returns:
            None
        """
        self.current_assignment_velocity = new_velocity

    def get_current_assignment_velocity(self):
        """
        Returns:
            int: The current assignment velocity.
        """
        return self.current_assignment_velocity

    def get_velocity_by_idx(self,idx):
        """
        Args:
            idx (int): Index of the MIDI velocity to retrieve.
            
        Returns:
            int: The MIDI velocity value.
        """
        return self.midi_velocities[idx]

    def set_all_midi_velocities(self, val, check_default=True):
        """
        Sets all MIDI velocities to the given value for pads that are at the current default velocity.
        
        Args:
            val (int): The new MIDI velocity value.
            check_default (bool, optional): If True, only pads with the default velocity will be updated. Default is False.
        """
        for i in range(16):
            if check_default:
                if self.midi_velocities[i] == s.default_velocity:
                    self.midi_velocities[i] = val
            else:
                self.midi_velocities[i] = val

    def set_midi_velocity_by_idx(self, idx, vel):
        """
        Sets the MIDI velocity for a given index.
        
        Args:
            idx (int): Index of the MIDI velocity to set.
            val (int): The new MIDI velocity value.
        
        Returns:
            None
        """
        self.midi_velocities[idx] = vel
        pixels.set_note_on(idx, vel)
        print_debug(f"Setting MIDI velocity: {vel}")
    

    def shift_note_octave(self, note, up_or_down=True, num_octaves=1):
        """
        Shifts a note up or down by one octave.

        Args:
            note (tuple): A tuple containing note value, velocity, and pad index.
            up_or_down (bool, optional): Determines whether to shift the note up or down. Default is True (up).
            num_octaves (int, optional): The number of octaves to shift the note. Default is 1.

        Returns:
            tuple: The shifted note.
        """
        shift_amt = 12 * num_octaves
        note_val, velocity, pad_idx = note

        if up_or_down:
            new_note_val = note_val + shift_amt
        else:
            new_note_val = note_val - shift_amt

        if new_note_val < 0 or new_note_val > 127:
            new_note_val = note_val

        return (new_note_val, velocity, pad_idx)

    def shift_all_notes_octaves(self, up_or_down=True, num_octaves=1):
        """
        Shifts all notes up or down by a certain number of octaves.

        Args:
            up_or_down (bool, optional): Determines whether to shift the notes up or down. Default is True (up).
            num_octaves (int, optional): The number of octaves to shift the notes. Default is 1.

        Returns:
            None
        """
        for i in range(16):
            shifted_note = self.shift_note_octave(s.midi_notes_default[i], up_or_down, num_octaves=num_octaves)
            if shifted_note[0] >= 0 and shifted_note[0] <= 127:
                s.midi_notes_default[i] = shifted_note

    def current_notes(self):
        """
        Returns the current MIDI notes assigned to pads (16)

        Returns:
            list: A list of 16 MIDI notes.
        """
        return s.midi_notes_default
    
    def get_midi_note_by_idx(self, idx):
        """
        Returns the MIDI note for a given index.
        
        Args:
            idx (int): Index of the MIDI note to retrieve.
            
        Returns:
            int: The MIDI note value.
        """
        print_debug(f"Getting MIDI note for pad index: {idx}")

        if idx > len(s.midi_notes_default) - 1:
            idx = len(s.midi_notes_default) - 1
            
        return s.midi_notes_default[idx]

    def set_midi_note_by_idx(self,idx, val):
        """
        Sets the MIDI note for a given index.
        
        Args:
            idx (int): Index of the MIDI note to set.
            val (int): The new MIDI note value.
        """
        s.midi_notes_default[idx] = val

    def get_velocity_singlenote_by_idx(self, idx):
        """
        Returns the MIDI note velocity for a specific pad index.
        
        Args:
            idx (int): Index of the pad.
            
        Returns:
            int: The MIDI velocity value.
        """
        return self.midi_velocities_singlenote[idx]
    

    # ------------------- MIDI Message Sending ------------------ #
    
    def send_note_on(self, note, velocity):
        """
        Sends a MIDI note-on message with the given note and velocity.
        
        Args:
            note (int): MIDI note value (0-127).
            velocity (int): MIDI velocity value (0-127).
        """
        if self.should_send("USB"):
            self.usb_port.send(NoteOn(note, velocity))
        
        if self.should_send("AUX"):
            self.uart_port.send(NoteOn(note, velocity))

    def send_note_off(self, note):
        """
        Sends a MIDI note-off message for the given note.
        
        Args:
            note (int): MIDI note value (0-127).
        """
        if self.should_send("USB"):
            self.usb_port.send(NoteOff(note, 1))

        if self.should_send("AUX"):
            self.uart_port.send(NoteOff(note, 1))
            
    def clear_all_notes(self):
        """
        Sends a MIDI "Note Off" message for all possible MIDI note values (0-127).

        This function iterates through all MIDI note numbers and ensures that any
        active notes are turned off by sending a "Note Off" message for each note.

        Note:
            CC val 123 with value 0 is the All Notes Off message in MIDI.
            Keeping this to esure compatibility with other MIDI devices.

        """
        for i in range(127):
            self.send_note_off(i)
    
    def send_aftertouch_for_note(self, _, velocity):
        """
        Sends an aftertouch (channel pressure) MIDI message for a specific velocity.

        Args:
            _ (int): Unused note parameter kept for backward compatibility
            velocity (int): The pressure value (0-127) representing the aftertouch intensity.
        """
        if self.should_send("USB"):
            adafruit_midi.channel_pressure.ChannelPressure(velocity,s.midi_channel_out)

        if self.should_receive("AUX"):
            adafruit_midi.channel_pressure.ChannelPressure(velocity,s.midi_channel_out)


    def send_cc(self, cc, val):
        """
        Sends a MIDI control change message with the given control change number and value.
        
        Args:
            cc (int): Control change number (0-127).
            val (int): Control change value (0-127).
        """
        # Ensure values are within valid MIDI range
        cc = max(0, min(127, int(cc)))
        val = max(0, min(127, int(val)))
        
        if self.should_send("USB"):
            self.usb_port.send(ControlChange(cc, val))

        if self.should_send("AUX"):
            self.uart_port.send(ControlChange(cc, val))
    


    # ------------------- MIDI Message Processing Utils ------------------ #
    def should_send(self, midi_type):
        """
        Determines whether or not to send MIDI based on the given MIDI type and the setup.
        
        Args:
            midi_type (str): The MIDI type, either "USB" or "AUX".
        
        Returns:
            bool: True if MIDI should be sent, False otherwise.
        """
        midi_type = midi_type.upper()
        
        if midi_type == "USB":
            return s.midi_type.upper() in ('USB', 'ALL') and s.midi_usb_io in ('both', 'out')
        if midi_type == "AUX":
            return s.midi_type.upper() in ('AUX', 'ALL') and s.midi_aux_io in ('both', 'out')
        
        return False

    def should_receive(self, midi_type):
        """
        Determines whether or not to receive MIDI based on the given MIDI type and the setup.
        
        Args:
            midi_type (str): The MIDI type, either "USB" or "AUX".
        
        Returns:
            bool: True if MIDI should be received, False otherwise.
        """
        midi_type = midi_type.upper()
        
        if midi_type == "USB":
            return s.midi_type.upper() in ('USB', 'ALL') and s.midi_usb_io in ('both', 'in')
        elif midi_type == "AUX":
            return s.midi_type.upper() in ('AUX', 'ALL') and s.midi_aux_io in ('both', 'in')
        
        return False
    
    def process_midi_in(self, msg):
        """
        Processes incoming MIDI messages and performs actions based on the message type.
        Args:
            msg: The incoming MIDI message. It can be of types such as Start, Stop, NoteOn, NoteOff, or TimingClock.
        Returns:
            Tuple[str, List]: Message type and associated data, or (None, None) if no relevant message
        """
        if isinstance(msg, Start):
            clock.start_clock()
            return "start", None

        elif isinstance(msg, Stop):
            clock.stop_clock()
            return "stop", None

        elif isinstance(msg, NoteOn):    # Note On message
            if not clock.get_playstate():
                clock.start_clock()
            return("notes_on", [(msg.note, msg.velocity, 0)])
            
        elif isinstance(msg, NoteOff): # Note Off message
            return("notes_off", [(msg.note, msg.velocity, 0)])
        
        elif isinstance(msg, ControlChange): # CC message
            return("cc", [(msg.control, msg.value)])

        if not s.midi_sync:
            return (None, None)

        if isinstance(msg, TimingClock) and clock.is_playing: # Timing Clock message
            clock.update_clock()
            return ("clock", None)

        return (None, None)

    def process_messages_in(self):
        """
        Checks for MIDI messages and processes them.
        """

        output = (None, None)

        # USB MIDI 
        if self.should_receive("USB"):
            msg = self.usb_port.receive()
            if msg is not None:
                output = self.process_midi_in(msg)

        # UART (DIN) MIDI
        if self.should_receive("AUX"):
            msg = self.uart_port.receive()
            if msg is not None:
                output = self.process_midi_in(msg)

        return output

    # ------------------ Get / Change settings ------- #
    def change_midi_channel(self, up_or_down=True, in_or_out="out", set_channel=None):
        """
        Changes the MIDI channel for input, output

        Args:
            up_or_down (bool, optional): Determines whether to increment or decrement the MIDI channel. Defaults to True (increment).
            set_channel (int, optional): The channel to set. Defaults to None. Use to directly set channel instead of cycling.

        Returns:
            None
        """
        if set_channel is not None and in_or_out == "in":
            s.midi_channel_in = set_channel
            self.usb_port.in_channel = s.midi_channel_in
            self.uart_port.in_channel = s.midi_channel_in
            debug.add_debug_line("Midi Channel In changed to ", f"Channel: {s.midi_channel_in}")

        elif set_channel is not None and in_or_out == "out":
            s.midi_channel_out = set_channel
            self.usb_port.out_channel = s.midi_channel_out
            self.uart_port.out_channel = s.midi_channel_out
            debug.add_debug_line("Midi Channel Out changed to ", f"Channel: {s.midi_channel_out}")

        elif in_or_out == "in":
            s.midi_channel_in = next_or_previous_index(s.midi_channel_in, 16, up_or_down)
            self.usb_port.in_channel = s.midi_channel_in
            self.uart_port.in_channel = s.midi_channel_in
            debug.add_debug_line("Midi Channel In changed to ", f"Channel: {s.midi_channel_in}")
        else:
            s.midi_channel_out = next_or_previous_index(s.midi_channel_out, 16, up_or_down)
            self.usb_port.out_channel = s.midi_channel_out
            self.uart_port.out_channel = s.midi_channel_out
            debug.add_debug_line("Midi Channel Out changed to ", f"Channel: {s.midi_channel_out}")

    def next_or_prev_scale(self, up_or_down=True, display_text=True):
        """
        Changes the current musical scale and updates MIDI note mappings.
        
        This function cycles through available scales (major, minor, etc.) and updates
        the MIDI note assignments accordingly. For chromatic scales, it uses a special
        handling approach.
        
        Args:
            up_or_down (bool): True to select next scale, False for previous scale.
                            Default is True.
            display_text (bool): Whether to update the display with the new scale name.
                                Default is True.
        """

        # Select next/previous scale from available scales
        s.scale_idx = next_or_previous_index(s.scale_idx, len(self.all_scales_list), up_or_down)
        self.current_scale_list = self.all_scales_list[s.scale_idx][1]
        
        # Update MIDI notes based on scale type
        if s.scale_idx == 0:
            s.midi_notes_default = self.current_scale_list[0][1][s.midibank_idx]                # Chromatic scale
        else:
            s.midi_notes_default =self.current_scale_list[s.rootnote_idx][1][s.scalenotes_idx] # Scale mode
        
        # Update display if requested
        if display_text:
            display.show_text_middle(get_scale_display_text(self.current_scale_list))
        
        print_debug(f"current midi notes: {s.midi_notes_default}")
        debug.add_debug_line("Current Scale", get_scale_display_text(self.current_scale_list))

    def next_or_prev_root(self, up_or_down=True, display_text=True):
        """
        Change the root note of the current scale.

        Args:
            up_or_down (bool, optional): Determines whether to change the root note up or down. Defaults to True.
            display_text (bool, optional): Determines whether to display the updated scale text. Defaults to True.

        Returns:
            None
        """
        if s.scale_idx == 0:  # doesn't make sense for chromatic.
            return

        s.rootnote_idx = next_or_previous_index(s.rootnote_idx, NUM_ROOTS, up_or_down)

        s.midi_notes_default = self.current_scale_list[s.rootnote_idx][1][s.scalenotes_idx]  # item 0 is c,d,etc.
        if display_text:
            display.show_text_middle(get_scale_display_text(self.current_scale_list))
        print_debug(f"current midi notes: {s.midi_notes_default}")
        debug.add_debug_line("Current Scale", get_scale_display_text(self.current_scale_list))

    def scale_fn_press_function(self, action_type):
        """
        Handle the function press action for changing the scale.

        Args:
            action_type (str): The type of action performed. Should be "release".

        Returns:
            None
        """
        if action_type not in ["release"]:
            return
        
        self.next_or_prev_root(up_or_down=True, display_text=True)

    def scale_fn_held_function(self, trigger_on_release=False):
        """
        Handle the function held action for changing the scale.

        Args:
            trigger_on_release (bool, optional): Whether to trigger the action on release. Defaults to False.

        Returns:
            None
        """
        if not trigger_on_release:
            display.display_dot(0, True)
            return

        if trigger_on_release:
            display.display_dot(0, False)
            display.display_dot(3, True)
            return

    def scale_setup_function(self):
        """
        Setup the scale selection function.

        Returns:
            None
        """
        display.display_dot(3, True)

    def change_bank(self, up_or_down=True):
        """
        Change the MIDI bank index and update the current MIDI notes.

        Args:
            up_or_down (bool, optional): Determines whether to move the MIDI bank index up or down. Defaults to True.

        Returns:
            None
        """

        # Chromatic mode    
        if s.scale_idx == 0:
            self.current_midibank_set = self.current_scale_list[0][1]  # chromatic is special
            s.midibank_idx = next_or_previous_index(s.midibank_idx, len(self.current_midibank_set), up_or_down)
            s.midi_notes_default = self.current_midibank_set[s.midibank_idx]
            self.clear_all_notes()
        # Scale Mode
        else:
            self.current_midibank_set = self.current_scale_list[s.rootnote_idx][1]
            s.scalenotes_idx = next_or_previous_index(s.scalenotes_idx, len(self.current_midibank_set), up_or_down)
            s.midi_notes_default = self.current_midibank_set[s.scalenotes_idx]
            self.clear_all_notes()

    def change_mode(self, up_or_down=True):
        """
        Changes the MIDI mode to the next or previous mode.

        This function cycles through the available MIDI modes ("usb", "aux", "all") 
        in either the forward or reverse direction based on the `up_or_down` parameter.

        Args:
            up_or_down (bool, optional): If True, cycles to the next mode. 
                                         If False, cycles to the previous mode. Default is True.

        Returns:
            None
        """
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
        """
        Sets up the MIDI configuration for the application.

        This function initializes the global variables `current_scale_list`, `s.midi_notes_default`, and `self.current_midibank_set`.
        It assigns the appropriate values based on the default settings.

        Returns:
            None
        """
        self.current_scale_list = self.all_scales_list[s.scale_idx][1]

        if s.scale_idx == 0:  # special handling for chromatic.
            self.current_midibank_set = self.current_scale_list[0][1]
            s.midi_notes_default = self.current_midibank_set[s.midibank_idx]
        else:
            self.current_midibank_set = self.current_scale_list[s.rootnote_idx][1]
            s.midi_notes_default = self.current_scale_list[s.rootnote_idx][1][s.scalenotes_idx]  # item 0 is c,d,etc.

midi = Midi(usb_midi, uart_midi)
