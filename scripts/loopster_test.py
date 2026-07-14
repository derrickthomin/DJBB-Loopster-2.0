#!/usr/bin/env python3
"""
Loopster on-device test harness.

Talks to the Loopster over its two USB interfaces:
  - CDC serial: the web-config CMD:/RSP: protocol, extended with TEST_* hooks
    (firmware built with -DLOOPSTER_TEST_HOOKS — see src/test_hooks.cpp)
  - USB MIDI:   sends test patterns, captures what the device plays back

Usage:
  python3 loopster_test.py               # interactive: pick tests or run all
  python3 loopster_test.py --all         # run everything in order
  python3 loopster_test.py --auto        # automated tests, minus "crashy" ones
  python3 loopster_test.py --test record-playback-multichannel
  python3 loopster_test.py --list

Tests tagged "crashy" (currently limits-cc-flood, which can trip the parked
R18 watchdog hang at the end of a full suite) are excluded from --auto and
the interactive [u]nattended pick; --all / --tag / --test still run them.

Each test ends PASS / FAIL / SKIP (manual steps prompt p/f/s; automated
assertions decide on their own). A report is printed and written to
scripts/test_reports/.

Adding a test: write a function taking a Ctx and decorate it:

    @test("my-test", "One-line description", tags=("auto",))
    def my_test(ctx):
        ctx.device.record(0)
        ...
        ctx.check(cond, "what was expected")

Dependencies: pip install mido python-rtmidi pyserial
"""

import argparse
import base64
import json
import os
import re
import struct
import subprocess
import sys
import threading
import time
import zlib
from collections import Counter
from datetime import datetime
from pathlib import Path

try:
    import mido
    import serial
    from serial.tools import list_ports
except ImportError as e:
    print(f"Missing dependency: {e.name}")
    print("Install with:  pip install mido python-rtmidi pyserial")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
PRESETS_FILE = SCRIPT_DIR / "presets.json"
REPORT_DIR = SCRIPT_DIR / "test_reports"

BASELINE_PRESET = "T_MULTI"  # uploaded from presets.json; sync off, record_cc on

# Menu indices (keep in sync with C::MENU_* in src/constants.h)
MENU_PLAY = 0
MENU_MIDI = 2

# 2026-07-06: the mid-flood heartbeat (CDC exchange during max-rate MIDI RX) is
# the prime suspect for the reproducible limits-cc-flood watchdog hang — set
# env CC_FLOOD_HEARTBEAT=0 to run the flood with zero serial traffic while
# notes stream (loses early death detection; the post-pad state call still runs).
CC_FLOOD_HEARTBEAT = os.environ.get("CC_FLOOD_HEARTBEAT", "1") != "0"


# --------------------------------------------------------------------------
# Device I/O
# --------------------------------------------------------------------------

class DeviceError(Exception):
    """Serial/MIDI communication failed — device may have crashed or rebooted."""


class Device:
    def __init__(self, serial_port=None, midi_name=None):
        self._serial_port_hint = serial_port
        self._midi_name_hint = midi_name
        self.ser = None
        self.midi_in = None
        self.midi_out = None
        self._rxbuf = b""
        self._awaiting = 0  # RSP lines the device still owes us
        self._clock_thread = None
        self._clock_stop = threading.Event()

    # ---- discovery / connection ----

    def _find_serial_port(self):
        if self._serial_port_hint:
            return self._serial_port_hint
        candidates = []
        for p in list_ports.comports():
            text = " ".join(filter(None, (p.product, p.description, p.manufacturer)))
            if "loopster" in text.lower():
                return p.device
            if "usbmodem" in p.device.lower() or "ttyACM" in p.device:
                candidates.append(p.device)
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            print("Multiple USB serial ports found:")
            for i, c in enumerate(candidates):
                print(f"  [{i}] {c}")
            pick = input("Which one is the Loopster? ")
            return candidates[int(pick)]
        return None

    def _find_midi_port(self, names):
        if self._midi_name_hint:
            hits = [n for n in names if self._midi_name_hint.lower() in n.lower()]
        else:
            hits = [n for n in names if "loopster" in n.lower()]
        return hits[0] if hits else None

    @staticmethod
    def _open_serial(port, open_timeout=5.0):
        """serial.Serial() blocks forever in tcsetattr/ioctl when a crashed
        device leaves its CDC endpoint half-dead but still enumerated (seen
        after the CC-flood crash). Open in a worker thread with a timeout."""
        result = {}
        abandoned = threading.Event()

        def worker():
            try:
                s = serial.Serial(port, 115200, timeout=0.1)
                if abandoned.is_set():
                    s.close()  # main thread gave up; don't leak the fd
                else:
                    result["ser"] = s
            except Exception as e:  # noqa: BLE001 — reported to caller
                result["err"] = e

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(open_timeout)
        if t.is_alive():
            abandoned.set()
            raise DeviceError(
                f"opening {port} hung — device is half-crashed; power-cycle it")
        if "err" in result:
            raise DeviceError(f"could not open {port}: {result['err']}")
        return result["ser"]

    @staticmethod
    def _warn_if_port_shared(port):
        """macOS lets several processes read one tty; a serial monitor left open
        (e.g. `pio device monitor`) steals bytes and corrupts every exchange."""
        try:
            out = subprocess.run(["lsof", port], capture_output=True, text=True,
                                 timeout=5).stdout.strip().splitlines()
        except Exception:  # noqa: BLE001 — diagnostics only
            return
        others = [l for l in out[1:] if f" {os.getpid()} " not in f" {l} "]
        if others:
            print(f"\n  WARNING: another process is already reading {port}:")
            for l in others:
                print(f"    {l}")
            print("  Close it (serial monitor / web config?) or every command will flake.\n")

    def connect(self, timeout=10.0):
        deadline = time.monotonic() + timeout
        last_err = "no Loopster serial port found"
        warned = False
        while time.monotonic() < deadline:
            try:
                port = self._find_serial_port()
                if port and not warned:
                    warned = True
                    self._warn_if_port_shared(port)
                in_name = self._find_midi_port(mido.get_input_names())
                out_name = self._find_midi_port(mido.get_output_names())
                if port and in_name and out_name:
                    self.ser = self._open_serial(port)
                    self.midi_in = mido.open_input(in_name)
                    self.midi_out = mido.open_output(out_name)
                    self.cmd("TEST_STATE")  # prove the link + hooks work
                    return
            except Exception as e:  # noqa: BLE001 — retry until deadline
                last_err = str(e)
                self.close()
            time.sleep(0.5)
        raise DeviceError(f"Could not connect to Loopster: {last_err}")

    def close(self):
        self.stop_clock()
        self._rxbuf = b""
        self._awaiting = 0
        for attr in ("ser", "midi_in", "midi_out"):
            obj = getattr(self, attr)
            if obj:
                try:
                    obj.close()
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, attr, None)

    def reconnect(self, timeout=30.0, settle=2.0):
        """After a reboot/crash: wait for re-enumeration and reopen everything."""
        self.close()
        time.sleep(settle)
        self.connect(timeout=timeout)

    # ---- serial protocol (never sends PING, so the device is never locked) ----
    #
    # Every CMD: gets exactly one RSP:, but flash-writing commands (SET_PRESET
    # et al) block the device main loop for 6-10+ seconds before answering.
    # So responses are tracked with a ledger (_awaiting): if a command times
    # out, its late RSP is collected and discarded before the next command is
    # sent — otherwise it would be misread as the next command's answer.
    # _rxbuf persists across calls so partial lines are never clipped.

    SLOW_CMDS = ("SET_PRESET", "GET_PRESET", "RENAME_PRESET", "SET_STARTUP",
                 "TEST_LOAD_PRESET", "TEST_STATE|FULL",
                 "TEST_SAVE_PRESET", "TEST_DELETE_PRESET")

    def _read_rsp_line(self, deadline):
        """Next complete RSP: line as text (JSON part), or None on timeout."""
        while time.monotonic() < deadline:
            self._rxbuf += self.ser.read(256)
            while b"\n" in self._rxbuf:
                line, self._rxbuf = self._rxbuf.split(b"\n", 1)
                text = line.decode(errors="replace").strip()
                if text.startswith("RSP:"):
                    return text[4:]
                # non-RSP lines are firmware debug output — ignore
        return None

    def cmd(self, command, timeout=None):
        if not self.ser:
            raise DeviceError("serial port not open")
        if timeout is None:
            timeout = 30.0 if command.startswith(self.SLOW_CMDS) else 5.0
        try:
            # Settle responses still owed from previously timed-out commands
            while self._awaiting > 0:
                if self._read_rsp_line(time.monotonic() + 30.0) is None:
                    self._awaiting = 0
                    raise DeviceError(
                        f"device never answered an earlier command (before {command})")
                self._awaiting -= 1

            self.ser.write(f"CMD:{command}\n".encode())
            self._awaiting += 1
            text = self._read_rsp_line(time.monotonic() + timeout)
            if text is None:
                # leave _awaiting at 1: the next cmd() will collect the late RSP
                raise DeviceError(f"timeout ({timeout}s) waiting for RSP to {command}")
            self._awaiting -= 1
            rsp = json.loads(text)
            if "error" in rsp:
                raise DeviceError(f"{command} -> {rsp['error']} ({rsp.get('code')})")
            return rsp
        except (serial.SerialException, OSError) as e:
            raise DeviceError(f"serial I/O failed during {command}: {e}") from e
        except json.JSONDecodeError as e:
            raise DeviceError(f"malformed RSP to {command}: {text[:120]!r} ({e})") from e

    def state(self, full=False):
        return self.cmd("TEST_STATE|FULL" if full else "TEST_STATE")

    def record(self, pad):
        return self.cmd(f"TEST_RECORD|{pad}")

    def stop_record(self):
        return self.cmd("TEST_STOP_RECORD")

    def play(self, pad):
        return self.cmd(f"TEST_PLAY|{pad}")

    def stop(self, pad):
        return self.cmd(f"TEST_STOP|{pad}")

    def toggle(self, pad):
        """Plain play toggle — same semantics as a user pad press: queues under
        midi_sync when the clock is stopped (TEST_PLAY force-plays instead)."""
        return self.cmd(f"TEST_TOGGLE|{pad}")

    def stop_all(self):
        return self.cmd("TEST_STOP_ALL")

    def clear(self, pad):
        """Remove a single loop (occupied-pad TEST_CLEAR)."""
        return self.cmd(f"TEST_CLEAR|{pad}")

    def clear_all(self):
        return self.cmd("TEST_CLEAR_ALL")

    def set_midi_sync(self, on):
        return self.cmd(f"TEST_MIDI_SYNC|{1 if on else 0}")

    def set_loop_type(self, loop_type):
        """New loops inherit the device's current loop type (loop/oneshot/hold).
        'hold' loops start stopped after recording, so tests pin 'loop'."""
        return self.cmd(f"TEST_LOOP_TYPE|{loop_type}")

    def inject_pad(self, pad, pressed):
        """Virtual pad press/release, consumed by the real input pipeline
        (identically to a pedal event) on the next input pass."""
        return self.cmd(f"TEST_PAD|{pad}|{1 if pressed else 0}")

    def inject_encoder(self, delta=1):
        """Virtual encoder detents (positive = clockwise = arp step forward)."""
        return self.cmd(f"TEST_ENCODER|{delta}")

    def set_menu(self, idx):
        """Jump to a menu by index (MENU_PLAY / MENU_MIDI / ...)."""
        return self.cmd(f"TEST_MENU|{idx}")

    def set_play_mode(self, mode):
        """'loop' / 'encoder' / 'velocity'. Encoder mode also locks the play
        menu, mirroring the device-side toggle."""
        return self.cmd(f"TEST_PLAY_MODE|{mode}")

    def change_bank(self, up=True):
        """Bank up/down through the real handler (sends all-notes-off)."""
        return self.cmd(f"TEST_BANK|{1 if up else 0}")

    def set_quantize(self, time_="none", strength=100, loop_amount=None):
        """Quantize settings applied to recordings finalized from now on."""
        c = f"TEST_QUANTIZE|{time_}|{strength}"
        if loop_amount is not None:
            c += f"|{loop_amount}"
        return self.cmd(c)

    def set_arp(self, polyphonic=True, length=None):
        c = f"TEST_ARP_CONFIG|{1 if polyphonic else 0}"
        if length:
            c += f"|{length}"
        return self.cmd(c)

    def rename_preset(self, old, new):
        return self.cmd(f"RENAME_PRESET|{old}|{new}")

    def upload_preset(self, name, preset_dict):
        payload = json.dumps(preset_dict, separators=(",", ":"))
        return self.cmd(f"SET_PRESET|{name}|{payload}")

    def get_preset(self, name):
        return self.cmd(f"GET_PRESET|{name}")

    def load_preset(self, name, reconnect_timeout=30.0):
        """Persist + reboot into a preset (same path as the device menu)."""
        self.cmd(f"TEST_LOAD_PRESET|{name}")
        self.reconnect(timeout=reconnect_timeout)

    def save_preset(self, name):
        """Device-menu save path: settings + recorded loops -> flash. Makes
        `name` the startup preset, exactly like a menu save. Fast on LittleFS
        (2026-07-06 switch; the FatFS FTL cost ~2 s per file op), but keep the
        long timeout so a genuine regression fails the budget test, not here."""
        return self.cmd(f"TEST_SAVE_PRESET|{name}", timeout=120.0)

    def delete_preset(self, name):
        """Test-hook cleanup; refuses the startup preset and reserved keys."""
        return self.cmd(f"TEST_DELETE_PRESET|{name}")

    def preset_names(self):
        return list(self.cmd("GET_PRESET_NAMES").get("names", []))

    def reboot(self, reconnect_timeout=30.0):
        self.cmd("TEST_REBOOT")
        self.reconnect(timeout=reconnect_timeout)

    # ---- MIDI ----

    def drain_midi(self):
        if self.midi_in:
            for _ in self.midi_in.iter_pending():
                pass

    def send(self, msg, pause=0.0):
        self.midi_out.send(msg)
        if pause:
            time.sleep(pause)

    def send_burst(self, msgs, burst=16, pause=0.002):
        """Send many messages fast: full USB-MIDI rate inside a burst, then a
        short breather so the device's RX FIFO can drain (~16x faster than the
        old per-message sleep; drops under load are acceptable in stress use)."""
        for i, msg in enumerate(msgs):
            self.midi_out.send(msg)
            if pause and i % burst == burst - 1:
                time.sleep(pause)

    def capture(self, duration, ignore_realtime=True):
        """Collect (elapsed_seconds, mido.Message) for `duration` seconds."""
        out = []
        t0 = time.perf_counter()
        while (elapsed := time.perf_counter() - t0) < duration:
            for msg in self.midi_in.iter_pending():
                if ignore_realtime and msg.type in ("clock", "start", "stop", "continue", "songpos"):
                    continue
                out.append((elapsed, msg))
            time.sleep(0.002)
        return out

    def capture_while(self, duration, actions, ignore_realtime=True):
        """capture(), but firing (at_seconds, fn) actions at their offsets while
        collecting — lets a test timestamp MIDI relative to serial commands it
        issues mid-capture (each cmd round-trip is only a few ms, so event
        timestamps stay accurate to ~20 ms)."""
        out = []
        pending = sorted(actions, key=lambda a: a[0])
        t0 = time.perf_counter()
        while (elapsed := time.perf_counter() - t0) < duration:
            while pending and elapsed >= pending[0][0]:
                pending.pop(0)[1]()
            for msg in self.midi_in.iter_pending():
                if ignore_realtime and msg.type in ("clock", "start", "stop", "continue", "songpos"):
                    continue
                out.append((time.perf_counter() - t0, msg))
            time.sleep(0.002)
        return out

    # ---- MIDI clock (for sync tests) ----

    def start_clock(self, bpm=120, send_start=False):
        self.stop_clock()
        self._clock_stop.clear()
        interval = 60.0 / (bpm * 24)

        def run():
            if send_start:
                self.midi_out.send(mido.Message("start"))
            nxt = time.perf_counter()
            while not self._clock_stop.is_set():
                self.midi_out.send(mido.Message("clock"))
                nxt += interval
                delay = nxt - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)

        self._clock_thread = threading.Thread(target=run, daemon=True)
        self._clock_thread.start()

    def stop_clock(self, send_stop=False):
        if self._clock_thread:
            self._clock_stop.set()
            self._clock_thread.join(timeout=1.0)
            self._clock_thread = None
        if send_stop and self.midi_out:
            self.midi_out.send(mido.Message("stop"))


