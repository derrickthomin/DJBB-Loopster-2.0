# DJBB MIDI Loopster

<div align="center">
<img src="https://github.com/user-attachments/assets/4930370d-5dd5-4f4c-8192-4d0b70316c29" alt="DJBB MIDI Loopster 2.0 - Light case with cloudy buttons" width="500px">
</div>

### Demo Vid Links
See my YouTube channel here for some vids of the Loopster in action: https://www.youtube.com/channel/UCpsQPNVT-AlGA7DJ-ZlrxLw

### firmware and updating

Latest is **[v3.0](https://github.com/derrickthomin/DJBB-Loopster-2.0/releases/latest)**. Never updated before? [Watch this video](https://youtu.be/EjhhI3hRFWo), it walks through the whole thing.

Easiest way is the [web config utility](https://derrickthomin.github.io/DJBB-Loopster-2.0/web_config.html) - it checks your version and installs the update for you. Otherwise grab `loopster.uf2` from the release and drag it onto the RPI-RP2 drive.

As of 3.0 the firmware is C++ (PlatformIO, arduino-pico core) instead of CircuitPython. Everything is baked into the one .uf2, so there are no loose files to edit on a drive anymore. Faster screen, tighter timing, and a lot more room for loops. To build it yourself: `pio run`. See [src/README.md](src/README.md) for details.

### key features

- **Record and Play MIDI Loops**: Record notes, CC messages, and aftertouch (channel pressure) on 16 pads with LED feedback. Loop, one-shot, or hold modes with arpeggiator compatibility.
- **MIDI I/O**: USB and DIN MIDI (full sized) input/output
- **Unique Arpeggiator**: Use encoder to scroll through arps. Supports various arpeggiator types (up, down, random, etc.) with gate and polyphony settings. Works with notes and CCs, respects per-pad MIDI channel assignments.
- **Scale Filtering**
- **Visual Feedback via Per Pad RGB LEDs**
- **Preset Management**: Load and save complete presets including recorded loops for session recall. Edit, rename, and back them up from the [web config utility](https://derrickthomin.github.io/DJBB-Loopster-2.0/web_config.html).
- **Per-Pad Loop MIDI Assignment**
- **Tempo and Sync Always On Screen**
- **Extra GPIOs**: Breakout pins for custom buttons, encoders, neopixels, and other add-ons.

### web config utility

**https://derrickthomin.github.io/DJBB-Loopster-2.0/web_config.html** - browser based, nothing to install. Plug in over USB and hit connect. Works in Chrome and Edge on a computer (Safari, Firefox, and phones can't talk to USB devices).

- Edit preset settings and save them straight to the device
- Rename presets
- Save and load backup files of all your presets
- Export loops off the pads as MIDI files, and import MIDI back onto them
- One click firmware updates

### using extra GPIOs for customization

The Midi Loopster 2.0 includes additional GPIO pins, allowing users to expand and customize their setup with extra buttons, encoders, potentiometers, neopixels, and more. This flexibility enables users to tailor the device to their specific needs and creative preferences.

#### available GPIO pins:
- **analog**: GP26, GP27, GP28, GP29
- **digital**: GP0, GP9, GP14, GP20, GP21, GP22, GP23, GP24, GP25

#### addon input/output examples:
```cpp
// extra neopixels on GP14
Adafruit_NeoPixel extra_pixels(16, 14, NEO_GRB + NEO_KHZ800);
extra_pixels.begin();

// button on GP0
pinMode(0, INPUT_PULLUP);
bool pressed = digitalRead(0) == LOW;

// potentiometer on GP26
int value = analogRead(A0);

// x/y joystick on GP26 / GP27
int x_axis = analogRead(A0);
int y_axis = analogRead(A1);

// i2c device on GP20 / GP21 (Wire)
Wire.setSDA(20);
Wire.setSCL(21);
Wire.begin();
```

For an encoder, copy the interrupt based one in [src/inputs.cpp](src/inputs.cpp).

### adding custom code to hooks

Custom code lives in [src/useraddons.cpp](src/useraddons.cpp). Drop your functions into the hooks below and they run at the right times during the device's operation. Rebuild with `pio run` and flash the new .uf2.

#### available hooks:
- **init()**: runs once at startup. do your `pinMode` / `begin()` setup here.
- **check_addons_fast()**: runs as fast as possible in the main loop. ideal for time-sensitive tasks.
- **slow()**: runs on a metered interval. suitable for less critical or time-sensitive tasks.
- **handle_new_notes_on(note, velocity, padidx, channel)**: triggered when a new note is played.
- **handle_new_notes_off(note, velocity, padidx, channel)**: triggered when a note is stopped.
- **handle_new_cc(cc, value, channel)**: triggered when a CC message is sent.

#### usage example:
```cpp
// ------------- place your code in one of the hooks below -------------

// runs once at boot
void init() {
    extra_pixels.begin();
}

// runs as fast as possible in main loop. don't put anything that takes a long time here.
void check_addons_fast() {
    // call your functions here...
    // change_midi_channel_with_encoder();
}

// runs on a metered interval in the main loop. do less critical or time-sensitive things here.
void slow() {
    // call your functions here...
    // change_all_midi_velocities_with_potentiometer();
}

// control neopixels with note events
void handle_new_notes_on(uint8_t note, uint8_t velocity, uint8_t padidx, int channel) {
    extra_pixels.setPixelColor(padidx, 0xFFFFFF); // white
    extra_pixels.show();
}

void handle_new_notes_off(uint8_t note, uint8_t velocity, uint8_t padidx, int channel) {
    extra_pixels.setPixelColor(padidx, 0); // off
    extra_pixels.show();
}
```

By placing your custom functions into these hooks, you can extend the functionality of the Midi Loopster 2.0 to meet your specific needs. With these extra GPIOs and customizable options, you can tailor the capabilities of the Midi Loopster 2.0 to suit your creative workflow perfectly.

---

### Changelog

#### July 2026 (Version 3.0)
Download here: https://github.com/derrickthomin/DJBB-Loopster-2.0/releases/tag/v3.0 - and [here's how to install it](https://youtu.be/EjhhI3hRFWo).

##### Speed & Responsiveness
- Firmware rewritten in C++ (PlatformIO / arduino-pico) - CircuitPython is gone
- Faster screen refresh
- Screen no longer can cause MIDI to stall for a sec
- Preset loading and saving is 10x-20x faster

##### MIDI & Sync
- CCs are now always stored in RAM = no more waiting 100ms or so for loops to save to flash
- Higher loop limits - up to 2048 CCs per loop
- More accurate and faster tempo sync to host
- Tempo and sync status now always show on the display

##### [Web Config Utility](https://derrickthomin.github.io/DJBB-Loopster-2.0/web_config.html)
- Browser based
- Edit preset settings and save to device
- Rename presets
- Save and load backup files of all presets
- Export MIDI from loopster pads for use in other programs
- Import MIDI to Loopster pads
- Easy firmware updates

<details>
<summary><b>Older changelogs</b></summary>

#### February 2026 (Version 2.41)
Download here: https://github.com/derrickthomin/DJBB-Loopster-2.0/releases/tag/2.41

- Larger loop limits in RAM
- Snappier menu navigation
- Architectural change: Now most code is baked into the new loopster.uf2. More RAM overhead.


#### January 2026 (Version 2.4)
##### New Features
- Hold Mode for Loops: New loop type that plays while pad is held and stops on release. Cycle through: loop → oneshot → hold.
- Flash Storage for Loops: Optional "CC to Flash" setting streams CC data to flash during recording, enabling ~10x more events than RAM storage.
- CC Snapback: New setting controls whether CC values reset to initial values when loops stop. Options: none, hold-only, or all loops.
- Settings Page Numbers: Settings screens now show page indicators (e.g., "1/13") for easier navigation.
- Aftertouch Recording: Records and plays back channel pressure (aftertouch) messages with loops. Supports flash storage for large recordings.
- Per Note MIDI Channel Mode: Records and plays back notes on their original MIDI channel

##### Enhancements
- MIDI Passthrough Optimization: Sends raw bytes instead of reconstructing MIDI objects for lower latency.
- Per-Event MIDI Channel Storage: MIDI channel stored per-event, allowing multi-channel recording into a single loop.
- Simplified Clock Source: Removed "AUTO" option; now only "USB" and "AUX" available.
- Memory Optimizations
- Synchronized Blinking: All blinking LEDs now blink in sync for cleaner visual feedback
- ALL Channels Input: New option to receive MIDI on all channels simultaneously
- Bank Offset Indicator: Display shows "+" suffixes (e.g., "Bank: 3+") when using quarter-bank navigation.
  
##### Bug Fixes
- MIDI Sync Fixes: Fixed queued recording starting early, blink state sync issues, and stuck pixels when sync enabled.
- Note Handling: Fixed held notes not closing on recording stop, and Note On velocity=0 now treated as Note Off (DX7 compatibility).
- Arpeggiator: Fixed notes not clearing when individual pad released.
- Navigation: Fixed quarter-bank navigation overflowing past bank boundaries.
- Loop Type Toggle: Fixed cycling desync when toggling backwards.
- FN Button: Fixed double-click counter not resetting properly.
- MIDI Continue Support: Properly handles MIDI Continue message for seamless transport control

##### Breaking Changes
- CSV chord storage format replaced with binary loop format. Old /chords/ directory no longer supported.
- USB device name changed from "LOOPSTER 2" to "LOOPSTER".
- "Startup Menu" setting removed.

#### June 2025 (Version 2.2)
##### New Features
- CC Recording: Loopster can now record and send CC messages just like notes - loop, oneshot, and arpeggiate them
- Midi Passthru: New setting to allow passing midi from the input directly back out.
- Preset Updates: Loops recorded to pads are now saved with presets
- Per Pad Loop Midi Assignment: Assign loops recorded to pads to different midi channels. Also respected by the arpeggiator.
- Quarter Bank Navigation: Hold FN and click the encoder to go up 1/4 of a bank, and the opposite to go down.
- New Oneshot Setting: Can change the behavior so that in oneshot mode, all notes are played at once (rather than in sequence).
- Quick Multi Chord Recording: Keep holding the FN button while recording a chord to a pad and press another pad to switch to recording to the new one. Only makes sense if recording to pads from an external source.


##### Optimizations
- (undocumented from prev update) Loopster is now 2X faster: RP2040 can safely be overclocked to double. Everything feels snappier, and timings are tighter.
- Expanded Event Capacity: Now you can record up to 500 notes or 1500 CC events per loop, and 5000 across all loops.
- Better MIDI Sync: More accurate clock, better handling of start and stop messages
- UI Improvements: Removed menu loop around behavior, optimized screen refreshes, and a bunch of other stuff
- Removed Looper Menu: Duplicitive since we can record to pads in a more flexible way. Downside is that there is no longer a way to overdub, though you can always "overdub" by just recording to a new pad
- Clock Source Detection: Wherever clock is received first is defaulted (USB vs DIN)
- Smarter Loop Type Assignment: Rather than always use what is in settings, if you change a loop to "oneshot", for example, the next recorded loop will be set to "oneshot" as well (or whatever the last loop type used was)
- Optimized "hold" Lenghts: FN button counts as "held" much faster so you can quickly start recording a chord.
- Auto Delete Empty Recordings: If a pad was recorded to but only contains off messages, or nothing at all, it will be auto deleted when recording is stopped.
- Updated Velocity Mode Colors: Now using a red scheme as to not conflict with note (yellow), playing (green), or CC (blue) colors.
- Major Code Refactoring: Easier to navigate and more efficient. Split out huge files into smaller ones (ie pixels.py), reduced use of global variables, and a bunch of other small stuff.
- Memory Improvements: Smarter generation of scales, earlier returns, etc. in order to save on RAM, which is what allowed us to greatly expand the event recording limits mentioned in the new features section above.
- Removed Useless Notifications: Displaying a notification on the screen costs ~30 ms. Since we have LEDs (as opposed to the loopster 1 which did not), we don't need to rely on the screen as much.
- Renamed "chord" to "loop" for clarity: Now the loop types are "loop" and "oneshot"
- MIDI I/O Indicators: Encoder button flashes yellow (note) or blue (cc) when external midi is coming in.

</details>
