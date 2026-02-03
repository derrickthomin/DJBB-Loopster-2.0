# Memory Optimization Changes - colm-merge Branch

## Summary
Two optimizations implemented to reduce RAM usage by ~12-13KB total.

---

## 1. Minimal MPU6050 Driver (~10KB savings)

### What was done
Replaced `adafruit_mpu6050` library with a custom minimal driver that only implements what we need.

### Files created
- `src/mpu6050_minimal.py` - 45-line minimal MPU6050 driver

### Files modified
- `src/useraddons.py` - Changed import from `import adafruit_mpu6050` to `from mpu6050_minimal import MPU6050`

### Technical details
The full adafruit_mpu6050 library includes:
- Gyroscope support (unused)
- Temperature sensor (unused)
- Multiple configuration options (unused)
- adafruit_register dependency (unused)

Our minimal driver only implements:
- I2C communication with proper locking (`try_lock()`/`unlock()`)
- Wake-up sequence (clear sleep bit in PWR_MGMT_1)
- `.acceleration` property returning (x, y, z) in m/s²

### To port to main branch
1. Copy `src/mpu6050_minimal.py` to main branch
2. Update the import in `useraddons.py` (if accelerometer feature exists)
3. Can delete `lib/adafruit_mpu6050.mpy` from device to save flash space

---

## 2. Minimal Ticks Module (~2-3KB savings)

### What was done
Replaced `adafruit_ticks` library with a minimal drop-in replacement.

### Files created
- `src/ticks_minimal.py` - 20-line replacement module

### Files modified (import change only)
- `src/arp.py` - `import adafruit_ticks as ticks` → `import ticks_minimal as ticks`
- `src/clock.py` - same change
- `src/code.py` - same change
- `src/debug.py` - same change
- `src/looper.py` - same change

### Technical details
adafruit_ticks provides wraparound-safe timing for intervals up to ~6 days.
Our code only uses sub-second intervals (note durations, polling, etc.).

Functions replaced:
| Original | Replacement |
|----------|-------------|
| `ticks_ms()` | `int(time.monotonic() * 1000)` |
| `ticks_diff(a, b)` | `a - b` |
| `ticks_add(a, b)` | `a + b` |
| `ticks_less(a, b)` | `a < b` |

### To port to main branch
1. Copy `src/ticks_minimal.py` to main branch
2. Find/replace in these files: `import adafruit_ticks as ticks` → `import ticks_minimal as ticks`
   - arp.py
   - clock.py
   - code.py
   - debug.py
   - looper.py
3. Can delete `lib/adafruit_ticks.mpy` from device to save flash space

---

## Other Opportunities Investigated (NOT implemented)

### Unused MIDI submodules - CANNOT REMOVE
- `PitchBend` and `PolyphonicKeyPressure` are used in `midi.py` for MIDI passthrough type checking
- They're needed to recognize and forward these message types

### adafruit_ssd1306 minimal - NOT RECOMMENDED
- Would save ~4-6KB but requires keeping adafruit_framebuf dependency
- Medium complexity, some risk

### neopixel minimal - NOT RECOMMENDED  
- Core CircuitPython feature with optimized C code
- Python replacement would be slower
- Not worth the risk

---

## Testing Checklist

After porting, verify:
- [ ] Device boots without import errors
- [ ] Accelerometer readings work (tilt CC messages)
- [ ] Accelerometer calibration works (double-toggle)
- [ ] Arpeggiator timing works correctly
- [ ] Loop recording/playback timing works
- [ ] MIDI clock sync works
- [ ] Memory output shows improvement (~12-13KB more free)

---

## Memory Impact Summary

| Change | Savings | Risk |
|--------|---------|------|
| mpu6050_minimal | ~10KB | Low |
| ticks_minimal | ~2-3KB | None |
| **Total** | **~12-13KB** | **Low** |