# --------------------------------------------------------------------------
# Test framework
# --------------------------------------------------------------------------

class TestSkipped(Exception):
    pass


class TestFailed(Exception):
    pass


TESTS = []  # (id, description, tags, fn)


def test(test_id, description, tags=("auto",)):
    def deco(fn):
        TESTS.append({"id": test_id, "desc": description, "tags": tuple(tags), "fn": fn})
        return fn

    return deco


class Ctx:
    def __init__(self, device):
        self.device = device
        self.notes = []  # log lines shown in the report

    def log(self, msg):
        print(f"    {msg}")
        self.notes.append(msg)

    def check(self, cond, what):
        """Automated assertion: records PASS detail or raises TestFailed."""
        if cond:
            self.log(f"ok: {what}")
        else:
            raise TestFailed(what)

    def instruct(self, msg):
        print(f"\n  >>> {msg}")

    def wait_enter(self, msg="Press ENTER when ready"):
        input(f"  >>> {msg} ")

    def ask_pass_fail(self, question):
        """Manual verdict. Returns normally on pass, raises on fail/skip."""
        while True:
            a = input(f"  >>> {question} [p]ass / [f]ail / [s]kip: ").strip().lower()
            if a in ("p", "pass"):
                return
            if a in ("f", "fail"):
                detail = input("      What went wrong? ").strip()
                raise TestFailed(detail or question)
            if a in ("s", "skip"):
                raise TestSkipped(question)

    def skip(self, why):
        raise TestSkipped(why)

    def heartbeat(self):
        """Assert the device is still alive; raises DeviceError if not."""
        return self.device.state()

    def crash_recovery(self):
        """Called after a DeviceError: try auto-reconnect, else ask for a power cycle."""
        print("    Device stopped responding — attempting reconnect...")
        try:
            self.device.reconnect(timeout=15.0)
            self.log("device came back on its own (rebooted?)")
            return
        except DeviceError:
            pass
        self.instruct("Device appears CRASHED. Power-cycle the Loopster now.")
        self.wait_enter("Press ENTER once it has rebooted")
        self.device.reconnect(timeout=30.0)


def cleanup_between_tests(device):
    """Best-effort return to a quiet baseline state."""
    try:
        device.stop_clock(send_stop=True)
        # Restores for the newer hooks; firmware without them answers
        # unknown_command, which must not abort the rest of the cleanup.
        for c in ("TEST_PLAY_MODE|loop", "TEST_QUANTIZE|none|100|none"):
            try:
                device.cmd(c)
            except DeviceError:
                pass
        device.clear_all()
        device.stop_all()
        time.sleep(0.3)
        device.drain_midi()
    except DeviceError:
        pass  # the runner's crash handling deals with it on the next test


# --------------------------------------------------------------------------
# MIDI helpers
# --------------------------------------------------------------------------

def note_on(note, vel, ch):
    return mido.Message("note_on", note=note, velocity=vel, channel=ch)


def note_off(note, ch):
    return mido.Message("note_off", note=note, channel=ch)


def cc(control, value, ch):
    return mido.Message("control_change", control=control, value=value, channel=ch)


def aftertouch(pressure, ch):
    return mido.Message("aftertouch", value=pressure, channel=ch)


def summarize(captured):
    """Multiset of hashable event keys from a capture."""
    keys = []
    for _, m in captured:
        if m.type == "note_on" and m.velocity > 0:
            keys.append(("on", m.note, m.velocity, m.channel))
        elif m.type == "note_off" or (m.type == "note_on" and m.velocity == 0):
            keys.append(("off", m.note, m.channel))
        elif m.type == "control_change":
            keys.append(("cc", m.control, m.value, m.channel))
        elif m.type == "aftertouch":
            keys.append(("at", m.value, m.channel))
    return Counter(keys)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

@test("serial-state", "TEST_STATE responds with sane fields over CDC serial")
def t_serial_state(ctx):
    st = ctx.device.state(full=True)
    ctx.log(f"state: preset={st.get('preset')} heap_free={st.get('heap_free')} "
            f"uptime_ms={st.get('uptime_ms')} midi_sync={st.get('midi_sync')}")
    for field in ("recording", "clock_playing", "bpm", "heap_free", "loops"):
        ctx.check(field in st, f"state has '{field}'")
    ctx.check(st["heap_free"] > 10_000, f"free heap looks sane ({st['heap_free']} bytes)")


@test("ping-identity", "PING ack carries device:'loopster' (W2 web Connected badge)")
def t_ping_identity(ctx):
    # PING web-locks the device — DISCONNECT must always follow, even on failure.
    try:
        rsp = ctx.device.cmd("PING")
        ctx.check(rsp.get("status") == "ok", f"PING acked ok ({rsp})")
        ctx.check(rsp.get("device") == "loopster",
                  f"PING ack identifies the device (got {rsp.get('device')!r})")
        # Build date fed to the web UI's "Check for Updates" verdict. Must be a real
        # __DATE__ ("Mmm dd yyyy") the browser's Date.parse() can read — a stale/blank
        # value silently breaks the up-to-date check.
        built = rsp.get("built")
        parsed = None
        if isinstance(built, str):
            try:
                # __DATE__ is "Mmm dd yyyy" (double-space pads single-digit days; strptime
                # collapses the run against a single-space format).
                parsed = datetime.strptime(built.strip(), "%b %d %Y")
            except ValueError:
                pass
        ctx.check(parsed is not None,
                  f"PING ack build date parses as a __DATE__ (got {built!r})")
    finally:
        ctx.device.cmd("DISCONNECT")


@test("preset-upload-roundtrip", "SET_PRESET then GET_PRESET returns the same settings")
def t_preset_roundtrip(ctx):
    presets = json.loads(PRESETS_FILE.read_text())
    sent = presets[BASELINE_PRESET]
    ctx.device.upload_preset(BASELINE_PRESET, sent)
    got = ctx.device.get_preset(BASELINE_PRESET)
    body = got.get("preset", got)  # tolerate either response shape
    if isinstance(body, str):
        body = json.loads(body)
    mismatches = [k for k, v in sent.items()
                  if k in body and body[k] != v and not isinstance(v, float)]
    ctx.check(not mismatches, f"round-tripped fields match (mismatched: {mismatches})")


@test("baseline-preset-load", "Upload test presets and reboot into T_MULTI (sync off)")
def t_baseline(ctx):
    presets = json.loads(PRESETS_FILE.read_text())
    for name, body in presets.items():
        if name.startswith("_"):
            continue
        ctx.device.upload_preset(name, body)
        ctx.log(f"uploaded preset {name}")
    ctx.instruct("Loading T_MULTI — the device will reboot (takes a few seconds)")
    ctx.device.load_preset(BASELINE_PRESET)
    st = ctx.device.state(full=True)
    ctx.check(st.get("preset") == BASELINE_PRESET, f"device booted into {BASELINE_PRESET}")
    ctx.check(st.get("midi_sync") is False, "midi_sync is off")
    ctx.check(st.get("record_cc") is True, "record_cc is on")


@test("preset-field-validation",
      "Out-of-range preset values are clamped on load, not crashed on (robustness #5)")
def t_field_validation(ctx):
    """Web SET_PRESET can write arbitrary JSON; loading it used to feed OOB indices
    straight into SCALE_INTERVALS/ROOT_NAMES/bank tables (crash) and malformed MIDI
    status bytes. _validate_loaded_fields() now clamps every field on apply. This
    uploads a deliberately garbage preset, loads it (reboot), and proves the device
    (a) comes back at all and (b) clamped midi_channel_out — the one clamped field
    TEST_STATE exposes. Old firmware would store 99 (or crash on the scale tables).

    Also covers the Q4 string-whitelist half: a garbage midi_type ("usbb") used to make
    should_send()/should_receive() false on BOTH ports — instrument looks alive but is
    mute. Now it falls back to "USB"; whitespaced/miscased values (" Velocity ") are
    trimmed + normalized to the canonical spelling instead of being reset."""
    presets = json.loads(PRESETS_FILE.read_text())
    junk = dict(presets[BASELINE_PRESET])   # start from a known-good preset
    junk.pop("loops", None)                  # don't drag baseline loop metadata along
    junk.update({
        "scale_idx": 99, "rootnote_idx": 99,        # OOB -> SCALE_INTERVALS / ROOT_NAMES
        "midibank_idx": 99, "scalenotes_idx": 99,   # OOB -> bank tables
        "midi_channel_out": 99, "midi_channel_in": 99,
        "default_velocity": 250, "default_bpm": 9999,
        "quantize_strength": 999, "cc_resolution": 999,
        "led_brightness": 5.0,
        "midi_type": "usbb",          # garbage -> fallback "USB" (Q4; old fw: mute instrument)
        "play_mode": " Velocity ",    # whitespace+case -> normalized "velocity", NOT reset to "loop"
    })
    ctx.device.upload_preset("T_JUNK", junk)
    ctx.instruct("Loading T_JUNK (out-of-range) — device reboots; old firmware could crash here")
    ctx.device.load_preset("T_JUNK")

    st = ctx.device.state(full=True)
    ctx.check(st.get("preset") == "T_JUNK", "device booted into the junk preset (no crash on load)")
    ch = st.get("channel_out")
    ctx.check(isinstance(ch, int) and 0 <= ch <= 15,
              f"midi_channel_out clamped into 0-15 (got {ch})")
    ctx.check(st.get("heap_free", 0) > 10_000,
              f"heap sane after loading junk preset ({st.get('heap_free')} bytes)")
    if "midi_type" in st:  # older firmware's TEST_STATE lacks the field
        ctx.check(st["midi_type"] == "USB",
                  f"garbage midi_type fell back to USB (got {st['midi_type']!r})")
        ctx.check(st.get("play_mode") == "velocity",
                  f"' Velocity ' normalized to canonical (got {st.get('play_mode')!r})")
    else:
        ctx.log("TEST_STATE has no midi_type field (pre-Q4 firmware) — string checks skipped")

    # Leave the device on the good baseline for the tests that follow,
    # and remove the junk preset now that it's proven harmless.
    ctx.device.load_preset(BASELINE_PRESET)
    try:
        ctx.device.delete_preset("T_JUNK")
        ctx.log("cleaned up T_JUNK")
    except DeviceError as e:
        ctx.log(f"could not delete T_JUNK (old firmware without the hook?): {e}")


@test("record-playback-multichannel",
      "Record notes+CCs on several channels into one loop; verify playback matches")
def t_record_playback(ctx):
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    sent_notes = [(60, 100, 0), (64, 90, 4), (67, 80, 9)]   # (note, vel, channel)
    sent_ccs = [(1, 50, 1), (74, 101, 6)]                   # (cc, value, channel)

    d.record(0)
    time.sleep(0.15)
    for n, v, ch in sent_notes:
        d.send(note_on(n, v, ch), pause=0.12)
        d.send(note_off(n, ch), pause=0.08)
    for c, v, ch in sent_ccs:
        d.send(cc(c, v, ch), pause=0.05)
    time.sleep(0.15)

    st = d.state()
    loop0 = next((l for l in st["loops"] if l["pad"] == 0), None)
    ctx.check(loop0 is not None, "loop exists on pad 0 while recording")
    ctx.check(loop0["notes_on"] == len(sent_notes),
              f"loop recorded {len(sent_notes)} note-ons (got {loop0['notes_on']})")
    ctx.check(loop0["ccs"] == len(sent_ccs),
              f"loop recorded {len(sent_ccs)} CCs (got {loop0['ccs']})")

    d.drain_midi()
    d.stop_record()  # sync off -> playback starts immediately
    loop_len = 0.15 + len(sent_notes) * 0.2 + len(sent_ccs) * 0.05 + 0.15
    captured = d.capture(loop_len * 2.5)
    d.stop_all()
    got = summarize(captured)

    for n, v, ch in sent_notes:
        ctx.check(got[("on", n, v, ch)] >= 2,
                  f"note {n} vel {v} ch {ch} played back on the right channel, looped "
                  f"(seen {got[('on', n, v, ch)]}x)")
        ctx.check(got[("off", n, ch)] >= 2, f"note {n} ch {ch} got its note-offs")
    for c, v, ch in sent_ccs:
        # CC sends are value-deduped by the firmware, so >=1 (not per repetition)
        ctx.check(got[("cc", c, v, ch)] >= 1, f"CC{c}={v} ch {ch} played back")

    wrong_ch = [k for k in got if k[0] == "on" and k[3] not in {ch for _, _, ch in sent_notes}]
    ctx.check(not wrong_ch, f"no notes on unexpected channels (got {wrong_ch})")
    d.clear_all()


@test("record-playback-aftertouch",
      "Channel pressure records, plays back, and stays time-aligned after trim (R4)")
