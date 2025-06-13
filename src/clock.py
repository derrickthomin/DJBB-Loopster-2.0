import adafruit_ticks as ticks

# DJT AI - check that documentation is up to date with the code
class Clock:
    """
    A class that represents the synchronization data for MIDI clock.
    """

    MILLISECONDS_TO_SECONDS = 1000.0
    BPM_OUTLIER_THRESHOLD = 3
    TICK_DURATION_THRESHOLD = 0.02
    TICKS_PER_QUARTER_NOTE = 24
    TICKS_PER_WHOLE_NOTE = TICKS_PER_QUARTER_NOTE * 4

    def __init__(self):
        self.midi_ticks_elapsed = 0                   
        self.last_tick_time = ticks.ticks_ms()
        self.bpm_current = 120.0
        self.set_bpm(self.bpm_current)
        self.is_playing = False
        self.last_whole_note_time = 0 
        self.new_tick = False 

    def reset_midi_tick_count(self):
        """
        Resets the MIDI tick count.
        """
        self.midi_ticks_elapsed = 0

    def set_bpm(self, bpm):
        """
        Updates all note timings based on the given BPM.
        """
        quarternote_duration = 60 / bpm
        self.bpm_current = bpm
        self.seconds_per_tick = 60 / (self.bpm_current * self.TICKS_PER_QUARTER_NOTE)
        self.quarternote_duration = quarternote_duration
        self.halfnote_duration = quarternote_duration * 2
        self.wholetime_duration = quarternote_duration * 4
        self.eighthnote_duration = quarternote_duration / 2
        self.sixteenthnote_duration = quarternote_duration / 4
        
    def reset_new_tick_flag(self):
        """
        Resets the new tick flag.
        """
        self.new_tick = False

    def update_clock(self):
        """
        Updates the clock and handles outliers. only called when new MIDI clock tick is received.
        """
        self.new_tick = True
        self.midi_ticks_elapsed += 1

        timenow = ticks.ticks_ms()
        self.last_tick_time = timenow

        # Update BPM Every Whole Note = 96 ticks 
        if self.midi_ticks_elapsed % self.TICKS_PER_WHOLE_NOTE == 0:
            whole_note_time = ticks.ticks_diff(timenow, self.last_whole_note_time) / self.MILLISECONDS_TO_SECONDS
            self.last_whole_note_time = timenow
            
            if whole_note_time > 0:
                new_bpm = round(60 * 4 / whole_note_time) # Divide by 4 to get the BPM from whole note time
            else:
                new_bpm = 0 

            if new_bpm != self.bpm_current and new_bpm > 0:
                self.set_bpm(new_bpm)
                self.bpm_current = new_bpm

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

clock = Clock()