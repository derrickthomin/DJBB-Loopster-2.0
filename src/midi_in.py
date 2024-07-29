from adafruit_midi.control_change import ControlChange
from adafruit_midi.note_off import NoteOff
from adafruit_midi.note_on import NoteOn
from adafruit_midi.pitch_bend import PitchBend
from adafruit_midi.start import Start
from adafruit_midi.stop import Stop
from adafruit_midi.timing_clock import TimingClock

messages = (NoteOn, 
            NoteOff, 
            PitchBend, 
            ControlChange, 
            TimingClock, 
            Start, 
            Stop,)

def process_midi_in(msg,midi_type="usb"):
    """
    Processes a MIDI message.
    
    Args:
        msg (MIDI message): The MIDI message to process.
        type (str): The type of MIDI message, either "usb" or "uart".
    """

    if isinstance(msg, NoteOn):
        #djt - add to note on queue
        #djt - record if needed
        pass

    if isinstance(msg, NoteOff):
        #djt - add to note off queue
        #djt - record if needed
        pass

    if isinstance(msg, ControlChange):
        #djt - not sure what to do with this yet..
        pass
    
    if isinstance(msg, TimingClock):
        clock.update_clock()

# def get_midi_messages_in():
#     """
#     Checks for MIDI messages and processes them.
#     """
#     # Check for MIDI messages from the USB MIDI port

#     msg = usb_midi.receive()
#     if msg is not None:
#         process_midi_in(msg,midi_type="usb")

#     # Check for MIDI messages from the UART MIDI port
#     msg = uart_midi.receive()
#     if msg is not None:
#         process_midi_in(msg,midi_type="uart")