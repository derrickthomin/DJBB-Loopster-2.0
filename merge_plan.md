# Merge Plan: Main ↔ Colm-Customization Branch

**Date:** December 1, 2025  
**Branches compared:**
- `main` (latest commit: `16b6e2d` - "New features - note level midi channel")
- `Colm-Customization` (latest commit: `d750c46` - "Add Hold Setting")

**Common ancestor:** `97bd142` ("Updated Manual")

---

## 📋 Summary

The branches diverged after the "Updated Manual" commit. Each branch has unique features:

| Branch | Commits Since Divergence | Key Features |
|--------|-------------------------|--------------|
| main | 1 commit | Per-note MIDI channel, MIDI Continue support, channel mode settings, BPM filtering |
| Colm-Customization | 5 commits | Hold loop type, accelerometer arp control, optimizations |

---

## ⚠️ HARDWARE-SPECIFIC CODE (DO NOT PORT TO MAIN)

These files/features exist ONLY for Colm's custom hardware build and should **NOT** be merged to main:

### New Files (Colm-only)
- `src/pedals.py` - Foot pedal hardware control (5 pedals with NeoPixels)
- `ACCELEROMETER_CLASS_SUMMARY.md` - Documentation for accelerometer

### constants.py Additions (Colm-only)
```python
# Hardware flags
USING_FOOT_PEDALS = True
USING_GLOVE_BUTTONS = True  
USING_ACCELEROMETER = True
USING_MOTOR_FEEDBACK = True

# Accelerometer I2C pins and settings
ACCEL_I2C_SCL = board.GP27
ACCEL_I2C_SDA = board.GP26
ACCEL_LEFT_TILT_CC, ACCEL_RIGHT_TILT_CC, etc.

# Glove button pins
GLOVE_LEFT_PIN = board.GP23
GLOVE_RIGHT_PIN = board.GP24

# Pedal pins
PEDAL_1_PIN through PEDAL_5_PIN
PEDAL_NEOPIXEL_PIN = board.GP14

# Motor haptic feedback
MOTOR_PWM_PIN = board.GP28
```

### useraddons.py Overhaul (Colm-only)
The Colm branch has a complete rewrite with:
- `MotorController` class - Haptic feedback via PWM motor
- `AccelerometerController` class - Tilt-based CC and arpeggiator control
- `check_glove_buttons()` - Glove button bank switching
- Pedal integration

### inputs.py Hardware Integration (Colm-only)
- Imports `pedals` module
- Imports `useraddons` for accelerometer
- `process_keymatrix()` now processes pedal events alongside regular keypad
- Calls `useraddons.should_trigger_accelerometer_arp()` for arp triggering

---

## ✅ FEATURES TO PORT: Main → Colm-Customization

These are general features from main that should be ported to Colm:

### 1. Per-Note MIDI Channel System (HIGH PRIORITY)
**Files:** `midi.py`, `settings.py`, `code.py`, `looper.py`, `chordmanager.py`, `inputs.py`, `arp.py`

Main introduces `midi_channel_mode` setting with options:
- `"per_note"` - Use stored channel from recording
- `"per_pad"` - Use pad-specific channel mapping
- `"global"` - Use global output channel

**Key changes:**
- Notes now store 5 elements: `(note, velocity, pad_idx, tick, midi_channel)`
- CC events store 4 elements: `(cc_num, value, tick, midi_channel)`  
- `pack_pad_channel()` / `unpack_pad_channel()` functions in looper.py
- `midi.send_note_on/off()` routes based on channel mode
- Chord file format updated to save/load MIDI channels

### 2. MIDI Input Channel "ALL" Mode
**Files:** `settings.py`, `midi.py`, `settingsmenu.py`

- `midi_channel_in` can be `-1` meaning "accept all channels"
- `should_accept_channel()` method filters incoming MIDI
- UI shows "ALL" option for input channel

### 3. MIDI Continue Support
**Files:** `midi.py`, `clock.py`

- Import and handle `adafruit_midi.midi_continue.Continue`
- `clock.continue_clock()` resumes without resetting tick count
- Treats Continue like Start for recording purposes

### 4. BPM Stability Filtering
**Files:** `clock.py`

- `pending_bpm` variable filters glitchy BPM changes
- Requires same BPM reading twice before applying
- Ignores ±1 BPM fluctuations (measurement noise)

### 5. Arpeggiator Per-Note Channel Support
**Files:** `arp.py`

- Arp notes now include midi_channel in tuple
- `remove_arp_note()` and `remove_arp_cc()` methods for proper cleanup
- Index clamping on removal to prevent crashes

### 6. Armed Recording State
**Files:** `chordmanager.py`

- `recording_is_armed` flag for MIDI sync mode
- Recording waits for transport start when MIDI sync enabled
- `start_armed_recording()` method triggers on transport start
- Visual feedback: blinking red = armed, solid red = recording

---

