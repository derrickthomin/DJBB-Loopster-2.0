# Loopster Firmware — C++ Port

Complete C++ port of the CircuitPython firmware (on the `main` branch history; all 25 modules,
1:1 file mapping). Builds with PlatformIO on the arduino-pico core.

## Build & flash

```sh
pio run                          # -> .pio/build/loopster/firmware.uf2
```

Flash: BOOTSEL-drag the UF2, or `picotool load -f .pio/build/loopster/firmware.uf2`.

## File mapping (Python -> C++)

| Python | C++ | Notes |
|---|---|---|
| boot.py + code.py | main.cpp | FN-at-boot = dedicated USB-drive service mode (see below) |
| constants.py | constants.h | float seconds -> uint32 ms (`_S` -> `_MS`) |
| ticks_minimal.py | ticks.h/.cpp | wrap-safe |
| utils.py | utils.h | |
| settings.py | settings.h/.cpp | presets.json keys byte-identical |
| presets.py | presets.h/.cpp | supervisor.reload() -> rp2040.reboot() |
| midiscales.py | midiscales.h/.cpp | |
| buttons.py | buttons.h/.cpp | |
| clock.py | clock.h/.cpp | global is `clock_` (Arduino claims `clock()`) |
| pixels.py | pixels.h/.cpp | shadow buffer preserves exact-color compare |
| display.py | display.h/.cpp | GP18/19 = I2C1 = Wire1 |
| midi.py | midi.h/.cpp | raw USB packets + UART running-status parser |
| looper.py | looper.h/.cpp | flash-streaming path removed (loops live in RAM) |
| loop_storage.py | loop_storage.h/.cpp | .bin formats byte-identical (packed structs) |
| loopmanager.py | loopmanager.h/.cpp | `loops[i] == ""` -> nullptr |
| inputs.py | inputs.h/.cpp | hand-rolled matrix scan + IRQ encoder |
| arp.py | arp.h/.cpp | |
| menus.py | menus.h/.cpp | actions dict -> std::function struct |
| playmenu.py | playmenu.h/.cpp | |
| settingsmenu.py | settingsmenu.h/.cpp | option lists as display strings |
| pedals.py | pedals.h/.cpp | |
| useraddons.py + mpu6050_minimal.py | useraddons.h/.cpp | GP20/21 = I2C0 = Wire |
| serial_config.py | serial_config.h/.cpp | web UI protocol byte-identical |

## Deliberate behavior differences

1. **Flash streaming removed** (per plan.md): loops always live in RAM; .bin files
   written only at preset save. `cc_stream_to_flash` remains in settings/JSON for
   compat but has no effect.
2. **Drive mode is exclusive**: FN held at boot -> MSC service mode (host owns the
   FS, app doesn't run). CircuitPython ran the app read-only alongside; TinyUSB MSC
   requires exclusivity. Eject + power-cycle to return to normal.
3. **No overclock**: stock 133 MHz (C++ headroom makes 270 MHz unnecessary).
4. **No GC/memory management**: all gc.collect()/mem_free threshold logic dropped.

Confirmed as improvements by the 2026-07-05 parity audit (`.claude/parity-audit-findings.md`;
that audit also found and fixed 4 real parity bugs — see its findings table):

5. **MIDI clock counting fixed**: only 0xF8 counts as a clock tick. Python counted
   ANY unrecognized message (active sensing 0xFE, pitch bend, poly pressure) as a
   tick while syncing, corrupting BPM detection.
6. **True hardware-thru passthru**: forwards ALL channels on both ports and passes
   ProgramChange. Python filtered USB passthru by `midi_channel_in` and dropped PC.
7. **CC/AT recording headroom**: RAM-mode limit raised 512 -> 2048 events per loop
   (`CC_RAM_LIMIT` retired; RAM is plentiful now).

## Untested — hardware bring-up checklist

Compiles green; not yet validated on the device. Verify in roughly this order:
1. Boot: startup screen, pixels clear, "Loopster" USB device (MIDI + CDC)
2. Pads: matrix scan direction (pre-mortem #9: if pads map wrong/dead, swap the
   drive/read direction in inputs.cpp KeyMatrix)
3. Encoder direction + detent rate; FN/encoder press, hold, double-press
4. Live play: pad -> note on/off in DAW, velocity, banks, scales
5. Loop record/playback; quantize; oneshot/hold modes
6. Preset save/load; power-cycle persistence; web UI connect
7. Addons: pedals, glove buttons, accelerometer (enable switch + double-toggle cal)
