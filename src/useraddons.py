from chordmanager import chord_manager
from midi import (change_midi_channel, set_all_midi_velocities, set_midi_velocity_by_idx, send_midi_note_on, send_midi_note_off, shift_all_notes_octaves, send_cc_message)
import settings
import board
import digitalio
import analogio
import rotaryio
import neopixel
import pwmio

"""
Instructions:
- Perform setup for your addons - initialize buttons, etc
- Create functions that do what you want. Some examples are below.
- Call your functions in the appropriate places in the code below.

* handle_new_notes_on() - Triggered when a new note is played
* handle_new_notes_off() - Triggered when a note is stopped

chord_manager.toggle_chord_by_index(idx) # Turns chord on / off
set_all_midi_velocities(velocity) # Set all velocities
shift_all_notes_octaves(dir, octaves) # Shift all notes by a certain amount
change_midi_channel(channel) # Change midi channel
settings.midi_sync = True # Enable midi sync
settings.set_next_arp_length() # Set next or prev arp length
settings.arpeggiator_length("1/8") # Set arp length
settings.arpeggiator_type("up") # Set arp type
.... see src/settings for full list of settings

AVAILABLE GPIO PINS
- GP26, GP27, GP28, GP29 (Analog)
- GP0, GP9, GP14, GP20, GP21, GP22, GP23, GP24, GP25 (Digital)
"""

# ------------- User Addons Setup -------------

# # 1) Neopixels

# extra_neopixels = neopixel.NeoPixel(board.GP25, 16, brightness=0.8)

# def handle_new_notes_on_extra_pixels(padidx):
#     extra_neopixels[padidx] = (255, 255, 255) # White

# def handle_new_notes_off_extra_pixels(padidx):
#     extra_neopixels[padidx] = (0, 0, 0) # Black / Off


# # 2) XY Joystick

# x_axis = analogio.AnalogIn(board.GP26)
# y_axis = analogio.AnalogIn(board.GP27)
# x_midival_prev = 0
# y_midival_prev = 0
# change_threshold = 3 # MIDI value not raw value

# def check_joystick():
#     global x_val_prev, y_val_prev, x_midival_prev, y_midival_prev
#     x_val = x_axis.value
#     y_val = y_axis.value
#     x_midival = int((x_val / 65535) * 127)
#     y_midival = int((y_val / 65535) * 127)
#     x_midival_delta = abs(x_midival - x_midival_prev)
#     y_midival_delta = abs(y_midival - y_midival_prev)
#     if x_midival_delta > change_threshold and x_midival != x_midival_prev:
#         set_all_midi_velocities(x_midival, False)
#         print(f"X: {x_midival}")
#     x_midival_prev = x_midival
#     y_midival_prev = y_midival


# # 3) Button for shifting octaves

# button = digitalio.DigitalInOut(board.GP0)
# button.direction = digitalio.Direction.INPUT
# button.pull = digitalio.Pull.UP

# def shift_all_notes():
#     if button.value:
#         shift_all_notes_octaves("up", 1)
#     else:
#         shift_all_notes_octaves("down", 1)


# # 4) Potentiometer for changing all MIDI velocities

# potentiometer = analogio.AnalogIn(board.GP28)
# prev_pot_value = 0

# def change_all_midi_velocities_with_potentiometer():
#     global prev_pot_value
#     pot_value = potentiometer.value // 512 # Scale to 0-127
#     if abs(pot_value - prev_pot_value) > change_threshold:
#         set_all_midi_velocities(pot_value)
#     prev_pot_value = pot_value


# # 5) Encoder for changing MIDI channels

# encoder = rotaryio.IncrementalEncoder(board.GP14, board.GP15)
# last_position = None

# def change_midi_channel_with_encoder():
#     global last_position
#     position = encoder.position
#     if last_position is None or position != last_position:
#         if position > last_position:
#             settings.midi_channel_out += 1
#         else:
#             settings.midi_channel_out -= 1
#         settings.midi_channel_out = max(0, min(15, settings.midi_channel_out))
#         change_midi_channel(settings.midi_channel_out)
#     last_position = position


# # 6) Photoresistor for changing all MIDI velocities

# photoresistor = analogio.AnalogIn(board.GP29)

# def change_all_midi_velocities_with_photoresistor():
#     global prev_pot_value
#     light_value = photoresistor.value // 512 # Scale to 0-127
#     if abs(light_value - prev_pot_value) > change_threshold:
#         set_all_midi_velocities(light_value)
#     prev_pot_value = light_value


# # 7) Servo Motors

# servo_kit = adafruit_servokit.ServoKit(channels=16)

# def move_servo(noteval):
#     servo_kit.servo[0].angle = (noteval / 127) * 180 # Scale MIDI note to servo angle


# # 8) 4x3 Keypad Matrix

# rows = [digitalio.DigitalInOut(x) for x in (board.GP0, board.GP1, board.GP2, board.GP3)]
# cols = [digitalio.DigitalInOut(x) for x in (board.GP4, board.GP5, board.GP6)]
# keys = ((1, 2, 3), (4, 5, 6), (7, 8, 9), ('*', 0, '#'))
# keypad = adafruit_matrixkeypad.Matrix_Keypad(rows, cols, keys)

# def check_keypad():
#     keys = keypad.pressed_keys
#     if keys:
#         for key in keys:
#             print(f"Key pressed: {key}")


# 9) Piezo Buzzer using PWM

buzzer = pwmio.PWMOut(board.GP21, duty_cycle=0, frequency=440, variable_frequency=True)

def play_buzzer(noteval):
    buzzer.frequency = 440 + (noteval * 2) # Simple way to change frequency based on MIDI note
    buzzer.duty_cycle = 32768 # 50% duty cycle

def stop_buzzer():
    buzzer.duty_cycle = 0 # Turn off buzzer


# # 10) Temperature Sensor

# temperature_sensor = analogio.AnalogIn(board.GP26)

# def read_temperature():
#     # Simple conversion assuming a TMP36 sensor
#     voltage = (temperature_sensor.value * 3.3) / 65536
#     temperature = (voltage - 0.5) * 100
#     print(f"Temperature: {temperature} C")


# # 11) Relay Switches

# relay = digitalio.DigitalInOut(board.GP22)
# relay.direction = digitalio.Direction.OUTPUT

# def toggle_relay(state):
#     relay.value = state


# ------------- Place functions in one of the hooks below -------------
# Use the slow hook for things that are less time sensitive or take longer to run
# Use the fast hook for things that need to run as fast as possible
# Use the note hooks to trigger functions when a new note is played or stopped

def check_addons_slow():
    # check_joystick()
    # change_all_midi_velocities_with_potentiometer()
    # change_all_midi_velocities_with_photoresistor()
    # check_keypad()
    # read_temperature()
    return


def check_addons_fast():
    # shift_all_notes()
    # change_midi_channel_with_encoder()
    return


def handle_new_notes_on(noteval, velocity, padidx):
    # handle_new_notes_on_extra_pixels(padidx)
    play_buzzer(noteval)
    # move_servo(noteval)
    # toggle_relay(True)
    return


def handle_new_notes_off(noteval, velocity, padidx):
    # handle_new_notes_off_extra_pixels(padidx)
    stop_buzzer()
    # toggle_relay(False)
    return