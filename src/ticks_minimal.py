# Minimal ticks replacement - saves ~2-3KB vs adafruit_ticks
# Drop-in replacement for adafruit_ticks with same API
# Safe for intervals under ~6 days (no wraparound handling needed)

import time

def ticks_ms():
    """Return milliseconds since boot."""
    return int(time.monotonic() * 1000)

def ticks_diff(ticks1, ticks2):
    """Return signed difference between two ticks values."""
    return ticks1 - ticks2

def ticks_add(ticks, delta):
    """Add delta to ticks value."""
    return ticks + delta

def ticks_less(ticks1, ticks2):
    """Return True if ticks1 is before ticks2."""
    return ticks1 < ticks2
