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

        self.screen_1 = ["Welcome to the loopster 2.0", "to repeat tut, hold enc button", "while powering on the device"]
        self.screen_2 = ["This is the main screen", "Press pad to play note", "Turn encoder to chg bank"]
        self.screen_3 = ["hold [fn] and press pad", "to record onto pad"]
        self.screen_4 = ["Press pad to play chord", "or toggle loop on/off"]
        self.screen_5 = ["hold pad and turn encoder", "to chg velocity"]
        self.screen_6 = ["hold pad and turn encoder", "to play notes"]
        self.screen_7 = ["Click encoder to toggle", "to nav mode"]
        self.screen_8 = ["turn encoder to navigate", "click encoder to select screen", "turn to chg setting"]
        self.screen_9 = ["Thanks for playing", "Enjoy the loopster", "v2.0"]
        self.screens  = [self.screen_1, self.screen_2, self.screen_3, 
                         self.screen_4, self.screen_5, self.screen_6, 
                         self.screen_7, self.screen_8, self.screen_9]

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
        while True:
            if self.screen_idx != self.prev_screen_idx:
                display.display_text_top(self.screen_titles[self.screen_idx])
                display.display_text_middle(self.screens[self.screen_idx])
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
