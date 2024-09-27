
# Usage Examples
from chordmanager import chord_manager
from midi import (change_midi_channel, 
                  set_all_midi_velocities, 
                  set_midi_velocity_by_idx, 
                  send_midi_note_on, 
                  send_midi_note_off,
                  shift_all_notes_octaves,
                  send_cc_message)
import settings
import board
import digitalio
import analogio
import rotaryio
import neopixel


"""

Instructions:
- Perform setup for your addons - initialize buttons, etc
- Create functions that do what you want. Some examples are below.
- Call your functions in the appropriate places in the code below.
    * handle_new_notes_on() - Triggered when a new note is played
    * handle_new_notes_off() - Triggered when a note is stopped


chord_manager.toggle_chord_by_index(idx) # Turns chord on / off
set_all_midi_velocities(velocity)        # Set all velocities
shift_all_notes_octaves(dir, octaves)    # Shift all notes by a certain amount
change_midi_channel(channel)             # Change midi channel
settings.midi_sync = True                # Enable midi sync
settings.set_next_arp_length()           # Set next or prev arp length
settings.arpeggiator_length("1/8")       # Set arp length
settings.arpeggiator_type("up")          # Set arp type
.... see src/settings for full list of settings

"""


# ------------- User Addons Setup -------------

"""
AVAILABLE GPIO PINS

    - GP26, GP27, GP28, GP29 (Analog)
    - GP0, GP9, GP14, GP20, GP21, GP22, GP23, GP24, GP25 (Digital)

EXAMPLES

    # Extra Neopixels
    extra_neopixels = neopixel.NeoPixel(board.GP14,16,brightness = 0.8)

    # Button
    button = digitalio.DigitalInOut(GP0)
    button.direction = digitalio.Direction.INPUT
    button.pull = digitalio.Pull.UP

    # Encoder
    encoder = rotaryio.IncrementalEncoder(board.GP0, board.GP1)

    # Potentiometer
    potentiometer = analogio.AnalogIn(board.GP26)

    # X/Y Joystick
    x_axis = analogio.AnalogIn(board.GP26)
    y_axis = analogio.AnalogIn(board.GP27)

    # Photoresistor
    photoresistor = analogio.AnalogIn(board.GP26)

"""

# Neopixels
extra_neopixels = neopixel.NeoPixel(board.GP25,16,brightness = 0.8)

# XY Joystick
x_axis = analogio.AnalogIn(board.GP26)
y_axis = analogio.AnalogIn(board.GP27)
x_midival_prev = 0
y_midival_prev = 0
change_threshold = 3  # MIDI value not raw value

def check_joystick():
    global x_val_prev, y_val_prev, x_midival_prev, y_midival_prev

    x_val = x_axis.value
    y_val = y_axis.value
    x_midival =  int((x_val / 65535) * 127)
    y_midival = int((y_val / 65535) * 127)
    x_midival_delta = abs(x_midival - x_midival_prev)
    y_midival_delta = abs(y_midival - y_midival_prev)

    if x_midival_delta > change_threshold and x_midival != x_midival_prev:
        set_all_midi_velocities(x_midival, False)
        print(f"X: {x_midival}")


    x_midival_prev = x_midival
    y_midival_prev = y_midival



# ------------- define User Addons Functions -------------

"""
EXAMPLES
!! note that these do not do validation in order to keep it simple. !!

# 1) Change midi channel with encoder
     - note that you would need to add a check to ensure the channel is between 0 and 15

    def change_midi_channel_with_encoder():
        if encoder.direction == 1:
            settings.midi_channel_out += 1
        else:
            settings.midi_channel_out -= 1
        change_midi_channel(settings.midi_channel_out)

# 2) Change all midi velocities with potentiometer
     - See https://github.com/derrickthomin/DJBB-Mini-Midi-Slider-51/blob/main/src/sliders.py
        for an example of how to track potentiometer changes so that
        you only send a message when the value changes by significant amount

    def change_all_midi_velocities_with_potentiometer():
        velocity = potentiometer.value // 16
        set_all_midi_velocities(velocity)

# 3) Turn on/off neopixels at index when new note is played or stopped

    def handle_new_notes_on(noteval, velocity, padidx):
        extra_neopixels[padidx] = (255, 255, 255) # White
    
    def handle_new_notes_off(noteval, velocity, padidx):
        extra_neopixels[padidx] = (0, 0, 0) # Black / Off

# 4) Shift all notes up when button is held down
    
        def shift_all_notes_up():
            shift_all_notes_octaves("up", 1)
    
        def shift_all_notes_down():
            shift_all_notes_octaves("down", 1)
    
        def check_addons_fast():
            if button.value:
                shift_all_notes_up()
            else:
                shift_all_notes_down() 


"""

def handle_new_notes_on_extra_pixels(padidx):
    extra_neopixels[padidx] = (255, 255, 255) # White

def handle_new_notes_off_extra_pixels(padidx):
    extra_neopixels[padidx] = (0, 0, 0) # Black / Off
# ------------- Place functions in one of the hooks below -------------

# Runs as fast as possible in main loop. Dont put anything that takes a long time here.
def check_addons_fast():

    # Call your functions here...

    pass

# Runs on a metered interval in the main loop. Do less critical or time sensitive things here.
def check_addons_slow():
    
    # Call your functions here...
    check_joystick()

    pass

def handle_new_notes_on(noteval, velocity, padidx):

    # Call your functions here...
    handle_new_notes_on_extra_pixels(padidx)

    pass

# Trigger a function when a new note off is played
def handle_new_notes_off(noteval, velocity, padidx):

    # Call your functions here...
    handle_new_notes_off_extra_pixels(padidx)

    pass

