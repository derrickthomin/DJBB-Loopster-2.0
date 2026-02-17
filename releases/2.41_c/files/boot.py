import storage
import board
import digitalio
import microcontroller
# release 2.41_c
microcontroller.cpu.frequency = 270_000_000 # RP2040 Safe to 2X overclock

storage.remount("/", readonly=False)

m = storage.getmount("/")
m.label = "Loopster"

fn_btn_PIN = board.GP10

fn_button = digitalio.DigitalInOut(fn_btn_PIN)
fn_button.direction = digitalio.Direction.INPUT
fn_button.pull = digitalio.Pull.UP

button_value = fn_button.value
storage.remount("/", readonly=button_value)

if not button_value:
    storage.enable_usb_drive()
else:
    storage.disable_usb_drive()
