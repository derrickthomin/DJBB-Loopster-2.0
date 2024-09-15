WORK IN PROGRESS. No guarantees that this code even works in the current state as I'm using this as basically a personal repo and constantly updating things / breaking things.

But I wanted to share it in case it gives folks ideas. Eventually it'll be tight. 

### key features

- **Versatile Arpeggiator**: Supports various arpeggiator types (e.g., up, down, random, random octave, random start). Has settings for arp note length (gate) and polyphony mode.
- **Chord Management**: Add, record, and delete chords on 16 pads with LED feedback. Compatible with arpeggiator - hold chord button and turn encoder to arpeggiate through chord notes. Chords can be loops or one-shot.
- **MIDI I/O**: USB and DIN midi input and output. Record midi from other sources into chords. BPM and start/stop sync.
- **Menu Navigation**: Intuitive menu system for various settings (play, scale select, looper, MIDI settings, etc.).
- **Visual Feedback**: LEDs indicate recording, playback, chord states, and navigation modes.
- **Preset Management**: Load and save presets with dedicated menus.
- **Lock and Navigation Mode**: Toggle lock mode to prevent accidental changes and switch between modes.
- **Encoder and Button Interactions**: Handle various interactions including encoder changes, button presses, double presses, and held actions.
- **Extra GPIOs broken out - add other inputs/outputs**: For advanced users. Option to add extra buttons, sliders, neopixels, or whatever to customize.

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
- **check_addons_slow()**: runs on a metered interval. suitable for less critical or time-sensitive tasks.
- **handle_new_notes_on(noteval, velocity, padidx)**: triggered when a new note is played.
- **handle_new_notes_off(noteval, velocity, padidx)**: triggered when a note is stopped.

#### usage example:
```python
# ------------- place functions in one of the hooks below -------------

# runs as fast as possible in main loop. don't put anything that takes a long time here.
def check_addons_fast():
    # call your functions here...
    # change_midi_channel_with_encoder()
    pass

# runs on a metered interval in the main loop. do less critical or time-sensitive things here.
def check_addons_slow():
    # call your functions here...
    # change_all_midi_velocities_with_potentiometer()
    pass

# trigger a function when a new note is played
def handle_new_notes_on(noteval, velocity, padidx):
    # call your functions here...
    # extra_neopixels[padidx] = (255, 255, 255) # white
    pass

# trigger a function when a new note off is played
def handle_new_notes_off(noteval, velocity, padidx):
    # call your functions here...
    # extra_neopixels[padidx] = (0, 0, 0) # black/off
    pass
```

### example usage:
```python
# control neopixels with note events
def handle_new_notes_on(noteval, velocity, padidx):
    extra_neopixels[padidx] = (255, 255, 255) # white

def handle_new_notes_off(noteval, velocity, padidx):
    extra_neopixels[padidx] = (0, 0, 0) # black/off
```

By placing your custom functions into these hooks, you can extend the functionality of the Midi Loopster 2.0 to meet your specific needs. With these extra GPIOs and customizable options, you can tailor the capabilities of the Midi Loopster 2.0 to suit your creative workflow perfectly.
