from chordmanager import chord_manager
from midi import (
    change_midi_channel, set_all_midi_velocities, set_midi_velocity_by_idx, 
    send_midi_note_on, send_midi_note_off, shift_all_notes_octaves, 
    send_cc_message, shift_note_octave, send_aftertouch_for_note
)
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
from arp import arpeggiator

"""
Below are some examples of how to use the additional GPIO pins and modules of the loopster 2 to
create custom functionality. Below are the 

* handle_new_notes_on() - Triggered when a new note is played
* handle_new_notes_off() - Triggered when a note is stopped

chord_manager.toggle_chord_by_index(idx)    # Turns chord on / off
set_all_midi_velocities(velocity)           # Set all velocities
shift_all_notes_octaves(dir, octaves)       # Shift all notes by a certain amount
change_midi_channel(channel)                # Change midi channel
settings.midi_sync = True                   # Enable midi sync
settings.set_next_arp_length()              # Set next or prev arp length
settings.arpeggiator_length("1/8")          # Set arp length
settings.arpeggiator_type("up")             # Set arp type
.... see src/settings for ideas

AVAILABLE GPIO PINS
- GP26, GP27, GP28, GP29 (Analog)
- GP0, GP9, GP14, GP20, GP21, GP22, GP23, GP24, GP25 (Digital)
"""


#***************************************************************
#*                                                             *
#*                        Neopixels                            *
#*                                                             *
#***************************************************************


# extra_neopixels = neopixel.NeoPixel(board.GP25, 16, brightness=0.8)

# def handle_new_notes_on_extra_pixels(padidx):
#     extra_neopixels[padidx] = (255, 255, 255) # White

# def handle_new_notes_off_extra_pixels(padidx):
#     extra_neopixels[padidx] = (0, 0, 0) # Black / Off


#***************************************************************
#*                                                             *
#*                       XY Joystick                           *
#*                                                             *
#***************************************************************

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


#***************************************************************
#*                                                             *
#*                Button for Shifting Octaves                  *
#*                                                             *
#***************************************************************

# button = digitalio.DigitalInOut(board.GP0)
# button.direction = digitalio.Direction.INPUT
# button.pull = digitalio.Pull.UP

# def shift_all_notes():
#     if button.value:
#         shift_all_notes_octaves("up", 1)
#     else:
#         shift_all_notes_octaves("down", 1)


#***************************************************************
#*                                                             *
#*      Potentiometer for Changing All MIDI Velocities         *
#*                                                             *
#***************************************************************

# potentiometer = analogio.AnalogIn(board.GP28)
# prev_pot_value = 0

# def change_all_midi_velocities_with_potentiometer():
#     global prev_pot_value
#     pot_value = potentiometer.value // 512 # Scale to 0-127
#     if abs(pot_value - prev_pot_value) > change_threshold:
#         set_all_midi_velocities(pot_value)
#     prev_pot_value = pot_value


#***************************************************************
#*                                                             *
#*             Encoder for Changing MIDI Channels              *
#*                                                             *
#***************************************************************

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


#***************************************************************
#*                                                             *
#*       Photoresistor for Changing All MIDI Velocities        *
#*                                                             *
#***************************************************************

# photoresistor = analogio.AnalogIn(board.GP29)

# def change_all_midi_velocities_with_photoresistor():
#     global prev_pot_value
#     light_value = photoresistor.value // 512 # Scale to 0-127
#     if abs(light_value - prev_pot_value) > change_threshold:
#         set_all_midi_velocities(light_value)
#     prev_pot_value = light_value


#***************************************************************
#*                                                             *
#*            Motor Control using PWM - DJT TESTED             *
#*                                                             *
#***************************************************************

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


#***************************************************************
#*                                                             *
#*               Piezo Buzzer using PWM - DJT TESTED           *
#*                                                             *
#***************************************************************

# buzzer = pwmio.PWMOut(board.GP21, duty_cycle=0, frequency=440, variable_frequency=True)

# def play_buzzer(noteval):
#     midi_note = noteval + 21  # Convert MIDI note value to MIDI note number
#     frequency = 440 * (2 ** ((midi_note - 69) / 12))  # Calculate frequency using MIDI note number
#     buzzer.frequency = int(frequency)  # Set the buzzer frequency
#     buzzer.duty_cycle = 32768  # 50% duty cycle

# def stop_buzzer():
#     buzzer.duty_cycle = 0 # Turn off buzzer


