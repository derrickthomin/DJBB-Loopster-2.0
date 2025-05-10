import adafruit_ticks as ticks
from debug import print_debug

class Clock:
    """
    A class that represents the synchronization data for MIDI clock.

    Attributes:
        testing (bool): Flag indicating if the class is in testing mode.
        last_clock_time (int): The time of the last clock update in milliseconds.
        midi_tick_count (int): The number of MIDI ticks.
        last_tick_time (int): The time of the last tick in milliseconds.
        last_tick_duration (float): The duration of the last tick in seconds.
        bpm_current (float): The current BPM (beats per minute).
        bpm_last (float): The previous BPM.
        wholetime_duration (float): The time duration of a whole note.
        halfnote_duration (float): The time duration of a half note.
        quarternote_duration (float): The time duration of a quarter note.
        eighthnote_duration (float): The time duration of an eighth note.
        sixteenthnote_duration (float): The time duration of a sixteenth note.
        play_state (bool): The play state of the clock.

    Methods:
        update_bpm(bpm): Updates the BPM value.
        update_all_timings(bpm): Updates all note timings based on the given BPM.
        update_clock(): Updates the clock and handles outliers.
        get_note_duration_seconds(note_type): Returns the time duration of a given note type.
        set_play_state(state): Sets the play state of the clock.
        get_playstate(): Returns the play state of the clock.
    """

    MILLISECONDS_TO_SECONDS = 1000.0
    BPM_OUTLIER_THRESHOLD = 3
    TICK_DURATION_THRESHOLD = 0.02
    TICKS_PER_QUARTER_NOTE = 24
    TICKS_PER_WHOLE_NOTE = TICKS_PER_QUARTER_NOTE * 4

    def __init__(self):
        self.testing = False
        self.last_clock_time = ticks.ticks_ms()
        self.midi_ticks_elapsed = 0                          # Resets on new start or stop message.
        self.last_tick_time = ticks.ticks_ms()
        self.last_tick_duration = 0.0
        self.bpm_current = 120.0
        self.bpm_last = 120.0
        self.update_all_timings(self.bpm_current)
        self.last_4_BPMs = [120.0] * 4
        self.is_playing = False
        self.last_whole_note_time = 0 # timestamp of last time 24 ticks elapsed
        self.seconds_per_tick = 60 / (self.bpm_current * self.TICKS_PER_QUARTER_NOTE)
        self.new_tick = False # Flag to indicate if a new tick has occurred since last update

    def reset_midi_tick_count(self):
        """
        Resets the MIDI tick count.
        """
        self.midi_ticks_elapsed = 0

    def update_all_timings(self, bpm):
        """
        Updates all note timings based on the given BPM.

        Args:
            bpm (float): The new BPM (beats per minute) value.
        """
        quarternote_duration = 60 / bpm
        self.bpm_last = self.bpm_current
        self.bpm_current = bpm
        self.seconds_per_tick = 60 / (self.bpm_current * self.TICKS_PER_QUARTER_NOTE)
        #print(f"seconds per tick: {self.seconds_per_tick}")
        self.quarternote_duration = quarternote_duration
        self.halfnote_duration = quarternote_duration * 2
        self.wholetime_duration = quarternote_duration * 4
        self.eighthnote_duration = quarternote_duration / 2
        self.sixteenthnote_duration = quarternote_duration / 4
        #print_debug(f"Updated timings: quarter={self.quarternote_duration}, half={self.halfnote_duration}, whole={self.wholetime_duration}")

    def reset_new_tick_flag(self):
        """
        Resets the new tick flag.
        """
        self.new_tick = False

    def update_clock(self):
        """
        Updates the clock and handles outliers.
        """
        self.new_tick = True
        self.midi_ticks_elapsed += 1

        # Only log every whole note (96 ticks) to reduce spam

        timenow = ticks.ticks_ms()
        # tick_duration = ticks.ticks_diff(timenow, self.last_tick_time) / self.MILLISECONDS_TO_SECONDS
        self.last_tick_time = timenow

        # Update BPM Every Whole Note = 96 ticks 
        if self.midi_ticks_elapsed % self.TICKS_PER_WHOLE_NOTE == 0:
            # Calculate BPM from whole note time
            whole_note_time = ticks.ticks_diff(timenow, self.last_whole_note_time) / self.MILLISECONDS_TO_SECONDS
            self.last_whole_note_time = timenow
            
            if whole_note_time > 0:
                new_bpm = round(60 * 4 / whole_note_time) # Divide by 4 to get the BPM from whole note time
            else:
                new_bpm = 0  # or handle the error appropriately

            # Compare with current BPM
            if new_bpm != self.bpm_current and new_bpm > 0:
                self.update_all_timings(new_bpm)
                self.bpm_current = new_bpm
                # Only log significant BPM changes
                print(f"Updated BPM: {self.bpm_current}")

    # Function to convert seconds to ticks. To be used with the looper - we record the time in seconds since the start of the loop
    # and then convert to ticks when we play it back if midi synch enabled
    def seconds_to_ticks(self, seconds, bpm=None):
        """
        Converts seconds to ticks.

        Args:
            seconds (float): The time in seconds.
            bpm (float, optional): The BPM to use for conversion. If None, uses current BPM.

        Returns:
            int: The time in ticks.
        """
        if bpm:
            seconds_per_tick = 60 / (bpm * self.TICKS_PER_QUARTER_NOTE)
        else:
            seconds_per_tick = self.seconds_per_tick
        return int(round(seconds / seconds_per_tick))
    
    def ticks_to_seconds(self, ticks, bpm=None):
        """
        Converts ticks to seconds.

        Args:
            ticks (int): The time in MIDI ticks.
            bpm (float, optional): The BPM to use for conversion. If None, uses current BPM.

        Returns:
            float: The time in seconds.
        """
        if bpm:
            seconds_per_tick = 60 / (bpm * self.TICKS_PER_QUARTER_NOTE)
        else:
            seconds_per_tick = self.seconds_per_tick
        return ticks * seconds_per_tick

    def get_note_duration_seconds(self, note_type):
        """
        Returns the time duration of a given note type.

        Args:
            note_type (str): The type of note. Valid values are "whole" or "1" for whole note,
                             "half" or "1/2" for half note, "quarter" or "1/4" for quarter note,
                             "eighth" or "1/8" for eighth note, "sixteenth" or "1/16" for sixteenth note,
                             "thirtysecond" or "1/32" for thirty-second note, "sixtyfourth" or "1/64" for sixty-fourth note.

        Returns:
            float: The time duration of the note in seconds.
        """
        note_times_seconds = {
            "whole": self.wholetime_duration,
            "1": self.wholetime_duration,
            "half": self.halfnote_duration,
            "1/2": self.halfnote_duration,
            "quarter": self.quarternote_duration,
            "1/4": self.quarternote_duration,
            "eighth": self.eighthnote_duration,
            "1/8": self.eighthnote_duration,
            "sixteenth": self.sixteenthnote_duration,
            "1/16": self.sixteenthnote_duration,
            "thirtysecond": self.sixteenthnote_duration / 2,
            "1/32": self.sixteenthnote_duration / 2,
            "sixtyfourth": self.sixteenthnote_duration / 4,
            "1/64": self.sixteenthnote_duration / 4,
        }

        return note_times_seconds.get(note_type, self.quarternote_duration)

    def start_clock(self):
        """
        Starts the clock.
        """
        self.is_playing = True
        self.reset_midi_tick_count()
        self.new_tick = True
    
    def stop_clock(self):
        """
        Stops the clock.
        """
        self.is_playing = False
        self.reset_midi_tick_count()

    def get_playstate(self):
        """
        Returns the play state of the clock.

        Returns:
            bool: The play state of the clock.
        """
        return self.is_playing

