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
        is_playing(): Returns the play state of the clock.
    """

    MILLISECONDS_TO_SECONDS = 1000.0
    BPM_OUTLIER_THRESHOLD = 3
    TICK_DURATION_THRESHOLD = 0.02
    TICKS_PER_QUARTER_NOTE = 24

    def __init__(self):
        self.testing = False
        self.last_clock_time = ticks.ticks_ms()
        self.midi_tick_count = 0
        self.last_tick_time = ticks.ticks_ms()
        self.last_tick_duration = 0.0
        self.bpm_current = 120.0
        self.bpm_last = 120.0
        self.update_all_timings(self.bpm_current)
        self.last_4_BPMs = [120.0] * 4
        self.is_playing = False

    def update_all_timings(self, bpm):
        """
        Updates all note timings based on the given BPM.

        Args:
            bpm (float): The new BPM (beats per minute) value.
        """
        quarternote_duration = 60 / bpm
        self.bpm_last = self.bpm_current
        self.bpm_current = bpm
        self.quarternote_duration = quarternote_duration
        self.halfnote_duration = quarternote_duration * 2
        self.wholetime_duration = quarternote_duration * 4
        self.eighthnote_duration = quarternote_duration / 2
        self.sixteenthnote_duration = quarternote_duration / 4
        print_debug(f"Updated timings: quarter={self.quarternote_duration}, half={self.halfnote_duration}, whole={self.wholetime_duration}")

    def update_clock(self):
        """
        Updates the clock and handles outliers.
        """
        self.midi_tick_count += 1
        timenow = ticks.ticks_ms()
        tick_duration = ticks.ticks_diff(timenow, self.last_tick_time) / self.MILLISECONDS_TO_SECONDS
        self.last_tick_time = timenow

        if abs(self.last_tick_duration - tick_duration) > self.TICK_DURATION_THRESHOLD:
            self.midi_tick_count = 0
            self.last_clock_time = timenow
            self.last_tick_duration = tick_duration
            return

        self.last_tick_duration = tick_duration

        if self.midi_tick_count % self.TICKS_PER_QUARTER_NOTE == 0:
            self.midi_tick_count = 0
            if self.last_clock_time != 0:
                self.update_bpm_from_clock(timenow)

            self.last_clock_time = timenow

    def update_bpm_from_clock(self, timenow):
        """
        Updates the BPM from the clock ticks.

        Args:
            timenow (int): The current time in milliseconds.
        """
        quarter_note_time = ticks.ticks_diff(timenow, self.last_clock_time) / self.MILLISECONDS_TO_SECONDS
        new_bpm = round(60 / quarter_note_time)
        self.last_4_BPMs.pop(0)
        self.last_4_BPMs.append(new_bpm)

        if self.last_4_BPMs.count(new_bpm) >= 3:
            outlier_amt = max(abs(bpm - (sum(self.last_4_BPMs) / 4)) for bpm in self.last_4_BPMs)
            if outlier_amt <= self.BPM_OUTLIER_THRESHOLD:
                average_bpm = round(sum(self.last_4_BPMs) / 4)
                self.update_all_timings(average_bpm)
                print_debug(f"Updated BPM: {self.bpm_current}")

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

    def set_play_state(self, state):
        """
        Sets the play state of the clock.

        Args:
            state (bool): The play state to set.
        """
        self.is_playing = state

    def is_playing(self):
        """
        Returns the play state of the clock.

        Returns:
            bool: The play state of the clock.
        """
        return self.is_playing

# Instantiate the Clock object
clock = Clock()