import board
import neopixel
mirrored_pixels = neopixel.NeoPixel(board.GP25, 5, brightness=0.3)
internalToExternalMap = {}
NUM_PEDAL_BUTTONS = 5  # Total number of external buttons

pedal_pixels_need_update = False # Flag to batch .show() calls

def set_mirrored_pixel(internalPadIdx, rgbColor):
    """Sets a single external pixel to a specific color if mapped."""
    global pedal_pixels_need_update

    if mirrored_pixels and internalPadIdx in internalToExternalMap:
        externalPixelIdx = internalToExternalMap[internalPadIdx]
        if mirrored_pixels[externalPixelIdx] != rgbColor:
            mirrored_pixels[externalPixelIdx] = rgbColor
            pedal_pixels_need_update = True

def clear_all_mirrored_pixels():
    """Turns off all mapped external pixels."""
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
#*                                                             *
#*                      Place Functions                        *
#*                                                             *
#  Call your custom code in one of the below hooks. These      *
#  functions are called at different intervals to optimize     *
#  performance.                                                *
#*                                                             *
#* slow():                                                     *
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

def slow():
    show_mirrored_pixels()  # Show any changes to the mirrored pixels
    return

def check_addons_fast():
    return

def handle_new_notes_on(noteval, velocity, padidx):
    global last_note_on
    note = False  # (noteval, velocity, padidx)
    return note

def handle_new_notes_off(noteval, velocity, padidx):
    note = False  # (noteval, velocity, padidx)
    return note

def handle_new_cc(cc_msg, cc_val, padidx):
    return