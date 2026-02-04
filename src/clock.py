import ticks_minimal as ticks
from settings import settings

class Clock:
    """MIDI clock: tracks ticks, BPM, and note durations."""

    MILLISECONDS_TO_SECONDS = 1000.0
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
        self.pending_bpm = None  # BPM waiting for confirmation (filters glitches) 

    def reset_midi_tick_count(self):
        self.midi_ticks_elapsed = 0

    def set_bpm(self, bpm):
        quarternote_duration = 60 / bpm
        self.bpm_current = bpm
        self.seconds_per_tick = 60 / (self.bpm_current * self.TICKS_PER_QUARTER_NOTE)
        self.quarternote_duration = quarternote_duration
        self.halfnote_duration = quarternote_duration * 2
        self.wholenote_duration = quarternote_duration * 4
        self.eighthnote_duration = quarternote_duration / 2
        self.sixteenthnote_duration = quarternote_duration / 4
        
    def reset_new_tick_flag(self):
        self.new_tick = False

    def update_clock(self):
        """Update on new MIDI clock tick. Calculates BPM from tick intervals."""
        self.new_tick = True
        self.midi_ticks_elapsed += 1

        timenow = ticks.ticks_ms()
        self.last_tick_time = timenow

        if self.midi_ticks_elapsed % self.TICKS_PER_WHOLE_NOTE == 0:
            whole_note_time = ticks.ticks_diff(timenow, self.last_whole_note_time) / self.MILLISECONDS_TO_SECONDS
            self.last_whole_note_time = timenow
            
            if whole_note_time > 0:
                new_bpm = round(60 * 4 / whole_note_time) # Divide by 4 to get the BPM from whole note time
            else:
                new_bpm = 0

            if new_bpm != self.bpm_current and new_bpm > 0:
                # Ignore ±1 BPM fluctuations (measurement noise from timing jitter)
                if abs(new_bpm - self.bpm_current) <= 1:
                    self.pending_bpm = None
                elif new_bpm == self.pending_bpm:
                    if settings.debug:
                        print(f"[DEBUG] BPM changed: {self.bpm_current} -> {new_bpm}")
                    self.set_bpm(new_bpm)
                    self.pending_bpm = None
                else:
                    # First time seeing this value, wait for confirmation
                    self.pending_bpm = new_bpm
            else:
                # Current BPM is stable, clear any pending
                self.pending_bpm = None

    def seconds_to_ticks(self, seconds, bpm=None):
        """Convert seconds to MIDI ticks. Uses current BPM if not specified."""
        if bpm:
            seconds_per_tick = 60 / (bpm * self.TICKS_PER_QUARTER_NOTE)
        else:
            seconds_per_tick = self.seconds_per_tick
        return int(round(seconds / seconds_per_tick))
    
    def ticks_to_seconds(self, ticks, bpm=None):
        """Convert MIDI ticks to seconds. Uses current BPM if not specified."""
        if bpm:
            seconds_per_tick = 60 / (bpm * self.TICKS_PER_QUARTER_NOTE)
        else:
            seconds_per_tick = self.seconds_per_tick
        return ticks * seconds_per_tick

    def get_note_duration_seconds(self, note_type):
        """Get duration in seconds for note type (e.g., 'quarter', '1/4', 'whole')."""
        note_times_seconds = {
            "whole": self.wholenote_duration,
            "1": self.wholenote_duration,
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
        self.is_playing = True
        self.reset_midi_tick_count()
        self.last_whole_note_time = ticks.ticks_ms()  # Fresh timing reference
        self.pending_bpm = None  # Clear any pending BPM
        self.new_tick = True

    def continue_clock(self):
        """Resume clock without resetting tick count (MIDI Continue)."""
        self.is_playing = True
        self.last_whole_note_time = ticks.ticks_ms()  # Fresh timing reference for BPM
        self.pending_bpm = None  # Clear any pending BPM to avoid glitches
        # Don't reset midi_ticks_elapsed - Continue resumes from current position
    
    def stop_clock(self):
        self.is_playing = False
        # Don't reset midi_ticks_elapsed - needed for recording finalization
        # when Stop is received before toggle_record_state() calculates total_midi_ticks

    def get_playstate(self):
        return self.is_playing

clock = Clock()