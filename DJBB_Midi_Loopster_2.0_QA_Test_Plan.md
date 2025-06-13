DJBB Midi Loopster 2.0 - Comprehensive QA Test Plan

Test Environment Setup
* Required Equipment
    * DJBB Midi Loopster 2.0 device
    * MIDI controller/keyboard
    * DAW or MIDI monitoring software
    * USB cable for power/MIDI
    * Standard 5-pin MIDI cables (if testing DIN MIDI)

Pre-Test Configuration
* Power on device
* Connect MIDI input source
* Connect MIDI output destination
* Set up MIDI monitoring to verify output

⸻

Recommended Test Presets Configuration
* PRESET 1 (Basic Testing): C Major, 120 BPM, Velocity Mode, No Arp
* PRESET 2 (Arp Testing): C Major, 120 BPM, Velocity Mode, Arp ON
* PRESET 3 (Encoder Testing): C Major, 120 BPM, Encoder Mode, No Arp
* PRESET 4 (Chord Testing): C Major, 120 BPM, Chord Mode, No Arp
* PRESET 5 (Advanced): G Minor, 140 BPM, Velocity Mode, Arp ON

⸻

SECTION 1: BASIC SYSTEM FUNCTIONALITY

1.1 Power and Initialization
* Device powers on correctly……………………………PASS/FAIL
* LED displays show initial state………………………PASS/FAIL
* All LEDs illuminate during startup sequence....PASS/FAIL
* Default settings load correctly……………………….PASS/FAIL

1.2 MIDI Connectivity
* USB MIDI input recognized by host....PASS/FAIL
* USB MIDI output sends to host....PASS/FAIL
* DIN MIDI input receives correctly (if applicable)....PASS/FAIL
* DIN MIDI output sends correctly (if applicable)....PASS/FAIL
* MIDI channel settings respected....PASS/FAIL

⸻

⸻
SECTION 2: NAVIGATION AND INTERFACE

2.1 Menu Navigation
* Main menu accessible via Menu button............................PASS/FAIL
* Encoder scrolls through menu options smoothly...............PASS/FAIL
* Encoder push selects menu items..................................PASS/FAIL
* Back/Exit functionality works from all submenus............PASS/FAIL
* Menu timeout returns to main screen.............................PASS/FAIL

2.2 LED Feedback
* Note LEDs illuminate when notes triggered......................PASS/FAIL
* Scale LEDs show current scale pattern...........................PASS/FAIL
* Mode indicators show current play mode.........................PASS/FAIL
* Status LEDs indicate system state correctly....................PASS/FAIL
* LED brightness appropriate for visibility...........................PASS/FAIL

2.3 Advanced Menu Navigation
* Menu double-click functionality works...........................PASS/FAIL
* Hold + encoder combinations function correctly..............PASS/FAIL
* Settings menu pagination works.....................................PASS/FAIL
* MIDI settings page switching works...............................PASS/FAIL
* Menu context switches properly....................................PASS/FAIL
* Navigation mode vs settings mode toggles.....................PASS/FAIL

⸻
SECTION 3: PLAY MODES (Use Preset 1-4)

3.1 Velocity Mode Testing
* Switch to Preset 1.........................................................PASS/FAIL
* Velocity mode activates correctly...................................PASS/FAIL
* Input velocity directly controls output velocity...............PASS/FAIL
* Soft playing produces quiet output.................................PASS/FAIL
* Hard playing produces loud output................................PASS/FAIL
* Full velocity range (1-127) accessible...........................PASS/FAIL
* Zero velocity (note off) handled correctly.......................PASS/FAIL

3.2 Encoder Mode Testing
* Switch to Preset 3.........................................................PASS/FAIL
* Encoder mode activates correctly..................................PASS/FAIL
* Encoder controls output velocity...................................PASS/FAIL
* Clockwise rotation increases velocity..............................PASS/FAIL
* Counter-clockwise rotation decreases velocity.................PASS/FAIL
* Velocity changes smooth and responsive........................PASS/FAIL
* Input velocity ignored when in encoder mode..................PASS/FAIL
* Encoder velocity persists between notes.........................PASS/FAIL

3.3 Chord Mode Testing
* Switch to Preset 4.........................................................PASS/FAIL
* Chord mode activates correctly....................................PASS/FAIL
* Single note input triggers chord output..........................PASS/FAIL
* Chord intervals match selected scale.............................PASS/FAIL
* Multiple simultaneous inputs handled correctly................PASS/FAIL
* Chord voicing appropriate and musical...........................PASS/FAIL
* Note off messages handled for full chord.......................PASS/FAIL

⸻
SECTION 4: ARPEGGIATOR FUNCTIONALITY