def t_aftertouch(ctx):
    """Aftertouch is recorded unconditionally (unlike CCs) but no other test sends
    any. Also automates the R4 checklist row: the loop trims leading silence at
    finalize, and pre-R4 the AT events were NOT shifted with everything else, so
    they played ~the trimmed amount late relative to their notes. Records a loop
    with a deliberate 0.6 s pause before the first note, AT pulses while the note
    is held, and asserts every played-back AT lands inside its note, not after it."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    at_values = (40, 80, 110)
    d.record(1)
    time.sleep(0.6)                         # leading silence for the trimmer to remove
    d.send(note_on(60, 100, 5), pause=0.10)
    for p in at_values:                     # pressure pulses while the note is held
        d.send(aftertouch(p, 5), pause=0.10)
    d.send(note_off(60, 5), pause=0.15)
    d.stop_record()

    st = d.state()
    lp = next((l for l in st["loops"] if l["pad"] == 1), None)
    ctx.check(lp is not None and lp["ats"] == len(at_values),
              f"{len(at_values)} AT events recorded (got {lp['ats'] if lp else 0})")

    d.drain_midi()
    captured = d.capture(3.0)
    d.stop_all()
    got = summarize(captured)
    for p in at_values:
        ctx.check(got[("at", p, 5)] >= 1, f"AT {p} played back on the recorded channel")

    # R4 alignment: every AT must land within ~0.5 s after a note-on (the note is
    # held 0.45 s). Pre-R4, the un-trimmed AT ticks played ~0.6 s late.
    ons = [t for t, m in captured if m.type == "note_on" and m.velocity > 0]
    ats = [t for t, m in captured if m.type == "aftertouch"]
    ctx.check(bool(ons) and bool(ats), "captured both notes and aftertouch")
    misaligned = []
    for at in ats:
        prev_on = max((t for t in ons if t <= at + 0.05), default=None)
        if prev_on is None:
            continue  # AT from a cycle whose note-on predates the capture window
        if at - prev_on > 0.55:
            misaligned.append(round(at - prev_on, 3))
    ctx.check(not misaligned,
              f"all ATs within their note (offsets late by {misaligned}s would mean "
              f"the trim skipped aftertouch — R4)")
    d.clear_all()


@test("loop-timing-stability",
      "Loop playback period is stable across repeats (tick/timing engine)")
def t_timing_stability(ctx):
    """Regression net for the timing core (tick math, loop-length calc, wrap
    handling): record a ~1.1 s loop with one note and verify the note repeats
    at a constant period. Timing bugs show up as drifting/erratic intervals
    long before they're audible in casual play."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    d.record(0)
    time.sleep(0.15)
    d.send(note_on(60, 100, 0), pause=0.10)
    d.send(note_off(60, 0))
    time.sleep(0.95)
    d.drain_midi()
    d.stop_record()  # sync off -> playback starts immediately

    captured = d.capture(6.0)
    d.stop_all()
    ons = [t for t, m in captured
           if m.type == "note_on" and m.note == 60 and m.velocity > 0]
    ctx.check(len(ons) >= 4, f"loop repeated enough to measure ({len(ons)} note-ons in 6 s)")
    intervals = [b - a for a, b in zip(ons, ons[1:])]
    mean = sum(intervals) / len(intervals)
    spread = max(intervals) - min(intervals)
    ctx.log("periods: " + ", ".join(f"{iv * 1000:.0f}ms" for iv in intervals))
    ctx.check(0.7 <= mean <= 1.6, f"loop period plausible for a ~1.1s loop (mean {mean:.3f}s)")
    ctx.check(spread < 0.08,
              f"repeat-to-repeat jitter under 80 ms (spread {spread * 1000:.0f} ms)")
    d.clear_all()


@test("quantize-record", "quantize_time snaps recorded notes onto the 1/8 grid")
def t_quantize(ctx):
    """Nothing else exercises the quantizer (quantize_events at record finalize).
    Records two notes deliberately ~120 ms off an 1/8 grid (max possible error on
    a 250 ms grid at 120 BPM) with 100% strength, then checks the played-back
    spacing between the two pitches is a clean grid multiple. A quantize
    regression currently only shows up in feel."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    st = d.state()
    bpm = float(st["bpm"])
    grid = 60.0 / bpm / 2  # 1/8 note in seconds (0.25 s at 120 BPM)
    ctx.log(f"bpm={bpm:g} -> 1/8 grid = {grid * 1000:.0f} ms")

    d.set_quantize("1/8", 100)
    try:
        d.record(0)
        time.sleep(0.15)
        d.send(note_on(60, 100, 0))
        time.sleep(0.10)
        d.send(note_off(60, 0))
        time.sleep(0.27)  # note 64 starts 0.37 s after 60 — maximally off-grid
        d.send(note_on(64, 100, 0))
        time.sleep(0.10)
        d.send(note_off(64, 0))
        time.sleep(0.35)
        d.drain_midi()
        d.stop_record()
        captured = d.capture(5.0)
        d.stop_all()
    finally:
        d.set_quantize("none")

    t60 = [t for t, m in captured if m.type == "note_on" and m.note == 60 and m.velocity > 0]
    t64 = [t for t, m in captured if m.type == "note_on" and m.note == 64 and m.velocity > 0]
    ctx.check(len(t60) >= 2 and len(t64) >= 2,
              f"loop repeated enough to measure ({len(t60)}/{len(t64)} onsets)")
    diffs = []
    for a in t60:
        nxt = min((b for b in t64 if b > a), default=None)
        if nxt is not None:
            diffs.append(nxt - a)
    ctx.check(bool(diffs), "found note-60 -> note-64 pairs")
    errs = []
    for dt in diffs:
        e = dt % grid
        errs.append(min(e, grid - e))
    mean_err = sum(errs) / len(errs)
    ctx.log("spacings: " + ", ".join(f"{dt * 1000:.0f}ms" for dt in diffs))
    ctx.check(mean_err < 0.06,
              f"spacing snapped to the {grid * 1000:.0f} ms grid (mean err "
              f"{mean_err * 1000:.0f} ms; unquantized would be ~120 ms)")
    d.clear_all()


# quantize_loop() snaps loop LENGTH to the nearest bar/unit (2026-07-12: nearest,
# up OR down, guarded on the last note-ON; was always ceil-up). One 4/4 bar =
# LOOPER_TICKS_PER_QUARTER_NOTE(24) * 4 = 96 loop ticks (looper.h). total_ticks is
# read straight from the loop via TEST_STATE, so these assert the exact length.
TICKS_PER_BAR = 96


@test("quantize-loop-down",
      "quantize_loop snaps length DOWN to the nearest bar when just over a boundary")
def t_quantize_loop_down(ctx):
    """Record ~1.15 bars with one note early in bar 1 and nothing late: the loop
    LENGTH must snap DOWN to exactly 1 bar (96 ticks). The old ceil-only behavior
    would have padded UP to 2 bars (192) — this is the decisive regression net for
    the round-to-nearest change."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    bpm = float(d.state()["bpm"])
    bar_s = 60.0 / bpm * 4  # one 4/4 bar in seconds
    ctx.log(f"bpm={bpm:g} -> 1 bar = {bar_s * 1000:.0f} ms = {TICKS_PER_BAR} ticks")

    d.set_quantize("none", 100, loop_amount="1")
    try:
        d.record(0)
        time.sleep(0.10)
        d.send(note_on(60, 100, 0), pause=0.10)  # first event -> tick 0 after trim
        d.send(note_off(60, 0))
        time.sleep(max(0.0, 1.15 * bar_s - 0.10))  # first-note -> stop span = 1.15 bars
        d.drain_midi()
        d.stop_record()
        d.stop_all()
    finally:
        d.set_quantize("none", 100, loop_amount="none")

    lp = next((l for l in d.state()["loops"] if l["pad"] == 0), None)
    ctx.check(lp is not None, "loop recorded on pad 0")
    if lp:
        ctx.log(f"total_ticks={lp['total_ticks']} "
                f"(expect {TICKS_PER_BAR}; old ceil-up would be {2 * TICKS_PER_BAR})")
        ctx.check(lp["total_ticks"] == TICKS_PER_BAR,
                  f"length snapped DOWN to 1 bar ({lp['total_ticks']} == {TICKS_PER_BAR})")
    d.clear_all()


@test("quantize-loop-up",
      "quantize_loop snaps length UP to the nearest bar when just under a boundary")
def t_quantize_loop_up(ctx):
    """Complement to quantize-loop-down and a no-regression net for the UP path:
    record ~1.8 bars with one early note. Nearest boundary is 2 bars, so the
    length must snap UP to 192 ticks."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    bpm = float(d.state()["bpm"])
    bar_s = 60.0 / bpm * 4
    ctx.log(f"bpm={bpm:g} -> 1 bar = {bar_s * 1000:.0f} ms")

    d.set_quantize("none", 100, loop_amount="1")
    try:
        d.record(0)
        time.sleep(0.10)
        d.send(note_on(60, 100, 0), pause=0.10)
        d.send(note_off(60, 0))
        time.sleep(max(0.0, 1.8 * bar_s - 0.10))  # span = 1.8 bars -> nearest is 2
        d.drain_midi()
        d.stop_record()
        d.stop_all()
    finally:
        d.set_quantize("none", 100, loop_amount="none")

    lp = next((l for l in d.state()["loops"] if l["pad"] == 0), None)
    ctx.check(lp is not None, "loop recorded on pad 0")
    if lp:
        ctx.log(f"total_ticks={lp['total_ticks']} (expect {2 * TICKS_PER_BAR})")
        ctx.check(lp["total_ticks"] == 2 * TICKS_PER_BAR,
                  f"length snapped UP to 2 bars ({lp['total_ticks']} == {2 * TICKS_PER_BAR})")
    d.clear_all()


@test("quantize-loop-note-guard",
      "quantize_loop forces UP (not down) when a note was struck past the down-snap point")
def t_quantize_loop_note_guard(ctx):
    """The nearest-bar snap must never clip a played note. Record ~1.25 bars
    (which rounds DOWN to 1 bar on length alone) but strike a second note at
    ~1.12 bars, inside bar 2. The last-note-ON guard must force the length UP to
    2 bars (192 ticks) so that note still fits; an ungated nearest-snap would give
    96 and strand the bar-2 note."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    bpm = float(d.state()["bpm"])
    bar_s = 60.0 / bpm * 4
    ctx.log(f"bpm={bpm:g} -> 1 bar = {bar_s * 1000:.0f} ms")

    d.set_quantize("none", 100, loop_amount="1")
    try:
        d.record(0)
        time.sleep(0.10)
        t0 = time.time()
        d.send(note_on(60, 100, 0), pause=0.10)  # first note -> tick 0 after trim
        d.send(note_off(60, 0))
        rem = (t0 + 1.12 * bar_s) - time.time()  # strike a note ~1.12 bars in (bar 2)
        if rem > 0:
            time.sleep(rem)
        d.send(note_on(64, 100, 0), pause=0.08)
        d.send(note_off(64, 0))
        rem = (t0 + 1.25 * bar_s) - time.time()  # stop at 1.25 bars (rounds DOWN alone)
        if rem > 0:
            time.sleep(rem)
        d.drain_midi()
        d.stop_record()
        d.stop_all()
    finally:
        d.set_quantize("none", 100, loop_amount="none")

    lp = next((l for l in d.state()["loops"] if l["pad"] == 0), None)
    ctx.check(lp is not None, "loop recorded on pad 0")
    if lp:
        ctx.log(f"total_ticks={lp['total_ticks']} (expect {2 * TICKS_PER_BAR}; "
                f"ungated nearest would strand the bar-2 note at {TICKS_PER_BAR})")
        ctx.check(lp["total_ticks"] == 2 * TICKS_PER_BAR,
                  f"guard forced length UP to 2 bars ({lp['total_ticks']} == {2 * TICKS_PER_BAR})")
        ctx.check(lp["notes_on"] == 2, f"both note-ons recorded ({lp['notes_on']})")
    d.clear_all()


@test("quantize-loop-drop-cc-at",
      "Down-snap strands CC/AT past the new end: they drop cleanly, loop stays healthy")
