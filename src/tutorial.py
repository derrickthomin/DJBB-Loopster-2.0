import display
import time

tutorial_text = []

# Main function.
def display_tutorial():
    """
    Displays the tutorial for the loopster 2.0 device.
    """
    display.display_text_top("!! Tutorial !!")
    add_tutorial_text_line("Welcome to the loopster 2.0")
    add_tutorial_text_line("to repeat tut, hold enc button")
    add_tutorial_text_line("while powering on the device")
    display_tutorial_text()

    add_tutorial_text_line("To skip, hold [FN] button")
    display_tutorial_text()

    display.display_text_top(" Play ")
    add_tutorial_text_line("This is the main screen")
    add_tutorial_text_line("Press pad to play note")
    add_tutorial_text_line("Turn encoder to chg bank")
    display_tutorial_text()

    display.display_text_top(" Play - Chord")
    add_tutorial_text_line("hold [fn] and press pad")
    add_tutorial_text_line("to record onto pad")
    display_tutorial_text()

    display.display_text_top(" Play - Chord")
    add_tutorial_text_line("Press pad to play chord")
    add_tutorial_text_line("or toggle loop on/off")
    display_tutorial_text()

    display.display_text_top(" Play - Chord")
    add_tutorial_text_line("hold pad and turn encoder")
    add_tutorial_text_line("to toggle loop / 1shot")
    display_tutorial_text()

    display.display_text_top(" Play - Velocity")
    add_tutorial_text_line("dbl click [FN] to chg mode")
    add_tutorial_text_line("hold pad and turn encoder")
    add_tutorial_text_line("to chg velocity")
    display_tutorial_text()

    display.display_text_top(" Play - encoder")
    add_tutorial_text_line("hold pad and turn encoder")
    add_tutorial_text_line("to play notes")
    display_tutorial_text()

    display.display_text_top(" Play - encoder")
    add_tutorial_text_line("hold multiple for arps")
    add_tutorial_text_line("works for chords too")
    display_tutorial_text()

    display.display_text_top(" Navigation ")
    add_tutorial_text_line("Click encoder to toggle")
    add_tutorial_text_line("to nav mode")
    display_tutorial_text()

    display.display_text_top(" Navigation ")
    add_tutorial_text_line("turn encoder to navigate")
    add_tutorial_text_line("click encoder to select screen")
    add_tutorial_text_line("turn to chg setting")
    display_tutorial_text()

    display.display_text_top(" BYEee ")
    add_tutorial_text_line("Thanks for playing")
    add_tutorial_text_line("Enjoy the loopster")
    add_tutorial_text_line("v2.0")
    display_tutorial_text()
    
    

def add_tutorial_text_line(text):
    """
    Adds a line of text to the tutorial_text list.

    Args:
        text (str): The text to be added to the tutorial_text list.

    Returns:
        None
    """
    global tutorial_text

    if len(tutorial_text) > 2:
        print("Tutorial text is full")
        return
    tutorial_text.append(text)
    
def display_tutorial_text():
    """
    Displays the tutorial text on the display.

    This function calls the `display.display_text_middle` function to display the tutorial text
    in the middle of the display. It also sets the update flag to True to update the display
    immediately. After displaying the tutorial text, it clears the `tutorial_text` list and
    waits for 2 seconds.

    Parameters:
        None

    Returns:
        None
    """
    global tutorial_text

    display.display_text_middle(tutorial_text)
    display.display_set_update_flag(True, True)
    tutorial_text = []
    time.sleep(2)