4.1 Basic Arpeggiator Operation
* Switch to Preset 2........................................................PASS/FAIL
* Arpeggiator toggles on/off correctly.............................PASS/FAIL
* Arp LED indicates on/off state.....................................PASS/FAIL
* Single note input starts arpeggio................................PASS/FAIL
* Multiple notes create chord arpeggio............................PASS/FAIL
* Arpeggio stops when all keys released..........................PASS/FAIL
* Tempo follows current BPM setting..............................PASS/FAIL

4.2 Arpeggiator Patterns
* Up pattern plays notes ascending.................................PASS/FAIL
* Down pattern plays notes descending...........................PASS/FAIL
* Up/Down pattern plays ascending then descending..........PASS/FAIL
* Random pattern varies note order.................................PASS/FAIL
* Pattern changes take effect immediately.......................PASS/FAIL

4.3 Arpeggiator with Different Modes
* Test with Presets 2, 3, 4...............................................PASS/FAIL
* Arp works correctly in Velocity mode............................PASS/FAIL
* Arp works correctly in Encoder mode............................PASS/FAIL
* Arp works correctly in Chord mode...............................PASS/FAIL
* Mode-specific behaviors maintained during arp...............PASS/FAIL

⸻
SECTION 5: SCALE SYSTEM

5.1 Scale Selection
* Major scale pattern correct (W-W-H-W-W-W-H)................PASS/FAIL
* Minor scale pattern correct (W-H-W-W-H-W-W)...............PASS/FAIL
* Dorian scale pattern correct.........................................PASS/FAIL
* Pentatonic scale pattern correct...................................PASS/FAIL
* All available scales selectable.......................................PASS/FAIL
* Scale LEDs show correct pattern...................................PASS/FAIL

5.2 Root Note Selection
* All 12 chromatic roots selectable..................................PASS/FAIL
* Root note changes shift scale correctly..........................PASS/FAIL
* Scale pattern LEDs update with root change..................PASS/FAIL
* Musical output matches selected root/scale..................PASS/FAIL

5.3 Scale Behavior Across Modes
* Test with different presets...........................................PASS/FAIL
* Scale limiting works in Velocity mode...........................PASS/FAIL
* Scale limiting works in Encoder mode...........................PASS/FAIL
* Chord mode respects scale intervals.............................PASS/FAIL
* Out-of-scale notes handled appropriately......................PASS/FAIL

⸻
SECTION 6: LOOPER/RECORDING FUNCTIONALITY

6.1 Basic Recording
* Record button starts recording....................................PASS/FAIL
* Recording LED indicates record state............................PASS/FAIL
* Input notes captured during recording............................PASS/FAIL
* Record button stops recording......................................PASS/FAIL
* Recorded sequence plays back correctly........................PASS/FAIL

6.2 Loop Operations
* Loop starts automatically after recording.......................PASS/FAIL
* Loop repeats continuously...........................................PASS/FAIL
* Loop timing accurate....................................................PASS/FAIL
* Stop button ends loop playback..................................PASS/FAIL
* Clear function erases recorded content..........................PASS/FAIL

6.3 Quantization
* Quantization setting affects recording timing..................PASS/FAIL
* Quarter note quantization works correctly......................PASS/FAIL
* Eighth note quantization works correctly........................PASS/FAIL
* Sixteenth note quantization works correctly...................PASS/FAIL
* No quantization preserves original timing......................PASS/FAIL

6.4 Recording with Different Modes
* Recording works in Velocity mode.................................PASS/FAIL
* Recording works in Encoder mode.................................PASS/FAIL
* Recording works in Chord mode....................................PASS/FAIL
* Arpeggiator patterns recorded correctly........................PASS/FAIL

⸻
SECTION 7: PRESET MANAGEMENT

7.1 Preset Storage
* Current settings save to preset slot................................PASS/FAIL
* Preset save confirmation works.....................................PASS/FAIL
* All preset slots (1-8) accessible......................................PASS/FAIL
* Save operation preserves all parameters........................PASS/FAIL

7.2 Preset Recall
* Preset loading restores all settings.................................PASS/FAIL
* Scale, mode, BPM restored correctly...............................PASS/FAIL
* Arpeggiator settings restored........................................PASS/FAIL
* Preset recall immediate and accurate...............................PASS/FAIL

7.3 Preset Indicators
* Current preset number displayed....................................PASS/FAIL
* Preset modified indicator works.....................................PASS/FAIL
* Unsaved changes warning functions...............................PASS/FAIL

7.4 Chord File Management
* Chord files save correctly with presets..............................PASS/FAIL
* Chord files load correctly with presets.............................PASS/FAIL
* Multiple chord files can be managed...............................PASS/FAIL
* Chord file loading shows progress indicators..................PASS/FAIL
* Invalid chord files handled gracefully..............................PASS/FAIL

⸻
SECTION 8: TIMING AND TEMPO

8.1 BPM Control
* BPM adjustable via encoder.........................................PASS/FAIL
* BPM range appropriate (60-200+ BPM)..........................PASS/FAIL
* BPM display updates in real-time...................................PASS/FAIL
* Tempo changes affect arpeggiator immediately...............PASS/FAIL
* Tempo changes affect looper timing...............................PASS/FAIL

