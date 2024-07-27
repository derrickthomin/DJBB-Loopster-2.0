import storage
import board
import digitalio
import time

SELECT_BTN_PIN = board.GP10

select_button = digitalio.DigitalInOut(SELECT_BTN_PIN)
select_button.direction = digitalio.Direction.INPUT
select_button.pull = digitalio.Pull.UP
# aa
# If holding the select button, we'll enter writable mode.
# DJT swap the logic so that the button is pressed to enter read-only mode

time.sleep(1)
button_value = select_button.value
storage.remount("/", readonly=button_value)

if button_value:
    storage.enable_usb_drive()
else:
    storage.disable_usb_drive()
time.sleep(1)
# if not select_button.value:
#     storage.remount("/", readonly=False)
#     storage.disable_usb_drive()
        
# else:
#     storage.remount("/", readonly=True)
#     storage.enable_usb_drive()