def t_quantize_loop_drop_cc_at(ctx):
    """The nearest-snap guard covers note-ONs only; CC + aftertouch events left past
    a down-snapped end are intentionally DROPPED (not clamped). This is a loop state
    the old ceil-only code could never produce, so prove it doesn't wedge: record a
    note in bar 1 plus in-loop CC/AT, then trailing CC/AT into bar 2 with sentinel
    values, and stop at ~1.3 bars so the length snaps DOWN to 1 bar. The trailing
    CC(74)=99 and AT=111 must NEVER play, while the loop keeps wrapping and its
    in-loop events keep firing (queues not stranded/wedged)."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    bpm = float(d.state()["bpm"])
    bar_s = 60.0 / bpm * 4
    ctx.log(f"bpm={bpm:g} -> 1 bar = {bar_s * 1000:.0f} ms = {TICKS_PER_BAR} ticks")

    d.set_quantize("none", 100, loop_amount="1")
    try:
        d.record(0)
        time.sleep(0.10)
        t0 = time.time()
        d.send(note_on(60, 100, 0), pause=0.10)  # first event -> tick 0 after trim
        d.send(note_off(60, 0), pause=0.05)
        d.send(cc(74, 40, 0), pause=0.05)         # in-loop CC (bar 1)
        d.send(aftertouch(50, 0), pause=0.05)     # in-loop AT (bar 1)
        rem = (t0 + 1.15 * bar_s) - time.time()   # trailing events land in bar 2
        if rem > 0:
            time.sleep(rem)
        d.send(cc(74, 99, 0), pause=0.05)         # STRANDED after down-snap
        d.send(aftertouch(111, 0), pause=0.05)    # STRANDED after down-snap
        rem = (t0 + 1.30 * bar_s) - time.time()   # stop -> length rounds DOWN to 1 bar
        if rem > 0:
            time.sleep(rem)
        d.drain_midi()
        d.stop_record()
    finally:
        d.set_quantize("none", 100, loop_amount="none")

    lp = next((l for l in d.state()["loops"] if l["pad"] == 0), None)
    ctx.check(lp is not None, "loop recorded on pad 0")
    if lp:
        ctx.log(f"total_ticks={lp['total_ticks']} ccs={lp['ccs']} ats={lp['ats']}")
        ctx.check(lp["total_ticks"] == TICKS_PER_BAR,
                  f"length snapped DOWN to 1 bar despite trailing CC/AT "
                  f"({lp['total_ticks']} == {TICKS_PER_BAR}) -- CC/AT don't pin length")
        ctx.check(lp["ccs"] == 2 and lp["ats"] == 2,
                  f"all events stored incl. the stranded ones (ccs={lp['ccs']}, ats={lp['ats']})")

    d.drain_midi()
    captured = d.capture(5.0)
    d.stop_all()
    got = summarize(captured)
    ons = got[("on", 60, 100, 0)]
    offs = got[("off", 60, 0)]
    ctx.log(f"playback: note60 on={ons} off={offs}; "
            f"cc74=40 x{got[('cc', 74, 40, 0)]}, cc74=99 x{got[('cc', 74, 99, 0)]}; "
            f"at50 x{got[('at', 50, 0)]}, at111 x{got[('at', 111, 0)]}")
    ctx.check(ons >= 2, f"loop kept wrapping -- note repeated ({ons}x in 5 s)")
    ctx.check(offs >= ons - 1, f"no stuck notes (offs {offs} >= ons {ons} - 1)")
    ctx.check(got[("cc", 74, 99, 0)] == 0,
              "stranded CC(74)=99 never played (dropped, not fired late/every wrap)")
    ctx.check(got[("at", 111, 0)] == 0, "stranded AT=111 never played (dropped)")
    ctx.check(got[("cc", 74, 40, 0)] >= 1, "in-loop CC(74)=40 still plays (CC queue not wedged)")
    ctx.check(got[("at", 50, 0)] >= 1, "in-loop AT=50 still plays (AT queue not wedged)")
    d.clear_all()


@test("loop-type-oneshot", "Oneshot loop plays exactly once per trigger, then stops")
def t_oneshot(ctx):
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("oneshot")
    d.clear_all()
    d.drain_midi()

    d.record(3)
    time.sleep(0.1)
    d.send(note_on(65, 90, 0), pause=0.12)
    d.send(note_off(65, 0), pause=0.3)
    d.drain_midi()
    d.stop_record()

    # By design (hw-confirmed 2026-07-06): a oneshot does NOT auto-play when
    # recording stops — it waits for a pad press.
    got = summarize(d.capture(1.5))
    ctx.check(got[("on", 65, 90, 0)] == 0,
              f"no auto-play after recording stops (got {got[('on', 65, 90, 0)]}x)")

    # Each trigger plays the shot exactly once; a "loop"-type regression would
    # show repeats in the ~5x-loop-length capture window.
    for trigger in (1, 2):
        d.drain_midi()
        d.play(3)
        got = summarize(d.capture(2.5))
        ctx.check(got[("on", 65, 90, 0)] == 1,
                  f"trigger {trigger} played exactly once (got {got[('on', 65, 90, 0)]}x)")

    d.set_loop_type("loop")
    d.clear_all()


@test("loop-type-hold", "Hold loop starts stopped after recording; play/stop works")
def t_hold(ctx):
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("hold")
    d.clear_all()
    d.drain_midi()

    d.record(6)
    time.sleep(0.1)
    d.send(note_on(67, 85, 0), pause=0.12)
    d.send(note_off(67, 0), pause=0.2)
    d.stop_record()

    st = d.state()
    lp = next((l for l in st["loops"] if l["pad"] == 6), None)
    ctx.check(lp is not None, "hold loop exists on pad 6")
    ctx.check(lp is not None and lp["playing"] is False,
              "hold loop starts in the STOPPED state after recording")
    d.drain_midi()
    silent = summarize(d.capture(1.0))
    ctx.check(not [k for k in silent if k[0] == "on"],
              "no playback until the pad is 'held'")

    d.play(6)
    got = summarize(d.capture(1.5))
    ctx.check(got[("on", 67, 85, 0)] >= 1, "force-play makes the hold loop audible")
    d.stop(6)

    d.set_loop_type("loop")
    d.clear_all()


@test("midi-sync-transport", "midi_sync=true: loops wait for MIDI Start and obey Stop")
def t_midi_sync(ctx):
    d = ctx.device
    d.clear_all()
    d.set_midi_sync(True)
    d.set_loop_type("loop")
    d.drain_midi()

    # Record a loop. With sync on and no clock, recording arms and waits.
    d.record(4)
    st = d.state()
    ctx.check(st["armed"] is True, "recording is armed (waiting for transport/note)")

    d.start_clock(bpm=120, send_start=True)
    time.sleep(0.3)
    d.send(note_on(62, 95, 2), pause=0.15)
    d.send(note_off(62, 2), pause=0.3)
    d.stop_record()
    st = d.state()
    ctx.check(any(l["pad"] == 4 for l in st["loops"]), "loop recorded on pad 4")

    # Playing clock -> loop should be audibly looping
    d.drain_midi()
    playing = summarize(d.capture(2.0))
    ctx.check(playing[("on", 62, 95, 2)] >= 1,
              f"loop plays while transport running (seen {playing[('on', 62, 95, 2)]}x)")

    # MIDI Stop -> everything halts (allow a short tail for note-offs)
    d.stop_clock(send_stop=True)
    time.sleep(0.5)
    d.drain_midi()
    silent = summarize(d.capture(2.0))
    stray = [k for k in silent if k[0] == "on"]
    ctx.check(not stray, f"no note-ons after MIDI Stop (got {stray})")

    # Design (parity with Python _stop_single_loop): a loop stopped by MIDI
    # Stop stays queued and auto-resumes on the next Start. Verify both halves.
    st = d.state()
    loop4 = next((l for l in st["loops"] if l["pad"] == 4), None)
    ctx.check(loop4 is not None and loop4["queued"],
              "loop remains queued after MIDI Stop (auto-resume design)")
    d.drain_midi()
    still = summarize(d.capture(1.5))
    ctx.check(not [k for k in still if k[0] == "on"],
              "queued loop stays silent until transport restarts")
    d.start_clock(bpm=120, send_start=True)
    d.drain_midi()
    started = summarize(d.capture(2.0))
    ctx.check(started[("on", 62, 95, 2)] >= 1, "queued loop auto-resumes on MIDI Start")

    d.stop_clock(send_stop=True)
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()


@test("clock-counter-semantics",
      "Tick counter == master song tick: Start/Continue downbeat swallow, SPP pinning")
def t_clock_counter(ctx):
    """Deterministic regression check for the 2026-07 clock-sync bug class (see
    .claude CHANGELOG 07-08/07-09): every grid-anchor bug was ultimately
    'midi_ticks_elapsed != the master's song tick'. Asserts that invariant with
    pure counting — no timing tolerances, so it cannot flake.
    Spec anchor: the first 0xF8 after Start OR Continue IS the resume-point tick
    (hw-proven vs Ableton: midi_diag/midimonitor_ableton_resume_130bpm.txt)."""
    d = ctx.device
    d.clear_all()
    d.set_midi_sync(True)
    d.drain_midi()
    settle = 0.15  # MIDI and CDC are separate USB endpoints; let sends land first

    def ticks():
        st = d.state()
        return st["clock_ticks"], st["tick_pending"]

    # Start alone: counter reset, downbeat swallow armed
    d.send(mido.Message("start"))
    time.sleep(settle)
    t, pending = ticks()
    ctx.check(t == 0, f"Start resets counter (got {t})")
    ctx.check(pending is True, "downbeat swallow armed after Start")

    # 10 clocks: first one IS the downbeat (tick 0) -> counter ends at 9
    for _ in range(10):
        d.send(mido.Message("clock"))
    time.sleep(settle)
    t, pending = ticks()
    ctx.check(t == 9, f"first clock after Start swallowed: 10 clocks -> counter 9 (got {t})")
    ctx.check(pending is False, "swallow consumed by first clock")

    # Stop preserves the count (recording finalization depends on it)
    d.send(mido.Message("stop"))
    time.sleep(settle)
    t, _ = ticks()
    ctx.check(t == 9, f"Stop preserves counter (got {t})")

    # SPP while stopped pins counter to song position (MIDI beats = 16ths = 6 ticks)
    d.send(mido.Message("songpos", pos=64))
    time.sleep(settle)
    t, _ = ticks()
    ctx.check(t == 64 * 6, f"SPP 64 while stopped -> counter 384 (got {t})")

    # Continue + 5 clocks: bundled first clock = the resume-point tick (swallowed)
    d.send(mido.Message("continue"))
    for _ in range(5):
        d.send(mido.Message("clock"))
    time.sleep(settle)
    t, _ = ticks()
    ctx.check(t == 384 + 4, f"Continue swallows its first clock: 384+4 (got {t})")

    # SPP while ROLLING is ignored (mid-roll jump would corrupt an active recording)
    d.send(mido.Message("songpos", pos=0))
    time.sleep(settle)
    t, _ = ticks()
    ctx.check(t == 388, f"SPP ignored while rolling (got {t})")

    d.send(mido.Message("stop"))
    time.sleep(settle)
    d.set_midi_sync(False)
    d.drain_midi()


@test("clock-bpm-latch",
      "External tempo change latches within 3 beats (quarter-note BPM window + confirm)")
def t_clock_bpm_latch(ctx):
    """Regression net for the 2026-07-12 BPM-responsiveness fix: the measurement
    window shrank from a whole note (96 ticks) to one beat (24 ticks), with the
    two-window confirmation and ±1 deadband kept. Worst-case latch is now 3 beats;
    the old algorithm needed >= 2 whole notes (~3.4 s at 140 even best-case), so
    the 3.0 s deadline cleanly discriminates old vs new."""
    d = ctx.device
    d.clear_all()
    d.set_midi_sync(True)
    d.drain_midi()

    def poll_bpm(target, deadline):
        got = None
        while time.time() < deadline:
            got = d.state()["bpm"]
            if abs(got - target) <= 1:
                break
            time.sleep(0.1)
        return got

    # Establish 100 BPM (device boots believing 120): 2 windows ~1.2 s
    d.start_clock(bpm=100, send_start=True)
    got = poll_bpm(100, time.time() + 4.0)
    ctx.check(abs(got - 100) <= 1, f"initial latch to 100 BPM (got {got})")

    # Tempo change mid-roll: swap generator threads without Stop/Start, like
    # dragging Live's tempo slider. The swap gap stretches one tick inside a
    # measurement window; confirmation must filter that bogus reading, then
    # latch 140 off two clean windows.
    t0 = time.time()
    d.start_clock(bpm=140)  # start_clock() stops the old thread first
    got = poll_bpm(140, t0 + 3.0)
    elapsed = time.time() - t0
    ctx.check(abs(got - 140) <= 1, f"latched 140 BPM after tempo change (got {got})")
    ctx.check(elapsed <= 3.0, f"latched in {elapsed:.2f}s (old algorithm needed >=3.4s)")
    ctx.log(f"tempo change 100 -> 140 latched in {elapsed:.2f}s")

    d.stop_clock(send_stop=True)
    d.set_midi_sync(False)
    d.drain_midi()


@test("spp-continue-resume",
      "Ableton-style resume: SPP + Continue (no Start) restarts queued loops on the pinned grid")
def t_spp_continue_resume(ctx):
    """End-to-end net for the 2026-07-09 clock bug class: Live never sends Start
    mid-song — it sends SPP then Continue, and every other sync test only ever
    exercised Start. Records a loop under a rolling transport, stops it, then
    resumes the Live way and asserts (a) the queued loop audibly auto-resumes on
    Continue and (b) the tick counter keeps growing from the SPP-pinned position
    with a real threaded clock (a Continue-treated-as-Start regression would
    restart it near zero). clock-counter-semantics proves the same counter math
    tick-by-tick; this proves the loop engine plays along."""
    d = ctx.device
    d.clear_all()
    d.set_midi_sync(True)
    d.set_loop_type("loop")
    d.drain_midi()

    d.record(0)
    d.start_clock(bpm=120, send_start=True)
    time.sleep(0.3)
    d.send(note_on(64, 100, 3), pause=0.15)
    d.send(note_off(64, 3), pause=0.3)
    d.stop_record()
    time.sleep(0.2)
    d.stop_clock(send_stop=True)  # loop stops but stays queued (auto-resume design)
    time.sleep(0.3)
    st = d.state()
    lp = next((l for l in st["loops"] if l["pad"] == 0), None)
    ctx.check(lp is not None and lp["queued"], "loop queued after MIDI Stop")

    # Live's resume sequence: SPP pins the song position, then Continue + clocks.
    d.send(mido.Message("songpos", pos=32))  # 32 MIDI beats = 192 ticks
    time.sleep(0.15)
    st = d.state()
    ctx.check(st["clock_ticks"] == 192, f"SPP pinned counter to 192 (got {st['clock_ticks']})")

    d.drain_midi()
    d.send(mido.Message("continue"))
    d.start_clock(bpm=120, send_start=False)  # ticks only — Live never sends Start here
    resumed = summarize(d.capture(2.0))
    st = d.state()
    d.stop_clock(send_stop=True)

    ctx.check(resumed[("on", 64, 100, 3)] >= 1,
              f"queued loop auto-resumed on Continue (seen {resumed[('on', 64, 100, 3)]}x)")
    # ~2.1 s at 120 BPM = ~100 ticks on top of 192. A reset-to-zero regression
    # would read ~100 here; keep the window wide for thread jitter.
    ctx.check(250 <= st["clock_ticks"] <= 360,
              f"counter grew from the SPP anchor, not from 0 (got {st['clock_ticks']})")
    ctx.check(st["clock_playing"] is True, "transport rolling during the resume")

    d.set_midi_sync(False)
    d.clear_all()


@test("transport-restart-mid-recording",
      "A fresh MIDI Start mid-recording (no Stop) doesn't crash, lose the take, or hang notes")
def t_restart_mid_recording(ctx):
    """Pattern-looping hardware sequencers re-send Start at every pattern wrap —
    so a Start with no preceding Stop can land while a recording is rolling,
    resetting midi_ticks_elapsed under the recording's tick math. Survival
    contract: device stays responsive, the recording finalizes into a loop that
    still holds its events, and nothing is left ringing."""
    d = ctx.device
    d.clear_all()
    d.set_midi_sync(True)
    d.set_loop_type("loop")
    d.drain_midi()

    d.start_clock(bpm=120, send_start=True)
    time.sleep(0.4)
    d.record(0)
    time.sleep(0.1)
    d.send(note_on(60, 100, 0), pause=0.15)
    d.send(note_off(60, 0), pause=0.9)
    st = d.state()
    ticks_before = st["clock_ticks"]
    ctx.check(st["recording"] is True, "recording is rolling under the clock")
    ctx.check(ticks_before > 40, f"clock accumulated before the restart (got {ticks_before})")

    d.send(mido.Message("start"))  # mid-recording restart — counter resets to 0
    time.sleep(0.25)
    st = d.state()
    ctx.check(st["clock_ticks"] < 40,
              f"Start reset the tick counter mid-recording (got {st['clock_ticks']})")
    ctx.check(st["recording"] is True, "recording survived the counter reset")

    d.send(note_on(64, 100, 0), pause=0.15)
    d.send(note_off(64, 0), pause=0.2)
    d.stop_record()
    d.stop_clock(send_stop=True)
    time.sleep(0.2)

    st = d.state()
    lp = next((l for l in st["loops"] if l["pad"] == 0), None)
    ctx.check(lp is not None, "loop finalized after the mid-recording restart")
    if lp:
        ctx.log(f"stored notes_on={lp['notes_on']} notes_off={lp['notes_off']}")
        ctx.check(lp["notes_on"] >= 1, "recorded events not lost across the reset")

    # Playability probe: the loop length may be odd after a counter reset — the
    # contract is only that playing it can't wedge the device or hang a note.
    d.set_midi_sync(False)
    d.drain_midi()
    d.play(0)
    d.capture(1.5)
    d.stop_all()
    ctx.heartbeat()
    d.drain_midi()
    stray = [k for k in summarize(d.capture(0.8)) if k[0] == "on"]
    ctx.check(not stray, f"nothing ringing after stop (got {stray})")
    st = d.state()
    ctx.check(st["heap_free"] > 50_000, f"heap sane afterwards ({st['heap_free']})")
    d.clear_all()


@test("clock-tempo-follow",
      "BPM tracker follows a mid-song tempo change (120 -> 90); loop keeps playing")
def t_tempo_follow(ctx):
    """A Live tempo-slider move changes only the 0xF8 rate — no transport
    message. The firmware re-measures BPM over whole-note windows and requires
    two consecutive agreeing windows before committing, so the follow takes a
    few seconds at 90 BPM. Nothing else ever varies the clock rate mid-song."""
    d = ctx.device
    d.clear_all()
    d.set_midi_sync(True)
    d.set_loop_type("loop")
    d.drain_midi()

    d.start_clock(bpm=120, send_start=True)
    time.sleep(0.3)
    d.record(0)
    time.sleep(0.1)
    d.send(note_on(60, 100, 0), pause=0.15)
    d.send(note_off(60, 0), pause=0.85)
    d.stop_record()  # ~1.15 s loop, playing under the clock
    time.sleep(0.5)
    bpm0 = float(d.state()["bpm"])
    ctx.check(abs(bpm0 - 120) <= 2, f"baseline BPM is 120 (got {bpm0:g})")

    # Tempo change: restart only the tick thread — no Start/Stop is sent, so
    # clock_.is_playing stays true and only the tick spacing changes.
    d.start_clock(bpm=90, send_start=False)
    deadline = time.monotonic() + 15.0
    bpm = bpm0
    while time.monotonic() < deadline:
        time.sleep(0.6)
        bpm = float(d.state()["bpm"])
        if abs(bpm - 90) <= 2:
            break
    ctx.check(abs(bpm - 90) <= 2,
              f"BPM tracked the tempo change within 15 s (got {bpm:g}; needs two "
              f"agreeing whole-note windows)")

    d.drain_midi()
    still = summarize(d.capture(2.5))
    ctx.check(still[("on", 60, 100, 0)] >= 1,
              f"loop still playing at the new tempo (seen {still[('on', 60, 100, 0)]}x)")

    # Re-train back to 120 before ending: bpm_current persists until re-measured,
    # and later tests derive arp lengths / quantize grids from it.
    d.start_clock(bpm=120, send_start=False)
    deadline = time.monotonic() + 9.0
    while time.monotonic() < deadline:
        time.sleep(0.6)
        if abs(float(d.state()["bpm"]) - 120) <= 2:
            break
    d.stop_clock(send_stop=True)
    time.sleep(0.3)
    ctx.log(f"re-trained BPM back to {float(d.state()['bpm']):g}")
    d.set_midi_sync(False)
    d.clear_all()


@test("clock-dropout",
      "Clock stream dying WITHOUT a Stop freezes playback gracefully; a late Stop recovers")
def t_clock_dropout(ctx):
    """Cable yank / DAW crash: the 0xF8 stream just stops, no Stop message.
    Synced playback is tick-driven, so the correct behavior is a freeze — no
    free-running notes, no hang — and a later Stop must still clean up."""
    d = ctx.device
    d.clear_all()
    d.set_midi_sync(True)
    d.set_loop_type("loop")
    d.drain_midi()

    d.record(0)
    d.start_clock(bpm=120, send_start=True)
    time.sleep(0.3)
    d.send(note_on(60, 100, 0), pause=0.15)
    d.send(note_off(60, 0), pause=0.3)
    d.stop_record()
    time.sleep(0.3)  # loop audibly rolling

    d.stop_clock(send_stop=False)  # ticks vanish mid-song
    time.sleep(0.5)
    st = d.state()
    ctx.check(st["clock_playing"] is True,
              "no Stop was seen — transport still nominally rolling")
    d.drain_midi()
    frozen = [k for k in summarize(d.capture(1.2)) if k[0] == "on"]
    ctx.check(not frozen, f"playback froze with the clock (free-running notes: {frozen})")

    d.send(mido.Message("stop"))  # late Stop must still work
    time.sleep(0.3)
    st = d.state()
    ctx.check(st["clock_playing"] is False, "late Stop honored after the dropout")
    lp = next((l for l in st["loops"] if l["pad"] == 0), None)
    ctx.check(lp is not None and lp["queued"],
              "loop parked queued by the late Stop (auto-resume design)")
    d.drain_midi()
    stray = [k for k in summarize(d.capture(0.8)) if k[0] == "on"]
    ctx.check(not stray, f"nothing ringing after recovery (got {stray})")

    d.set_midi_sync(False)
    d.clear_all()


@test("edge-empty-loop", "Stopping a recording with no events removes the empty loop")
def t_empty_loop(ctx):
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.record(2)
    time.sleep(0.2)
    d.stop_record()
    st = d.state()
    ctx.check(not any(l["pad"] == 2 for l in st["loops"]), "empty loop was removed")
    ctx.check(st["recording"] is False, "recording state cleared")


@test("edge-switch-recording-pad",
      "Starting a recording on a second pad finalizes the first loop")
def t_switch_pad(ctx):
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.record(1)
    time.sleep(0.1)
    d.send(note_on(60, 100, 0), pause=0.1)
    d.send(note_off(60, 0), pause=0.1)
    d.record(3)  # switch while recording
    st = d.state()
    pads = {l["pad"]: l for l in st["loops"]}
    ctx.check(1 in pads and pads[1]["notes_on"] == 1, "pad 1 loop kept its recorded note")
    ctx.check(st["recording_pad"] == 3, "recording moved to pad 3")
    d.stop_record()
    d.clear_all()


@test("edge-hanging-note-cleanup",
      "Stopping a loop mid-note releases the note (note-off or CC123)")
def t_hanging_note(ctx):
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.record(5)
    time.sleep(0.1)
    d.send(note_on(72, 100, 0), pause=1.0)   # long note...
    d.send(note_off(72, 0), pause=0.1)
    d.drain_midi()
    d.stop_record()  # starts playback
    time.sleep(0.4)  # note 72 should be sounding now
    d.stop(5)
    captured = d.capture(1.0, ignore_realtime=True)
    released = any(
        (m.type == "note_off" and m.note == 72)
        or (m.type == "note_on" and m.note == 72 and m.velocity == 0)
        or (m.type == "control_change" and m.control == 123)
        for _, m in captured
    )
    ctx.check(released, "device released the sounding note when the loop stopped")
    d.clear_all()


@test("arp-repeated-pitch",
      "Mono arp on a repeated pitch: every step audibly sounds (offs-before-ons, item 9)")
def t_arp_repeated(ctx):
    """Drives the arp through the REAL input path (virtual pad hold + encoder
    detents). A monophonic arp queues the previous note's off together with the
    new note's on; pre-item-9 the on went out first, so on a repeated pitch the
    off landed right after it and produced a silent zero-length note. Asserts
    every step's note-on actually rings (no off in the same USB batch)."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    # A loop whose note list is the same pitch twice -> consecutive steps repeat it
    d.record(0)
    time.sleep(0.1)
    for _ in range(2):
        d.send(note_on(60, 100, 0), pause=0.10)
        d.send(note_off(60, 0), pause=0.06)
    d.stop_record()
    d.stop(0)  # playback would pollute the capture

    d.set_play_mode("encoder")
    d.set_arp(polyphonic=False, length="1/8")  # mono: each step offs the previous note
    try:
        d.inject_pad(0, True)
        time.sleep(0.1)
        st = d.state()
        ctx.check(st.get("arp_notes") == 2,
                  f"arp sourced the pad's 2 note-ons (got {st.get('arp_notes')})")
        d.drain_midi()
        steps = 4
        actions = [(0.2 + 0.35 * i, lambda: d.inject_encoder(1)) for i in range(steps)]
        captured = d.capture_while(2.2, actions)

        evs = [(t, "on" if m.velocity > 0 else "off") if m.type == "note_on" else (t, "off")
               for t, m in captured
               if m.type in ("note_on", "note_off") and m.note == 60]
        ons = [t for t, kind in evs if kind == "on"]
        ctx.check(len(ons) == steps, f"every step produced a note-on ({len(ons)}/{steps})")
        # Zero-length regression: an off in the same batch immediately AFTER an on.
        # Correct order is off-then-on, so the event following each on is a later
        # note-off >= 250 ms out (arp length 1/8 at 120 BPM).
        killed = [f"{t:.3f}s" for i, (t, kind) in enumerate(evs)
                  if kind == "on" and i + 1 < len(evs)
                  and evs[i + 1][1] == "off" and evs[i + 1][0] - t < 0.05]
        ctx.check(not killed,
                  f"no note-on was killed by a same-pass off (zero-length at {killed})")
    finally:
        d.inject_pad(0, False)
        time.sleep(0.1)
        d.set_arp(polyphonic=True, length="1/8")
        d.set_play_mode("loop")
    d.clear_all()