## ✅ FEATURES TO PORT: Colm-Customization → Main

These features from Colm should be ported to main (excluding hardware-specific code):

### 1. "Hold" Loop Type (HIGH PRIORITY)
**Files:** `chordmanager.py`, `inputs.py`, `settingsmenu.py`

A new loop type where the loop plays ONLY while the pad is held:
- `toggle_chord_playstate()` accepts `force_play` and `force_stop` parameters
- On pad press: `force_play=True`
- On pad release: `force_stop=True`
- Recording finishes in stopped state for hold mode

### 2. Encoder Steps Per Arp Note Setting
**Files:** `arp.py`, `settings.py`

- `encoder_steps_per_arpnote` setting (1 = every turn, 2 = every other turn, etc.)
- `skip_this_turn()` method in arpeggiator
- `encoder_step_counter` tracking

### 3. Manual Button Event Processing
**Files:** `buttons.py`

- `process_keymatrix_event()` accepts optional `manual_event` parameter
- Allows programmatic button presses/releases (useful for pedal integration)
- Values: `"pressed"` or `"released"`

---

## 🔄 STRUCTURAL DIFFERENCES (Need Manual Resolution)

### Note Tuple Format Conflict
| Branch | Note Format |
|--------|-------------|
| Main | `(note, vel, pad_idx, tick, midi_channel)` - 5 elements |
| Colm | `(note, vel, pad_idx, tick)` - 4 elements |

**Resolution:** Main's 5-element format should be adopted in Colm.

### Menu Index Constants
| Branch | Approach |
|--------|----------|
| Main | Uses `C.MENU_PLAY`, `C.MENU_SCALE`, etc. constants |
| Colm | Uses raw integers `0`, `1`, `2` |

**Resolution:** Main's approach is cleaner, adopt constants.

### Import Statement for settings
| Branch | Import Style |
|--------|-------------|
| Main | `from settings import settings as s` |
| Colm | `from settings import settings` |

**Resolution:** Cosmetic, but consistency preferred.

---

## ❓ QUESTIONS FOR YOU

1. **Hold Mode Priority:** Should hold mode be available for all users in main, or is it specific to Colm's workflow?

2. **Encoder Steps Setting:** Is the "encoder steps per arp note" feature useful for the general firmware, or was this specifically for accelerometer control?

3. **Armed Recording:** The main branch has "armed recording" where recording waits for transport in MIDI sync mode. The Colm branch removed this. Which behavior do you prefer?
   - Main: Recording is armed on pad hold, starts on transport start
   - Colm: Recording starts immediately on pad hold

4. **BPM Filtering:** Main has BPM stability filtering (waits for confirmation). Colm doesn't. Include in both?

5. **MIDI Channel Mode Default:** Main defaults to `"per_note"` channel mode. Is this the desired default for everyone?

6. **Pedal Bank System:** The pedal system has a "bank" concept (0-2) allowing 15 pads via 5 pedals. Should any of this bank-switching UI/logic be preserved in a way that could work without the pedals?

---

## 📝 Recommended Merge Order

### Phase 1: Port Main → Colm (Non-breaking)
1. Add per-note MIDI channel system
2. Add MIDI Continue support  
3. Add BPM filtering
4. Add armed recording state
5. Update note/CC tuple formats

### Phase 2: Port Colm → Main (After your answers)
1. Add Hold loop type (if desired)
2. Add encoder steps per arp note setting (if desired)
3. Add manual button event parameter

### Phase 3: Cleanup
1. Standardize menu index constants
2. Standardize import style
3. Test both branches thoroughly

---

## 📁 Files Changed Summary

| File | Main Changes | Colm Changes | Conflict Level |
|------|-------------|--------------|----------------|
| `arp.py` | Channel support, remove methods | Skip turn, encoder step counter | Medium |
| `buttons.py` | Cleanup | Manual event parameter | Low |
| `chordmanager.py` | Armed recording, channel support | Hold mode, force play/stop | High |
| `clock.py` | Continue, BPM filter, pending_bpm | Simpler, no filtering | Medium |
| `code.py` | Channel routing in process_notes/cc | Accelerometer integration | High |
| `constants.py` | Menu constants | Hardware pins/flags | Low (separate sections) |
| `inputs.py` | Channel mode handling, cleanup | Pedal integration, accelerometer | High |
| `looper.py` | pack/unpack channel, 5-element tuples | process_cc_values rename | High |
| `midi.py` | Channel mode, Continue, accept filter | Simpler channel handling | High |
| `settings.py` | channel_mode, channel_in=-1 | encoder_steps_per_arpnote | Low |
| `settingsmenu.py` | Channel mode UI | Hold mode option | Low |
| `useraddons.py` | Empty hooks | Full accelerometer/motor/glove code | N/A (keep separate) |
| `pedals.py` | N/A (doesn't exist) | Full pedal system | N/A (Colm only) |