#***************************************************************
#*                                                             *
#*           Temperature Sensor - DJT TESTED                   *
#*                                                             *
#***************************************************************

# dht_pin = board.GP26
# dht_sensor = adafruit_dht.DHT22(dht_pin)

# def read_temperature():
#     try:
#         temperature = dht_sensor.temperature
#         print(f"Temperature: {temperature} C")
#     except RuntimeError as e:
#         print(f"Error reading temperature: {e}")


#***************************************************************
#*                                                             *
#*                Relay Switches - DJT TESTED                  *
#*                                                             *
#***************************************************************

# relay = digitalio.DigitalInOut(board.GP22)
# relay.direction = digitalio.Direction.OUTPUT
 
# def toggle_relay(state):
#     relay.value = state


#***************************************************************
#*                                                             *
#*                   PIR Sensor - DJT TESTED                   *
#*                                                             *
#***************************************************************

# pir_pin = board.GP24
# pir_sensor = digitalio.DigitalInOut(pir_pin)
# pir_sensor.direction = digitalio.Direction.INPUT 

# def handle_pir_motion(note):
#     if pir_sensor.value:
#         return shift_note_octave(note, 1)
#     else:
#         return False 


#***************************************************************
#*                                                             *
#*          Accelerometer GY-521 MPU6050 Module                *
#*                                                             *
#***************************************************************

# import busio
# import board
# import adafruit_mpu6050
# import digitalio
# import time

# # Initialize I2C and MPU6050
# i2c = busio.I2C(board.GP21, board.GP20)
# mpu = adafruit_mpu6050.MPU6050(i2c)

# # Initialize button
# button = digitalio.DigitalInOut(board.GP25)
# button.direction = digitalio.Direction.INPUT
# button.pull = digitalio.Pull.UP

# # Global variables to store accelerometer data and MIDI velocities
# prev_acceleration = (0, 0, 0)
# prev_gyro = (0, 0, 0)
# current_acc_cc_val = 0
# last_acc_cc_val = 0
# midi_chg_thresh = 3
# hold_cc_value = False
# start_time = time.time()
# gyro_start_time = time.time()
# last_gyro_cc_val = 0
# def check_sensors():
#     print("Acceleration: X:%.2f, Y: %.2f, Z: %.2f m/s^2" % mpu.acceleration)
#     print("Gyro X:%.2f, Y: %.2f, Z: %.2f rad/s" % mpu.gyro)
#     print("Temperature: %.2f C" % mpu.temperature)
#     print("")

# def accelerometer_send_cc(cc_msg=1, decay_time=1):
#     global prev_acceleration, current_acc_cc_val, last_acc_cc_val, hold_cc_value, start_time
#     acceleration = mpu.acceleration
#     total_change = sum(abs(acceleration[i] - prev_acceleration[i]) for i in range(3))
#     current_acc_cc_val = int((total_change / 29.4) * 127)  # Scale the total change to MIDI velocity range
#     current_acc_cc_val = max(0, min(127, current_acc_cc_val))  # Clamp the velocity to the MIDI range
#     decay_midi_amt_per_sec = 100 / decay_time

#     if not button.value:
#         if current_acc_cc_val < last_acc_cc_val:
#             current_acc_cc_val = last_acc_cc_val

#     send_cc_message(cc_msg, current_acc_cc_val)
#     print(f"Accel CC: {current_acc_cc_val}")

#     prev_acceleration = acceleration
#     last_acc_cc_val = current_acc_cc_val

# def gyroscope_send_cc(cc_msg=110, decay_time=4):
#     global prev_gyro, current_gyro_cc_val, last_gyro_cc_val, hold_cc_value, gyro_start_time

#     gyro = mpu.gyro
#     total_change = sum(abs(gyro[i] - prev_gyro[i]) for i in range(3))
#     current_gyro_cc_val = int((total_change / 10) * 127 * 1)  # Scale the total change to MIDI velocity range
#     current_gyro_cc_val = max(0, min(127, current_gyro_cc_val))  # Clamp the velocity to the MIDI range

#     if not button.value:
#         if current_gyro_cc_val < last_gyro_cc_val:
#             current_gyro_cc_val = last_gyro_cc_val
#     else:
#         if current_gyro_cc_val > last_gyro_cc_val:
#             last_gyro_cc_val = current_gyro_cc_val
#             gyro_start_time = time.time()
#         else:
#             elapsed_time = time.time() - gyro_start_time
#             if elapsed_time < decay_time:
#                 decay_rate = last_gyro_cc_val / decay_time
#                 current_gyro_cc_val = max(0, int(last_gyro_cc_val - decay_rate * elapsed_time))