@test("arp-flush-note-offs",
      "Releasing arp pads while in the MIDI menu doesn't leave notes ringing (item 10)")
def t_arp_flush(ctx):
    """The item-10 scenario end-to-end: in encoder mode the per-pad release
    handler doesn't run while the MIDI menu is open, so the arp source stays
    registered; back on the play menu the pressed_count==0 sweep must FLUSH the
    pending note-offs before clearing (pre-fix it dropped the off queue and the
    note rang forever). Uses a 1 s arp note so a flush-sourced off (<1 s) is
    distinguishable from a duration-expiry off.

    Hardware finding 2026-07-06: the sweep is LAZY — process_inputs_fast
    early-returns on passes with no press/release/encoder event, so the sweep
    only runs on the next input-bearing pass (harmless: expiry offs are sent
    ungated at pass start, so nothing ever hangs). The test nudges it with a
    CCW encoder detent, which defeats the early-return but can never step the
    arp (steps need encoder_delta > 0, and the flush clears the sources first
    anyway)."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    d.record(3)
    time.sleep(0.1)
    d.send(note_on(72, 90, 0), pause=0.12)
    d.send(note_off(72, 0), pause=0.06)
    d.stop_record()
    d.stop(3)

    d.set_play_mode("encoder")
    d.set_arp(polyphonic=True, length="half")  # 1 s note at 120 BPM
    try:
        d.inject_pad(3, True)
        time.sleep(0.1)
        d.drain_midi()
        actions = [
            (0.05, lambda: d.inject_encoder(1)),     # step: note on, off queued +1 s
            (0.30, lambda: d.set_menu(MENU_MIDI)),   # leave the arp's menu
            (0.45, lambda: d.inject_pad(3, False)),  # release handler doesn't run here
            (0.60, lambda: d.set_menu(MENU_PLAY)),   # back on the arp's menu...
            (0.75, lambda: d.inject_encoder(-1)),    # ...input nudge -> flush must fire
        ]
        captured = d.capture_while(1.8, actions)
        ons = [t for t, m in captured
               if m.type == "note_on" and m.note == 72 and m.velocity > 0]
        offs = [t for t, m in captured
                if (m.type == "note_off" and m.note == 72)
                or (m.type == "note_on" and m.note == 72 and m.velocity == 0)]
        ctx.check(len(ons) == 1, f"arp step played the note once (got {len(ons)})")
        ctx.check(bool(offs), "note-off arrived — nothing left ringing (item 10)")
        if ons and offs:
            ring = offs[0] - ons[0]
            ctx.log(f"note rang {ring * 1000:.0f} ms")
            ctx.check(ring < 0.95,
                      "off came from the flush path, not the 1 s duration expiry")
        st = d.state()
        ctx.check(st.get("arp_notes") == 0, "arp sources cleared after the flush")
    finally:
        d.set_arp(polyphonic=True, length="1/8")
        d.set_play_mode("loop")
    d.clear_all()


@test("playmode-switch-mid-hold",
      "Switching play mode while a pad is held doesn't strand the live note-off (mode latch)")
def t_playmode_switch_mid_hold(ctx):
    """Press a loop-less pad in loop mode (live note-on goes out), flip the play
    mode to encoder via the hook WHILE the pad is held, then release. Pre-latch
    the release was dispatched under the NEW mode: the encoder branch only does
    arpeggiator.remove_source() on a never-registered source and the regular
    release handler (the only thing that ever offs a live note) was skipped, so
    the note rang forever. The per-press-session latch in inputs.cpp dispatches
    the release under the mode its press ran under. A matching off can only come
    from the release handler — live notes have no duration expiry — so its mere
    arrival is the discriminator. Bug inherited from the Python original."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()  # pad 0 has no loop -> press sends a live note
    d.set_menu(MENU_PLAY)
    d.set_play_mode("loop")
    d.drain_midi()
    try:
        actions = [
            (0.05, lambda: d.inject_pad(0, True)),
            (0.40, lambda: d.set_play_mode("encoder")),  # mid-hold mode flip
            (0.75, lambda: d.inject_pad(0, False)),
        ]
        captured = d.capture_while(1.4, actions)
    finally:
        d.inject_pad(0, False)  # idempotent (release clamp, R16)
        time.sleep(0.1)
        d.set_play_mode("loop")

    ons = [(t, m) for t, m in captured if m.type == "note_on" and m.velocity > 0]
    ctx.check(len(ons) == 1, f"pad press sent exactly one live note-on (got {len(ons)})")
    if ons:
        t_on, on = ons[0]
        offs = [t for t, m in captured
                if ((m.type == "note_off" and m.note == on.note)
                    or (m.type == "note_on" and m.note == on.note and m.velocity == 0))
                and m.channel == on.channel]
        ctx.check(bool(offs),
                  "release sent the note-off despite the mid-hold mode switch (no stranded note)")
        if offs:
            ctx.log(f"note {on.note} rang {(offs[0] - t_on) * 1000:.0f} ms")
    st = d.state()
    ctx.check(st.get("arp_notes") == 0,
              "release didn't leak an arp source under the latched mode")
    d.clear_all()


@test("bank-cc123-dedup",
      "Consecutive bank changes both emit All-Notes-Off — CC 120-127 never deduped (R1)")
def t_bank_cc123(ctx):
    """R1: channel-mode commands (CC 120-127) must bypass the CC value-dedup
    cache. Two identical CC123=0 sends in one session — bank up then bank down —
    would have had the second one silently swallowed pre-fix, leaving notes stuck
    after the second bank change of a set."""
    d = ctx.device
    d.set_midi_sync(False)
    d.clear_all()
    bank0 = d.state().get("bank_idx")
    d.drain_midi()

    d.change_bank(True)
    first = summarize(d.capture(0.4))
    d.change_bank(False)  # restores the original bank
    second = summarize(d.capture(0.4))

    n1 = sum(v for k, v in first.items() if k[0] == "cc" and k[1] == 123)
    n2 = sum(v for k, v in second.items() if k[0] == "cc" and k[1] == 123)
    ctx.check(n1 >= 1, f"first bank change sent CC123 all-notes-off ({n1}x)")
    ctx.check(n2 >= 1,
              f"second identical CC123 not swallowed by the dedup cache ({n2}x — R1)")
    st = d.state()
    ctx.check(st.get("bank_idx") == bank0, f"bank restored to {bank0}")


@test("gesture-held-pads-loop-type",
      "Holding TWO pads + encoder cycles BOTH loops' type together, both directions")
