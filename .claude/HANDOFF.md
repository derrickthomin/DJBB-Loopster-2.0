# Loopster C++ Firmware — Handoff Notes

Carried over from the sandbox conversion repo (2026-07-13). This is the ONLY doc that
transferred — full history/plans stayed behind in the sandbox repo's `.claude/`.

## What this is

Complete C++ port (PlatformIO, arduino-pico core) of the original CircuitPython firmware;
it replaced the Python tree on this branch. `src/` now holds the C++ sources,
`platformio.ini` + `version_stamp.py` sit at the repo root (standard PIO layout).
1:1 module mapping documented in `src/README.md`. The old Python firmware lives on in
`main`'s history and the archived `releases/` trees (kept on purpose for Python modders).

## Layout couplings — do NOT rename these directories

| Path | Depended on by |
|---|---|
| repo root = PIO project | `web_interface/index.html` dev-mode firmware path (`../.pio/build/loopster/firmware.uf2`) |
| `scripts/` next to `web_interface/` | Both `.mjs` harnesses load `../web_interface/index.html` at runtime |
| `scripts/presets.json` | Harness baseline preset `T_MULTI` (sync off, record_cc on) |
| `scripts/fixtures/*.mid` | Auto-discovered ground truth for `midi_codec_test.mjs` |

## Build & flash

- Dev build: `pio run` at the repo root → `.pio/build/loopster/firmware.uf2`
- Flash: `pio run -e loopster -t upload`, or BOOTSEL-drag the UF2
- **Customer/release build: `pio run -e loopster-release`** — identical fw but ALL
  `TEST_*` hooks compile out. Never ship the dev env.
- `version_stamp.py` (pre-build hook in platformio.ini) re-touches `fw_version.cpp` every
  build so `__DATE__` is fresh — the web UI's "Check for Updates" depends on it. Keep it.
- ⚠ After header changes made in another session/checkout, stale `.pio` cache causes
  phantom compile errors → `pio run -t clean` first.

## Test harnesses

### On-device suite (needs the device, dev-env firmware)
```sh
python3 -m venv scripts/.venv
scripts/.venv/bin/pip install mido python-rtmidi pyserial
scripts/.venv/bin/python scripts/loopster_test.py --auto
```
- 45 tests; `--auto` runs 44 (skips `limits-cc-flood`, tagged `crashy` — can trip the
  parked R18 hang). `--list`, `--test <name>`, `--all` also available.
- Reports auto-written to `scripts/test_reports/` (gitignored).
- **Re-run `--auto` after every firmware batch.** Last full run 2026-07-13: 43/44, sole
  fail was the new test's own bug (fixed, standalone PASS).
- ⚠ NEVER run a serial monitor or a second harness process during tests — shared tty
  corrupts responses and mimics crashes.
- ⚠ A rolling Ableton set on the same machine sends MIDI clock and poisons clock tests.

