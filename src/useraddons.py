from chordmanager import chord_manager
from midi import (change_midi_channel, set_all_midi_velocities, set_midi_velocity_by_idx, send_midi_note_on, send_midi_note_off, shift_all_notes_octaves, send_cc_message, shift_note_octave, send_aftertouch_for_note)
import settings
import board
import digitalio
import analogio
import rotaryio
import neopixel
import pwmio
from adafruit_motor import motor
import time
import adafruit_dht
import busio
import adafruit_mpu6050

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


# # 8) Motor Control using PWM - DJT TESTED

# PWM_PIN_A = board.GP22  # Replace with your desired pin
# PWM_PIN_B = board.GP23  # Replace with your desired pin
# PWM_FREQ = 1000  # Custom PWM frequency in Hz; PWMOut min/max 1Hz/50kHz, default is 500Hz
# DECAY_MODE = motor.SLOW_DECAY  # Set controller to Slow Decay (braking) mode
# THROTTLE_HOLD = 1  # Hold the throttle (seconds)

# # DC motor setup; Set pins to custom PWM frequency
# pwm_a = pwmio.PWMOut(PWM_PIN_A, frequency=PWM_FREQ)
# pwm_b = pwmio.PWMOut(PWM_PIN_B, frequency=PWM_FREQ)
# motor1 = motor.DCMotor(pwm_a, pwm_b)
# motor1.decay_mode = DECAY_MODE
# def control_motor(noteval, reverse=False):
#     if noteval == -1:  # Stop motor1
#         motor1.throttle = 0
#         return  
#     throttle = (noteval / 127) * 0.6 + 0.4  # Scale MIDI note value to throttle range (0.4 to 1.0)
#     if reverse:
#         throttle *= -1
#     motor1.throttle = throttle
#     print((throttle,))  # Plot/print current throttle value



# # 9) Piezo Buzzer using PWM - DJT TESTED

# buzzer = pwmio.PWMOut(board.GP21, duty_cycle=0, frequency=440, variable_frequency=True)

# def play_buzzer(noteval):
#     midi_note = noteval + 21  # Convert MIDI note value to MIDI note number
#     frequency = 440 * (2 ** ((midi_note - 69) / 12))  # Calculate frequency using MIDI note number
#     buzzer.frequency = int(frequency)  # Set the buzzer frequency
#     buzzer.duty_cycle = 32768  # 50% duty cycle

# def stop_buzzer():
#     buzzer.duty_cycle = 0 # Turn off buzzer


# # 10) Temperature Sensor - DJT TESTED

# dht_pin = board.GP26
# dht_sensor = adafruit_dht.DHT22(dht_pin)

# def read_temperature():
#     try:
#         temperature = dht_sensor.temperature
#         print(f"Temperature: {temperature} C")
#     except RuntimeError as e:
#         print(f"Error reading temperature: {e}")


# # 11) Relay Switches - DJT TESTED

# relay = digitalio.DigitalInOut(board.GP22)
# relay.direction = digitalio.Direction.OUTPUT
 
# def toggle_relay(state):
#     relay.value = state

# 12) PIR Sensor - DJT TESTED

# pir_pin = board.GP24
# pir_sensor = digitalio.DigitalInOut(pir_pin)
# pir_sensor.direction = digitalio.Direction.INPUT 

# def handle_pir_motion(note):
#     if pir_sensor.value:
#         return shift_note_octave(note, 1)
#     else:
#         return False 




# 7) Accelerometer GY-521 MPU6050 Module - DJT Works


iimport busio
import board
import adafruit_mpu6050

# Initialize I2C and MPU6050
i2c = busio.I2C(board.GP21, board.GP20)
mpu = adafruit_mpu6050.MPU6050(i2c)

# Global variables to store accelerometer data and MIDI velocities
prev_acceleration = (0, 0, 0)
current_midi_velocity = 0
last_midi_velocity = 0

def check_accelerometer():
    print("Acceleration: X:%.2f, Y: %.2f, Z: %.2f m/s^2" % mpu.acceleration)
    print("Gyro X:%.2f, Y: %.2f, Z: %.2f rad/s" % mpu.gyro)
    print("Temperature: %.2f C" % mpu.temperature)
    print("")

def calculate_midi_velocity(acceleration):
    global prev_acceleration, current_midi_velocity, last_midi_velocity

    total_change = sum(abs(acceleration[i] - prev_acceleration[i]) for i in range(3))
    velocity = int((total_change / 29.4) * 127)  # Scale the total change to MIDI velocity range
    velocity = max(0, min(127, velocity))        # Clamp the velocity to the MIDI range

    if last_midi_velocity == velocity:
        return last_midi_velocity
    
    prev_acceleration = acceleration
    last_midi_velocity = current_midi_velocity
    current_midi_velocity = velocity

    send_cc_message(1, velocity)

    print(f"Velocity: {velocity}")
    return velocity

def update_note_velocity(note_tuple):
    note, _, padindex = note_tuple
    return (note, current_midi_velocity, padindex)


# Example usage:

# 7) 7 Segment Display with 4 Digits - DJT TESTED

# from adafruit_ht16k33.segments import Seg7x4

# i2c = busio.I2C(board.GP21, board.GP20)
# display = Seg7x4(i2c)
# number = 1
# def display_number(number):
#     display.fill(0)  # Clear the display
#     display.print(number)  # Display the number

# display_number(number)

# Call the display_number() function in the appropriate place in the code
# ------------- Place functions in one of the hooks below -------------

def check_addons_slow():
    # check_joystick()
    # change_all_midi_velocities_with_potentiometer()
    # change_all_midi_velocities_with_photoresistor()
    # check_keypad()
    # read_temperature()
    _=calculate_midi_velocity(mpu.acceleration)
    return


def check_addons_fast():
    # shift_all_notes()
    # change_midi_channel_with_encoder()
    return


def handle_new_notes_on(noteval, velocity, padidx):
    global last_note_on
    note = update_note_velocity((noteval, velocity, padidx))
    last_note_on = note
    if note:
        print(f"Updated Note: {note}")
    else:
        return False
    # handle_new_notes_on_extra_pixels(padidx)
    # play_buzzer(noteval)
    # move_servo(noteval)
    # toggle_relay(True)
    # control_motor(noteval, reverse=False)
    # note = handle_pir_motion((noteval, velocity, padidx))
 
    return note


def handle_new_notes_off(noteval, velocity, padidx):
    # handle_new_notes_off_extra_pixels(padidx)
    # stop_buzzer()
    # toggle_relay(False)
    # control_motor(-1)
    # toggle_relay(False)
    return