# Instantiate the Clock object
clock = Clock()

# if __name__ == "__main__":
#     # Test the Clock class

#     import adafruit_midi
#     from adafruit_midi.control_change import ControlChange
#     from adafruit_midi.note_off import NoteOff
#     from adafruit_midi.note_on import NoteOn
#     from adafruit_midi.pitch_bend import PitchBend
#     from adafruit_midi.start import Start
#     from adafruit_midi.stop import Stop
#     from adafruit_midi.timing_clock import TimingClock
#     import usb_midi
#     from settings import settings as s

#     messages = (NoteOn, 
#             NoteOff, 
#             PitchBend, 
#             ControlChange, 
#             TimingClock, 
#             Start, 
#             Stop,)

#     usb_midi = adafruit_midi.MIDI(
#         midi_in=usb_midi.ports[0],
#         midi_out=usb_midi.ports[1],
#         in_channel=s.midi_channel_out,
#         out_channel=s.midi_channel_out,
#         debug=False)
    
#     def process_midi_in():
#         """
#         Processes a MIDI message.
        
#         Args:
#             msg (MIDI message): The MIDI message to process.
#             type (str): The type of MIDI message, either "usb" or "uart".
#         """

#         msg = usb_midi.receive()
#         if not isinstance(msg, TimingClock):
#             print_debug(f"Processing MIDI In: {msg}")

#         if isinstance(msg, TimingClock):
#             clock.update_clock()

#         elif isinstance(msg, Start):
#             clock.start_clock()
#             print("Start message received")

#         elif isinstance(msg, Stop):
#             clock.stop_clock()
#             print("Stop message received")

#     while True:
#         process_midi_in()
#         # if clock.midi_ticks_elapsed > 1:
#         #     print(f"tick count: {clock.midi_ticks_elapsed}")