### Node harnesses (no device, no deps, Node ≥ 18)
```sh
node scripts/serial_queue_test.mjs   # web serial command queue (W1) — 43 tests
node scripts/midi_codec_test.mjs     # web MIDI import/export codecs
```
Both extract and eval the live sections of `index.html` — the queue and codec sections
must stay pure/no-DOM or these break (that's intentional pressure).

## Web interface / releases

- `web_interface/index.html` is a single static file (GitHub-Pages hostable; keep it
  static-hosting-safe — no build step, no server).
- Firmware releases live at GitHub `derrickthomin/DJBB-Loopster-2.0`. The one-click
  installer fetch chain ends at raw.githubusercontent.com because release-asset downloads
  are CORS-blocked; **committing a `loopster*.uf2` into that repo tree at the release tag
  activates true one-click with zero code change** (strict name match — other UF2s in the
  tree can't be auto-flashed).
- "Check for Updates" compares fw `__DATE__` (PING ack `built`) to the GitHub release
  `published_at` with 24 h slack. No version bookkeeping anywhere.

## Outstanding work (priority order)

1. **One manual browser + device session** — everything web-side since 07-08 is
   Node/fw-verified but never opened in a real browser: Connected badge + Update-Firmware
   enable (W2), both firmware-install paths end-to-end (W7), MIDI drag-import + discard
   banner + .mid export, pad-detail/backup-zip/restore-from-zip, Restart button,
   preset delete (trash + confirm; startup preset shows explain-only modal), W1 happy
   paths + mid-backup unplug (should toast, not hang).
2. **Screen eyeballs owed** (flashed but never visually checked): preset-save star/
   overwrite-confirm UX, WEB CONFIG lock takeover screen, BPM ♩ glyph + record beat
   blink, manual icon/panic chord feel.
3. **Q2** — UART MIDI TX is blocking; USB→AUX passthru can stall core 0 ~20–30 ms/pass.
   Fix: software TX ring drained non-blockingly (or per-pass byte budget).
4. **Q3** — clock ticks batched into one pass advance loop playback only 1 tick → synced
   loops play late after any slow pass until wrap. Fix: absolute position
   (`midi_ticks_elapsed - start_tickstamp`). Priority weakened by .mid round-trip evidence.
5. **W3 remainder** — preset Create/Duplicate in web UI (pure UI over SET_PRESET,
   16-cap enforced fw-side). Delete is done.
6. **W5/W6** — web dropdowns for scale/root/bank + range fixes; input validation +
   dirty-state polish. W5 pairs with fw-side Q4 whitelist (done).
7. **Manual/feel hardware checklist** — pre-ship sweep once churn settles (power-pull
   mid-save, flash-full, watchdog recovery, out-of-range presets, accel toggle mid-play…).

## Enhancement backlog (unscheduled)

- **Looper library extraction** — spin the loop engine into a reusable lib. Spec'd,
  difficulty ~6/10, 11 open design decisions. START ONLY AFTER v1 ships.
- **UI-D1** — invert settings-menu roles (turn=scroll, click=edit) per commercial
  convention. User: "skip for now".
- **UI-D2** — replace 3×3-px corner modifier dots with a readable one-line hint while
  FN/encoder held. Deferred by user.
- **Code-janitor cleanup backlog** — post-v1 hygiene sweep existed in the sandbox;
  nothing from it ships in v1. Re-run a janitor pass after v1 rather than porting the list.

## Decisions that will look wrong later (don't relitigate)

| Decision | Why |
|---|---|
| Parity with Python is NOT sacred | User rule: judge bugs on merit; never revert C++-only fixes to match Python |
| LittleFS, not FatFS | FatFS/SPIFTL persisted ~63 KB metadata per file op → flat ~2.1 s saves; LittleFS ~0.2 s, +66 KB heap. USB drive mode removed (user-waived); atomic tmp+rename kept |
| Loop storage v2 | One `loop_%04d.bin` per loop (magic 0x4C02, CRC-32 body); preset carries only `{loop_id}` |
| `.mid` never stored on device | Import: browser converts SMF→loop .bin, streams via `PUT_LOOP_FILE_CHUNK`. Loop-id allocation is host-side (`ALLOC_LOOP_ID` was built then removed — don't re-add) |
| CC/PB/AT MIDI *import* declined FINAL | Dismissible amber discard-warning banner instead. Export of CC/AT works |
| Quantize snaps to NEAREST bar; CC/AT tail past a down-snap is DROPPED | Accepted residual sustain-hang hazard; don't re-propose clamping |
| No auto-reconnect after web "Restart Now" | User call. Helper `reconnectWhenReEnumerated` kept unused in index.html — don't delete |
| Update check = build date, not content hash | W8 sha256 plan declined; build-date is zero-bookkeeping. Dev builds always show "update available" — expected |
| Bank chords, velocity bar, hard stops, knockout status strip | All DECLINED FINAL (burn-in / user taste) — don't re-propose |
| R18 (MIDI-flood watchdog hang) | PARKED, user call: extreme-edge. Repro = flood at END of full suite. Breadcrumbs (`hang_phase` in TEST_STATE) + bounded-CDC mitigation stay in firmware. If resuming: sub-marks in phase 8, and rule Q2's UART writes in/out |
| Constant ~17 ms host clock latency | Real, tempo-independent; user calibrates via Ableton Live Sync Delay ≈ −17 ms. Not a bug to chase |

## Firmware safety rules

- Watchdog must stay fed around multi-file flash work; **NEVER `idleOtherCore()` around
  flash ops** (arduino-pico flash writes already handle the other core; idling deadlocks).
- All runtime CDC prints must go through the bounded write path (`cdc_write_bounded`) —
  a raw `Serial.print` with a wedged host busy-waits into a watchdog reboot on stage (Q1,
  fixed at 14 sites; hold that line in new code).