8.2 Clock Synchronization
* External MIDI clock sync works......................................PASS/FAIL
* Internal clock stable and accurate..................................PASS/FAIL
* Clock source switching functions..................................PASS/FAIL
* Tempo LED blinks at correct rate....................................PASS/FAIL

8.3 MIDI Sync with Ableton Live Testing
* Connect to Ableton Live and test MIDI sync behavior.........PASS/FAIL
* MIDI sync ON: Device follows Ableton tempo...................PASS/FAIL
* MIDI sync ON: Chords play when Ableton starts...............PASS/FAIL
* MIDI sync ON: Chords stop when Ableton stops................PASS/FAIL
* MIDI sync OFF: Device ignores Ableton clock...................PASS/FAIL
* MIDI sync OFF: Chords don't start with Ableton..............PASS/FAIL
* Sync state change stops all playing chords......................PASS/FAIL
* Switching sync OFF clears chord play queue.....................PASS/FAIL
* Tempo changes in Ableton reflected on device................PASS/FAIL

⸻
SECTION 9: ADVANCED FEATURES

9.1 MIDI Channel Management
* MIDI input channel selectable.......................................PASS/FAIL
* MIDI output channel selectable....................................PASS/FAIL
* Channel filtering works correctly..................................PASS/FAIL
* Multi-channel operation (if supported)............................PASS/FAIL

9.2 Velocity Curves
* Linear velocity curve works..........................................PASS/FAIL
* Exponential curve affects response................................PASS/FAIL
* Logarithmic curve affects response................................PASS/FAIL
* Curve selection responsive............................................PASS/FAIL

9.3 Note Priority
* Last note priority works in monophonic modes..................PASS/FAIL
* First note priority works correctly................................PASS/FAIL
* Highest note priority functions......................................PASS/FAIL
* Lowest note priority functions.......................................PASS/FAIL

9.4 MIDI Passthrough
* MIDI passthrough toggle on/off works...........................PASS/FAIL
* Passthrough only works with AUX MIDI.........................PASS/FAIL
* Input notes passed through correctly..............................PASS/FAIL
* Input CC messages passed through correctly..................PASS/FAIL
* Start/stop messages passed through................................PASS/FAIL
* Passthrough LED indication works..................................PASS/FAIL

9.5 Pad Channel Assignment
* Individual pad MIDI channel assignment works................PASS/FAIL
* Pad hold + encoder changes channel assignment...........PASS/FAIL
* Visual feedback for channel assignment...........................PASS/FAIL
* Multiple pads can be assigned simultaneously................PASS/FAIL
* Channel assignment persists in presets...........................PASS/FAIL

⸻
SECTION 10: STRESS TESTING

10.1 High Note Density
* Rapid note sequences handled correctly........................PASS/FAIL
* No MIDI data loss at high input rates.............................PASS/FAIL
* System remains responsive during high load...................PASS/FAIL
* No hanging notes or stuck states....................................PASS/FAIL

10.2 Extended Operation
* Device stable after 30+ minutes operation......................PASS/FAIL
* No memory leaks or degradation....................................PASS/FAIL
* Settings persist through extended use.............................PASS/FAIL
* LEDs maintain consistent brightness..............................PASS/FAIL

10.3 Edge Cases
* All notes off (MIDI panic) handled correctly....................PASS/FAIL
* Simultaneous button presses handled.............................PASS/FAIL
* Menu navigation during playback stable.........................PASS/FAIL
* Power interruption recovery appropriate........................PASS/FAIL

⸻
SECTION 11: INTEGRATION TESTING

11.1 DAW Integration
* Works correctly with Ableton Live..................................PASS/FAIL
* Works correctly with Logic Pro.......................................PASS/FAIL
* Works correctly with Cubase...........................................PASS/FAIL
* Generic MIDI device recognition....................................PASS/FAIL

11.2 Hardware Integration
* Works with various MIDI keyboards................................PASS/FAIL
* Chain with other MIDI devices.........................................PASS/FAIL
* USB hub compatibility...................................................PASS/FAIL
* Powered USB hub operation........................................PASS/FAIL

⸻
SECTION 12: USER EXPERIENCE

12.1 Ease of Use
* Intuitive button layout...................................................PASS/FAIL
* Clear visual feedback...................................................PASS/FAIL
* Logical menu structure...................................................PASS/FAIL
* Appropriate response times...........................................PASS/FAIL

12.2 Documentation Accuracy
* Manual matches actual behavior......................................PASS/FAIL
* All features documented................................................PASS/FAIL
* Setup instructions accurate............................................PASS/FAIL
* Troubleshooting guide helpful......................................PASS/FAIL

⸻
Ensure that the alignment and spacing match the style demonstrated here for consistency throughout the document. This will provide a professional and uniform appearance that enhances readability.