def t_gesture_loop_type(ctx):
    """The real loop-type gesture end-to-end (virtual pads through the 350 ms
    hold detector + virtual encoder): in loop play mode pad_held_function applies
    change_loop_mode to EVERY held pad, and settings.loop_type follows so new
    recordings inherit the type. A regression where only the first held pad
    changes — or the default stops following — is invisible to every other test.
    Cycle: fwd loop->oneshot->hold, back hold->oneshot."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.set_play_mode("loop")
    d.set_menu(MENU_PLAY)
    d.clear_all()
    d.drain_midi()

    for pad, note in ((0, 60), (1, 64)):
        d.record(pad)
        time.sleep(0.1)
        d.send(note_on(note, 100, 0), pause=0.12)
        d.send(note_off(note, 0), pause=0.1)
        d.stop_record()
        d.stop(pad)

    def pad_types():
        st = d.state()
        return {l["pad"]: l for l in st["loops"]}

    try:
        # Presses also toggle playback (loop-mode pad semantics) — the gesture
        # stops the loops again, asserted below. 0.5 s clears the hold threshold.
        d.inject_pad(0, True)
        d.inject_pad(1, True)
        time.sleep(0.5)

        for delta, want in ((1, "oneshot"), (1, "hold"), (-1, "oneshot")):
            d.inject_encoder(delta)
            time.sleep(0.2)
            loops = pad_types()
            t0 = loops.get(0, {}).get("type")
            t1 = loops.get(1, {}).get("type")
            ctx.check(t0 == want and t1 == want,
                      f"detent {delta:+d}: BOTH held pads -> {want} (pad0={t0} pad1={t1})")
        for pad, lp in pad_types().items():
            ctx.check(lp["playing"] is False and not lp["queued"],
                      f"pad {pad} left stopped/dequeued by the gesture")
    finally:
        d.inject_pad(0, False)
        d.inject_pad(1, False)
        time.sleep(0.2)

    st = d.state()
    ctx.check(st["pressed"] == 0, "pressed_count reconciled to 0 after release")

    # settings.loop_type followed the gesture: a NEW recording inherits "oneshot"
    d.record(2)
    lp2 = next((l for l in d.state()["loops"] if l["pad"] == 2), None)
    ctx.check(lp2 is not None and lp2["type"] == "oneshot",
              f"new recording inherits the gestured type (got {lp2 and lp2['type']})")
    d.stop_record()  # no events -> empty loop auto-removed

    d.drain_midi()
    stray = [k for k in summarize(d.capture(0.6)) if k[0] == "on"]
    ctx.check(not stray, f"no stuck notes after the gesture (got {stray})")
    d.set_loop_type("loop")
    d.clear_all()


@test("sync-clear-queued-loop",
      "Clearing a loop while it's QUEUED under midi_sync leaves no ghost on Start")
def t_clear_queued(ctx):
    """User queues a loop (pad press, clock stopped, sync on), changes their
    mind, and deletes it before the transport ever starts. _remove_loop must
    drop the play_queue slot too — a stale queue bit over a null loop would
    ghost-start (or crash) on the next MIDI Start."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    d.record(0)
    time.sleep(0.1)
    d.send(note_on(60, 100, 0), pause=0.12)
    d.send(note_off(60, 0), pause=0.1)
    d.stop_record()
    d.stop(0)

    d.set_midi_sync(True)
    d.toggle(0)  # user-press semantics: clock stopped + sync -> queue, don't play
    lp = next((l for l in d.state()["loops"] if l["pad"] == 0), None)
    ctx.check(lp is not None and lp["queued"] and not lp["playing"],
              "loop queued (not playing) while the clock is stopped")

    d.clear(0)
    st = d.state()
    ctx.check(not any(l["pad"] == 0 for l in st["loops"]), "queued loop removed")

    d.drain_midi()
    d.start_clock(bpm=120, send_start=True)
    ghost = [k for k in summarize(d.capture(1.5)) if k[0] == "on"]
    d.stop_clock(send_stop=True)
    ctx.check(not ghost, f"no ghost playback from the cleared queue slot (got {ghost})")
    ctx.heartbeat()
    d.set_midi_sync(False)
    d.clear_all()


@test("oneshot-retrigger-spam",
      "Rapid pad-mashing a oneshot loop: every note released, input state reconciles")
def t_oneshot_spam(ctx):
    """8 press/release pairs at ~60 ms intervals through the real input pipeline
    — every press toggles/retriggers the oneshot mid-flight. Stuck notes and a
    drifted pressed_count are the historical failure modes of fast toggle paths."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("oneshot")
    d.set_play_mode("loop")
    d.set_menu(MENU_PLAY)
    d.clear_all()
    d.drain_midi()

    d.record(0)
    time.sleep(0.1)
    d.send(note_on(65, 90, 0), pause=0.1)
    d.send(note_off(65, 0), pause=0.15)
    d.stop_record()  # oneshot: waits for a trigger

    try:
        actions = []
        tpt = 0.15
        for _ in range(8):
            for pressed in (True, False):
                actions.append((tpt, lambda p=pressed: d.inject_pad(0, p)))
                tpt += 0.06
        captured = d.capture_while(tpt + 1.5, actions)
    finally:
        try:
            d.inject_pad(0, False)  # belt-and-braces: never leave a virtual pad down
        except DeviceError:
            pass
    time.sleep(0.2)

    ons = sum(1 for _, m in captured
              if m.type == "note_on" and m.note == 65 and m.velocity > 0)
    offs = sum(1 for _, m in captured
               if (m.type == "note_off" and m.note == 65)
               or (m.type == "note_on" and m.note == 65 and m.velocity == 0))
    cc123 = sum(1 for _, m in captured
                if m.type == "control_change" and m.control == 123)
    ctx.log(f"spam produced ons={ons} offs={offs} cc123={cc123}")
    ctx.check(ons >= 1, "spam actually triggered the oneshot")
    ctx.check(offs >= ons or cc123 > 0,
              f"every note-on released — no stuck notes (ons={ons} offs={offs})")

    st = d.state()
    ctx.check(st["pressed"] == 0, f"pressed_count reconciled to 0 (got {st['pressed']})")
    lp = next((l for l in st["loops"] if l["pad"] == 0), None)
    ctx.check(lp is not None, "loop survived the spam")
    d.set_loop_type("loop")
    d.clear_all()


@test("bank-change-during-playback",
      "Bank up/down mid-playback: recorded loop notes unaffected, bank restored")
def t_bank_during_playback(ctx):
    """Bank changes remap the pad->note table for LIVE presses; recorded loops
    store absolute notes and must keep playing them untransposed through the
    bank's all-notes-off. bank-cc123-dedup proves the CC path idle — this is
    the with-a-loop-running combo."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    bank0 = d.state().get("bank_idx")
    d.drain_midi()

    d.record(0)
    time.sleep(0.1)
    d.send(note_on(60, 100, 0), pause=0.12)
    d.send(note_off(60, 0), pause=0.4)
    d.stop_record()  # ~0.65 s loop, playing
    d.drain_midi()

    captured = d.capture_while(3.0, [(0.8, lambda: d.change_bank(True)),
                                     (1.5, lambda: d.change_bank(False))])
    d.stop_all()

    ons_pre = [t for t, m in captured
               if m.type == "note_on" and m.velocity > 0 and t < 0.8]
    ons_post = [t for t, m in captured
                if m.type == "note_on" and m.velocity > 0 and t > 1.6]
    wrong = sorted({m.note for _, m in captured
                    if m.type == "note_on" and m.velocity > 0 and m.note != 60})
    cc123 = sum(1 for _, m in captured
                if m.type == "control_change" and m.control == 123)
    ctx.check(bool(ons_pre), "loop playing before the bank change")
    ctx.check(bool(ons_post), "loop still playing after bank up + down")
    ctx.check(not wrong, f"recorded notes not transposed by the bank change (stray {wrong})")
    ctx.check(cc123 >= 2, f"each bank change sent its all-notes-off ({cc123}x)")
    st = d.state()
    ctx.check(st.get("bank_idx") == bank0, f"bank restored to {bank0}")
    d.clear_all()


@test("loop-save-reboot-restore",
      "Recorded loops survive preset save + reboot (loop .bin flash round-trip)")
def t_save_restore(ctx):
    """The most data-loss-prone path on the device: menu save writes loop events
    to .bin files + presets.json (atomic write), boot reads them back. Records
    two loops (multi-channel notes + CCs), saves preset T_PERSIST via the same
    code path as the menu, reboots, and verifies the loops come back with the
    same event counts AND actually play the right notes."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    # Pad 0: three notes on channel 0
    d.record(0)
    time.sleep(0.1)
    for n in (60, 64, 67):
        d.send(note_on(n, 100, 0), pause=0.1)
        d.send(note_off(n, 0), pause=0.05)
    d.stop_record()
    d.stop_all()
    # Pad 5: a note on channel 2 + CCs on channel 3
    d.record(5)
    time.sleep(0.1)
    d.send(note_on(72, 88, 2), pause=0.1)
    d.send(note_off(72, 2), pause=0.05)
    for c, v in ((20, 10), (21, 40), (22, 90)):
        d.send(cc(c, v, 3), pause=0.04)
    time.sleep(0.1)
    d.stop_record()
    d.stop_all()

    before = {l["pad"]: l for l in d.state()["loops"]}
    ctx.check(set(before) == {0, 5}, f"two loops recorded (pads {sorted(before)})")

    ctx.instruct("Saving preset T_PERSIST (flash write) and rebooting into it")
    d.save_preset("T_PERSIST")
    d.reboot()

    st = d.state(full=True)
    ctx.check(st.get("preset") == "T_PERSIST", "device rebooted into the saved preset")
    after = {l["pad"]: l for l in st["loops"]}
    ctx.check(set(after) == {0, 5},
              f"both loops restored from flash (pads {sorted(after)})")
    if 0 in after and 0 in before:
        ctx.check(after[0]["notes_on"] == before[0]["notes_on"],
                  f"pad 0 notes survived ({before[0]['notes_on']} -> {after[0]['notes_on']})")
    if 5 in after and 5 in before:
        ctx.check(after[5]["notes_on"] == before[5]["notes_on"],
                  f"pad 5 notes survived ({before[5]['notes_on']} -> {after[5]['notes_on']})")
        ctx.check(after[5]["ccs"] >= 1, f"pad 5 kept its CC data ({after[5]['ccs']} CCs)")

    # The restored loop must actually play the recorded events
    d.drain_midi()
    d.play(0)
    got = summarize(d.capture(2.0))
    d.stop(0)
    for n in (60, 64, 67):
        ctx.check(got[("on", n, 100, 0)] >= 1, f"restored loop plays note {n} ch 0")

    # Cleanup: back to baseline (frees T_PERSIST from startup), then delete it
    d.clear_all()
    ctx.instruct("Loading back into T_MULTI (reboot), then deleting T_PERSIST")
    d.load_preset(BASELINE_PRESET)
    d.delete_preset("T_PERSIST")
    ctx.check("T_PERSIST" not in d.preset_names(), "scratch preset deleted")


@test("loop-files-v2",
      "Saved loops land as single v2 files: /loops holds only loop_%04d.bin, magic 0x4C02")
def t_loop_files_v2(ctx):
    """Loop storage v2 (2026-07-09): one self-contained file per loop replaced
    the 3-file _notes/_cc/_at split. After a preset save, /loops must contain
    ONLY v2-named files (the legacy sweep removes anything else), and every
    file's 20-byte header must be internally consistent: magic 0x4C02 and
    file size == 20 + 5 x (sum of the four section counts) — the same checks
    the firmware loader applies."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    # One loop with notes + a CC so the file has multiple sections
    d.record(1)
    time.sleep(0.1)
    d.send(note_on(62, 90, 0), pause=0.1)
    d.send(note_off(62, 0), pause=0.05)
    d.send(cc(30, 55, 0), pause=0.05)
    time.sleep(0.1)
    d.stop_record()
    d.stop_all()

    ctx.instruct("Saving preset T_V2FILES (flash write)")
    d.save_preset("T_V2FILES")

    files = d.cmd("LIST_LOOP_FILES").get("files", [])
    ctx.check(len(files) >= 1, f"loop file written ({len(files)} file(s) in /loops)")
    bad = [f["name"] for f in files if not re.fullmatch(r"loop_\d{4}\.bin", f["name"])]
    ctx.check(not bad, f"only v2-named files in /loops (offenders: {bad})")

    for f in files:
        rsp = d.cmd(f"GET_LOOP_FILE_CHUNK|{f['name']}|0")
        raw = base64.b64decode(rsp["data"])
        ctx.check(len(raw) >= 20, f"{f['name']}: contains at least a header ({len(raw)} B)")
        magic, _ltype, _res, n_on, n_off, n_cc, n_at, _ticks, _bpm10, _crc = \
            struct.unpack("<HBBHHHHHHI", raw[:20])
        ctx.check(magic == 0x4C02, f"{f['name']}: v2 magic (got 0x{magic:04X})")
        expected = 20 + 5 * (n_on + n_off + n_cc + n_at)
        ctx.check(f["size"] == expected,
                  f"{f['name']}: size matches header counts ({f['size']} == {expected})")

    # Cleanup: back to baseline, drop the scratch preset
    d.clear_all()
    ctx.instruct("Loading back into T_MULTI (reboot), then deleting T_V2FILES")
    d.load_preset(BASELINE_PRESET)
    d.delete_preset("T_V2FILES")
    ctx.check("T_V2FILES" not in d.preset_names(), "scratch preset deleted")


@test("midi-import-put",
      "PUT_LOOP_FILE_CHUNK installs a valid v2 loop file, rejects bad names/CRC")
def t_midi_import_put(ctx):
    """The web UI's .mid import (drag onto a pad) converts the MIDI file to a v2
    loop .bin IN THE BROWSER and streams it over the one new serial command,
    PUT_LOOP_FILE_CHUNK (chunks -> <name>.tmp; the final chunk validates
    magic/size/CRC with the loader's own checks, then installs via the atomic
    remove+rename). This covers the firmware half: chunked append + byte-exact
    round-trip, plus every reject path. The uploaded file is a deliberate orphan
    (no preset references it) — the next device-side save sweeps it."""
    d = ctx.device

    # A v2 file exactly like the web encoder emits: 2 ons + 2 offs, pad 3 / ch 0,
    # 1 bar (96 ticks) @ 120 bpm.
    def ev(note, vel, tick):
        return struct.pack("<BBBH", note, vel, (0 << 4) | 3, tick)
    body = ev(60, 100, 0) + ev(64, 90, 24) + ev(60, 0, 24) + ev(64, 0, 36)
    blob = struct.pack("<HBBHHHHHHI", 0x4C02, 0, 0, 2, 2, 0, 0, 96, 1200,
                       zlib.crc32(body) & 0xFFFFFFFF) + body

    def put(name, off, done, raw):
        b64 = base64.b64encode(raw).decode()
        return d.cmd(f"PUT_LOOP_FILE_CHUNK|{name}|{off}|{1 if done else 0}|{b64}")

    def expect_reject(what, fn):
        try:
            fn()
        except DeviceError as e:
            ctx.log(f"ok: {what} rejected ({e})")
            return
        raise TestFailed(f"{what} was accepted")

    # Happy path: two chunks (exercises the append + size==offset check), then
    # read the installed file back and compare byte-for-byte.
    name = "loop_9917.bin"  # scratch id far above anything the test presets use
    rsp = put(name, 0, False, blob[:20])
    ctx.check(rsp.get("put_offset") == 0 and rsp.get("received") == 20,
              f"chunk 1 acked with put_offset/received ({rsp})")
    rsp = put(name, 20, True, blob[20:])
    ctx.check(rsp.get("installed") is True, f"final chunk installs the file ({rsp})")
    got = base64.b64decode(d.cmd(f"GET_LOOP_FILE_CHUNK|{name}|0")["data"])
    ctx.check(got == blob, f"round-trip is byte-exact ({len(got)}/{len(blob)} B)")

    # Reject paths — none of these may leave an installed file behind.
    expect_reject("path traversal name", lambda: put("../evil.bin", 0, True, blob))
    expect_reject("non-v2 filename", lambda: put("notaloop.bin", 0, True, blob))
    expect_reject("out-of-order offset", lambda: put("loop_9918.bin", 40, False, blob[:20]))
    corrupt = bytearray(blob)
    corrupt[25] ^= 0xFF  # body byte flip -> CRC mismatch
    expect_reject("corrupt CRC", lambda: put("loop_9918.bin", 0, True, bytes(corrupt)))
    expect_reject("read-back of the rejected file",
                  lambda: d.cmd("GET_LOOP_FILE_CHUNK|loop_9918.bin|0"))


