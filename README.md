# DJBB MIDI Loopster 2.0

<div align="center">
<img src="https://github.com/user-attachments/assets/4930370d-5dd5-4f4c-8192-4d0b70316c29" alt="DJBB MIDI Loopster 2.0 - Light case with cloudy buttons" width="500px">
</div>

### Demo Vid Links
See my YouTube channel here for some vids of the Loopster in action: https://www.youtube.com/channel/UCpsQPNVT-AlGA7DJ-ZlrxLw

### key features

- **Record and Play MIDI Loops**: Record notes, CC messages, and aftertouch (channel pressure) on 16 pads with LED feedback. Loop, one-shot, or hold modes with arpeggiator compatibility. Optional flash storage for extended CC capacity.
- **MIDI I/O**: USB and DIN MIDI (full sized) input/output with improved sync and passthrough option. Visual indicators for incoming MIDI data.
- **Unique Arpeggiator**: Use encoder to scroll through arps. Supports various arpeggiator types (up, down, random, etc.) with gate and polyphony settings. Works with notes and CCs, respects per-pad MIDI channel assignments.
- **Scale Filtering**
- **Visual Feedback via Per Pad RGB LEDs**
- **Preset Management**: Load and save complete presets including recorded loops for session recall.
- **Per-Pad Loop MIDI Assignment**
- **Extra GPIOs**: Breakout pins for custom buttons, encoders, neopixels, and other add-ons.

### using extra GPIOs for customization

The Midi Loopster 2.0 includes additional GPIO pins, allowing users to expand and customize their setup with extra buttons, encoders, potentiometers, neopixels, and more. This flexibility enables users to tailor the device to their specific needs and creative preferences.

#### available GPIO pins:
- **analog**: GP26, GP27, GP28, GP29
- **digital**: GP0, GP9, GP14, GP20, GP21, GP22, GP23, GP24, GP25

#### addon input/output examples:
```python
# extra neopixels
extra_neopixels = neopixel.NeoPixel(board.GP14, 16, brightness=0.8)

# button
button = digitalio.DigitalInOut(board.GP0)
button.direction = digitalio.Direction.INPUT
button.pull = digitalio.Pull.UP

# encoder
encoder = rotaryio.IncrementalEncoder(board.GP0, board.GP1)

# potentiometer
potentiometer = analogio.AnalogIn(board.GP26)

# x/y joystick
x_axis = analogio.AnalogIn(board.GP26)
y_axis = analogio.AnalogIn(board.GP27)

# photoresistor
photoresistor = analogio.AnalogIn(board.GP26)
```

### adding custom code to hooks

The Midi Loopster 2.0 allows you to integrate custom functions by placing them into predefined hooks. This ensures that your custom logic runs at the appropriate times during the device's operation.

#### available hooks:
- **check_addons_fast()**: runs as fast as possible in the main loop. ideal for time-sensitive tasks.
- **slow()**: runs on a metered interval. suitable for less critical or time-sensitive tasks.
- **handle_new_notes_on(noteval, velocity, padidx, midi_channel)**: triggered when a new note is played.
- **handle_new_notes_off(noteval, velocity, padidx, midi_channel)**: triggered when a note is stopped.
- **handle_new_cc(cc_num, cc_val, midi_channel)**: triggered when a CC message is sent.

#### usage example:
```python
# ------------- place functions in one of the hooks below -------------

# runs as fast as possible in main loop. don't put anything that takes a long time here.
def check_addons_fast():
    # call your functions here...
    # change_midi_channel_with_encoder()
    pass

# runs on a metered interval in the main loop. do less critical or time-sensitive things here.
def slow():
    # call your functions here...
    # change_all_midi_velocities_with_potentiometer()
    pass

# trigger a function when a new note is played
def handle_new_notes_on(noteval, velocity, padidx, midi_channel):
    # call your functions here...
    # extra_neopixels[padidx] = (255, 255, 255) # white
    pass

# trigger a function when a new note off is played
def handle_new_notes_off(noteval, velocity, padidx, midi_channel):
    # call your functions here...
    # extra_neopixels[padidx] = (0, 0, 0) # black/off
    pass
```

