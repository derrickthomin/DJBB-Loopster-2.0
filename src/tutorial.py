import display
import constants
import time
import board
import rotaryio

tutorial_text = []

class Tutorial:
    def __init__(self):
        self.tutorial_text = []
        self.screen_titles = ["!! Tutorial !!", " Play ", " Play - Chord", " Play - Velocity", " Play - encoder", " Navigation ", " BYEee "]
        self.screen_idx = 0 # tracks the current screen
        self.prev_screen_idx = 0 # tracks the previous screen
        self.last_encoder_position = 0
        self.screens = []

        self.screens.append((" General ", ["turn encoder to chg", "setting on cur scrn", "press pad to", "play note"]))
        self.screens.append((" General ", ["click encoder to", "enter nav mode.", "turn encoder to", "choose screen"]))
        self.screens.append((" General ", ["hold [fn] and", "press pad", "to record onto", "pad"]))

        self.screens.append((" Play Screen ", ["this is the main scrn", "press pad to ply notes", "turn encoder to", "chg banks"]))
        self.screens.append((" Play Screen ", ["there are mult modes", "on this screen", "dbl click [fn]", "to chg modes"]))
        self.screens.append((" Play Screen ", ["MODES:", " -Chord", " -Velocity", " -Arp"]))

        self.screens.append((" Play - Chord", ["hold [fn] and", "press pad", "to record onto", "pad"]))
        self.screens.append((" Play - Chord", ["click [fn]", "to stop recording"]))
        self.screens.append((" Play - Chord", ["hold recorded pad", "and turn encoder", "to change mode:", " -1 shot", " -Loop (toggle)"]))

        self.screens.append((" Play - Velocity", ["Press pad to", "play chord", "or toggle loop", "on/off"]))
        self.screens.append((" Play - encoder", ["hold pad and", "turn encoder", "to chg velocity"]))
        self.screens.append((" Navigation ", ["hold pad and", "turn encoder", "to play notes"]))
        self.screens.append((" BYEee ", ["Click encoder to", "toggle", "to nav mode"]))
        self.screens.append((" BYEee ", ["turn encoder to", "navigate", "click encoder to", "select screen", "turn to chg", "setting"]))
        self.screens.append((" BYEee ", ["Thanks for", "playing", "Enjoy the", "loopster", "v2.0"]))

    # Function to check if encoder has turned and return the direction
    def check_encoder_turn(self, encoder):
        encoder_delta = encoder.position - self.last_encoder_position

        if encoder_delta > 0:
            self.last_encoder_position = encoder.position
            return True
        elif encoder_delta < 0:
            self.last_encoder_position = encoder.position
            return False
        
        return None
    
    # Use a while loop to check for encoder turn and display the tutorial text one screen at a time
    # Advance to the next if check_encoder_turn is true, else go to the last. Update screen_idx
    # Once the last screen is displayed, clear the display and exit the loop.
    # Only update hte display if the index has changed

    def display_tutorial(self, encoder):
        display.clear_all()
        display.display_text_top("  !! Tutorial !!  ")
        display.display_text_middle("Turn encoder to start")
        display.display_set_update_flag(True, True)
        while True:
            if self.screen_idx != self.prev_screen_idx:
                display.clear_all()
                screen_title, screen_text = self.screens[self.screen_idx]
                display.display_text_top(screen_title)
                display.display_text_middle(screen_text)
                self.prev_screen_idx = self.screen_idx
                display.display_set_update_flag(True, True)
            
            encoder_turn = self.check_encoder_turn(encoder)
            if encoder_turn:
                self.screen_idx += 1
            elif encoder_turn == False:
                self.screen_idx -= 1
            if self.screen_idx < 0:
                self.screen_idx = 0
            elif self.screen_idx > len(self.screens) - 1:
                display.display_text_top("BYEee")
                display.display_text_middle(["Thanks for playing", "Enjoy the loopster", "v2.0"])
                display.display_set_update_flag(True, True)
                time.sleep(2)
                break

            
            time.sleep(0.05)
tutorial = Tutorial()