@test("cc-loop-save-arp",
      "CC-only loop survives save+reboot with its arp CC cache rebuilt (R2)")
def t_cc_loop_save_arp(ctx):
    """Two gaps in one flow. (a) A loop with ONLY CCs (no notes) exercises the
    length/trim logic that keys off note events — save-restore always had notes.
    (b) R2: the arp's per-loop unique-CC cache is built at record time and used
    to be EMPTY after a preset load, leaving the arp CC-dead on restored loops.
    The arp is stepped first, straight after the reboot, because the CC dedup
    cache would otherwise swallow values a playback pass already sent."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    ccs_sent = [(21, 10), (22, 35), (23, 60), (24, 85), (25, 110)]
    d.record(2)
    time.sleep(0.15)
    for c, v in ccs_sent:
        d.send(cc(c, v, 0), pause=0.08)
    time.sleep(0.15)
    d.stop_record()
    d.stop_all()

    st = d.state()
    lp = next((l for l in st["loops"] if l["pad"] == 2), None)
    ctx.check(lp is not None and lp["notes_on"] == 0 and lp["ccs"] == len(ccs_sent),
              f"CC-only loop recorded ({lp['ccs'] if lp else 0} CCs, no notes)")
    ctx.check(lp is not None and lp.get("unique_ccs") == len(ccs_sent),
              f"unique-CC cache built at record time ({lp.get('unique_ccs') if lp else 0})")

    ctx.instruct("Saving preset T_CCARP (flash write) and rebooting into it")
    d.save_preset("T_CCARP")
    d.reboot()

    st = d.state(full=True)
    ctx.check(st.get("preset") == "T_CCARP", "device rebooted into the saved preset")
    lp = next((l for l in st["loops"] if l["pad"] == 2), None)
    ctx.check(lp is not None and lp["ccs"] == len(ccs_sent),
              f"CC-only loop restored from flash ({lp['ccs'] if lp else 0} CCs)")
    ctx.check(lp is not None and lp.get("unique_ccs") == len(ccs_sent),
              f"unique-CC arp cache rebuilt on load (R2; got "
              f"{lp.get('unique_ccs') if lp else 0})")

    # Arp-step the restored loop (R2 end-to-end): all 5 distinct (cc, value)
    # pairs must reach the wire.
    d.set_play_mode("encoder")
    try:
        d.inject_pad(2, True)
        time.sleep(0.1)
        st = d.state()
        ctx.check(st.get("arp_ccs") == len(ccs_sent),
                  f"arp sees the restored loop's CCs (got {st.get('arp_ccs')})")
        d.drain_midi()
        for _ in range(len(ccs_sent)):
            d.inject_encoder(1)
            time.sleep(0.1)
        time.sleep(0.2)
        got = summarize(d.capture(0.3))
        stepped = sum(1 for c, v in ccs_sent if got[("cc", c, v, 0)] >= 1)
        ctx.check(stepped == len(ccs_sent),
                  f"arp stepped the restored CCs onto the wire "
                  f"({stepped}/{len(ccs_sent)} distinct)")
    finally:
        d.inject_pad(2, False)
        time.sleep(0.1)
        d.set_play_mode("loop")

    # Cleanup: back to baseline (frees T_CCARP from startup), then delete it
    d.clear_all()
    ctx.instruct("Loading back into T_MULTI (reboot), then deleting T_CCARP")
    d.load_preset(BASELINE_PRESET)
    d.delete_preset("T_CCARP")
    ctx.check("T_CCARP" not in d.preset_names(), "scratch preset deleted")


@test("preset-rename", "RENAME_PRESET renames a preset and its contents survive")
def t_preset_rename(ctx):
    """RENAME_PRESET is part of the web protocol but nothing exercised it."""
    d = ctx.device
    presets = json.loads(PRESETS_FILE.read_text())
    body = dict(presets[BASELINE_PRESET])
    body.pop("loops", None)

    d.upload_preset("T_RENAME_A", body)
    d.rename_preset("T_RENAME_A", "T_RENAME_B")
    names = d.preset_names()
    ctx.check("T_RENAME_B" in names and "T_RENAME_A" not in names,
              f"rename took effect (names now {names})")

    got = d.get_preset("T_RENAME_B")
    renamed = got.get("preset", got)
    if isinstance(renamed, str):
        renamed = json.loads(renamed)
    ctx.check(renamed.get("default_bpm") == body.get("default_bpm"),
              "renamed preset kept its contents")
    d.delete_preset("T_RENAME_B")
    ctx.check("T_RENAME_B" not in d.preset_names(), "scratch preset deleted")


@test("preset-delete-web",
      "DELETE_PRESET removes a preset; startup/reserved/missing are refused")
def t_preset_delete_web(ctx):
    """Web-UI delete path (2026-07-13): the preset bar's trash button sends
    DELETE_PRESET|name after a confirmation modal. Distinct from the harness's
    own TEST_DELETE_PRESET hook — this is the release-build command with
    per-cause error codes. The startup preset is refused so the boot path
    never points at a missing preset (the modal explains instead of offering
    Delete, but the firmware must hold the line on its own)."""
    d = ctx.device
    presets = json.loads(PRESETS_FILE.read_text())
    body = dict(presets[BASELINE_PRESET])
    body.pop("loops", None)

    d.upload_preset("T_DELETEME", body)
    ctx.check("T_DELETEME" in d.preset_names(), "scratch preset created")
    rsp = d.cmd("DELETE_PRESET|T_DELETEME")
    ctx.check(rsp.get("needs_restart") is False, f"delete acks with needs_restart=false ({rsp})")
    names = d.preset_names()
    ctx.check("T_DELETEME" not in names, f"delete took effect (names now {names})")

    def expect_reject(what, fn):
        try:
            fn()
        except DeviceError as e:
            ctx.log(f"ok: {what} refused ({e})")
            return
        raise TestFailed(f"{what} was accepted")

    startup = d.cmd("GET_PRESET_NAMES").get("startup", "")
    ctx.check(bool(startup), f"device reports a startup preset ({startup!r})")
    expect_reject("deleting the startup preset", lambda: d.cmd(f"DELETE_PRESET|{startup}"))
    ctx.check(startup in d.preset_names(), "startup preset still present after refusal")
    expect_reject("deleting an already-deleted preset", lambda: d.cmd("DELETE_PRESET|T_DELETEME"))
    expect_reject("deleting a reserved key", lambda: d.cmd("DELETE_PRESET|STARTUP_PRESET"))


@test("save-time-budget",
      "2-loop preset save + every single file op stay inside time budgets",
      tags=("auto",))
def t_save_time_budget(ctx):
    """Filesystem-performance regression guard (2026-07-06). FatFS's flash-
    translation layer rewrote ~63 KB of FTL metadata on EVERY file op — a flat
    ~2.1 s per create/remove/rename/close, 12.6 s for a 2-loop save, ~70-100 s
    worst case. The LittleFS switch made ops data-proportional (2-loop save
    ~0.2 s). Budgets are ~10x current so they only trip on a real regression
    (FS swap, per-write sync, etc.), not normal jitter."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()
    for pad, notes in ((0, (60, 64, 67)), (5, (72,))):
        d.record(pad)
        time.sleep(0.1)
        for n in notes:
            d.send(note_on(n, 100, 0), pause=0.1)
            d.send(note_off(n, 0), pause=0.05)
        d.stop_record()
        d.stop_all()

    t0 = time.monotonic()
    d.save_preset("T_SAVETIME")
    elapsed = time.monotonic() - t0
    ctx.check(elapsed < 3.0,
              f"2-loop save under 3 s budget (took {elapsed:.2f}s; FatFS era was 12.6 s)")

    bench = d.cmd("TEST_FS_BENCH", timeout=60.0)
    op, worst = max(((k, v) for k, v in bench.items() if k.endswith("_us")),
                    key=lambda kv: kv[1])
    ctx.check(worst < 1_000_000,
              f"worst single file op under 1 s ({op}={worst}us; FatFS era was ~2.1 s/op)")

    # Cleanup: back to baseline (frees T_SAVETIME from startup), then delete it
    d.clear_all()
    ctx.instruct("Loading back into T_MULTI (reboot), then deleting T_SAVETIME")
    d.load_preset(BASELINE_PRESET)
    d.delete_preset("T_SAVETIME")
    ctx.check("T_SAVETIME" not in d.preset_names(), "scratch preset deleted")


@test("preset-cap-16",
      "Creating a 17th preset is refused on both the web and device-save paths",
      tags=("auto", "slow"))
def t_preset_cap(ctx):
    """Robustness #18. Fills presets.json to C::MAX_PRESETS (16) with scratch
    presets, then proves (a) web SET_PRESET refuses the 17th, (b) the device
    save path refuses too, (c) overwriting an existing preset still works at
    the cap. Each fill/delete is a flash write, so this test takes a while."""
    d = ctx.device
    presets = json.loads(PRESETS_FILE.read_text())
    body = dict(presets[BASELINE_PRESET])
    body.pop("loops", None)

    existing = d.preset_names()
    ctx.log(f"{len(existing)} presets on device: {existing}")
    ctx.check(len(existing) <= 16, f"device not already over the cap ({len(existing)})")

    fillers = []
    try:
        for i in range(16 - len(existing)):
            name = f"T_FILL{i:02d}"
            d.upload_preset(name, body)
            fillers.append(name)
        ctx.log(f"filled to the cap with {len(fillers)} scratch presets")

        try:
            d.upload_preset("T_OVERCAP", body)
            raise TestFailed("web SET_PRESET accepted a 17th preset — cap not enforced")
        except DeviceError as e:
            ctx.check("preset_limit" in str(e) or "limit" in str(e).lower(),
                      f"web path refused the 17th preset ({e})")

        try:
            d.save_preset("T_OVERCAP2")
            raise TestFailed("device-side save created a 17th preset — cap not enforced")
        except DeviceError as e:
            ctx.check("save_failed" in str(e) or "refused" in str(e).lower(),
                      f"device save path refused at the cap ({e})")

        d.upload_preset(BASELINE_PRESET, presets[BASELINE_PRESET])
        ctx.log("overwriting an existing preset at the cap still works")
    finally:
        leftovers = []
        for name in fillers:
            try:
                d.delete_preset(name)
            except DeviceError:
                leftovers.append(name)
        if leftovers:
            ctx.log(f"cleanup: could not delete {leftovers}")
    ctx.check(all(n not in d.preset_names() for n in fillers),
              "all scratch presets cleaned up")


@test("serial-cmd-flood",
      "CDC protocol stays intact under rapid commands interleaved with MIDI traffic")
def t_serial_flood(ctx):
    """The CMD/RSP channel shares USB with MIDI; a past P1 (TX FIFO truncation
    mid-MIDI-traffic) corrupted responses exactly here. Hammers the serial
    protocol while notes stream, and checks the device-side cmds/rsps ledgers
    agree with ours — any parse error or lost RSP fails via cmd() itself."""
    d = ctx.device
    d.set_midi_sync(False)
    d.clear_all()
    d.drain_midi()

    st0 = d.state()
    c0, r0 = st0.get("cmds"), st0.get("rsps")
    n_cmds = 0
    for _ in range(25):
        d.send_burst([m for k in range(8)
                      for m in (note_on(40 + k, 100, 0), note_off(40 + k, 0))],
                     burst=16, pause=0.001)
        d.state()          # small RSP under MIDI RX load
        n_cmds += 1
        d.get_preset(BASELINE_PRESET)  # big multi-hundred-byte RSP
        n_cmds += 1

    st = d.state()
    n_cmds += 1
    ctx.log(f"{n_cmds} commands answered during ~400 interleaved MIDI messages")
    if c0 is not None and r0 is not None:
        ctx.check(st["cmds"] - c0 == n_cmds,
                  f"device saw every CMD exactly once ({st['cmds'] - c0}/{n_cmds})")
        ctx.check(st["rsps"] - r0 == n_cmds,
                  f"device sent exactly one RSP per CMD ({st['rsps'] - r0}/{n_cmds})")
    d.drain_midi()


@test("memory-churn",
      "Heap survives creating/destroying many loops: no leaks, no fragmentation",
      tags=("auto", "stress"))
