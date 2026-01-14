"""
Below are some examples of how to use the additional GPIO pins and modules of the loopster 2 to
create custom functionality. Below are the 

* handle_new_notes_on(noteval, velocity, padidx, midi_channel) - Triggered when a new note is played
* handle_new_notes_off(noteval, velocity, padidx, midi_channel) - Triggered when a note is stopped
* handle_new_cc(cc_num, cc_val, midi_channel) - Triggered when a CC message is sent

loop_manager.toggle_loop_playstate(idx)     # Turns loop on / off
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
#*                        Neopixels                            *
#***************************************************************
import board
import neopixel

extra_neopixels = neopixel.NeoPixel(board.GP25, 16, brightness=0.8)

def handle_new_notes_on_extra_pixels(padidx):
    extra_neopixels[padidx] = (255, 255, 255)

def handle_new_notes_off_extra_pixels(padidx):
    extra_neopixels[padidx] = (0, 0, 0)

#***************************************************************
#*                       XY Joystick                           *
#***************************************************************
import board
import analogio

x_axis = analogio.AnalogIn(board.GP26)
y_axis = analogio.AnalogIn(board.GP27)
x_midival_prev = 0
y_midival_prev = 0
change_threshold = 3

def check_joystick():
    global x_val_prev, y_val_prev, x_midival_prev, y_midival_prev
    x_val = x_axis.value
    y_val = y_axis.value
    x_midival = int((x_val / 65535) * 127)
    y_midival = int((y_val / 65535) * 127)
    x_midival_delta = abs(x_midival - x_midival_prev)
    y_midival_delta = abs(y_midival - y_midival_prev)
    if x_midival_delta > change_threshold and x_midival != x_midival_prev:
        set_all_midi_velocities(x_midival, False)
        print(f"X: {x_midival}")
    x_midival_prev = x_midival
    y_midival_prev = y_midival

#***************************************************************
#*                Button for Shifting Octaves                  *
#***************************************************************
import board
import digitalio

button = digitalio.DigitalInOut(board.GP0)
button.direction = digitalio.Direction.INPUT
button.pull = digitalio.Pull.UP

def shift_all_notes():
    if button.value:
        shift_all_notes_octaves("up", 1)
    else:
        shift_all_notes_octaves("down", 1)

#***************************************************************
#*      Potentiometer for Changing All MIDI Velocities         *
#***************************************************************
import board
import analogio

potentiometer = analogio.AnalogIn(board.GP28)
prev_pot_value = 0

def change_all_midi_velocities_with_potentiometer():
    global prev_pot_value
    pot_value = potentiometer.value // 512
    if abs(pot_value - prev_pot_value) > change_threshold:
        set_all_midi_velocities(pot_value)
    prev_pot_value = pot_value

#***************************************************************
#*             Encoder for Changing MIDI Channels              *
#***************************************************************
import board
import rotaryio
import settings

encoder = rotaryio.IncrementalEncoder(board.GP14, board.GP15)
last_position = None

def change_midi_channel_with_encoder():
    # TODO: This example needs updating - change_midi_channel is now a method on midi object
    # Use: from midi import midi; midi.change_midi_channel(set_channel=X, in_or_out="out")
    global last_position
    position = encoder.position
    if last_position is None or position != last_position:
        if position > last_position:
            settings.midi_channel_out += 1
        else:
            settings.midi_channel_out -= 1
        settings.midi_channel_out = max(0, min(15, settings.midi_channel_out))
        change_midi_channel(settings.midi_channel_out)  # Deprecated - see TODO above
    last_position = position

#***************************************************************
#*       Photoresistor for Changing All MIDI Velocities        *
#***************************************************************
import board
import analogio

photoresistor = analogio.AnalogIn(board.GP29)

def change_all_midi_velocities_with_photoresistor():
    global prev_pot_value
    light_value = photoresistor.value // 512
    if abs(light_value - prev_pot_value) > change_threshold:
        set_all_midi_velocities(light_value)
    prev_pot_value = light_value

#***************************************************************
#*            Motor Control using PWM                          *
#***************************************************************
import board
import pwmio
from adafruit_motor import motor

PWM_PIN_A = board.GP22
PWM_PIN_B = board.GP23
PWM_FREQ = 1000
DECAY_MODE = motor.SLOW_DECAY
THROTTLE_HOLD = 1

pwm_a = pwmio.PWMOut(PWM_PIN_A, frequency=PWM_FREQ)
pwm_b = pwmio.PWMOut(PWM_PIN_B, frequency=PWM_FREQ)
motor1 = motor.DCMotor(pwm_a, pwm_b)
motor1.decay_mode = DECAY_MODE

def control_motor(noteval, reverse=False):
    if noteval == -1:
        motor1.throttle = 0
        return  
    throttle = (noteval / 127) * 0.6 + 0.4
    if reverse:
        throttle *= -1
    motor1.throttle = throttle
    print((throttle,))

#***************************************************************
#*               Piezo Buzzer using PWM                        *
#***************************************************************
import board
import pwmio

buzzer = pwmio.PWMOut(board.GP21, duty_cycle=0, frequency=440, variable_frequency=True)

def play_buzzer(noteval):
    midi_note = noteval + 21
    frequency = 440 * (2 ** ((midi_note - 69) / 12))
    buzzer.frequency = int(frequency)
    buzzer.duty_cycle = 32768

def stop_buzzer():
    buzzer.duty_cycle = 0

#***************************************************************
#*           Temperature Sensor                                *
#***************************************************************
import board
import adafruit_dht

dht_pin = board.GP26
dht_sensor = adafruit_dht.DHT22(dht_pin)

def read_temperature():
    try:
        temperature = dht_sensor.temperature
        print(f"Temperature: {temperature} C")
    except RuntimeError as e:
        print(f"Error reading temperature: {e}")

#***************************************************************
#*                Relay Switches                               *
#***************************************************************
import board
import digitalio

relay = digitalio.DigitalInOut(board.GP22)
relay.direction = digitalio.Direction.OUTPUT
 
def toggle_relay(state):
    relay.value = state

#***************************************************************
#*                   PIR Sensor                                *
#***************************************************************
import board
import digitalio

pir_pin = board.GP24
pir_sensor = digitalio.DigitalInOut(pir_pin)
pir_sensor.direction = digitalio.Direction.INPUT 

def handle_pir_motion(note):
    if pir_sensor.value:
        return shift_note_octave(note, 1)
    else:
        return False 

#***************************************************************
#*          Accelerometer GY-521 MPU6050 Module                *
#***************************************************************
import busio
import board
import adafruit_mpu6050
import digitalio
import time

i2c = busio.I2C(board.GP21, board.GP20)
mpu = adafruit_mpu6050.MPU6050(i2c)

button = digitalio.DigitalInOut(board.GP25)
button.direction = digitalio.Direction.INPUT
button.pull = digitalio.Pull.UP

prev_acceleration = (0, 0, 0)
prev_gyro = (0, 0, 0)
current_acc_cc_val = 0
last_acc_cc_val = 0
midi_chg_thresh = 3
hold_cc_value = False
start_time = time.time()
gyro_start_time = time.time()
last_gyro_cc_val = 0

def check_sensors():
    print("Acceleration: X:%.2f, Y: %.2f, Z: %.2f m/s^2" % mpu.acceleration)
    print("Gyro X:%.2f, Y: %.2f, Z: %.2f rad/s" % mpu.gyro)
    print("Temperature: %.2f C" % mpu.temperature)
    print("")

def accelerometer_send_cc(cc_msg=1, decay_time=1):
    global prev_acceleration, current_acc_cc_val, last_acc_cc_val, hold_cc_value, start_time
    acceleration = mpu.acceleration
    total_change = sum(abs(acceleration[i] - prev_acceleration[i]) for i in range(3))
    current_acc_cc_val = int((total_change / 29.4) * 127)
    current_acc_cc_val = max(0, min(127, current_acc_cc_val))
    decay_midi_amt_per_sec = 100 / decay_time

    if not button.value:
        if current_acc_cc_val < last_acc_cc_val:
            current_acc_cc_val = last_acc_cc_val

    send_cc_message(cc_msg, current_acc_cc_val)
    print(f"Accel CC: {current_acc_cc_val}")

    prev_acceleration = acceleration
    last_acc_cc_val = current_acc_cc_val

def gyroscope_send_cc(cc_msg=110, decay_time=4):
    global prev_gyro, current_gyro_cc_val, last_gyro_cc_val, hold_cc_value, gyro_start_time

    gyro = mpu.gyro
    total_change = sum(abs(gyro[i] - prev_gyro[i]) for i in range(3))
    current_gyro_cc_val = int((total_change / 10) * 127 * 1)
    current_gyro_cc_val = max(0, min(127, current_gyro_cc_val))

    if not button.value:
        if current_gyro_cc_val < last_gyro_cc_val:
            current_gyro_cc_val = last_gyro_cc_val
    else:
        if current_gyro_cc_val > last_gyro_cc_val:
            last_gyro_cc_val = current_gyro_cc_val
            gyro_start_time = time.time()
        else:
            elapsed_time = time.time() - gyro_start_time
            if elapsed_time < decay_time:
                decay_rate = last_gyro_cc_val / decay_time
                current_gyro_cc_val = max(0, int(last_gyro_cc_val - decay_rate * elapsed_time))

    if abs(last_gyro_cc_val - current_gyro_cc_val) >= midi_chg_thresh:
        send_cc_message(cc_msg, current_gyro_cc_val)
        print(f"Gyro CC: {current_gyro_cc_val}")

    prev_gyro = gyro
    last_gyro_cc_val = current_gyro_cc_val

#***************************************************************
#*          7 Segment Display with 4 Digits                    *
#***************************************************************
import busio
import board
from adafruit_ht16k33.segments import Seg7x4

i2c = busio.I2C(board.GP21, board.GP20)
display = Seg7x4(i2c)
number = 1

def display_number(number):
    display.fill(0)
    display.print(number)

display_number(number)

#***************************************************************
#*         DC Motor Control using Analog Input                 *
#***************************************************************
import analogio
import board
import time

prev_midi_velocity = 0
dc_motor_voltage_pin = analogio.AnalogIn(board.GP26)

def read_dc_motor_voltage():
    global prev_midi_velocity
    raw_value = dc_motor_voltage_pin.value
    
    raw_voltage = (raw_value / 65535) * 3.3
    if raw_voltage < 0.03:
        return
    voltage = raw_voltage * 10  
    
    midi_velocity = int((voltage / 3.3) * 127)

    if abs(midi_velocity - prev_midi_velocity) < 3:
        return
    
    print(f"Raw value: {raw_value}, Voltage: {voltage:.2f}V, MIDI Velocity: {midi_velocity}")
    send_cc_message(1, midi_velocity)
    prev_midi_velocity = midi_velocity
    time.sleep(0.1)
    
    return midi_velocity

#***************************************************************
#*                      Mirror Pixels                          *
#***************************************************************
mirrored_pixels = neopixel.NeoPixel(board.GP25, 5, brightness=0.3)
internalToExternalMap = {}
NUM_PEDAL_BUTTONS = 5
pedal_pixels_need_update = False

def set_mirrored_pixel(internalPadIdx, rgbColor):
    global pedal_pixels_need_update

    if mirrored_pixels and internalPadIdx in internalToExternalMap:
        externalPixelIdx = internalToExternalMap[internalPadIdx]
        if mirrored_pixels[externalPixelIdx] != rgbColor:
            mirrored_pixels[externalPixelIdx] = rgbColor
            pedal_pixels_need_update = True

def clear_all_mirrored_pixels():
    global pedal_pixels_need_update
    if mirrored_pixels:
        current_sum = sum(sum(mirrored_pixels[i]) for i in range(NUM_PEDAL_BUTTONS) if i < len(mirrored_pixels))
        if current_sum > 0 : 
            mirrored_pixels.fill(0,0,0) 
            pedal_pixels_need_update = True

def show_mirrored_pixels(): 
    global pedal_pixels_need_update
    if mirrored_pixels and pedal_pixels_need_update:
        mirrored_pixels.show()
        pedal_pixels_need_update = False

#***************************************************************
#*                      Place Functions                        *
#***************************************************************
def slow():
    show_mirrored_pixels()
    # check_joystick()
    # change_all_midi_velocities_with_potentiometer()
    # change_all_midi_velocities_with_photoresistor()
    # read_temperature()
    # accelerometer_send_cc()
    # gyroscope_send_cc()
    # read_dc_motor_voltage()
    return

def check_addons_fast():
    # shift_all_notes()
    # change_midi_channel_with_encoder()
    return

def handle_new_notes_on(noteval, velocity, padidx, midi_channel):
    global last_note_on
    note = False
    # handle_new_notes_on_extra_pixels(padidx)
    # play_buzzer(noteval)
    # toggle_relay(True)
    # control_motor(noteval, reverse=False)
    # note = handle_pir_motion((noteval, velocity, padidx))
    return note

def handle_new_notes_off(noteval, velocity, padidx, midi_channel):
    note = False
    # handle_new_notes_off_extra_pixels(padidx)
    # stop_buzzer()
    # toggle_relay(False)
    # control_motor(-1)
    return note

def handle_new_cc(cc_msg, cc_val, midi_channel):
    return