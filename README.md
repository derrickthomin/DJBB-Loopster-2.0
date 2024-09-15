WORK IN PROGRESS. No guarantees that this code even works in the current state as I'm using this as basically a personal repo and constantly updating things / breaking things.

But I wanted to share it in case it gives folks ideas. Eventually it'll be tight. 


### using extra gpios for customization

our midi drumpad device comes equipped with additional gpio pins, allowing users to expand and customize their setup with extra buttons, encoders, potentiometers, neopixels, and more. this flexibility empowers users to tailor the device to their specific needs and creative preferences.

#### available gpio pins:
- **analog**: gp26, gp27, gp28, gp29
- **digital**: gp0, gp9, gp14, gp20, gp21, gp22, gp23, gp24, gp25

#### Addon input/output examples:
```python
# extra neopixels
extra_neopixels = neopixel.neopixel(board.gp14, 16, brightness=0.8)

# button
button = digitalio.digitalinout(board.gp0)
button.direction = digitalio.direction.input
button.pull = digitalio.pull.up

# encoder
encoder = rotaryio.incrementalencoder(board.gp0, board.gp1)

# potentiometer
potentiometer = analogio.analogin(board.gp26)

# x/y joystick
x_axis = analogio.analogin(board.gp26)
y_axis = analogio.analogin(board.gp27)

# photoresistor
photoresistor = analogio.analogin(board.gp26)
```

### adding custom code to hooks

our midi drumpad device allows you to integrate your custom functions by placing them into predefined hooks. this ensures that your custom logic runs at the appropriate times during the device's operation.

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
# ....

# control neopixels with note events
def handle_new_notes_on(noteval, velocity, padidx):
    extra_neopixels[padidx] = (255, 255, 255) # white

def handle_new_notes_off(noteval, velocity, padidx):
    extra_neopixels[padidx] = (0, 0, 0) # black/off
```

by placing your custom functions into these hooks, you can extend the functionality of your midi drumpad device to meet your specific needs.
with these extra gpios and customizable options, you can extend the capabilities of your midi drumpad device to suit your creative workflow perfectly.