#     if abs(last_gyro_cc_val - current_gyro_cc_val) >= midi_chg_thresh:
#         send_cc_message(cc_msg, current_gyro_cc_val)
#         print(f"Gyro CC: {current_gyro_cc_val}")

#     prev_gyro = gyro
#     last_gyro_cc_val = current_gyro_cc_val


#***************************************************************
#*                                                             *
#*          7 Segment Display with 4 Digits - DJT TESTED       *
#*                                                             *
#***************************************************************

# from adafruit_ht16k33.segments import Seg7x4

# i2c = busio.I2C(board.GP21, board.GP20)
# display = Seg7x4(i2c)
# number = 1
# def display_number(number):
#     display.fill(0)  # Clear the display
#     display.print(number)  # Display the number

# display_number(number)


#***************************************************************
#*                                                             *
#*         DC Motor Control using Analog Input - DJT TESTED    *
#*                                                             *
#***************************************************************

# import analogio
# import board

# prev_midi_velocity = 0
# # Setup the analog pin for reading the voltage
# dc_motor_voltage_pin = analogio.AnalogIn(board.GP26)  # Use the appropriate analog pin

# # Function to read and process the voltage generated by the DC motor
# def read_dc_motor_voltage():
#     global prev_midi_velocity
#     # Read the raw value from the analog pin (0-65535)
#     raw_value = dc_motor_voltage_pin.value
    
#     # Convert the raw value to a voltage (assuming a 3.3V reference)
#     raw_voltage = (raw_value / 65535) * 3.3
#     if raw_voltage < 0.03:
#         return
#     voltage = raw_voltage * 10  
    
#     # Optionally, convert the voltage to a MIDI velocity (0-127)
#     midi_velocity = int((voltage / 3.3) * 127)

#     if abs(midi_velocity - prev_midi_velocity) < 3:
#         return
    
#     # Print the values for debugging
#     print(f"Raw value: {raw_value}, Voltage: {voltage:.2f}V, MIDI Velocity: {midi_velocity}")
#     send_cc_message(1, midi_velocity)
#     prev_midi_velocity = midi_velocity
#     time.sleep(0.1)

    
#     # Return the MIDI velocity
#     return midi_velocity

#***************************************************************
#*                                                             *
#*                      Place Functions                        *
#*                                                             *
#  Call your custom code in one of the below hooks. These      *
#  functions are called at different intervals to optimize     *
#  performance.                                                *
#*                                                             *
#* check_addons_slow():                                        *
#*     - Less frequent calls for non-urgent tasks.             *
#*                                                             *
#* check_addons_fast():                                        *
#*     - More frequent calls for time-sensitive tasks.         *
#*                                                             *
#* handle_new_notes_on(noteval, velocity, padidx):             *
#*     - Triggered when a new note is played.                  *
#*                                                             *
#* handle_new_notes_off(noteval, velocity, padidx):            *
#*     - Triggered when a note is released.                    *
#*                                                             *
#***************************************************************

def check_addons_slow():
    # -------- examples --------
    # check_joystick()
    # change_all_midi_velocities_with_potentiometer()
    # change_all_midi_velocities_with_photoresistor()
    # check_keypad()
    # read_temperature()
    # accelerometer_send_cc()
    # gyroscope_send_cc()
    # read_dc_motor_voltage()
    # -------- examples --------
    return

def check_addons_fast():
    # -------- examples --------
    # shift_all_notes()
    # change_midi_channel_with_encoder()
    # -------- examples --------
    return

def handle_new_notes_on(noteval, velocity, padidx):
    global last_note_on
    note = False  # (noteval, velocity, padidx)
    # -------- examples --------
    # handle_new_notes_on_extra_pixels(padidx)
    # play_buzzer(noteval)
    # move_servo(noteval)
    # toggle_relay(True)
    # control_motor(noteval, reverse=False)
    # note = handle_pir_motion((noteval, velocity, padidx))
    # -------- examples --------
    return note

def handle_new_notes_off(noteval, velocity, padidx):
    note = False  # (noteval, velocity, padidx)
    # -------- examples --------
    # handle_new_notes_off_extra_pixels(padidx)
    # stop_buzzer()
    # toggle_relay(False)
    # control_motor(-1)
    # toggle_relay(False)
    # -------- examples --------
    return note