### example usage:
```python
# control neopixels with note events
def handle_new_notes_on(noteval, velocity, padidx, midi_channel):
    extra_neopixels[padidx] = (255, 255, 255) # white

def handle_new_notes_off(noteval, velocity, padidx, midi_channel):
    extra_neopixels[padidx] = (0, 0, 0) # black/off
```

By placing your custom functions into these hooks, you can extend the functionality of the Midi Loopster 2.0 to meet your specific needs. With these extra GPIOs and customizable options, you can tailor the capabilities of the Midi Loopster 2.0 to suit your creative workflow perfectly.

### All available examples
see [examples/useraddons_examples.py](examples/useraddons_examples.py) for details

| Example                              | Description                                                                                  |
|--------------------------------------|----------------------------------------------------------------------------------------------|
| Neopixels                            | Control Neopixel LEDs to display colors based on MIDI notes.                                 |
| XY Joystick                          | Use an analog joystick to control MIDI velocities or other parameters.                       |
| Button for Shifting Octaves          | Use a button to shift all MIDI notes up or down by octaves.                                  |
| Potentiometer for Changing All MIDI Velocities | Adjust all MIDI velocities with a potentiometer.                                 |
| Encoder for Changing MIDI Channels   | Change MIDI channels using a rotary encoder.                                                 |
| Photoresistor for Changing All MIDI Velocities | Adjust all MIDI velocities based on ambient light levels using a photoresistor. |
| Motor Control using PWM              | Control a DC motor using PWM signals based on MIDI input.                                    |
| Piezo Buzzer using PWM               | Play tones on a piezo buzzer based on MIDI notes.                                            |
| Temperature Sensor                   | Read temperature values from a DHT22 sensor and display or use them in MIDI control.         |
| Relay Switches                       | Control relay switches to turn devices on or off based on MIDI input.                        |
| PIR Sensor                           | Detect motion using a PIR sensor and trigger MIDI actions.                                   |
| Accelerometer (GY-521 MPU6050 Module)| Use an accelerometer to send MIDI control changes based on movement.                         |
| 7 Segment Display (i2c)    | Display numbers or values on a 7-segment display.                                            |
| DC Motor as a modulation source  | Read voltage from a DC motor and convert it to MIDI values                              |

---

### Changelog 
#### February 2026 (Version 2.41)
Download here: https://github.com/derrickthomin/DJBB-Loopster-2.0/releases/tag/2.41

- Larger loop limits in RAM
- Snappier menu navigation
- Architectural change: Now most code is baked into the new loopster.uf2. More RAM overhead.


#### January 2026 (Version 2.4)
##### New Features
- Hold Mode for Loops: New loop type that plays while pad is held and stops on release. Cycle through: loop → oneshot → hold.
- Flash Storage for Loops: Optional "CC to Flash" setting streams CC data to flash during recording, enabling ~10x more events than RAM storage.
- CC Snapback: New setting controls whether CC values reset to initial values when loops stop. Options: none, hold-only, or all loops.
- Settings Page Numbers: Settings screens now show page indicators (e.g., "1/13") for easier navigation.
- Aftertouch Recording: Records and plays back channel pressure (aftertouch) messages with loops. Supports flash storage for large recordings.
- Per Note MIDI Channel Mode: Records and plays back notes on their original MIDI channel

##### Enhancements
- MIDI Passthrough Optimization: Sends raw bytes instead of reconstructing MIDI objects for lower latency.
- Per-Event MIDI Channel Storage: MIDI channel stored per-event, allowing multi-channel recording into a single loop.
- Simplified Clock Source: Removed "AUTO" option; now only "USB" and "AUX" available.
- Memory Optimizations
- Synchronized Blinking: All blinking LEDs now blink in sync for cleaner visual feedback
- ALL Channels Input: New option to receive MIDI on all channels simultaneously
- Bank Offset Indicator: Display shows "+" suffixes (e.g., "Bank: 3+") when using quarter-bank navigation.
  
