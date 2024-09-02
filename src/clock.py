import time
from debug import print_debug

class Clock:
    """
    A class that represents the synchronization data for MIDI clock.

    Attributes:
        testing (bool): Flag indicating if the class is in testing mode.
        last_clock_time (float): The time of the last clock update.
        midi_tick_count (int): The number of MIDI ticks.
        last_tick_time (float): The time of the last tick.
        last_tick_duration (float): The duration of the last tick.
        bpm_current (float): The current BPM (beats per minute).
        bpm_last (float): The previous BPM.
        wholetime_time (float): The time duration of a whole note.
        halfnote_time (float): The time duration of a half note.
        quarternote_time (float): The time duration of a quarter note.
        eighthnote_time (float): The time duration of an eighth note.
        sixteenthnote_time (float): The time duration of a sixteenth note.
        play_state (bool): The play state of the clock.

    Methods:
        update_bpm(bpm): Updates the BPM value.
        update_all_timings(bpm): Updates all note timings based on the given BPM.
        update_clock(): Updates the clock and handles outliers.
        get_note_time(note_type): Returns the time duration of a given note type.
        set_play_state(state): Sets the play state of the clock.
        get_play_state(): Returns the play state of the clock.
    """

    def __init__(self):
        self.testing = False
        self.last_clock_time = 0
        self.midi_tick_count = 0
        self.last_tick_time = 0
        self.last_tick_duration = 0
        self.bpm_current = 120
        self.bpm_last = 120
        self.update_all_timings(self.bpm_current)
        self.last_4_BPMs = [120] * 4
        self.play_state = False

    def update_all_timings(self, bpm):
        """
        Updates all note timings based on the given BPM.

        Args:
            bpm (float): The new BPM (beats per minute) value.
        """
        quarternote_time = 60 / bpm
        self.bpm_last = self.bpm_current
        self.bpm_current = bpm
        self.quarternote_time = quarternote_time
        self.halfnote_time = quarternote_time * 2
        self.wholetime_time = quarternote_time * 4
        self.eighthnote_time = quarternote_time / 2
        self.sixteenthnote_time = quarternote_time / 4
        print_debug(f"Updated timings: quarter={self.quarternote_time}, half={self.halfnote_time}, whole={self.wholetime_time}")

    def update_clock(self):
        """
        Updates the clock and handles outliers.
        """
        self.midi_tick_count += 1
        timenow = time.monotonic()
        tick_duration = timenow - self.last_tick_time
        self.last_tick_time = timenow

        if abs(self.last_tick_duration - tick_duration) > 0.02:
            self.midi_tick_count = 0
            self.last_clock_time = timenow
            self.last_tick_duration = tick_duration
            return

        self.last_tick_duration = tick_duration

        if self.midi_tick_count % 24 == 0:
            self.midi_tick_count = 0
            if self.last_clock_time != 0:
                quarter_note_time = timenow - self.last_clock_time
                new_bpm = round(60 / quarter_note_time)
                self.last_4_BPMs.pop(0)
                self.last_4_BPMs.append(new_bpm)

                if self.last_4_BPMs.count(new_bpm) >= 3:
                    outlier_amt = max(abs(bpm - (sum(self.last_4_BPMs) / 4)) for bpm in self.last_4_BPMs)
                    if outlier_amt <= 3:
                        average_bpm = round(sum(self.last_4_BPMs) / 4)
                        self.update_all_timings(average_bpm)
                        print_debug(f"Updated BPM: {self.bpm_current}")

            self.last_clock_time = timenow

    def get_note_time(self, note_type):
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
        note_times = {
            "whole": self.wholetime_time,
            "1": self.wholetime_time,
            "half": self.halfnote_time,
            "1/2": self.halfnote_time,
            "quarter": self.quarternote_time,
            "1/4": self.quarternote_time,
            "eighth": self.eighthnote_time,
            "1/8": self.eighthnote_time,
            "sixteenth": self.sixteenthnote_time,
            "1/16": self.sixteenthnote_time,
            "thirtysecond": self.sixteenthnote_time / 2,
            "1/32": self.sixteenthnote_time / 2,
            "sixtyfourth": self.sixteenthnote_time / 4,
            "1/64": self.sixteenthnote_time / 4,
        }

        return note_times.get(note_type, self.quarternote_time)

    def set_play_state(self, state):
        """
        Sets the play state of the clock.

        Args:
            state (bool): The play state to set.
        """
        self.play_state = state

    def get_play_state(self):
        """
        Returns the play state of the clock.

        Returns:
            bool: The play state of the clock.
        """
        return self.play_state

# Instantiate the Clock object
clock = Clock()