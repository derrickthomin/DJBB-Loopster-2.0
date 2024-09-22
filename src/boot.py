import storage
import board
import digitalio

SELECT_BTN_PIN = board.GP10

fn_button = digitalio.DigitalInOut(SELECT_BTN_PIN)
fn_button.direction = digitalio.Direction.INPUT
fn_button.pull = digitalio.Pull.UP

button_value = fn_button.value
storage.remount("/", readonly=button_value)

if button_value:
    storage.enable_usb_drive()
else:
    storage.disable_usb_drive()