##### Bug Fixes
- MIDI Sync Fixes: Fixed queued recording starting early, blink state sync issues, and stuck pixels when sync enabled.
- Note Handling: Fixed held notes not closing on recording stop, and Note On velocity=0 now treated as Note Off (DX7 compatibility).
- Arpeggiator: Fixed notes not clearing when individual pad released.
- Navigation: Fixed quarter-bank navigation overflowing past bank boundaries.
- Loop Type Toggle: Fixed cycling desync when toggling backwards.
- FN Button: Fixed double-click counter not resetting properly.
- MIDI Continue Support: Properly handles MIDI Continue message for seamless transport control

##### Breaking Changes
- CSV chord storage format replaced with binary loop format. Old /chords/ directory no longer supported.
- USB device name changed from "LOOPSTER 2" to "LOOPSTER".
- "Startup Menu" setting removed.

#### June 2025 (Version 2.2)
##### New Features
- CC Recording: Loopster can now record and send CC messages just like notes - loop, oneshot, and arpeggiate them
- Midi Passthru: New setting to allow passing midi from the input directly back out.
- Preset Updates: Loops recorded to pads are now saved with presets
- Per Pad Loop Midi Assignment: Assign loops recorded to pads to different midi channels. Also respected by the arpeggiator.
- Quarter Bank Navigation: Hold FN and click the encoder to go up 1/4 of a bank, and the opposite to go down.
- New Oneshot Setting: Can change the behavior so that in oneshot mode, all notes are played at once (rather than in sequence).
- Quick Multi Chord Recording: Keep holding the FN button while recording a chord to a pad and press another pad to switch to recording to the new one. Only makes sense if recording to pads from an external source.


##### Optimizations
- (undocumented from prev update) Loopster is now 2X faster: RP2040 can safely be overclocked to double. Everything feels snappier, and timings are tighter.
- Expanded Event Capacity: Now you can record up to 500 notes or 1500 CC events per loop, and 5000 across all loops.
- Better MIDI Sync: More accurate clock, better handling of start and stop messages
- UI Improvements: Removed menu loop around behavior, optimized screen refreshes, and a bunch of other stuff
- Removed Looper Menu: Duplicitive since we can record to pads in a more flexible way. Downside is that there is no longer a way to overdub, though you can always "overdub" by just recording to a new pad
- Clock Source Detection: Wherever clock is received first is defaulted (USB vs DIN)
- Smarter Loop Type Assignment: Rather than always use what is in settings, if you change a loop to "oneshot", for example, the next recorded loop will be set to "oneshot" as well (or whatever the last loop type used was)
- Optimized "hold" Lenghts: FN button counts as "held" much faster so you can quickly start recording a chord.
- Auto Delete Empty Recordings: If a pad was recorded to but only contains off messages, or nothing at all, it will be auto deleted when recording is stopped.
- Updated Velocity Mode Colors: Now using a red scheme as to not conflict with note (yellow), playing (green), or CC (blue) colors.
- Major Code Refactoring: Easier to navigate and more efficient. Split out huge files into smaller ones (ie pixels.py), reduced use of global variables, and a bunch of other small stuff.
- Memory Improvements: Smarter generation of scales, earlier returns, etc. in order to save on RAM, which is what allowed us to greatly expand the event recording limits mentioned in the new features section above.
- Removed Useless Notifications: Displaying a notification on the screen costs ~30 ms. Since we have LEDs (as opposed to the loopster 1 which did not), we don't need to rely on the screen as much.
- Renamed "chord" to "loop" for clarity: Now the loop types are "loop" and "oneshot"
- MIDI I/O Indicators: Encoder button flashes yellow (note) or blue (cc) when external midi is coming in.


