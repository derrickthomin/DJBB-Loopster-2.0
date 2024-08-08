# For managing MIDI timing 
import time
from debug import print_debug

# ------------------ Clock & Timing ------------------ #
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

    Methods:
        update_bpm(bpm): Updates the BPM value.
        update_all_timings(quarternote_time): Updates all note timings based on the given quarter note time.
        update_clock(): Updates the clock and handles outliers.
    """

    def __init__(self):
        self.testing = False 
        self.last_clock_time = 0
        self.midi_tick_count = 0
        self.last_tick_time = 0
        self.last_tick_duration = 0
        self.bpm_current = 0
        self.bpm_last = 0
        self.wholetime_time = 0
        self.halfnote_time = 0
        self.quarternote_time = 0
        self.eighthnote_time = 0
        self.sixteenthnote_time = 0
        self.update_all_timings(120) # 120 bpm default
        self.last_4_BPMs = [120, 120, 120, 120]
    
    
    def update_all_timings(self, bpm):
        """
        Updates all note timings based on the given quarter note time.

        Args:
            quarternote_time (float): The time duration of a quarter note.
        """
        self.bpm_last = self.bpm_current
        self.bpm_current = bpm

        quarternote_time = 60 / bpm
        self.quarternote_time = quarternote_time
        self.halfnote_time = quarternote_time * 2
        self.wholetime_time = quarternote_time * 4
        self.eighthnote_time = quarternote_time / 2
        self.sixteenthnote_time = quarternote_time / 4
        print_debug(f"whole: {self.wholetime_time}, half: {self.halfnote_time}, quarter: {self.quarternote_time}, eighth: {self.eighthnote_time}, sixteenth: {self.sixteenthnote_time}")


    def update_clock(self):
        """
        Updates the clock and handles outliers.
        """

        self.midi_tick_count += 1
        timenow = time.monotonic()

        # Check to see if this tick duration is the same as the last. If not, reset the tick count and clock_time

        tick_duration = self.last_tick_time - timenow
        self.last_tick_time = timenow
        if abs(self.last_tick_duration - tick_duration) > 0.02:
            self.midi_tick_count = 0
            self.last_clock_time = timenow
            self.last_tick_duration = tick_duration
            return

        self.last_tick_duration = tick_duration
 
        # If we got here, we got 12 ticks in a row. Update the clock
        if self.midi_tick_count % 24 == 0:
            self.midi_tick_count = 0
                
            if self.last_clock_time != 0:
                quarter_note_time = (timenow - self.last_clock_time)
                new_bpm = 60 / quarter_note_time
                new_bpm = round(new_bpm, 0)
                self.last_4_BPMs.pop(0)
                self.last_4_BPMs.append(new_bpm)
                #print(f"last 4 BPMs: {self.last_4_BPMs}")

                # # Get rid of outlier
                # outlier_amt = abs(new_bpm - (sum(self.last_4_BPMs) / 4))
                # print(f"outlier_amt: {outlier_amt}")
                # if outlier_amt > 3:
                #     print(f"outlier detected: {outlier_amt}")
                #     return
                
                # determine if at least 3 of the last 4 BPMs are the same
                same_bpm = False
                count = 0
                for bpm in self.last_4_BPMs:
                    count = self.last_4_BPMs.count(bpm)
                    
                if count >= 3:
                    same_bpm = True
                
                if same_bpm:
                    for bpm in self.last_4_BPMs:
                        outlier_amt = abs(bpm - (sum(self.last_4_BPMs) / 4))
                        if outlier_amt > 3:
                            #print(f"outlier detected: {outlier_amt}")
                            return

                if same_bpm:
                    average_bpm = round(sum(self.last_4_BPMs) / 4)
                    self.update_all_timings(average_bpm)
                    print(f"bpm: {self.bpm_current}") 

            self.last_clock_time = timenow
        return

    def get_note_time(self, note_type):
        """
        Returns the time duration of a given note type.

        Args:
            note_type (str): The type of note. Valid values are "whole" or "1" for whole note,
                             "half" or "1/2" for half note, "quarter" or "1/4" for quarter note,
                             "eighth" or "1/8" for eighth note, "sixteenth" or "1/16" for sixteenth note,
                             "thirtysecond" or "1/32" for thirty-second note.

        Returns:
            float: The time duration of the note in seconds.
        """
        if note_type == "whole" or note_type == "1":
            return self.wholetime_time
        if note_type == "half" or note_type == "1/2":
            return self.halfnote_time
        if note_type == "quarter" or note_type == "1/4":
            return self.quarternote_time
        if note_type == "eighth" or note_type == "1/8":
            return self.eighthnote_time
        if note_type == "sixteenth" or note_type == "1/16":
            return self.sixteenthnote_time
        if note_type == "thirtysecond" or note_type == "1/32":
            return self.sixteenthnote_time / 2
        return self.quarternote_time

clock = Clock()