def t_memory_churn(ctx):
    """Loops are heap-allocated vectors; every record/clear cycle allocates and
    frees dozens of blocks. A leak of even ~100 bytes/cycle or creeping
    fragmentation would eventually kill a live set. Churns ~45 record->play->
    clear cycles across all pads, tracks heap after every clear, then proves a
    big contiguous recording still fits (fragmentation canary) and that the
    global event budget and loop-ID counter didn't leak (robustness #14)."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    time.sleep(0.3)
    st = d.state()
    baseline = st["heap_free"]
    id0 = st.get("next_loop_id")
    ctx.log(f"baseline: heap_free={baseline} next_loop_id={id0}")

    recordings = 0
    heaps = []
    cycles = 30
    for cycle in range(cycles):
        pad = cycle % 16
        d.record(pad)
        d.send_burst([m for i in range(12)
                      for m in (note_on(36 + i, 100, i % 4), note_off(36 + i, i % 4))],
                     burst=8, pause=0.004)
        d.send_burst([cc(1 + (i % 4), i % 128, 0) for i in range(80)])
        time.sleep(0.05)
        d.stop_record()   # playback starts: exercises playback-state allocs too
        recordings += 1
        time.sleep(0.15)
        d.clear_all()
        d.drain_midi()
        heaps.append(d.state()["heap_free"])
        if cycle % 5 == 4:
            ctx.log(f"cycle {cycle + 1}/{cycles}: heap_free={heaps[-1]}")

    # Multi-pad phase: all 16 pads occupied at once, then mass-clear, 3 rounds
    for _ in range(3):
        for pad in range(16):
            d.record(pad)
            d.send(note_on(48 + pad, 100, 0), pause=0.03)
            d.send(note_off(48 + pad, 0), pause=0.01)
            d.stop_record()
            recordings += 1
        d.stop_all()
        d.clear_all()
        d.drain_midi()
        heaps.append(d.state()["heap_free"])
    ctx.log(f"after 3 all-16-pad rounds: heap_free={heaps[-1]}")

    st = d.state()
    ctx.check(st["total_events"] == 0,
              f"global event budget fully released after clears (total_events="
              f"{st['total_events']})")
    if id0 is not None and st.get("next_loop_id") is not None:
        burned = st["next_loop_id"] - id0
        ctx.check(burned == recordings,
                  f"loop IDs advanced exactly once per finalized recording "
                  f"({burned} for {recordings} recordings — robustness #14)")

    early = sum(heaps[:5]) / 5
    late = sum(heaps[-5:]) / 5
    ctx.log(f"heap after clears: first-5 avg {early:.0f}, last-5 avg {late:.0f}")
    ctx.check(late >= early - 2048,
              f"no leak trend across churn (first-5 avg {early:.0f} -> "
              f"last-5 avg {late:.0f})")
    ctx.check(heaps[-1] >= baseline - 4096,
              f"heap returned to baseline after churn ({baseline} -> {heaps[-1]})")

    # Fragmentation canary: one big recording needs large contiguous vectors.
    d.record(0)
    d.send_burst([cc(1 + (i % 4), i % 128, 0) for i in range(900)])
    time.sleep(0.3)
    st = d.state()
    if st["recording"]:
        d.stop_record()
        st = d.state()
    d.stop_all()
    big = next((l for l in st["loops"] if l["pad"] == 0), None)
    ctx.check(big is not None and big["ccs"] >= 500,
              f"big contiguous recording still fits after churn "
              f"(stored {big['ccs'] if big else 0} CCs)")
    d.clear_all()
    time.sleep(0.3)
    final = d.state()["heap_free"]
    ctx.check(final >= baseline - 4096,
              f"heap recovered after the big loop too ({baseline} -> {final})")


@test("limits-note-flood",
      "Note-on cap (LOOP_NOTES_LIMIT 512) is enforced without crash or data loss",
      tags=("auto", "stress"))
def t_note_flood(ctx):
    """limits-cc-flood covers CC_EVENTS_LIMIT (1024) but the note cap
    (C::LOOP_NOTES_LIMIT = 512 note-ons) was never hit. Floods one recording
    with 600 note pairs and asserts the clamp holds, the device stays alive,
    and the clamped loop still plays."""
    NOTE_CAP = 512  # keep in sync with C::LOOP_NOTES_LIMIT
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    d.record(0)
    time.sleep(0.1)
    for chunk in range(3):  # 3 x 200 pairs with a heartbeat between
        msgs = []
        for i in range(200):
            n = 36 + ((chunk * 200 + i) % 48)
            msgs.append(note_on(n, 100, 0))
            msgs.append(note_off(n, 0))
        d.send_burst(msgs, burst=16, pause=0.002)
        ctx.heartbeat()
    time.sleep(0.3)

    st = d.state()
    if st["recording"]:
        d.stop_record()
        st = d.state()
    else:
        ctx.log("firmware auto-stopped the recording at the limit")
    d.stop_all()
    lp = next((l for l in st["loops"] if l["pad"] == 0), None)
    ctx.check(lp is not None, "loop survived the note flood")
    if lp:
        ctx.log(f"stored notes_on={lp['notes_on']} notes_off={lp['notes_off']} "
                f"max_reached={lp.get('max_reached')}")
        ctx.check(lp["notes_on"] <= NOTE_CAP,
                  f"note-ons clamped to the {NOTE_CAP} cap (got {lp['notes_on']})")
        ctx.check(lp["notes_off"] <= NOTE_CAP,
                  f"note-offs clamped too (got {lp['notes_off']})")
        ctx.check(lp["notes_on"] >= 400,
                  f"flood actually stressed the cap ({lp['notes_on']} stored; "
                  f"USB drops under load are expected but not this many)")

    # The clamped loop must still be playable
    d.drain_midi()
    d.play(0)
    got = summarize(d.capture(0.8))
    d.stop(0)
    ctx.check(any(k[0] == "on" for k in got), "clamped loop still plays notes")
    d.clear_all()
    time.sleep(0.3)
    st = d.state()
    ctx.check(st["heap_free"] > 100_000,
              f"heap recovered after clearing (free={st['heap_free']})")


@test("limits-cc-flood",
      "Fill EVERY pad with max CC data until the firmware refuses or the device breaks",
      tags=("auto", "stress", "crashy"))
def t_limits(ctx):
    """Endurance sweep. Per-loop CC cap is CC_EVENTS_LIMIT (1024); the memory
    guards are the global event budget (20,000) plus a 72 KB free-heap floor on
    NEW recordings (sized on-device 2026-07-06: ~5.4 KB per maxed loop, frag
    panic ~55 KB). Verified 2026-07-06: the firmware REFUSES a new recording
    (record_failed) before the heap fragments into a panic, so an over-full
    instrument stops gracefully instead of crashing. Per-pad findings are
    collected (not raised) so one bad pad doesn't end the sweep early.

    Tagged "crashy" (2026-07-09): at the end of a full suite this flood can
    reproduce the parked R18 MIDI-flood watchdog hang (report_20260709_130015),
    so unattended runs (--auto / [u]) exclude it — see unattended_tests()."""
    CC_CAP = 1024  # keep in sync with C::CC_EVENTS_LIMIT
    d = ctx.device
    ctx.log("WARNING: endurance test, known-crash territory — run last / after a save")
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()
    per_loop_target = CC_CAP + 500  # overshoot the per-loop cap to test clamping
    problems = []
    filled = 0

    for pad in range(16):
        try:
            d.record(pad)
        except DeviceError as e:
            if "record_failed" in str(e) or "limit" in str(e).lower():
                ctx.log(f"pad {pad}: firmware refused a new recording — graceful stop "
                        f"after {filled} full pads")
                break
            ctx.crash_recovery()
            raise TestFailed(
                f"device died starting a recording on pad {pad} "
                f"(after {filled} full pads): {e}") from e
        try:
            # Bursts of 16 at full USB rate + 2 ms breathers (was 2 ms per
            # message): ~16x faster. The heartbeat every 400 also lets the
            # device's RX FIFO fully drain between stretches.
            for i in range(per_loop_target):
                d.send(cc(1 + (i % 8), i % 128, 0))
                if i % 16 == 15:
                    time.sleep(0.002)
                if i and i % 400 == 0 and CC_FLOOD_HEARTBEAT:
                    ctx.heartbeat()  # raises DeviceError if it died
            time.sleep(0.3)
            st = d.state()
            if st["recording"]:
                d.stop_record()
                st = d.state()
            else:
                ctx.log(f"pad {pad}: firmware auto-stopped recording at the limit")
            d.stop_all()
            loop = next((l for l in st["loops"] if l["pad"] == pad), None)
            heap = st["heap_free"]
            if loop is None:
                problems.append(f"pad {pad}: loop vanished after the flood")
            elif loop["ccs"] > CC_CAP:
                problems.append(f"pad {pad}: stored {loop['ccs']} CCs — {CC_CAP} limit not enforced")
            filled += 1
            ctx.log(f"pad {pad}: {loop['ccs'] if loop else '?'} CCs stored, heap_free={heap}")
            if heap < 15_000:
                ctx.log(f"pad {pad}: heap critically low — the next pads probe the failure edge")
        except DeviceError as e:
            ctx.crash_recovery()
            raise TestFailed(
                f"device died during CC flood on pad {pad} "
                f"(after {filled} full pads, see log for last heap reading): {e}") from e

    st = ctx.heartbeat()
    ctx.log(f"survived the sweep: {filled} pads filled, heap_free={st['heap_free']}")
    ctx.check(not problems, f"per-pad limit violations: {problems}")
    d.clear_all()
    time.sleep(0.5)
    st = d.state()
    ctx.check(st["heap_free"] > 100_000,
              f"heap recovered after clearing all loops (free={st['heap_free']})")


@test("manual-pad-press", "Physical pad press sends a MIDI note (checks the button matrix)",
      tags=("manual",))
def t_pad_press(ctx):
    d = ctx.device
    d.clear_all()
    d.drain_midi()
    ctx.instruct("On the device, make sure you're on the PLAY screen, then press any PAD once.")
    captured = d.capture(6.0)
    notes = [m for _, m in captured if m.type == "note_on" and m.velocity > 0]
    ctx.check(bool(notes), f"received a note from the pad press (got {len(notes)} note-ons)")
    ctx.log(f"pad sent note {notes[0].note} vel {notes[0].velocity} ch {notes[0].channel}"
            if notes else "no notes received")


@test("manual-preset-menu", "Load a preset through the device menu and verify the OLED",
      tags=("manual",))
def t_preset_menu(ctx):
    ctx.instruct("Using the encoder, navigate to the preset menu and load preset 'T_SYNC'. "
                 "The device will reboot.")
    ctx.wait_enter("Press ENTER after it has rebooted")
    ctx.device.reconnect(timeout=30.0)
    st = ctx.device.state(full=True)
    ctx.check(st.get("preset") == "T_SYNC", f"device reports preset T_SYNC (got {st.get('preset')})")
    ctx.check(st.get("midi_sync") is True, "T_SYNC's midi_sync=true took effect")
    ctx.ask_pass_fail("Did the OLED/menu behave correctly during navigation and load?")
    ctx.instruct("Loading back into T_MULTI over serial...")
    ctx.device.load_preset(BASELINE_PRESET)


@test("manual-visuals", "Pixels and OLED look right during record/playback", tags=("manual",))
def t_visuals(ctx):
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.record(0)
    ctx.ask_pass_fail("Pad 0 pixel is SOLID RED (recording)?")
    d.send(note_on(60, 100, 0), pause=0.3)
    d.send(note_off(60, 0), pause=0.3)
    d.stop_record()
    ctx.ask_pass_fail("Pad 0 pixel is now the PLAYING color and flashes with the loop?")
    d.stop_all()
    d.clear_all()


# --------------------------------------------------------------------------
# Runner / report
# --------------------------------------------------------------------------

def run_tests(selected, device):
    results = []
    for t in selected:
        print(f"\n=== {t['id']} — {t['desc']}")
        ctx = Ctx(device)
        t0 = time.monotonic()
        try:
            t["fn"](ctx)
            status, detail = "PASS", ""
        except TestSkipped as e:
            status, detail = "SKIP", str(e)
        except TestFailed as e:
            status, detail = "FAIL", str(e)
        except DeviceError as e:
            status, detail = "FAIL", f"device communication lost: {e}"
            try:
                ctx.crash_recovery()
            except DeviceError:
                print("    Could not recover the device — aborting the run.")
                results.append(_result(t, status, detail, ctx, t0))
                break
        except KeyboardInterrupt:
            status, detail = "SKIP", "interrupted by user"
            if input("\n  Abort the whole run? [y/N] ").strip().lower() == "y":
                results.append(_result(t, status, detail, ctx, t0))
                break
        results.append(_result(t, status, detail, ctx, t0))
        print(f"--- {t['id']}: {status}" + (f" ({detail})" if detail else ""))
        cleanup_between_tests(device)
    return results


def _result(t, status, detail, ctx, t0):
    return {
        "id": t["id"],
        "desc": t["desc"],
        "status": status,
        "detail": detail,
        "notes": ctx.notes,
        "seconds": round(time.monotonic() - t0, 1),
    }


def write_report(results):
    REPORT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (REPORT_DIR / f"report_{stamp}.json").write_text(json.dumps(results, indent=2))

    lines = [f"# Loopster test report — {datetime.now():%Y-%m-%d %H:%M}", ""]
    lines.append("| Test | Status | Time | Detail |")
    lines.append("|---|---|---|---|")
    for r in results:
        lines.append(f"| {r['id']} | {r['status']} | {r['seconds']}s | {r['detail']} |")
    md = REPORT_DIR / f"report_{stamp}.md"
    md.write_text("\n".join(lines) + "\n")

    print("\n" + "=" * 64)
    counts = Counter(r["status"] for r in results)
    print(f"RESULTS: {counts.get('PASS', 0)} passed, {counts.get('FAIL', 0)} failed, "
          f"{counts.get('SKIP', 0)} skipped")
    width = max((len(r["id"]) for r in results), default=1)
    for r in results:
        mark = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️ "}[r["status"]]
        print(f"  {mark} {r['id']:<{width}}  {r['detail']}")
    print(f"\nReport written to {md}")
    return counts.get("FAIL", 0)


def unattended_tests():
    """--auto / [u]nattended selection: no manual steps AND no known-crash tests.
    "crashy" = can hang/watchdog-reboot the device (parked R18 flood). Those
    still run via --all, --tag stress, an explicit --test, or [a]ll."""
    skipped = [t["id"] for t in TESTS if "crashy" in t["tags"]]
    if skipped:
        print(f"Note: skipping known-crash test(s): {', '.join(skipped)} "
              f"(include with --all or --test)")
    return [t for t in TESTS if "manual" not in t["tags"] and "crashy" not in t["tags"]]


def pick_interactively():
    print("Available tests:")
    for i, t in enumerate(TESTS):
        tags = ",".join(t["tags"])
        print(f"  [{i}] {t['id']:<32} ({tags})  {t['desc']}")
    raw = input("\nRun which? [a]ll / [u]nattended-only / numbers like 0,3,5: ").strip().lower()
    if raw in ("a", "all", ""):
        return TESTS
    if raw in ("u", "auto"):
        return unattended_tests()
    idx = [int(x) for x in raw.replace(",", " ").split()]
    return [TESTS[i] for i in idx]


def main():
    ap = argparse.ArgumentParser(description="Loopster on-device test harness")
    ap.add_argument("--all", action="store_true", help="run every registered test")
    ap.add_argument("--auto", action="store_true",
                    help="run only non-manual tests (also skips 'crashy' ones)")
    ap.add_argument("--test", nargs="+", metavar="ID", help="run specific test id(s)")
    ap.add_argument("--tag", help="run tests with this tag (auto/manual/stress/crashy)")
    ap.add_argument("--list", action="store_true", help="list tests and exit")
    ap.add_argument("--serial-port", help="override serial port autodetection")
    ap.add_argument("--midi-port", help="override MIDI port name match")
    args = ap.parse_args()

    if args.list:
        for t in TESTS:
            print(f"{t['id']:<34} [{','.join(t['tags'])}] {t['desc']}")
        return 0

    if args.test:
        by_id = {t["id"]: t for t in TESTS}
        missing = [i for i in args.test if i not in by_id]
        if missing:
            print(f"Unknown test id(s): {missing}. Use --list.")
            return 2
        selected = [by_id[i] for i in args.test]
    elif args.tag:
        selected = [t for t in TESTS if args.tag in t["tags"]]
    elif args.auto:
        selected = unattended_tests()
    elif args.all:
        selected = TESTS
    else:
        selected = pick_interactively()

    if not selected:
        print("Nothing selected.")
        return 2

    print("\nConnecting to Loopster (USB serial + MIDI)...")
    device = Device(serial_port=args.serial_port, midi_name=args.midi_port)
    try:
        device.connect()
    except DeviceError as e:
        print(f"FAILED: {e}")
        print("Is the Loopster plugged in and running firmware built with LOOPSTER_TEST_HOOKS?")
        return 2
    print("Connected.")

    try:
        results = run_tests(selected, device)
    finally:
        cleanup_between_tests(device)
        device.close()
    return 1 if write_report(results) else 0


if __name__ == "__main__":
    sys.exit(main())
