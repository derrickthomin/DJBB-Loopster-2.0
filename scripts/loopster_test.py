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

from loop_v2 import loop_filename, sample_loop  # scripts/loop_v2.py — v2 .bin builder

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
FIXTURES_DIR = SCRIPT_DIR / "fixtures"   # old-version presets.json corpus + .mid samples
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
        after the CC-flood crash). Open in a worker thread with a timeout.

        write_timeout matters as much as the read timeout: pyserial defaults it to
        None = block forever, so when the device stops draining its CDC OUT endpoint
        (mid-reboot, or half-enumerated) a one-line `CMD:` write hangs the harness
        with no deadline anywhere above it — a whole --auto gate stalled 25 minutes
        that way on 2026-09-11 and had to be killed. Bounded, it surfaces as
        SerialTimeoutException -> DeviceError, which cmd() already turns into a
        failed test the runner can recover from and carry on."""
        result = {}
        abandoned = threading.Event()

        def worker():
            try:
                s = serial.Serial(port, 115200, timeout=0.1, write_timeout=5.0)
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
        """After a reboot/crash: wait for re-enumeration and reopen everything.

        ⚠ ORDER MATTERS: the settle sleep happens BEFORE the MIDI ports are closed,
        not after. rtmidi's close_port() calls CoreMIDI MIDIPortDispose(), which spins
        in LocalMIDIReceiverList::Remove() (usleep) when it runs at the instant the USB
        MIDI device is disappearing — and python-rtmidi does NOT release the GIL around
        it (the extension imports PyGILState_Ensure/Release but no PyEval_SaveThread),
        so the ENTIRE interpreter freezes with no deadline anywhere above it. Two
        --auto gates stalled 25+ minutes that way on 2026-09-11 (caught with
        `sample <pid>`, both at a save+reboot test) and had to be killed; the device was
        healthy and answering PING the whole time, so this is emphatically NOT the
        "wedged USB enumeration needs a power cycle" failure it looks like from outside.
        Dropping the serial link first and letting CoreMIDI finish processing the
        removal keeps the dispose out of that race window. For the same reason a
        watchdog thread cannot rescue this: it would never get the GIL.
        """
        self.stop_clock()
        # Serial first: cheap, no CoreMIDI involvement, and it stops the ledger from
        # carrying a dead command across the reboot.
        if self.ser:
            try:
                self.ser.close()
            except Exception:  # noqa: BLE001
                pass
            self.ser = None
        self._rxbuf = b""
        self._awaiting = 0
        time.sleep(settle)
        self.close()  # MIDI ports disposed only now, after the removal has settled
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

    def pixels_state(self):
        """Logical LED state dump (TEST_PIXELS): per-pad shadow color, blink
        flag/color, pending flash, plus the palette constants for comparison."""
        return self.cmd("TEST_PIXELS")

    def inject_din(self, data):
        """Queue raw bytes for the DIN/AUX input; parsed by the real UART
        running-status parser on the next MIDI drain (source 'AUX')."""
        return self.cmd("TEST_DIN|" + bytes(data).hex().upper())

    def set_midi_cfg(self, midi_type, clock_source):
        """midi_type USB/AUX/ALL + clock_source USB/AUX without a preset reboot."""
        return self.cmd(f"TEST_MIDI_CFG|{midi_type}|{clock_source}")

    def set_passthru(self, mode):
        return self.cmd(f"TEST_PASSTHRU|{mode}")

    def set_channel_in(self, ch):
        return self.cmd(f"TEST_CHANNEL_IN|{ch}")

    def set_record_cc(self, on):
        return self.cmd(f"TEST_RECORD_CC|{1 if on else 0}")

    def set_pad_channel(self, pad, ch):
        """Per-pad output channel mapping (-2 global, -1 as-recorded, 0-15)."""
        return self.cmd(f"TEST_PAD_CHANNEL|{pad}|{ch}")

    def toggle_velocity_map(self, pad):
        """FN+pad equivalent in velocity play mode: toggle single-note mapping."""
        return self.cmd(f"TEST_VELOCITY_MODE|{pad}")

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

    # ---- raw files (presets.json + /loops) ----

    RAW_CHUNK = 384  # bytes per chunk -> 512 base64 chars, matches the firmware's 512 B buffers

    def read_presets_raw(self):
        """Whole presets.json, byte-exact, via GET_PRESETS_RAW_CHUNK (the web backup path)."""
        raw = b""
        offset = 0
        while True:
            rsp = self.cmd(f"GET_PRESETS_RAW_CHUNK|{offset}")
            data = base64.b64decode(rsp["data"])
            raw += data
            offset += len(data)
            if rsp.get("done") or not data:
                return raw
            if offset > 200_000:
                raise DeviceError(f"runaway raw stream ({offset} bytes and no done flag)")

    def write_presets_raw(self, blob):
        """Put presets.json on flash BYTE-EXACT (TEST_PRESETS_RAW) — the way an older
        firmware left it, untouched by this firmware's serializer."""
        chunks = [blob[i:i + self.RAW_CHUNK] for i in range(0, len(blob), self.RAW_CHUNK)] or [b""]
        offset = 0
        for i, chunk in enumerate(chunks):
            done = 1 if i == len(chunks) - 1 else 0
            b64 = base64.b64encode(chunk).decode()
            rsp = self.cmd(f"TEST_PRESETS_RAW|{offset}|{done}|{b64}")
            offset += len(chunk)
        if rsp.get("size") != len(blob):
            raise DeviceError(f"presets.json size after raw write {rsp.get('size')} != {len(blob)}")
        return rsp

    def put_loop_file(self, name, blob):
        """Install a v2 loop file via PUT_LOOP_FILE_CHUNK (the web .mid-import path)."""
        chunks = [blob[i:i + self.RAW_CHUNK] for i in range(0, len(blob), self.RAW_CHUNK)]
        offset = 0
        for i, chunk in enumerate(chunks):
            done = 1 if i == len(chunks) - 1 else 0
            b64 = base64.b64encode(chunk).decode()
            rsp = self.cmd(f"PUT_LOOP_FILE_CHUNK|{name}|{offset}|{done}|{b64}")
            offset += len(chunk)
        return rsp

    def read_loop_file(self, name):
        raw = b""
        offset = 0
        while True:
            rsp = self.cmd(f"GET_LOOP_FILE_CHUNK|{name}|{offset}")
            data = base64.b64decode(rsp["data"])
            raw += data
            offset += len(data)
            if rsp.get("done") or not data:
                return raw

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
        # TEST_MIDI_CFG restores the T_MULTI baseline (ALL/USB — the as-shipped
        # config), NOT USB/USB. Sync / transport / loop type / per-pad channel
        # are reset too, so a test that died half-way (sync left on, a "hold"
        # default, a pad mapped to ch 9...) cannot poison the next one; the
        # baseline pad mapping is as-recorded (-1) on every pad.
        restores = ["TEST_MIDI_SYNC|0", "TEST_TRANSPORT|on", "TEST_LOOP_TYPE|loop",
                    "TEST_PLAY_MODE|loop", "TEST_QUANTIZE|none|100|none",
                    "TEST_MIDI_CFG|ALL|USB", "TEST_PASSTHRU|off",
                    "TEST_CHANNEL_IN|-1", "TEST_RECORD_CC|1",
                    "TEST_ARP_CONFIG|1|1/8|up"]
        restores += [f"TEST_PAD_CHANNEL|{i}|-1" for i in range(16)]
        for c in restores:
            try:
                device.cmd(c)
            except DeviceError:
                pass
        # Velocity map is a toggle — only flip it if a test left it engaged.
        try:
            if device.state().get("velocity_mapped"):
                device.cmd("TEST_VELOCITY_MODE|0")
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


def _error_code(err):
    """Machine-readable code of a DeviceError raised by Device.cmd(): the RSP's
    "code" field is embedded as the trailing "(code)" of the message
    ("CMD -> human text (code)"). None when the error carried no code."""
    m = re.search(r"\((\w+)\)$", str(err))
    return m.group(1) if m else None


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


@test("quantize-end-of-loop-note",
      "Event quantize wraps a note snapped past the loop end to the loop start instead of dropping it")
def t_quantize_end_of_loop_note(ctx):
    """quantize_events() snaps a note struck in the last half-unit before the stop
    FORWARD to the next grid line — which lies beyond total_midi_ticks whenever the
    loop length itself sits in the second half of a unit and no loop-length
    quantize pads it out. Playback never reaches a tick >= the loop length, so the
    note silently vanished: still counted by notes_on, never heard again (0 plays
    before the fix). The fix moves such a note to tick 0 — the grid line at/past
    the end IS the next cycle's downbeat — so it plays every cycle, together with
    (not a few ticks after) whatever already sits on the downbeat.

    Geometry at 120 BPM (1 tick = 20.8 ms), on a WHOLE-note grid (96 ticks) so host
    jitter cannot miss the window, in DEVICE ticks from the record start (the T_MULTI
    baseline records with trim_silence_mode "none", so device ticks are absolute):
    note B at ~60 (past the half-unit point 48 -> snaps to 96), stop at ~70. Any
    total_ticks in 61..95 keeps 96 past the end with B inside the loop — a 35-tick
    (~730 ms) window. Note A at ~10 snaps down to 0 and is the downbeat companion B
    must line up with. Device time runs ~100 ms ahead of the host's t0 (record()'s
    RSP read waits out pyserial's 0.1 s timeout after the device has already
    started) plus the stop command's latency, so each take measures that lag from
    total_ticks vs the host stop time and a missed window is retried with the
    corrected lag (3 takes max). A take that still misses is logged and B is then
    only asserted to play."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    bpm = float(d.state()["bpm"])
    tick_s = 60.0 / bpm / 24
    ctx.log(f"bpm={bpm:g} -> 1 tick = {tick_s * 1000:.1f} ms, whole-note grid = 96 ticks "
            f"({96 * tick_s * 1000:.0f} ms)")
    A_ON, A_OFF, B_ON, B_OFF, STOP = 10, 15, 60, 63, 70  # device-tick targets
    GRID = 96
    WINDOW = (61, 95)  # total_ticks range where B (60) is inside the loop but its snap (96) is not

    def loop0():
        return next((l for l in d.state()["loops"] if l["pad"] == 0), None)

    def at(t0, tick, lag):  # sleep until the host time that maps to a device tick
        rem = t0 + tick * tick_s - lag - time.time()
        if rem > 0:
            time.sleep(rem)

    d.set_quantize("1", 100, loop_amount="none")  # "1" = whole note (TEST_QUANTIZE accepts it)
    lag = 0.10  # host t0 -> device recording origin (s); refined from each take
    hit = False
    lp = None
    try:
        for take in range(1, 4):
            d.record(0)
            t0 = time.time()
            at(t0, A_ON, lag)
            d.send(note_on(60, 100, 0))     # A: snaps down to 0 (the downbeat)
            at(t0, A_OFF, lag)
            d.send(note_off(60, 0))
            at(t0, B_ON, lag)
            d.send(note_on(64, 100, 0))     # B: snaps UP to 96, past the end
            at(t0, B_OFF, lag)
            d.send(note_off(64, 0))
            at(t0, STOP, lag)
            host_stop = time.time() - t0
            d.drain_midi()
            d.stop_record()                 # playback starts (sync off)
            lp = loop0()
            if lp is None:
                raise TestFailed("no loop recorded on pad 0")
            ticks = lp["total_ticks"]
            measured = ticks * tick_s - host_stop
            hit = WINDOW[0] <= ticks <= WINDOW[1]
            ctx.log(f"take {take}: total_ticks={ticks} notes_on={lp['notes_on']} (host stop "
                    f"at {host_stop:.3f} s -> device ran {measured * 1000:+.0f} ms ahead; "
                    f"drop window {WINDOW[0]}..{WINDOW[1]} {'HIT' if hit else 'missed'})")
            if hit:
                break
            lag = measured
            d.stop_all()
            d.clear_all()
            d.drain_midi()
        ctx.check(lp["notes_on"] == 2, f"both note-ons kept by finalize ({lp['notes_on']})")
        if not hit:
            ctx.log(f"NOTE: never hit the {WINDOW[0]}..{WINDOW[1]} drop window — host timing; "
                    "B's playback below is not a regression probe this run")
        cap = d.capture(4.6)  # ~3 cycles of a ~1.5 s (70-tick) loop
        d.stop_all()
    finally:
        d.set_quantize("none", 100, loop_amount="none")

    got = summarize(cap)
    b_ons = got[("on", 64, 100, 0)]
    ctx.log(f"note-ons over 4.6 s: B(64)={b_ons} A(60)={got[('on', 60, 100, 0)]}")
    ctx.check(b_ons >= 2,
              f"note B snapped past the loop end still plays every cycle ({b_ons} note-ons; "
              "before the fix: 0 — the note vanished)")
    ctx.check(got[("on", 60, 100, 0)] >= 2, "note A (sanity companion) plays every cycle")
    if hit:
        # B wrapped onto tick 0 = A's tick, so both go out in the same playback pass. A
        # modulo wrap (96 % total) would trail A by 96 - total = 1..35 ticks (up to 730 ms).
        a_t = [t for t, m in cap if m.type == "note_on" and m.note == 60 and m.velocity > 0]
        b_t = [t for t, m in cap if m.type == "note_on" and m.note == 64 and m.velocity > 0]
        gaps = [min(abs(b - a) for a in a_t) for b in b_t] if a_t else []
        ctx.log("B-to-nearest-A note-on gap per cycle: "
                + (", ".join(f"{g * 1000:.0f} ms" for g in gaps) or "none"))
        worst = max(gaps) if gaps else -1.0
        ctx.check(bool(gaps) and worst <= 0.015,
                  f"wrapped note B lands ON the downbeat with A (worst gap {worst * 1000:.0f} ms, "
                  f"limit 15; a modulo wrap would trail by {GRID - lp['total_ticks']} tick(s))")
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
    the old algorithm needed >= 2 whole notes (~3.4 s at 140 even best-case), so a
    sub-3.2 s latch cleanly discriminates new from old.

    Why the tempo-change leg gets up to 3 attempts (added 2026-09-11): the firmware
    latches a new tempo only after two IDENTICAL consecutive 24-tick window reads
    (clock.cpp — a deliberate glitch filter), and the window is bounded by two
    individual tick ARRIVALS. Our clock generator is a Python thread on time.sleep(),
    which overshoots by ~1-2 ms; at 140 BPM a beat is 428.6 ms and the 139/140/141
    rounding boundaries are only ±1.5 ms away, so consecutive windows measurably read
    138/140/141 (sampled 2026-09-11: only 3 of 8 window pairs matched). When the reads
    happen not to repeat, the device correctly withholds the latch and the leg times
    out on HOST jitter with the device still reporting the old tempo — seen twice in
    full-gate runs while the same build passed 3/3 standalone. Each attempt re-arms
    from 100 BPM and is an independent draw, so the retries cancel that jitter without
    weakening the net one bit: a firmware on the old algorithm cannot beat 3.2 s in
    ANY attempt. Do not "simplify" this back to a single attempt, and do not raise
    deadline_s past ~3.3 s — the gap to 3.4 s IS the test.
    """
    d = ctx.device
    d.clear_all()
    d.set_midi_sync(True)
    d.drain_midi()

    def poll_bpm(target, deadline):
        """Poll until within ±1 of target or out of time. Returns (last value, trail)
        — the trail is logged so a failure shows whether the device walked toward the
        target and ran out of time, or never moved at all (= the confirm never fired)."""
        got = None
        trail = []
        while time.time() < deadline:
            got = d.state()["bpm"]
            if not trail or trail[-1] != got:
                trail.append(got)
            if abs(got - target) <= 1:
                break
            time.sleep(0.1)
        return got, trail

    deadline_s = 3.2
    attempts = []
    latched = False
    for attempt in range(3):
        # (Re-)establish 100 BPM — the device boots believing 120, and a failed attempt
        # leaves it wherever it got to. send_start resets the window cleanly.
        d.start_clock(bpm=100, send_start=True)
        base, base_trail = poll_bpm(100, time.time() + 4.0)
        if abs(base - 100) <= 1:
            # Tempo change mid-roll: swap generator threads without Stop/Start, like
            # dragging Live's tempo slider. The swap gap stretches one tick inside a
            # measurement window; confirmation must filter that bogus reading, then
            # latch 140 off two clean windows.
            t0 = time.time()
            d.start_clock(bpm=140)  # start_clock() stops the old thread first
            got, trail = poll_bpm(140, t0 + deadline_s)
            elapsed = time.time() - t0
            attempts.append(f"#{attempt + 1}: 100->140 got {got} in {elapsed:.2f}s {trail}")
            if abs(got - 140) <= 1 and elapsed <= deadline_s:
                latched = True
                break
        else:
            attempts.append(f"#{attempt + 1}: baseline never reached 100 (got {base}) {base_trail}")
        d.stop_clock(send_stop=True)
        d.drain_midi()

    ctx.check(any("baseline never reached" not in a for a in attempts),
              f"initial latch to 100 BPM (never reached it in {len(attempts)} attempts)")
    ctx.check(latched,
              f"tempo change 100 -> 140 latched within {deadline_s}s "
              f"(old algorithm needed >=3.4s) — took {len(attempts)} attempt(s)")
    for a in attempts:
        ctx.log(f"  attempt {a}")

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


@test("preset-load-releases-notes",
      "Preset load (reboot) releases sounding loop notes before USB drops",
      tags=("auto", "slow"))
def t_preset_load_releases_notes(ctx):
    """Loading a preset reboots the device (the menu path and TEST_LOAD_PRESET are
    the same code). Before the fix the reboot simply pulled the plug on a playing
    looper: a note sounding at that instant was never released, and the fresh boot
    had no memory of it — the synth rang until the player found panic, with no way
    to release it from the device. TEST_LOAD_PRESET / TEST_REBOOT now stop all
    loops and send note-offs / CC64=0 / CC123 / CC120 on every channel BEFORE
    rebooting. The ack goes out first (deferred reboot), so the harness reads USB
    MIDI for a moment after the RSP and must see the release before the port
    disappears."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    d.record(0)
    time.sleep(0.1)
    d.send(note_on(72, 100, 0), pause=1.0)   # long note...
    d.send(note_off(72, 0), pause=0.1)
    d.drain_midi()
    d.stop_record()  # starts playback (sync off)
    time.sleep(0.4)  # note 72 is sounding now
    d.drain_midi()

    ctx.instruct(f"Loading {BASELINE_PRESET} while note 72 sounds — the device reboots")
    d.cmd(f"TEST_LOAD_PRESET|{BASELINE_PRESET}")  # ack now; reboot is deferred
    # Read what the device sends between the ack and the USB drop. Inline rather
    # than capture() so messages already collected survive the port dying mid-read.
    seen = []
    deadline = time.perf_counter() + 1.5
    try:
        while time.perf_counter() < deadline:
            for msg in d.midi_in.iter_pending():
                if msg.type not in ("clock", "start", "stop", "continue", "songpos"):
                    seen.append(msg)
            time.sleep(0.002)
    except Exception as e:  # noqa: BLE001 — MIDI port gone = the reboot happened
        ctx.log(f"MIDI port dropped mid-read (expected on reboot): {e}")
    d.reconnect()

    keys = sorted(summarize([(0.0, m) for m in seen]))
    ctx.log(f"{len(seen)} MIDI message(s) arrived after the ack, before USB dropped: {keys}")
    released = any(
        (m.type == "note_off" and m.note == 72 and m.channel == 0)
        or (m.type == "note_on" and m.note == 72 and m.velocity == 0 and m.channel == 0)
        or (m.type == "control_change" and m.control == 123 and m.channel == 0)
        for m in seen)
    ctx.check(released,
              "note 72 released (note-off / vel-0 / CC123 on ch 0) before the reboot "
              "(before the fix: nothing — the note rang until panic)")
    st = d.state(full=True)
    ctx.check(st.get("preset") == BASELINE_PRESET, f"device rebooted into {BASELINE_PRESET}")
    ctx.check(st["recording"] is False and st["any_playing"] is False,
              "device came back idle (nothing recording or playing)")
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


@test("loop-mode-persist-after-save",
      "A loop's mode change (loop -> oneshot gesture) survives preset save + reboot",
      tags=("auto", "slow"))
def t_loop_mode_persist_after_save(ctx):
    """A loop's type lives ONLY in its .bin file header (the preset JSON stores
    just {"loop_id"}), so a mode change made AFTER the loop was first saved must
    re-write that file on the next save. Before the fix the second save skipped
    the file because the loop's flash path was already set ("already on disk"),
    the header kept the ORIGINAL type, and after a reboot the pad came back as a
    plain loop — the customer's oneshot silently reverted. Sequence: record, save
    (path set), gesture the mode to oneshot (pad hold + encoder, exactly as in
    gesture-held-pads-loop-type), save again, reboot, assert oneshot + it still
    plays. settings.loop_type is forced back to "loop" before the second save so
    the preset JSON cannot mask a header that was not rewritten."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.set_play_mode("loop")
    d.set_menu(MENU_PLAY)
    d.clear_all()
    d.drain_midi()

    d.record(0)
    time.sleep(0.1)
    for n in (60, 64):
        d.send(note_on(n, 100, 0), pause=0.12)
        d.send(note_off(n, 0), pause=0.08)
    d.stop_record()
    d.stop(0)

    def loop0():
        return next((l for l in d.state()["loops"] if l["pad"] == 0), None)

    ctx.instruct("Saving preset T_MODE (first save: the loop's flash path gets set)")
    d.save_preset("T_MODE")
    try:
        # The real loop-type gesture: hold past the 350 ms threshold, one detent
        # forward = loop -> oneshot. The press also toggles playback; the gesture
        # stops the loop again (asserted by gesture-held-pads-loop-type).
        try:
            d.inject_pad(0, True)
            time.sleep(0.5)
            d.inject_encoder(1)
            time.sleep(0.2)
        finally:
            d.inject_pad(0, False)
            time.sleep(0.2)
        lp = loop0()
        ctx.check(lp is not None and lp["type"] == "oneshot",
                  f"gesture changed pad 0 to oneshot (got {lp and lp['type']})")
        # The default for NEW loops followed the gesture — put it back so only the
        # .bin header carries "oneshot" into the second save.
        d.set_loop_type("loop")
        lp = loop0()
        ctx.check(lp is not None and lp["type"] == "oneshot",
                  "existing loop keeps its type when the new-loop default is reset")
        d.stop_all()
        d.drain_midi()

        ctx.instruct("Saving T_MODE again (must re-write the loop file header), then rebooting")
        d.save_preset("T_MODE")
        d.reboot()

        st = d.state(full=True)
        ctx.check(st.get("preset") == "T_MODE", "device rebooted into T_MODE")
        lp = next((l for l in st["loops"] if l["pad"] == 0), None)
        ctx.check(lp is not None, "loop restored on pad 0")
        ctx.check(lp["type"] == "oneshot",
                  f"restored loop is still a oneshot (got {lp['type']!r}; before the fix: "
                  "'loop' — the second save never re-wrote the header)")
        d.drain_midi()
        d.play(0)
        got = summarize(d.capture(1.5))
        d.stop_all()
        ons = sorted(k for k in got if k[0] == "on")
        ctx.check(got[("on", 60, 100, 0)] >= 1 or got[("on", 64, 100, 0)] >= 1,
                  f"restored oneshot still plays its notes (saw {ons})")
    finally:
        # Cleanup like loop-save-reboot-restore: back to baseline (frees T_MODE
        # from startup), then delete it. Tolerant: a dead device is reported by
        # the runner's crash handling, not by masking the original failure here.
        try:
            d.clear_all()
            ctx.instruct("Loading back into T_MULTI (reboot), then deleting T_MODE")
            d.load_preset(BASELINE_PRESET)
            d.delete_preset("T_MODE")
        except DeviceError as e:
            ctx.log(f"cleanup incomplete: {e}")
    ctx.check("T_MODE" not in d.preset_names(), "scratch preset deleted")


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


@test("webconfig-fresh-unit",
      "Factory-fresh unit (no presets.json) completes the web-config handshake")
def t_webconfig_fresh_unit(ctx):
    """Regression guard for the Aug 2026 customer bug: every shipped unit leaves
    the bench with NO /presets.json (full-flash wipe; the file only appears on
    the first on-device save), and serial_config treated that as io_error — so
    the first thing a customer tries (the config page) failed on every fresh
    unit. Wipes the file via test hook, then runs the page's exact handshake:
    PING -> GET_PRESET_NAMES (must be ok + empty) -> SET_PRESET (must create the
    file from nothing). Fixtures are restored afterwards either way."""
    d = ctx.device
    wiped = d.cmd("TEST_WIPE_PRESETS_FILE")
    ctx.log(f"presets.json wiped (existed before: {wiped.get('existed')})")
    try:
        rsp = d.cmd("PING")
        ctx.check(rsp.get("device") == "loopster", "PING identifies the device")
        try:
            names = d.cmd("GET_PRESET_NAMES")
        except DeviceError as e:
            raise TestFailed(
                f"fresh unit fails the handshake at GET_PRESET_NAMES ({e}) — "
                "the web config page dies here on every unit as shipped") from e
        ctx.check(names.get("names") == [],
                  f"fresh unit reports an empty preset list (got {names.get('names')})")

        fixtures = json.loads(PRESETS_FILE.read_text())
        d.upload_preset(BASELINE_PRESET, fixtures[BASELINE_PRESET])
        names = d.cmd("GET_PRESET_NAMES")
        ctx.check(names.get("names") == [BASELINE_PRESET],
                  "SET_PRESET creates presets.json from nothing")
    finally:
        d.cmd("DISCONNECT")  # PING locked web-config mode; release it
        # Restore state on BOTH firmware generations: the menu-path save always
        # recreates presets.json (settings.cpp tolerates a missing file), after
        # which SET_PRESET works even on pre-fix firmware.
        d.save_preset("T_FRESHFIX")
        fixtures = json.loads(PRESETS_FILE.read_text())
        for name, body in fixtures.items():
            if not name.startswith("_"):
                d.upload_preset(name, body)
        d.load_preset(BASELINE_PRESET)
        d.delete_preset("T_FRESHFIX")


@test("preset-save-refuses-corrupt-file",
      "Save refuses (file_unreadable) when presets.json exists but won't parse; nothing is touched",
      tags=("auto", "slow"))
def t_preset_save_refuses_corrupt_file(ctx):
    """save_preset_to_file() used to treat an unparsable presets.json exactly like
    a missing one ("empty doc, same as Python"): the save rewrote the file with
    ONLY the preset being saved — every other preset the customer had was gone —
    and the orphan sweep that follows a save then deleted their loop .bin files,
    turning a transient parse failure (interrupted write, flash glitch) into
    permanent loss. A MISSING file must still save fine (fresh unit —
    webconfig-fresh-unit), but an EXISTING file that won't parse must refuse with
    code file_unreadable and touch nothing. A loop is saved and then cleared from
    RAM first, so /loops holds a file that only the (corrupt) presets.json
    references: the old code's sweep would delete it, the refused save must not.
    Restored the way webconfig-fresh-unit restores (wipe, fixtures, startup
    pointer, reboot) — the corrupt file cannot be loaded past, so the wipe is the
    only way back — whatever happens."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    fixtures = {k: v for k, v in json.loads(PRESETS_FILE.read_text()).items()
                if not k.startswith("_")}
    names_before = d.preset_names()
    ctx.log(f"presets before: {names_before}")
    # Non-fixture presets left by other tests are re-uploaded verbatim on restore
    # so the snapshot comparison holds whatever state the suite arrived in.
    extras = {}
    for name in names_before:
        if name not in fixtures:
            try:
                body = d.get_preset(name)
                body = body.get("preset", body)
                extras[name] = json.loads(body) if isinstance(body, str) else body
            except DeviceError as e:
                ctx.log(f"could not fetch leftover preset {name}: {e}")
    try:
        # Seed one saved loop file, referenced only by the soon-corrupt file
        d.record(0)
        time.sleep(0.1)
        d.send(note_on(60, 100, 0), pause=0.1)
        d.send(note_off(60, 0), pause=0.05)
        d.stop_record()
        d.stop_all()
        ctx.instruct("Saving T_BADLOOP (flash write; seeds a loop .bin file)")
        d.save_preset("T_BADLOOP")
        d.clear_all()  # file stays (orphan sweeps handle files, not removals)
        files_before = len(d.cmd("LIST_LOOP_FILES").get("files", []))
        ctx.check(files_before >= 1, f"seed loop file present ({files_before} file(s) in /loops)")

        try:
            d.cmd("TEST_CORRUPT_PRESETS_FILE")
        except DeviceError as e:
            raise TestFailed(
                f"TEST_CORRUPT_PRESETS_FILE refused ({e}) — firmware lacks the hook?") from e
        ctx.log("presets.json now holds invalid JSON")

        try:
            d.cmd("TEST_SAVE_PRESET|T_BAD", timeout=120.0)
        except DeviceError as e:
            code = _error_code(e)
            ctx.check(code == "file_unreadable",
                      f"save refused with code file_unreadable (got {code!r}: {e})")
        else:
            raise TestFailed("TEST_SAVE_PRESET|T_BAD succeeded on a corrupt presets.json "
                             "(old firmware: rewrites the file with only T_BAD in it)")
        files_after = len(d.cmd("LIST_LOOP_FILES").get("files", []))
        ctx.check(files_after == files_before,
                  f"refused save ran no orphan sweep ({files_before} -> {files_after} loop files)")
    finally:
        try:
            d.clear_all()
        except DeviceError:
            pass
        d.cmd("TEST_WIPE_PRESETS_FILE")
        for name, body in fixtures.items():
            d.upload_preset(name, body)
        for name, body in extras.items():
            d.upload_preset(name, body)
        d.cmd(f"SET_STARTUP|{BASELINE_PRESET}")
        ctx.instruct("Loading back into T_MULTI (reboot; boot sweep reclaims the seed file)")
        d.load_preset(BASELINE_PRESET)
    names_after = d.preset_names()
    ctx.check(sorted(names_after) == sorted(names_before),
              f"preset list restored to the snapshot ({names_after})")
    ctx.check(d.cmd("GET_PRESET_NAMES").get("startup") == BASELINE_PRESET,
              "startup preset back on the baseline")


@test("clock-source-matrix",
      "External clock syncs from any enabled input regardless of Clock Source preference")
def t_clock_source_matrix(ctx):
    """The Aug 2026 customer bug, USB-mirrored: with MIDI Type = ALL (both inputs
    enabled), the Clock Source *preference* must not hard-mute clock arriving on
    the other port. The customer had ALL + the default Clock Source USB, and DIN
    clock was silently dropped (should_accept_clock's then-final `return false`,
    midi.cpp) while DIN Start/Stop still worked — transport ran, loops froze at
    tick 0. The harness can only inject USB MIDI, so it proves the same branch
    with the ports swapped: ALL + Clock Source AUX + USB clock. Written failing;
    now pins the fix (clock_source is a tiebreaker, not a filter — the yield
    half lives in din-clock-tiebreaker)."""
    d = ctx.device
    base = json.loads(PRESETS_FILE.read_text())["T_SYNC"]
    combos = [
        # (name, midi_type, clock_source, why USB clock must be honored)
        ("T_CLK_A", "ALL", "USB", "preferred source matches the clock's port"),
        ("T_CLK_B", "USB", "AUX", "preferred port can't receive -> documented fallback"),
        ("T_CLK_C", "ALL", "AUX", "customer bug mirrored: preference must not mute "
                                  "the only clock present"),
    ]
    failures = []
    try:
        for name, midi_type, clock_source, why in combos:
            d.upload_preset(name, dict(base, midi_type=midi_type, clock_source=clock_source))
            ctx.log(f"{name}: midi_type={midi_type} clock_source={clock_source} — rebooting")
            d.load_preset(name)
            d.drain_midi()
            # Start + 10 clocks: the first clock after Start is the swallowed
            # downbeat, so an accepted stream counts exactly 9 (see
            # clock-counter-semantics for the spec anchor).
            d.send(mido.Message("start"))
            for _ in range(10):
                d.send(mido.Message("clock"))
            time.sleep(0.15)
            st = d.state()
            d.send(mido.Message("stop"))
            time.sleep(0.1)
            ctx.log(f"{name}: clock_playing={st['clock_playing']} "
                    f"clock_ticks={st['clock_ticks']} (want 9)")
            if st["clock_ticks"] != 9:
                failures.append(
                    f"{name} ({midi_type}/{clock_source}): ticks={st['clock_ticks']}, "
                    f"transport started={st['clock_playing']} — {why}")
        ctx.check(not failures, "clock followed on every enabled-input combo "
                                "(dropped: " + "; ".join(failures) + ")")
    finally:
        d.stop_clock(send_stop=True)
        d.load_preset(BASELINE_PRESET)
        for name, _mt, _cs, _why in combos:
            try:
                d.delete_preset(name)
            except DeviceError:
                pass


@test("transport-off-follow",
      "Transport=off: bare clock (no Start) starts the grid, exact count survives UI activity")
def t_transport_off_follow(ctx):
    """Free-run sync (Aug 2026, Walrus Canvas Clock): with midi_transport='off' the
    first accepted 0xF8 must synthesize the downbeat — same swallow semantics as a
    real Start, so N clocks always count N-1. Also a sustained exact-count leg with
    menu jumps interleaved, to catch tick loss under display/UI load."""
    d = ctx.device
    base = json.loads(PRESETS_FILE.read_text())["T_SYNC"]
    d.upload_preset("T_FREERUN", dict(base, midi_transport="off"))
    ctx.log("loading T_FREERUN (midi_transport=off) — rebooting")
    d.load_preset("T_FREERUN")
    d.drain_midi()
    st = d.state()
    ctx.check(st.get("midi_transport") == "off", "preset applied midi_transport=off")
    ctx.check(st["clock_playing"] is False, "no clock yet -> not playing")

    # Bare clock, no Start: first tick = synthesized downbeat (swallowed), so 10 -> 9.
    for _ in range(10):
        d.send(mido.Message("clock"))
    time.sleep(0.15)
    st = d.state()
    ctx.check(st["clock_playing"] is True, "clock alone started the grid (no Start needed)")
    ctx.check(st["clock_ticks"] == 9,
              f"first tick is the downbeat: 10 clocks -> counter 9 (got {st['clock_ticks']})")

    # Sustained exact count with UI activity: 6 batches of 24 ticks, menu jumps between.
    sent = 0
    for batch in range(6):
        for _ in range(24):
            d.send(mido.Message("clock"))
        sent += 24
        d.set_menu(2 if batch % 2 else 0)  # PLAY <-> MIDI menu — forces redraws mid-stream
    d.set_menu(0)
    time.sleep(0.3)
    st = d.state()
    ctx.check(st["clock_ticks"] == 9 + sent,
              f"exact count under UI activity: {9 + sent} (got {st['clock_ticks']})")

    # Armed recording must start immediately (grid is running), not blink forever.
    d.record(4)
    st = d.state()
    ctx.check(st["armed"] is False, "recording starts under free-run clock (not armed)")
    d.send(mido.Message("clock"))
    d.send(note_on(64, 90, 2), pause=0.1)
    d.send(note_off(64, 2), pause=0.1)
    for _ in range(24):
        d.send(mido.Message("clock"))
    d.stop_record()
    st = d.state()
    ctx.check(any(l["pad"] == 4 for l in st["loops"]), "loop recorded under free-run clock")
    d.clear_all()
    # Own the scratch preset this test created: reboot back to the baseline and drop it.
    # This used to be the immunity test's job below, which meant running THIS test alone
    # left the unit booted into T_FREERUN with the preset still on flash (2026-09-11).
    _drop_preset(d, "T_FREERUN")


@test("transport-off-immunity",
      "Transport=off: Start/Stop/SPP are ignored; switching back to 'on' demands a real Start")
def t_transport_off_immunity(ctx):
    """Transport messages from other gear sharing the clock line must not move the grid,
    and the off->on switch must drop the free-run latch (message mode = real Start
    required).

    Sets up its own free-run state via _enter_freerun (sync on + TEST_TRANSPORT|off),
    like its three sibling transport-off tests. It used to inherit T_FREERUN from
    transport-off-follow and skip itself when it did not find midi_transport == "off";
    since cleanup_between_tests began restoring TEST_TRANSPORT|on after every test
    (2026-09-11) that inheritance never survives, and the test silently SKIPped in the
    full gate while still passing when run alone. Hooks, not a preset load: stacking
    reboots at the tail of the suite is what the re-enumeration flakiness feeds on."""
    d = ctx.device
    _enter_freerun(d)
    try:
        _transport_off_immunity_body(ctx, d)
    finally:
        _exit_freerun(d)


def _transport_off_immunity_body(ctx, d):
    d.drain_midi()
    # (Re)establish a running grid and a known count.
    for _ in range(5):
        d.send(mido.Message("clock"))
    time.sleep(0.15)
    c0 = d.state()["clock_ticks"]

    d.send(mido.Message("stop"))
    time.sleep(0.15)
    st = d.state()
    ctx.check(st["clock_playing"] is True, "Stop ignored: grid keeps rolling")
    d.send(mido.Message("start"))
    d.send(mido.Message("songpos", pos=64))
    time.sleep(0.15)
    st = d.state()
    ctx.check(st["clock_ticks"] == c0,
              f"Start/SPP ignored: counter unmoved (got {st['clock_ticks']}, want {c0})")
    for _ in range(5):
        d.send(mido.Message("clock"))
    time.sleep(0.15)
    st = d.state()
    ctx.check(st["clock_ticks"] == c0 + 5,
              f"clock still counts after ignored transport (got {st['clock_ticks']})")

    # off -> on drops the latch: message mode must wait for a real Start.
    d.cmd("TEST_TRANSPORT|on")
    st = d.state()
    ctx.check(st["clock_playing"] is False, "switching transport on drops the free-run latch")
    d.send(mido.Message("clock"))
    time.sleep(0.15)
    ctx.check(d.state()["clock_playing"] is False, "bare clock no longer starts the grid")
    d.send(mido.Message("start"))
    d.send(mido.Message("clock"))
    time.sleep(0.15)
    ctx.check(d.state()["clock_playing"] is True, "real Start works again in message mode")
    d.send(mido.Message("stop"))
    time.sleep(0.1)
    # No teardown here any more: this test never loads a preset (see the docstring),
    # and transport-off-follow now drops T_FREERUN itself.


def _enter_freerun(d):
    """Free-run sync (midi_sync on, transport off) via hooks — deliberately NOT a preset
    load: that reboots, and stacking reboots at the tail of the suite is what the
    re-enumeration flakiness feeds on. TEST_TRANSPORT|on drops the latch on the way out."""
    d.set_midi_sync(True)
    d.cmd("TEST_TRANSPORT|off")
    d.drain_midi()


def _exit_freerun(d):
    d.stop_clock()
    d.cmd("TEST_TRANSPORT|on")
    d.set_midi_sync(False)
    d.clear_all()


def _drop_preset(d, name):
    d.load_preset(BASELINE_PRESET)
    try:
        d.delete_preset(name)
    except DeviceError:
        pass


@test("transport-off-clock-loss",
      "Transport=off: clock going quiet stops loops, releases notes, drops the latch")
def t_transport_off_clock_loss(ctx):
    """Free-run swallows Stop, so a clock that simply CEASES (Canvas Clock tap-stop,
    cable pull) is the only stop signal there is. Before the timeout it left loops
    frozen mid-note with notes ringing and clock_playing latched true forever — after
    which recordings stamped every event at one tick and stop_all_loops was a no-op.
    The timeout must behave like a Stop, then release the latch so the NEXT tick
    anchors a fresh downbeat (proven by the 10 -> 9 swallow on the re-latch leg)."""
    d = ctx.device
    _enter_freerun(d)
    try:
        d.clear_all()
        d.set_loop_type("loop")

        d.start_clock(bpm=120)
        time.sleep(0.4)
        ctx.check(d.state()["clock_playing"] is True, "bare clock started the grid")

        # Long note so the loop is most likely mid-note when the clock dies.
        d.record(0)
        d.send(note_on(60, 100, 0), pause=0.5)
        d.send(note_off(60, 0), pause=0.15)
        d.stop_record()
        time.sleep(0.5)  # loop audibly rolling

        d.drain_midi()
        d.stop_clock(send_stop=False)  # ticks vanish; no Stop message exists in this mode
        captured = summarize(d.capture(2.0))

        st = d.state()
        ctx.check(st["clock_playing"] is False,
                  "clock loss dropped the free-run latch without a Stop message")
        ctx.check(not any(l["playing"] for l in st["loops"]),
                  f"loops stopped when the clock died (loops={st['loops']})")
        ons = {(k[1], k[3]) for k in captured if k[0] == "on"}
        offs = {(k[1], k[2]) for k in captured if k[0] == "off"}
        ctx.check(not (ons - offs),
                  f"nothing left ringing after the dropout (stuck: {sorted(ons - offs)})")

        # Re-latch: the next bare clock must start a FRESH grid, swallowing tick 1.
        for _ in range(10):
            d.send(mido.Message("clock"))
        time.sleep(0.2)
        st = d.state()
        ctx.check(st["clock_playing"] is True, "clock returning restarted the grid")
        ctx.check(st["clock_ticks"] == 9,
                  f"re-latched downbeat: 10 clocks -> counter 9 (got {st['clock_ticks']})")
    finally:
        _exit_freerun(d)


@test("transport-off-stray-tick",
      "Transport=off: a stray clock burst times out instead of latching 'rolling' forever")
def t_transport_off_stray_tick(ctx):
    """Any receivable port can hand the free-run grid a stray 0xF8 (a DAW brushing the
    transport, another device sharing the line). That used to latch clock_playing true
    permanently: armed recordings fired instantly at a frozen tick and never re-armed.
    The timeout has to walk it back to idle on its own."""
    d = ctx.device
    _enter_freerun(d)
    try:
        d.clear_all()
        for _ in range(3):
            d.send(mido.Message("clock"))
        time.sleep(0.15)
        ctx.check(d.state()["clock_playing"] is True, "stray ticks did start the grid")

        time.sleep(1.5)  # past FREERUN_CLOCK_LOST_MS with no further ticks
        ctx.check(d.state()["clock_playing"] is False,
                  "stray burst timed out back to idle instead of latching")

        # And with no clock, a new recording must ARM (wait for the grid), not run free.
        d.record(1)
        st = d.state()
        ctx.check(st["armed"] is True,
                  "recording arms again once the stale latch is gone")
        d.stop_record()
    finally:
        _exit_freerun(d)


@test("transport-off-queue-resume",
      "Transport=off: queued loop waits for clock, starts on the fresh downbeat, "
      "survives tap-stop/tap-start")
def t_transport_off_queue_resume(ctx):
    """The queue path never consults midi_transport (it gates on midi_sync +
    clock_.is_playing), so free-run queueing shares message mode's tested code —
    but nothing pinned the full Canvas Clock workflow: queue with NO clock ->
    blink-wait; the first bare tick latches a fresh downbeat and
    process_loop_on_queue starts the loop; ticks ceasing (tap-stop) stops it
    cleanly but KEEPS its play_queue slot (_stop_single_loop's keep-queued
    branch); ticks returning auto-resume it from the top. Guards the "Canvas
    tap-stop doubles as stop-all / tap-start as re-sync" design decision."""
    d = ctx.device

    def pad0(st):
        return next((l for l in st["loops"] if l["pad"] == 0), None)

    # Content to queue: record with sync OFF so the loop parks cleanly, unqueued.
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()
    d.record(0)
    time.sleep(0.1)
    d.send(note_on(60, 100, 0), pause=0.15)
    d.send(note_off(60, 0), pause=0.1)
    time.sleep(0.3)
    d.stop_record()
    d.stop_all()
    time.sleep(0.2)
    lp = pad0(d.state())
    ctx.check(lp is not None and not lp["playing"] and not lp["queued"],
              f"baseline: loop parked and unqueued (got {lp})")

    _enter_freerun(d)  # sync on + transport off; no clock yet
    try:
        d.toggle(0)
        time.sleep(0.3)
        lp = pad0(d.state())
        ctx.check(lp is not None and lp["queued"] and not lp["playing"],
                  f"queued loop waits while no clock exists "
                  f"(queued={lp and lp['queued']}, playing={lp and lp['playing']})")

        # First bare ticks: fresh downbeat starts the queued loop.
        d.drain_midi()
        d.start_clock(bpm=120)
        time.sleep(0.7)
        lp = pad0(d.state())
        ctx.check(lp is not None and lp["playing"],
                  "first bare ticks started the queued loop (no Start message)")
        got = summarize(d.capture(1.5))
        ctx.check(got[("on", 60, 100, 0)] >= 1, "queued loop audible after the latch")

        # Tap-stop: ticks cease -> loop stops cleanly but stays queued for resume.
        d.drain_midi()
        d.stop_clock(send_stop=False)  # no Stop message exists in this mode
        captured = summarize(d.capture(2.0))
        st = d.state()
        lp = pad0(st)
        ctx.check(st["clock_playing"] is False, "clock loss dropped the free-run latch")
        ctx.check(lp is not None and not lp["playing"], "tap-stop stopped the loop")
        ctx.check(lp is not None and lp["queued"],
                  "loop kept its play-queue slot through the dropout (auto-resume armed)")
        ons = {(k[1], k[3]) for k in captured if k[0] == "on"}
        offs = {(k[1], k[2]) for k in captured if k[0] == "off"}
        ctx.check(not (ons - offs),
                  f"nothing ringing across the dropout (stuck: {sorted(ons - offs)})")

        # Tap-start: ticks return -> fresh grid, loop restarts by itself.
        d.drain_midi()
        d.start_clock(bpm=120)
        time.sleep(0.7)
        lp = pad0(d.state())
        ctx.check(lp is not None and lp["playing"],
                  "loop auto-resumed when the clock returned")
        got = summarize(d.capture(1.5))
        ctx.check(got[("on", 60, 100, 0)] >= 1, "resumed loop audible again")
        d.stop_clock(send_stop=False)
        time.sleep(0.5)
    finally:
        _exit_freerun(d)


@test("bank-change-held-pad-channel",
      "Bank change with a pad held releases the exact note it sent, on the channel it went out on")
def t_bank_change_held_pad_channel(ctx):
    """#265. The note-off used to be RECOMPUTED at release time from the current
    bank and channel instead of replaying what the press actually sent — so once
    a bank change moved the pad's note, the original note rang until panic. The
    property pinned: the off replays the exact (note, channel) the press sent,
    after the bank changed the pad's note.

    Channel: per-pad mapping is LOOP-scoped as of the live-vs-loop split
    (pad-channel-live-vs-loop) — it applies to the loop stored on a pad, never to
    a live press. So the held pad, mapped to ch 9 by the T_PADCH fixture, sends
    its live note-on on the GLOBAL channel 0, and the bank change must release
    that exact note on ch 0 (and nothing on ch 9). The fixture keeps the mapping
    in play so a regression that routes live presses through it shows up."""
    d = ctx.device
    base = json.loads(PRESETS_FILE.read_text())[BASELINE_PRESET]
    mapping = [-1] * 16
    mapping[0] = 9  # pad 0's LOOP -> ch 9; live presses use the preset's global ch 0
    d.upload_preset("T_PADCH", dict(base, midi_channel_pad_mapping=mapping))
    try:
        d.load_preset("T_PADCH")
        d.clear_all()  # no loop on pad 0, so a press plays a note instead of toggling
        d.drain_midi()

        d.inject_pad(0, True)
        on_keys = [k for k in summarize(d.capture(0.3)) if k[0] == "on"]
        ctx.check(len(on_keys) == 1, f"held pad sent exactly one note-on (got {on_keys})")
        note, ch = on_keys[0][1], on_keys[0][3]
        ctx.check(ch == 0, f"live note-on went out on the GLOBAL ch 0, not the pad's "
                           f"loop mapping ch 9 (got {ch})")

        d.drain_midi()
        d.change_bank(True)
        after = summarize(d.capture(0.4))
        ctx.check(after[("off", note, 0)] >= 1,
                  f"bank change released note {note} on ch 0 (saw {sorted(after)})")
        ch9 = sorted(k for k in after if k[0] in ("on", "off") and k[-1] == 9)
        ctx.check(not ch9, f"nothing sent on the loop-only mapping ch 9 (saw {ch9})")

        d.inject_pad(0, False)
        time.sleep(0.1)
        d.change_bank(False)
    finally:
        _drop_preset(d, "T_PADCH")


@test("pad-channel-live-vs-loop",
      "Pad channel mapping is loop-scoped: live presses use the global channel, "
      "the pad's loop (playback + stop-path offs) uses the mapping")
def t_pad_channel_live_vs_loop(ctx):
    """Contract: a live pad press ALWAYS goes out on the global output channel,
    whatever midi_channel_pad_mapping says for that pad. The mapping applies only
    to the loop STORED on the pad — its playback, its stop note-offs, CC snapback
    and the arp reading it. Pinned: pad 3 mapped to ch 5 still plays live on ch
    0; a pad-3 press recorded into pad 0's loop plays back per pad 0's mapping
    (as-recorded = the global channel at record time, then a fixed ch 9), and the
    STOP-path note-off follows the same resolution. Before the fix the stop-path
    off was resolved through the PLAYED pad's mapping (pad 3 -> ch 5) instead of
    the loop's own pad, so the note rang on ch 9 while a stray off went to ch 5."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.set_play_mode("loop")
    d.set_menu(MENU_PLAY)
    d.clear_all()
    d.drain_midi()
    glob = d.state().get("channel_out")
    ctx.check(glob == 0, f"baseline global out channel is 0 (got {glob})")

    everything = Counter()  # every key seen, for the final "nothing on ch 5" check

    def grab(seconds):
        got = summarize(d.capture(seconds))
        everything.update(got)
        return got

    def count(got, kind, note, ch):
        return sum(v for k, v in got.items() if k[0] == kind and k[1] == note and k[-1] == ch)

    try:
        d.set_pad_channel(3, 5)   # the pad that gets PRESSED
        d.set_pad_channel(0, -1)  # the pad whose LOOP plays it back: as-recorded

        # Live press/release: global channel, never the pressed pad's mapping
        d.inject_pad(3, True)
        got = grab(0.3)
        ons = [k for k in got if k[0] == "on"]
        ctx.check(len(ons) == 1, f"live press sent exactly one note-on (got {ons})")
        note = ons[0][1]
        ctx.check(ons[0][3] == 0,
                  f"live note-on on the global ch 0, not mapped ch 5 (got ch {ons[0][3]})")
        d.inject_pad(3, False)
        got = grab(0.3)
        ctx.check(count(got, "off", note, 0) >= 1,
                  f"live release sent note {note} off on ch 0 (saw {sorted(got)})")

        # Record that press into pad 0's loop: on at ~0.1 s, held ~0.5 s of a ~0.7 s
        # loop, so it is still sounding when the loop is stopped ~0.3 s in below.
        d.record(0)
        time.sleep(0.1)
        d.inject_pad(3, True)
        time.sleep(0.5)
        d.inject_pad(3, False)
        time.sleep(0.1)
        d.drain_midi()
        d.stop_record()  # playback starts (sync off)
        got = grab(0.3)
        ctx.check(count(got, "on", note, 0) >= 1,
                  f"loop playback (pad 0 as-recorded) on ch 0 (saw {sorted(got)})")
        d.stop(0)  # note sounding -> stop-path off
        got = grab(0.4)
        ctx.check(count(got, "off", note, 0) >= 1,
                  f"stop-path off on ch 0 (saw {sorted(got)})")

        # Fixed mapping on the LOOP's pad: playback AND the stop-path off move to 9
        d.set_pad_channel(0, 9)
        d.drain_midi()
        d.play(0)
        got = grab(0.3)
        ctx.check(count(got, "on", note, 9) >= 1,
                  f"loop playback on pad 0's mapped ch 9 (saw {sorted(got)})")
        d.stop(0)
        got = grab(0.4)
        ctx.check(count(got, "off", note, 9) >= 1,
                  f"stop-path off on ch 9 — resolved via the LOOP's pad, not the played "
                  f"pad's ch 5 (saw {sorted(got)})")

        ch5 = sorted(k for k in everything if k[0] in ("on", "off") and k[-1] == 5)
        ctx.check(not ch5, f"no note-on/off ever went to pad 3's mapping ch 5 (saw {ch5})")
    finally:
        d.set_pad_channel(3, -1)
        d.set_pad_channel(0, -1)
        d.clear_all()


@test("cc-loop-channel-mapping",
      "Loop CC playback resolves the pad's channel mapping, not the recorded channel (#269)")
def t_cc_loop_channel_mapping(ctx):
    """#269: notes and aftertouch resolve get_midi_channel_for_pad at playback; CCs went
    out on the raw recorded channel — record a filter sweep from a ch-1 controller onto a
    pad mapped to ch 10 and the notes moved but the sweep hit the wrong synth."""
    d = ctx.device
    base = json.loads(PRESETS_FILE.read_text())[BASELINE_PRESET]
    mapping = [-1] * 16
    mapping[0] = 9
    d.upload_preset("T_CCCH", dict(base, midi_channel_pad_mapping=mapping))
    try:
        d.load_preset("T_CCCH")
        d.clear_all()
        d.set_loop_type("loop")
        d.drain_midi()

        d.record(0)
        d.send(note_on(60, 100, 1), pause=0.1)
        d.send(cc(74, 40, 1), pause=0.1)
        d.send(cc(74, 90, 1), pause=0.1)
        d.send(note_off(60, 1), pause=0.1)
        d.stop_record()
        d.drain_midi()

        got = summarize(d.capture(1.2))
        cc74 = {k: v for k, v in got.items() if k[0] == "cc" and k[1] == 74}
        ctx.check(any(k[3] == 9 for k in cc74),
                  f"CC74 played on mapped ch 9 (saw {sorted(cc74)})")
        ctx.check(not any(k[3] == 1 for k in cc74),
                  f"no CC74 leaked on recorded ch 1 (saw {sorted(cc74)})")
        ctx.check(any(k == ("on", 60, 100, 9) for k in got),
                  "note also on mapped ch 9 (sanity)")
        d.stop_all()
    finally:
        _drop_preset(d, "T_CCCH")


@test("sustain-release-on-stop",
      "Stopping a loop that recorded a pedal-down sends CC64=0; loops without CC64 don't")
def t_sustain_release_on_stop(ctx):
    """Damper-held notes ignore Note Off and CC123 until the pedal lifts, so a stopped
    loop with a recorded CC64=127 left the synth's sustain latched forever. Release is
    scoped to loops that recorded a pedal-down — a plain loop must NOT emit CC64=0 and
    stomp the player's own pedal."""
    d = ctx.device
    d.set_midi_sync(False)
    d.clear_all()
    d.set_loop_type("loop")
    d.drain_midi()

    # Loop A (pad 0): note + pedal down, no release recorded.
    d.record(0)
    d.send(note_on(62, 90, 2), pause=0.1)
    d.send(cc(64, 127, 2), pause=0.1)
    d.send(note_off(62, 2), pause=0.1)
    d.stop_record()
    time.sleep(0.2)
    d.drain_midi()
    d.stop(0)
    got = summarize(d.capture(0.5))
    ctx.check(got[("cc", 64, 0, 2)] >= 1,
              f"stop sent CC64=0 on the loop's channel (saw {sorted(got)})")

    # Loop B (pad 1): no CC64 recorded -> stop must not touch the pedal.
    d.record(1)
    d.send(note_on(64, 90, 3), pause=0.1)
    d.send(note_off(64, 3), pause=0.1)
    d.stop_record()
    time.sleep(0.2)
    d.drain_midi()
    d.stop(1)
    got = summarize(d.capture(0.5))
    ctx.check(not any(k[0] == "cc" and k[1] == 64 for k in got),
              f"no-pedal loop stop sent no CC64 (saw {sorted(got)})")
    d.clear_all()


@test("record-unmatched-off-parity",
      "An unmatched note-off can't balance the count and skip note-off synthesis")
def t_record_unmatched_off_parity(ctx):
    """_ensure_all_notes_have_offs used size equality as pairing: a key held before
    record and released mid-take (off with no on) equalized on/off counts while the
    held note had no off — a permanent stuck note baked into the loop file. The
    unmatched off must land AFTER the first note-on: leading offs are already
    stripped by _remove_leading_off_notes, which masked the bug for that order."""
    d = ctx.device
    d.set_midi_sync(False)
    d.clear_all()
    d.set_loop_type("loop")
    d.drain_midi()

    d.record(2)
    d.send(note_on(60, 90, 5), pause=0.15)
    d.send(note_off(76, 5), pause=0.1)   # E released mid-take; its on predates the record
    d.stop_record()                        # C4 still held — no off sent
    time.sleep(0.2)
    st = d.state()
    lp = next((l for l in st["loops"] if l["pad"] == 2), None)
    ctx.check(lp is not None, "loop recorded on pad 2")
    if lp:
        ctx.check(lp["notes_on"] == 1, f"one note-on stored (got {lp['notes_on']})")
        ctx.check(lp["notes_off"] == 2,
                  f"off synthesized for the held note despite equal counts (offs={lp['notes_off']})")
    d.send(note_off(60, 5))  # release the physically-held key
    d.stop_all()
    d.clear_all()


@test("loop-mode-change-during-record",
      "Pad-held+encoder loop-mode gesture is refused while that pad is recording")
def t_loop_mode_change_during_record(ctx):
    """change_loop_mode reset() the recording pad: start_timestamp zeroed, next event
    finalized the take at full-uptime length — minutes of silence, a loop that never
    ends. The gesture must be refused for the recording pad and recording continue."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_play_mode("loop")
    d.clear_all()
    d.set_loop_type("loop")
    d.drain_midi()

    d.record(3)
    d.send(note_on(65, 90, 0), pause=0.1)
    d.send(note_off(65, 0), pause=0.1)
    ctx.check(d.state()["recording"] is True, "recording rolling")

    d.inject_pad(3, True)      # hold the recording pad...
    time.sleep(0.5)            # ...past the 350 ms hold threshold
    d.inject_encoder(1)        # ...and turn: the loop-mode gesture
    time.sleep(0.2)
    d.inject_pad(3, False)
    st = d.state()
    ctx.check(st["recording"] is True, "gesture did not kill the recording")

    d.send(note_on(67, 90, 0), pause=0.1)
    d.send(note_off(67, 0), pause=0.1)
    d.stop_record()
    time.sleep(0.2)
    st = d.state()
    lp = next((l for l in st["loops"] if l["pad"] == 3), None)
    ctx.check(lp is not None, "loop finalized on pad 3")
    if lp:
        ctx.check(lp["type"] == "loop", f"loop type unchanged (got {lp['type']})")
        ctx.check(0 < lp["total_ticks"] < 2000,
                  f"take length sane, not uptime-length (ticks={lp['total_ticks']})")
    d.clear_all()


@test("save-under-clock-recovery",
      "Preset save mid-clock-stream: counting recovers exactly once the save returns")
def t_save_under_clock(ctx):
    """A flash save blocks the main loop for seconds while clock keeps arriving —
    some tick loss is physically possible (RX FIFO limits). The guarantee worth
    pinning: the device neither wedges nor miscounts AFTER the save; ticks lost
    during it are logged for the record (Q2/Q3 in HANDOFF track the deeper fix)."""
    d = ctx.device
    base = json.loads(PRESETS_FILE.read_text())["T_SYNC"]
    d.upload_preset("T_SAVECLK", dict(base, midi_transport="off"))
    d.load_preset("T_SAVECLK")
    d.drain_midi()
    d.start_clock(bpm=120)  # threaded, free-running, no Start needed
    time.sleep(0.5)
    before = d.state()["clock_ticks"]
    ctx.check(before > 0, f"following the threaded clock (ticks={before})")

    d.save_preset("T_SAVECLK")  # blocks the device main loop while clock streams
    d.stop_clock()
    time.sleep(0.3)
    c0 = d.state()["clock_ticks"]
    ctx.log(f"ticks before save: {before}; after save+stop: {c0} (loss during save is logged, not judged)")

    for _ in range(10):
        d.send(mido.Message("clock"))
    time.sleep(0.15)
    st = d.state()
    ctx.check(st["clock_playing"] is True, "still following after the save")
    ctx.check(st["clock_ticks"] == c0 + 10,
              f"exact counting resumes post-save (got {st['clock_ticks']}, want {c0 + 10})")

    d.load_preset(BASELINE_PRESET)
    d.delete_preset("T_SAVECLK")


@test("pixels-loop-state-machine",
      "Pad LEDs track empty/record/armed/play/queue/stop transitions (hotspot #4)")
def t_pixels_state_machine(ctx):
    """First automated coverage of the LED state machine — the 4th-densest bug
    cluster (~14 issues, recurring theme: states not restored after stop/mode
    switch/external events). TEST_PIXELS dumps the LOGICAL pixel state (shadow
    color + blink flag/color) plus the palette constants, so nothing is
    hardcoded. Solid states assert the shadow color; blinking states assert the
    flag + blink color (the shadow alternates with the global blink phase)."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()
    time.sleep(0.2)

    px = d.pixels_state()
    pal = px["palette"]
    dark = [i for i, p in enumerate(px["pads"]) if p["c"] != pal["black"] or p["blink"]]
    ctx.check(not dark, f"all cleared pads dark (lit: {dark})")

    d.record(0)  # sync off -> records immediately
    time.sleep(0.15)
    px = d.pixels_state()
    p0 = px["pads"][0]
    ctx.check(p0["c"] == pal["recording"] and not p0["blink"],
              f"recording pad solid red (c={p0['c']} blink={p0['blink']})")

    d.send(note_on(60, 100, 0), pause=0.12)
    d.send(note_off(60, 0), pause=0.1)
    d.stop_record()  # playback starts
    # The loop's own note-on paints the pad orange for ~120 ms every cycle and the cycle
    # is only ~250 ms, so a single sample can legitimately land on the note (seen 2026-09-14
    # on stock firmware: c=C88100). Poll across a cycle: the pad must show the playing color
    # between notes and never blink.
    seen = []
    for _ in range(10):
        time.sleep(0.05)
        p0 = d.pixels_state()["pads"][0]
        seen.append((p0["c"], p0["blink"]))
    ctx.check(any(c == pal["playing"] and not b for c, b in seen) and not any(b for _, b in seen),
              f"playing pad shows solid playing-color between notes (saw {sorted(set(seen))})")

    d.stop(0)
    time.sleep(0.15)
    px = d.pixels_state()
    p0 = px["pads"][0]
    ctx.check(p0["c"] == pal["loop"] and not p0["blink"],
              f"stopped loop shows the has-loop color (c={p0['c']})")

    # Queued under sync: pad must BLINK the playing color while the clock is stopped
    d.set_midi_sync(True)
    d.toggle(0)
    time.sleep(0.15)
    px = d.pixels_state()
    p0 = px["pads"][0]
    ctx.check(p0["blink"] and p0["bc"] == pal["playing"],
              f"queued pad blinks the playing color (blink={p0['blink']} bc={p0['bc']})")

    # Armed recording (sync on, no clock): blinking red
    d.record(1)
    time.sleep(0.15)
    px = d.pixels_state()
    p1 = px["pads"][1]
    ctx.check(p1["blink"] and p1["bc"] == pal["recording"],
              f"armed recording pad blinks red (blink={p1['blink']} bc={p1['bc']})")
    d.stop_record()  # empty armed take -> removed

    d.set_midi_sync(False)  # dequeues pad 0
    time.sleep(0.25)
    px = d.pixels_state()
    p0, p1 = px["pads"][0], px["pads"][1]
    ctx.check(not p0["blink"] and p0["c"] == pal["loop"],
              f"sync-off restored pad 0 to the has-loop color (c={p0['c']})")
    ctx.check(p1["c"] == pal["black"] and not p1["blink"],
              "removed armed take left pad 1 dark")

    d.clear_all()
    time.sleep(0.25)
    px = d.pixels_state()
    lit = [i for i, p in enumerate(px["pads"]) if p["c"] != pal["black"] or p["blink"]]
    ctx.check(not lit, f"clear-all returned every pad to dark (lit: {lit})")


@test("pedal-pixels-loop-state",
      "Pedal LEDs render loop state only: empty/record/armed/play/queue/stop/delete + bank, never note activity")
def t_pedal_pixels_loop_state(ctx):
    """2026-09-14: pedal NeoPixels stopped mirroring the pad strip 1:1 (orange note
    flashes and blue CC flashes were distracting on the floor). They are now derived
    from loop state, polled every 20 ms (Pedals::refresh_from_loop_state). TEST_PIXELS
    reports the STATE ENUM each pedal LED was last rendered from, so this asserts the
    filter, not colors. Also pins the pre-change bug where deleting a loop left the
    pedal purple (the remove path's set_blink(false) never forwarded to the pedals)."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()
    time.sleep(0.2)

    def pedal(pad, settle=0.1):
        time.sleep(settle)  # >= one 20 ms poll
        ped = d.pixels_state()["pedals"]
        for p in ped["pads"]:
            if p["pad"] == pad:
                return p["state"]
        return f"<pad {pad} not in bank {ped['bank']}>"

    try:
        ctx.check(all(pedal(i, 0) == "none" for i in range(5)), "cleared: all 5 pedals 'none'")

        d.record(0)  # sync off -> records immediately
        ctx.check(pedal(0) == "recording", f"recording pad -> pedal 'recording' (got {pedal(0, 0)})")
        d.send(note_on(60, 100, 0), pause=0.12)
        d.send(note_off(60, 0), pause=0.1)
        d.send(cc(1, 64, 0), pause=0.1)  # a CC in the loop = blue pad flash every cycle
        d.stop_record()  # playback starts
        ctx.check(pedal(0) == "playing", f"playing loop -> pedal 'playing' (got {pedal(0, 0)})")

        # Filter: the loop's own note + CC playback flashes pad 0, the pedal must not budge.
        seen = set()
        for _ in range(8):
            seen.add(pedal(0, 0.05))
        ctx.check(seen == {"playing"}, f"pedal held 'playing' across playback activity (saw {sorted(seen)})")

        # Filter: a LIVE press on an empty pad lights the pad orange; its pedal stays 'none'.
        d.inject_pad(3, True)
        time.sleep(0.1)
        px = d.pixels_state()
        p3 = px["pads"][3]
        ctx.check(p3["c"] != px["palette"]["black"], f"held empty pad 3 lit on the pad strip (c={p3['c']})")
        ctx.check(pedal(3, 0) == "none", f"held empty pad 3 leaves pedal 3 'none' (got {pedal(3, 0)})")
        d.inject_pad(3, False)
        time.sleep(0.1)

        d.stop(0)
        ctx.check(pedal(0) == "loop", f"stopped loop -> pedal 'loop' (got {pedal(0, 0)})")

        d.set_midi_sync(True)
        d.toggle(0)  # queued: clock stopped
        ctx.check(pedal(0) == "queued", f"queued loop -> pedal 'queued' (got {pedal(0, 0)})")
        d.record(1)  # armed: sync on, no clock
        ctx.check(pedal(1) == "armed", f"armed record -> pedal 'armed' (got {pedal(1, 0)})")
        d.stop_record()  # empty armed take -> removed
        ctx.check(pedal(1) == "none", f"removed armed take -> pedal 'none' (got {pedal(1, 0)})")
        d.set_midi_sync(False)  # dequeues pad 0
        ctx.check(pedal(0) == "loop", f"sync-off dequeue -> pedal 'loop' (got {pedal(0, 0)})")

        # Delete bug: the pedal must clear with the pad (used to stay purple).
        d.clear(0)
        ctx.check(pedal(0) == "none", f"deleted loop -> pedal 'none' (got {pedal(0, 0)})")

        # Bank switch: bank 1 = pads 5-9, pedal 0 mirrors pad 5.
        d.record(5)
        d.send(note_on(62, 100, 0), pause=0.1)
        d.send(note_off(62, 0), pause=0.1)
        d.stop_record()
        d.stop(5)
        d.cmd("TEST_PEDAL_BANK|1")
        time.sleep(0.1)
        ped = d.pixels_state()["pedals"]
        ctx.check(ped["bank"] == 1 and ped["pads"][0]["pad"] == 5,
                  f"bank 1 maps pedal 0 to pad 5 (bank={ped['bank']} pad={ped['pads'][0]['pad']})")
        ctx.check(ped["pads"][0]["state"] == "loop", f"pedal 0 shows pad 5's loop (got {ped['pads'][0]['state']})")
        d.cmd("TEST_PEDAL_BANK|0")
        ctx.check(pedal(0) == "none" and pedal(4, 0) == "none", "back on bank 0: pads 0-4 empty again")
    finally:
        d.cmd("TEST_PEDAL_BANK|0")
        d.set_midi_sync(False)
        d.clear_all()


@test("din-clock-customer-config",
      "DIN clock drives sync in the exact as-shipped config (MIDI Type ALL + Clock Source USB)")
def t_din_clock_customer(ctx):
    """The Aug 2026 RMA scenario on the REAL port, no USB mirror: clock arrives
    only on DIN while clock_source prefers USB. TEST_DIN feeds bytes through the
    genuine UART running-status parser as source 'AUX', so should_accept_clock's
    tiebreaker branch is exercised where the customer hit it. clock-source-matrix
    keeps the USB-mirrored combos; this is the end-to-end DIN leg #275 flagged."""
    d = ctx.device
    d.clear_all()
    d.set_midi_sync(True)
    d.set_midi_cfg("ALL", "USB")  # baseline values, restated for standalone runs
    d.drain_midi()
    try:
        d.inject_din([0xFA] + [0xF8] * 10)  # DIN Start + 10 clocks
        time.sleep(0.25)
        st = d.state()
        ctx.check(st["clock_playing"] is True, "DIN Start started the transport")
        ctx.check(st["clock_ticks"] == 9,
                  f"DIN clock accepted despite Clock Source USB: 10 clocks -> 9 "
                  f"(got {st['clock_ticks']} — 0 = the RMA bug)")

        d.inject_din([0xF8] * 24)  # sustained exact count
        time.sleep(0.25)
        st = d.state()
        ctx.check(st["clock_ticks"] == 33, f"exact DIN count continues (got {st['clock_ticks']})")

        d.inject_din([0xFC])  # DIN Stop
        time.sleep(0.2)
        ctx.check(d.state()["clock_playing"] is False, "DIN Stop honored")
    finally:
        d.set_midi_cfg("ALL", "USB")
        d.set_midi_sync(False)
        d.drain_midi()


@test("din-running-status",
      "DIN running-status stream with interleaved realtime bytes records the right events")
def t_din_running_status(ctx):
    """First coverage of the UART running-status parser itself: one status byte,
    running-status data pairs, a 0xF8 interleaved MID-message (realtime may split
    any message), and a stray data byte with no status (must be dropped). The
    recorded loop proves the parse: 2 note-ons + 2 note-offs on channel 2."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.set_midi_cfg("ALL", "USB")
    d.drain_midi()
    try:
        d.record(2)
        time.sleep(0.1)
        # F3: system common resets any running status left by earlier tests.
        # 3C: stray data byte, no status -> dropped.
        # 92 3C 64: note-on ch2 n60 v100.  3E F8 5A: running-status note-on n62 v90
        # with a realtime clock byte INSIDE the message.  82 3C 00 3E 00: note-offs
        # via running status on the off status byte.
        d.inject_din([0xF3, 0x3C,
                      0x92, 0x3C, 0x64,
                      0x3E, 0xF8, 0x5A,
                      0x82, 0x3C, 0x00, 0x3E, 0x00])
        time.sleep(0.3)
        st = d.state()
        lp = next((l for l in st["loops"] if l["pad"] == 2), None)
        ctx.check(lp is not None and lp["notes_on"] == 2,
                  f"2 note-ons parsed from the running-status stream "
                  f"(got {lp['notes_on'] if lp else 0})")
        ctx.check(lp is not None and lp["notes_off"] == 2,
                  f"2 note-offs parsed (got {lp['notes_off'] if lp else 0})")
        d.stop_record()
        d.stop_all()

        d.drain_midi()
        d.play(2)
        got = summarize(d.capture(1.2))
        d.stop(2)
        ctx.check(got[("on", 60, 100, 2)] >= 1, "n60 v100 on ch 2 (channel survived the parse)")
        ctx.check(got[("on", 62, 90, 2)] >= 1,
                  "n62 v90 on ch 2 (message split by the realtime byte reassembled)")
    finally:
        d.set_midi_cfg("ALL", "USB")
        d.clear_all()


@test("din-clock-tiebreaker",
      "Fresh USB clock keeps ownership: DIN ticks yield instead of double-counting")
def t_din_clock_tiebreaker(ctx):
    """The dual-clock half of the should_accept_clock fix, previously unreachable:
    #272 notes that with USB-only injection `_last_clock_seen_aux` is always 0, so
    inverting the tiebreaker still passed the whole suite. With ticks on BOTH ports
    the preferred (USB) source must own the count while it is fresh (<1 s hold) —
    a regression to accept-everything shows up as a double-counted grid.
    Deliberately NOT asserted: the >1 s mid-roll takeover — #272 tracks changing
    that behavior (foreign-tick injection into a live grid)."""
    d = ctx.device
    d.clear_all()
    d.set_midi_sync(True)
    d.set_midi_cfg("ALL", "USB")
    d.drain_midi()
    try:
        d.send(mido.Message("start"))
        for _ in range(10):
            d.send(mido.Message("clock"))
        time.sleep(0.2)
        c0 = d.state()["clock_ticks"]
        ctx.check(c0 == 9, f"USB clock established (10 clocks -> 9, got {c0})")

        d.inject_din([0xF8] * 8)  # foreign DIN ticks while USB is fresh
        time.sleep(0.2)
        st = d.state()
        ctx.check(st["clock_ticks"] == c0,
                  f"DIN ticks yielded to the fresh preferred USB clock "
                  f"(got {st['clock_ticks']}, want {c0})")

        for _ in range(5):
            d.send(mido.Message("clock"))
        time.sleep(0.2)
        st = d.state()
        ctx.check(st["clock_ticks"] == c0 + 5,
                  f"USB ticks still counted after the DIN burst (got {st['clock_ticks']})")
        d.send(mido.Message("stop"))
        time.sleep(0.1)
    finally:
        d.set_midi_cfg("ALL", "USB")
        d.set_midi_sync(False)
        d.drain_midi()


@test("multiloop-simultaneous-playback",
      "Two loops playing at once: independent streams, per-loop CC channels via one coalesce map")
def t_multiloop_playback(ctx):
    """Nothing else ever PLAYS two loops simultaneously — the core use case of a
    looper. Two loops of different lengths run together: both note streams must
    interleave cleanly on their resolved channels, and — the coalescing-map
    collision cc-loop-channel-mapping can't reach with one loop — the SAME CC#
    from both loops must reach BOTH resolved channels (#269: the coalesce key is
    (cc#, resolved channel); the pre-fix key collapsed them into one send).

    Also pins the any_loop_playing finalize bug this test caught on first run:
    the sync-off record-finalize autoplay never set the flag, so stop_all_loops
    early-outed as a no-op on every loop born from a finalize — loops kept
    playing (and their first-wrap CC sends landed pre-capture, where the CC
    value-dedup then hid them forever)."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    # Loop A (pad 0, ~0.8 s): note 60 + CC74=10, recorded from a ch-0 controller
    d.record(0)
    time.sleep(0.1)
    d.send(note_on(60, 100, 0), pause=0.12)
    d.send(note_off(60, 0), pause=0.08)
    d.send(cc(74, 10, 0), pause=0.05)
    time.sleep(0.45)
    d.stop_record()
    d.stop_all()
    # Loop B (pad 5, ~1.3 s): note 64 + the SAME CC74, also recorded on ch 0
    d.record(5)
    time.sleep(0.1)
    d.send(note_on(64, 90, 0), pause=0.12)
    d.send(note_off(64, 0), pause=0.08)
    d.send(cc(74, 99, 0), pause=0.05)
    time.sleep(0.95)
    d.stop_record()
    d.stop_all()

    st = d.state()
    ctx.check(st["any_playing"] is False,
              "stop_all stopped the finalize-autoplay loops (any_loop_playing upkeep)")

    d.set_pad_channel(5, 9)  # loop B's pad resolves to ch 9; loop A stays as-recorded
    try:
        d.drain_midi()
        d.play(0)
        d.play(5)
        captured = d.capture(4.0)
        d.stop_all()
        got = summarize(captured)

        ctx.check(got[("on", 60, 100, 0)] >= 2, "loop A looping on its recorded ch 0")
        ctx.check(got[("on", 64, 90, 9)] >= 2, "loop B looping on its MAPPED ch 9")
        ctx.check(got[("on", 64, 90, 0)] == 0, "no loop-B crosstalk onto ch 0")
        ctx.check(got[("cc", 74, 10, 0)] >= 1, "loop A's CC74 on ch 0")
        ctx.check(got[("cc", 74, 99, 9)] >= 1,
                  "loop B's CC74 reaches ch 9 — same CC# coalesced per resolved "
                  "channel, not collapsed (#269)")

        ons = {(k[1], k[3]) for k in got if k[0] == "on"}
        offs = {(k[1], k[2]) for k in got if k[0] == "off"}
        ctx.check(not (ons - offs),
                  f"every sounded (note, ch) got an off (stuck: {sorted(ons - offs)})")
        d.drain_midi()
        stray = [k for k in summarize(d.capture(0.6)) if k[0] == "on"]
        ctx.check(not stray, f"silence after stop_all (got {stray})")
    finally:
        d.set_pad_channel(5, -1)  # back to as-recorded
    d.clear_all()


@test("weblock-seize-and-autounlock",
      "PING seizes cleanly (stop + all-notes-off, inputs inert) and 6 s of silence auto-unlocks",
      tags=("auto", "slow"))
def t_weblock_lifecycle(ctx):
    """The web-lock lifecycle beyond ping-identity's ack fields. Entry: loops
    stop, CC123 goes out on ALL 16 channels, and pads/MIDI are dead while locked
    (loop() early-returns). Exit: with no PINGs for PING_TIMEOUT_MS (6 s) the
    device must free itself — a stuck lock is a customer-visible brick-until-
    power-cycle. Pad events injected while locked queue up and fire AT unlock,
    which doubles as the timing probe for when processing resumed."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    d.record(0)
    time.sleep(0.1)
    d.send(note_on(60, 100, 0), pause=0.3)
    d.send(note_off(60, 0), pause=0.1)
    d.stop_record()  # loop playing
    time.sleep(0.3)
    d.drain_midi()
    try:
        d.cmd("PING")  # seize
        got = summarize(d.capture(0.8))
        cc123_chans = {k[3] for k in got if k[0] == "cc" and k[1] == 123}
        ctx.check(len(cc123_chans) == 16,
                  f"seize sent All-Notes-Off on all 16 channels (got {len(cc123_chans)})")
        st = d.state()  # TEST_STATE is still served while locked
        ctx.check(st.get("web_locked") is True, "state reports the web lock")
        ctx.check(st["any_playing"] is False and st["recording"] is False,
                  "loops stopped by the seize")
        lp = next((l for l in st["loops"] if l["pad"] == 0), None)
        ctx.check(lp is not None and not lp["queued"],
                  "nothing left queued to ghost-resume after the session")

        # While locked: pad + MIDI input must be inert (events queue, nothing plays)
        d.inject_pad(1, True)
        d.inject_pad(1, False)
        d.send(note_on(72, 90, 0))
        d.send(note_off(72, 0))
        quiet = [k for k in summarize(d.capture(1.0)) if k[0] == "on"]
        ctx.check(not quiet, f"no note processing while locked (got {quiet})")

        # Auto-unlock: re-PING for a known deadline, then stay silent. The pad
        # press queued above fires the moment input processing resumes.
        d.cmd("PING")
        captured = d.capture(8.0)
        ons = [t for t, m in captured if m.type == "note_on" and m.velocity > 0]
        ctx.check(bool(ons), "queued pad press played once the lock expired")
        if ons:
            ctx.log(f"input processing resumed {ons[0]:.1f}s after the last PING")
            ctx.check(4.0 < ons[0] < 8.0,
                      f"resume happened at the ~6 s timeout, not while locked ({ons[0]:.1f}s)")
        st = d.state()
        ctx.check(st.get("web_locked") is False, "lock reports released")
        ctx.check(st["pressed"] == 0, "pressed_count reconciled after the queued events")
    finally:
        try:
            d.cmd("DISCONNECT")  # harmless if already unlocked
        except DeviceError:
            pass
    d.clear_all()


@test("sync-stop-mid-recording",
      "MIDI Stop mid-recording finalizes the take; Stop while merely armed keeps it armed")
def t_sync_stop_mid_recording(ctx):
    """transport-restart-mid-recording covers a Start landing mid-take; the Stop
    twin was uncovered although stop/start semantics are hotspot #1's recurring
    theme. Contract (main.cpp transport_stop block): an ACTIVE recording is
    finalized into a loop via the same FN path, everything stops cleanly; an
    ARMED recording (clock never started) must survive the Stop untouched —
    the !armed guard exists so a stray Stop can't eat an armed take."""
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
    d.send(note_off(60, 0), pause=0.4)
    st = d.state()
    ctx.check(st["recording"] is True and st["armed"] is False,
              "actively recording under the rolling clock")

    d.stop_clock(send_stop=True)  # Stop lands mid-take; no stop_record was sent
    time.sleep(0.4)
    st = d.state()
    ctx.check(st["recording"] is False, "Stop finalized the active recording")
    lp = next((l for l in st["loops"] if l["pad"] == 0), None)
    ctx.check(lp is not None and lp["notes_on"] >= 1,
              f"take survived as a loop with its events "
              f"(notes_on={lp['notes_on'] if lp else 0})")
    d.drain_midi()
    quiet = [k for k in summarize(d.capture(1.0)) if k[0] == "on"]
    ctx.check(not quiet, f"nothing playing/ringing after the mid-take Stop (got {quiet})")

    # Armed branch: clock stopped -> a new recording arms; Stop must NOT eat it
    d.record(1)
    ctx.check(d.state()["armed"] is True, "second recording armed (clock stopped)")
    d.send(mido.Message("stop"))
    time.sleep(0.3)
    st = d.state()
    ctx.check(st["recording"] is True and st["armed"] is True,
              "Stop while merely armed left the armed recording in place")
    d.stop_record()  # empty armed take -> removed
    d.set_midi_sync(False)
    d.clear_all()


@test("din-passthru-usb-out",
      "AUX->USB passthru forwards DIN traffic on all channels, ahead of the channel filter")
def t_din_passthru(ctx):
    """First passthru coverage of any kind. Asserts the working core of the
    documented contract: passthru_mode='aux' forwards DIN channel traffic to USB
    out BEFORE the midi_channel_in filter (hardware-thru semantics), realtime
    Start is re-sent, and passthru off forwards nothing. Deliberately NOT
    asserted (#273, open): the unbounded consecutive-duplicate window, USB->AUX
    gating, and the AUX->AUX echo — distinct messages are used throughout so the
    dup filter never engages."""
    d = ctx.device
    d.set_midi_sync(False)
    d.clear_all()
    d.set_midi_cfg("ALL", "USB")
    d.set_passthru("aux")
    d.set_channel_in(2)  # recording filter; passthru must ignore it
    try:
        d.drain_midi()
        d.inject_din([0x95, 0x3C, 0x64])  # ch-5 note-on: filtered from recording…
        d.inject_din([0x85, 0x3C, 0x00])  # …but must pass through
        time.sleep(0.3)
        got = summarize(d.capture(0.5))
        ctx.check(got[("on", 60, 100, 5)] >= 1,
                  "DIN ch-5 note forwarded to USB out despite channel_in=2")
        ctx.check(got[("off", 60, 5)] >= 1, "its note-off forwarded too")

        d.drain_midi()
        d.inject_din([0xFA])  # realtime Start is re-sent, not just channel traffic
        time.sleep(0.25)
        rt = [m.type for _, m in d.capture(0.4, ignore_realtime=False)
              if m.type in ("start", "stop")]
        ctx.check("start" in rt, f"DIN Start forwarded as realtime (saw {rt})")
        d.inject_din([0xFC])  # matching Stop: clean transport + forward path both ways
        time.sleep(0.2)

        d.set_passthru("off")
        d.drain_midi()
        d.inject_din([0x95, 0x3E, 0x64])
        d.inject_din([0x85, 0x3E, 0x00])
        time.sleep(0.3)
        leak = [k for k in summarize(d.capture(0.4)) if k[0] in ("on", "off")]
        ctx.check(not leak, f"passthru off forwards nothing (got {leak})")
    finally:
        d.set_passthru("off")
        d.set_channel_in(-1)
        d.set_midi_cfg("ALL", "USB")
        d.drain_midi()


@test("channel-in-filter",
      "midi_channel_in records only its channel; realtime/transport bypass the filter")
def t_channel_in_filter(ctx):
    """The RX channel filter (_should_accept_channel) had zero coverage — the
    baseline always runs -1/ALL. With channel_in=3: notes on other channels must
    not record, while clock/transport (status >= 0xF0) pass untouched."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.set_channel_in(3)
    try:
        d.drain_midi()
        d.record(0)
        time.sleep(0.1)
        d.send(note_on(60, 100, 3), pause=0.12)  # accepted
        d.send(note_off(60, 3), pause=0.08)
        d.send(note_on(64, 100, 7), pause=0.12)  # filtered
        d.send(note_off(64, 7), pause=0.08)
        st = d.state()
        lp = next((l for l in st["loops"] if l["pad"] == 0), None)
        ctx.check(lp is not None and lp["notes_on"] == 1,
                  f"only the ch-3 note recorded (got {lp['notes_on'] if lp else 0})")
        d.stop_record()
        d.stop_all()
        d.clear_all()

        # Transport/clock are non-channel messages — the filter must not touch them
        d.set_midi_sync(True)
        d.send(mido.Message("start"))
        for _ in range(10):
            d.send(mido.Message("clock"))
        time.sleep(0.2)
        st = d.state()
        ctx.check(st["clock_ticks"] == 9,
                  f"clock counted normally under a channel filter (got {st['clock_ticks']})")
        d.send(mido.Message("stop"))
        time.sleep(0.1)
    finally:
        d.set_channel_in(-1)
        d.set_midi_sync(False)
    d.clear_all()


@test("record-cc-toggle",
      "record_cc=false keeps CCs out of the take (notes/AT still in); re-enable records again")
def t_record_cc_toggle(ctx):
    """The baseline pins record_cc=true and asserts the flag, never the off
    behavior. Off: CCs must not enter the recording while notes and aftertouch
    (always recorded by design) do. Back on: CCs record again — catches both a
    stuck gate and an inverted one."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    d.set_record_cc(False)
    try:
        d.record(0)
        time.sleep(0.1)
        d.send(note_on(60, 100, 0), pause=0.1)
        d.send(note_off(60, 0), pause=0.05)
        d.send(cc(74, 50, 0), pause=0.05)
        d.send(cc(1, 20, 0), pause=0.05)
        d.send(aftertouch(77, 0), pause=0.05)
        time.sleep(0.1)
        st = d.state()
        lp = next((l for l in st["loops"] if l["pad"] == 0), None)
        ctx.check(lp is not None and lp["notes_on"] == 1, "note recorded with the gate off")
        ctx.check(lp is not None and lp["ccs"] == 0,
                  f"no CCs recorded with record_cc off (got {lp['ccs'] if lp else 0})")
        ctx.check(lp is not None and lp["ats"] == 1,
                  f"aftertouch still recorded — its path is ungated (got {lp['ats'] if lp else 0})")
        d.stop_record()
        d.stop_all()
    finally:
        d.set_record_cc(True)

    d.record(1)
    time.sleep(0.1)
    d.send(cc(74, 60, 0), pause=0.08)
    time.sleep(0.15)
    st = d.state()
    lp = next((l for l in st["loops"] if l["pad"] == 1), None)
    ctx.check(lp is not None and lp["ccs"] == 1,
              f"CCs record again once re-enabled (got {lp['ccs'] if lp else 0})")
    d.stop_record()
    d.stop_all()
    d.clear_all()


@test("velocity-play-mode",
      "Velocity mode: one mapped note across all pads with the per-pad velocity ramp")
def t_velocity_play_mode(ctx):
    """Velocity play mode was only ever tested as a string normalization. The
    real behavior: FN+pad (TEST_VELOCITY_MODE delegates to the same handler)
    latches that pad's note as THE note; every pad then plays it at the fixed
    per-pad ramp velocity (8 for pad 0 … 127 for pad 15). Toggling off restores
    normal per-pad notes."""
    d = ctx.device
    d.set_midi_sync(False)
    d.clear_all()
    d.set_menu(MENU_PLAY)
    d.set_play_mode("velocity")
    try:
        rsp = d.toggle_velocity_map(4)
        ctx.check(rsp.get("velocity_mapped") is True, "velocity map engaged")
        d.drain_midi()
        d.inject_pad(0, True)
        time.sleep(0.15)
        d.inject_pad(0, False)
        time.sleep(0.15)
        d.inject_pad(15, True)
        time.sleep(0.15)
        d.inject_pad(15, False)
        time.sleep(0.25)
        captured = d.capture(0.5)
        ons = [m for _, m in captured if m.type == "note_on" and m.velocity > 0]
        ctx.check(len(ons) == 2, f"two pad presses -> two notes (got {len(ons)})")
        if len(ons) == 2:
            ctx.check(ons[0].note == ons[1].note,
                      f"both pads played the SAME mapped note ({ons[0].note}/{ons[1].note})")
            ctx.check([m.velocity for m in ons] == [8, 127],
                      f"velocity ramp applied: pad0=8, pad15=127 "
                      f"(got {[m.velocity for m in ons]})")
        offs = [m for _, m in captured
                if m.type == "note_off" or (m.type == "note_on" and m.velocity == 0)]
        ctx.check(len(offs) >= 2, f"both ramp notes released (got {len(offs)})")

        rsp = d.toggle_velocity_map(4)
        ctx.check(rsp.get("velocity_mapped") is False, "velocity map toggled back off")
        d.drain_midi()
        d.inject_pad(0, True)
        time.sleep(0.15)
        d.inject_pad(0, False)
        time.sleep(0.2)
        normal = [m for _, m in d.capture(0.4) if m.type == "note_on" and m.velocity > 0]
        ctx.check(bool(normal) and normal[0].velocity != 8,
                  f"normal per-pad velocity restored (got "
                  f"{normal[0].velocity if normal else 'none'})")
    finally:
        if ctx.device.state().get("velocity_mapped"):
            d.toggle_velocity_map(0)
        d.set_play_mode("loop")
    d.clear_all()


@test("preset-name-validation",
      "SET_PRESET/RENAME/SET_STARTUP enforce name rules; startup pointer follows a rename")
def t_preset_name_validation(ctx):
    """The firmware guards (NAME_MAX=10, reserved keys, A-Z/0-9/_ charset,
    case-insensitive rename collision) existed with zero tests — a silent
    regression would let the web UI corrupt presets.json root keys. Also the
    first exercise of SET_STARTUP, and of the rename-the-startup-preset path
    (the STARTUP_PRESET pointer must follow or boot strands on a missing name)."""
    d = ctx.device
    presets = json.loads(PRESETS_FILE.read_text())
    body = dict(presets[BASELINE_PRESET])
    body.pop("loops", None)
    payload = json.dumps(body, separators=(",", ":"))

    def expect_reject(what, fn):
        try:
            fn()
        except DeviceError as e:
            ctx.log(f"ok: {what} refused ({e})")
            return
        raise TestFailed(f"{what} was accepted")

    expect_reject("11-char preset name",
                  lambda: d.cmd(f"SET_PRESET|ELEVENCHARZZ|{payload}"))
    expect_reject("reserved name STARTUP_PRESET",
                  lambda: d.cmd(f"SET_PRESET|STARTUP_PRESET|{payload}"))
    expect_reject("reserved name next_loop_id",
                  lambda: d.cmd(f"SET_PRESET|next_loop_id|{payload}"))
    expect_reject("reserved name *NEW*",
                  lambda: d.cmd(f"SET_PRESET|*NEW*|{payload}"))
    expect_reject("bad charset (dash)",
                  lambda: d.cmd(f"SET_PRESET|BAD-NAME|{payload}"))
    expect_reject("SET_STARTUP on a missing preset",
                  lambda: d.cmd("SET_STARTUP|T_MISSING"))

    d.upload_preset("T_NVA", body)
    try:
        expect_reject("rename to a reserved key", lambda: d.rename_preset("T_NVA", "*NEW*"))
        expect_reject("rename to 11 chars", lambda: d.rename_preset("T_NVA", "ELEVENCHARZZ"))
        expect_reject("rename of a missing preset", lambda: d.rename_preset("T_GONE", "T_NVB"))
        expect_reject("case-insensitive collision",
                      lambda: d.rename_preset("T_NVA", BASELINE_PRESET.lower()))

        rsp = d.cmd("SET_STARTUP|T_NVA")
        ctx.check(rsp.get("status") == "ok", f"SET_STARTUP acked ({rsp})")
        ctx.check(d.cmd("GET_PRESET_NAMES").get("startup") == "T_NVA",
                  "startup pointer moved to T_NVA")
        d.rename_preset("T_NVA", "T_NVB")
        ctx.check(d.cmd("GET_PRESET_NAMES").get("startup") == "T_NVB",
                  "STARTUP_PRESET pointer followed the rename")
    finally:
        try:
            d.cmd(f"SET_STARTUP|{BASELINE_PRESET}")
        except DeviceError:
            pass
        for name in ("T_NVA", "T_NVB"):
            try:
                d.delete_preset(name)
            except DeviceError:
                pass
    names = d.preset_names()
    ctx.check("T_NVA" not in names and "T_NVB" not in names, "scratch presets cleaned up")
    ctx.check(d.cmd("GET_PRESET_NAMES").get("startup") == BASELINE_PRESET,
              "startup restored to the baseline preset")


@test("presets-raw-chunk",
      "GET_PRESETS_RAW_CHUNK streams the whole presets.json, consistent with GET_PRESET_NAMES")
def t_presets_raw_chunk(ctx):
    """The web UI's raw-backup command had zero coverage. Stream every chunk,
    parse the reassembled JSON, and cross-check it against GET_PRESET_NAMES:
    same presets, same startup pointer, reserved root keys present exactly once
    and the *NEW* sentinel never on disk."""
    d = ctx.device
    raw = b""
    offset = 0
    while True:
        rsp = d.cmd(f"GET_PRESETS_RAW_CHUNK|{offset}")
        data = base64.b64decode(rsp["data"])
        raw += data
        offset += len(data)
        if rsp.get("done") or not data:
            break
        if offset > 200_000:
            raise TestFailed(f"runaway raw stream ({offset} bytes and no done flag)")
    ctx.log(f"streamed {len(raw)} bytes of presets.json in {max(1, (offset + 511) // 512)} chunk(s)")
    doc = json.loads(raw.decode())

    names = set(d.preset_names())
    doc_names = {k for k in doc if k not in ("STARTUP_PRESET", "next_loop_id")}
    ctx.check(doc_names == names,
              f"raw doc's presets match GET_PRESET_NAMES (doc-only: {doc_names - names}, "
              f"names-only: {names - doc_names})")
    ctx.check("STARTUP_PRESET" in doc and "next_loop_id" in doc,
              "reserved root keys present in the raw doc")
    ctx.check(doc.get("STARTUP_PRESET") == d.cmd("GET_PRESET_NAMES").get("startup"),
              "startup pointer consistent between raw doc and names command")
    ctx.check("*NEW*" not in doc, "the *NEW* UI sentinel never lands on disk")


def _fixture_doc(name):
    """A corpus fixture minus its _comment key (the comment is for humans, never on flash)."""
    doc = json.loads((FIXTURES_DIR / name).read_text())
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def _fixture_presets(doc):
    return {k: v for k, v in doc.items() if k not in ("STARTUP_PRESET", "next_loop_id")}


@test("preset-compat-corpus",
      "presets.json written by OLDER firmware (v3.0, v2.4 Python) loads right and is never rewritten by a boot",
      tags=("auto", "slow"))
def t_preset_compat_corpus(ctx):
    """Guards the field: units arrive at a new firmware carrying whatever presets.json
    their OLD firmware wrote. Nothing exercised that — every test here uploads presets
    through THIS firmware's serializer. Two fixtures in scripts/fixtures/ are written to
    flash byte-exact (TEST_PRESETS_RAW) and the device rebooted onto them:

      presets_v3.0.json — the v3.0 key set (v3.1 minus midi_transport), a pad referencing
        a real loop file, a Python-era null pad-channel entry.
      presets_v2.4.json — the CircuitPython release file verbatim + one preset in the
        Python 'loops' shape with Python-only spellings (playmode, midi_passthru).

    Asserted per fixture: (1) the boot does NOT rewrite the file — byte-identical after
    the reboot (Derrick, 2026-09-14: updates must never touch customer presets unless
    the user saves); (2) missing keys land on their defaults and Python-only keys are
    ignored, with the expectations written down here so a semantic change is a
    deliberate edit to this table; (3) a referenced loop file loads (v3.0) and a dead
    Python loop id is skipped without a crash (v2.4); (4) a regressed root next_loop_id is
    reconciled up past the on-disk floor / referenced ids, and orphaned loop files are swept
    at boot (files only — never the presets file); (5) a user-driven load (startup change) rewrites the file but
    keeps every other preset intact; (6) the restore-from-backup path (SET_PRESET with a
    Python-era body) is accepted. Restored like preset-save-refuses-corrupt-file: wipe,
    fixtures, extras, startup pointer, reboot — whatever happens."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    fixtures = {k: v for k, v in json.loads(PRESETS_FILE.read_text()).items()
                if not k.startswith("_")}
    names_before = d.preset_names()
    ctx.log(f"presets before: {names_before}")
    extras = {}
    for name in names_before:
        if name not in fixtures:
            try:
                body = d.get_preset(name)
                body = body.get("preset", body)
                extras[name] = json.loads(body) if isinstance(body, str) else body
            except DeviceError as e:
                ctx.log(f"could not fetch leftover preset {name}: {e}")

    def state_full():
        return d.state(full=True)

    def loops_of(st):
        return {lp["pad"]: lp for lp in st.get("loops", [])}

    try:
        # ------------------------------------------------------------------
        # Leg 1: v3.0 presets.json + a referenced v2 loop file
        # ------------------------------------------------------------------
        v30 = _fixture_doc("presets_v3.0.json")
        loop_id = v30["V30_A"]["loops"]["0"]["loop_id"]
        loop_blob = sample_loop(pad=0)
        d.put_loop_file(loop_filename(loop_id), loop_blob)
        ctx.check(d.read_loop_file(loop_filename(loop_id)) == loop_blob,
                  f"seed loop file {loop_filename(loop_id)} installed byte-exact")
        # ArduinoJson writes compact JSON — that's what a v3.0 unit has on flash.
        v30_bytes = json.dumps(v30, separators=(",", ":")).encode()
        d.write_presets_raw(v30_bytes)
        ctx.check(d.read_presets_raw() == v30_bytes, "v3.0 file written byte-exact")

        ctx.instruct("Rebooting onto the v3.0 presets.json")
        d.reboot()
        after = d.read_presets_raw()
        ctx.check(after == v30_bytes,
                  f"boot did NOT rewrite the v3.0 presets.json ({len(after)} B vs {len(v30_bytes)} B)")
        names = d.cmd("GET_PRESET_NAMES")
        ctx.check(sorted(names.get("names", [])) == sorted(_fixture_presets(v30)),
                  f"v3.0 preset names listed ({names.get('names')})")
        ctx.check(names.get("startup") == v30["STARTUP_PRESET"],
                  f"startup pointer honoured ({names.get('startup')})")

        st = state_full()
        ctx.check(st.get("preset") == "V30_A", f"booted into V30_A (got {st.get('preset')!r})")
        # Expectation table — v3.0 file, keys present carry through, the one v3.1-only key
        # (midi_transport) is absent and must land on its settings.h default.
        expect_a = {"midi_transport": "on", "midi_sync": True, "clock_source": "AUX",
                    "passthru": "aux", "channel_in": 3, "channel_out": 5,
                    "midi_type": "ALL", "record_cc": True, "play_mode": "loop"}
        for k, v in expect_a.items():
            ctx.check(st.get(k) == v, f"V30_A: {k} == {v!r} (got {st.get(k)!r})")
        lp = loops_of(st).get(0)
        ctx.check(lp is not None and lp["notes_on"] == 2 and lp["notes_off"] == 2
                  and lp["ccs"] == 1 and lp["total_ticks"] == 96 and lp["type"] == "loop",
                  f"V30_A pad 0 loaded loop_{loop_id:04d}.bin (got {lp})")
        ctx.check(len(loops_of(st)) == 1, f"only pad 0 carries a loop ({sorted(loops_of(st))})")
        ctx.check(st.get("next_loop_id") == loop_id + 1,
                  f"regressed root next_loop_id={v30['next_loop_id']} reconciled up to "
                  f"{loop_id + 1} (on-disk floor + referenced ids; got {st.get('next_loop_id')})")
        got = d.get_preset("V30_A")
        got = got.get("preset", got)
        got = json.loads(got) if isinstance(got, str) else got
        ctx.check(got == v30["V30_A"], "GET_PRESET|V30_A returns the fixture body unchanged")

        # A user-driven load switches the startup pointer -> that IS a legitimate rewrite,
        # and it must keep every other preset and the root keys intact.
        ctx.instruct("Loading V30_B (user action; the file may now be rewritten)")
        d.load_preset("V30_B")
        st = state_full()
        expect_b = {"preset": "V30_B", "midi_type": "AUX", "record_cc": False,
                    "midi_sync": False, "clock_source": "USB", "channel_in": -1,
                    "passthru": "off", "midi_transport": "on"}
        for k, v in expect_b.items():
            ctx.check(st.get(k) == v, f"V30_B: {k} == {v!r} (got {st.get(k)!r})")
        ctx.check(not loops_of(st), f"V30_B carries no loops ({sorted(loops_of(st))})")
        doc = json.loads(d.read_presets_raw().decode())
        ctx.check(doc.get("STARTUP_PRESET") == "V30_B", "startup pointer rewritten to V30_B")
        ctx.check(doc.get("V30_A") == v30["V30_A"], "V30_A survives the rewrite unchanged")
        ctx.check(doc.get("V30_B") == v30["V30_B"], "V30_B survives the rewrite unchanged")
        ctx.check(doc.get("next_loop_id") == v30["next_loop_id"],
                  f"root next_loop_id left as the file had it ({doc.get('next_loop_id')}) — "
                  "a load rewrites only the startup pointer, a save persists the reconciled value")
        ctx.check("midi_transport" not in doc["V30_A"] and "midi_transport" not in doc["V30_B"],
                  "no new keys injected into presets the user never saved")

        # ------------------------------------------------------------------
        # Leg 2: v2.4 (CircuitPython) presets.json
        # ------------------------------------------------------------------
        v24 = _fixture_doc("presets_v2.4.json")
        v24_bytes = json.dumps(v24, indent=4).encode()   # the Python firmware wrote it indented
        d.write_presets_raw(v24_bytes)
        ctx.instruct("Rebooting onto the v2.4 presets.json")
        d.reboot()
        after = d.read_presets_raw()
        ctx.check(after == v24_bytes,
                  f"boot did NOT rewrite the v2.4 presets.json ({len(after)} B vs {len(v24_bytes)} B)")
        names = d.cmd("GET_PRESET_NAMES")
        ctx.check(sorted(names.get("names", [])) == sorted(_fixture_presets(v24)),
                  f"v2.4 preset names listed ({names.get('names')})")
        st = state_full()
        ctx.check(st.get("preset") == "DEFAULT", f"booted into DEFAULT (got {st.get('preset')!r})")
        # Expectation table — Python-era file. Spellings v3.x never had (playmode,
        # midi_passthru, quantize_cc-as-bool is fine) are IGNORED, not translated.
        expect_def = {"midi_type": "ALL", "play_mode": "loop", "passthru": "off",
                      "midi_sync": False, "record_cc": True, "clock_source": "USB",
                      "channel_in": -1, "channel_out": 0, "midi_transport": "on"}
        for k, v in expect_def.items():
            ctx.check(st.get(k) == v, f"v2.4 DEFAULT: {k} == {v!r} (got {st.get(k)!r})")

        ctx.instruct("Loading PY_LOOPS (Python loops metadata pointing at files that don't exist)")
        d.load_preset("PY_LOOPS")
        st = state_full()
        expect_py = {"preset": "PY_LOOPS", "midi_type": "USB", "play_mode": "loop",
                     "passthru": "off", "midi_transport": "on"}
        for k, v in expect_py.items():
            ctx.check(st.get(k) == v, f"PY_LOOPS: {k} == {v!r} (got {st.get(k)!r})")
        ctx.check(not loops_of(st),
                  f"dead Python loop ids skipped, no pad loaded ({sorted(loops_of(st))})")
        # Boot-time orphan sweep (load_startup_preset -> cleanup_orphan_loops): the moment the
        # v2.4 file became the doc, nothing referenced loop_0007.bin any more, so the FIRST boot
        # onto it deleted the file. That's loop FILES only — presets.json itself was proven
        # untouched above — and it's what keeps /loops from filling with dead files. With no
        # files left the floor is 1 and the file's own next_loop_id (3) stands.
        files = [f["name"] for f in d.cmd("LIST_LOOP_FILES").get("files", [])]
        ctx.check(loop_filename(loop_id) not in files,
                  f"orphaned loop_{loop_id:04d}.bin swept at boot once no preset referenced it ({files})")
        ctx.check(st.get("next_loop_id") == v24["next_loop_id"],
                  f"file's next_loop_id ({v24['next_loop_id']}) honoured with no on-disk floor above it "
                  f"(got {st.get('next_loop_id')})")

        # Restore-from-backup path: a Python-era body through SET_PRESET must be accepted.
        d.upload_preset("PY_RESTORE", v24["DEFAULT"])
        got = d.get_preset("PY_RESTORE")
        got = got.get("preset", got)
        got = json.loads(got) if isinstance(got, str) else got
        ctx.check(got.get("midi_type") == "ALL" and got.get("playmode") == "oneshot",
                  "SET_PRESET accepts a v2.4 body verbatim (unknown keys kept on disk, ignored on load)")
    finally:
        try:
            d.clear_all()
        except DeviceError:
            pass
        d.cmd("TEST_WIPE_PRESETS_FILE")
        for name, body in fixtures.items():
            d.upload_preset(name, body)
        for name, body in extras.items():
            d.upload_preset(name, body)
        d.cmd(f"SET_STARTUP|{BASELINE_PRESET}")
        ctx.instruct("Loading back into T_MULTI (reboot)")
        d.load_preset(BASELINE_PRESET)
    names_after = d.preset_names()
    ctx.check(sorted(names_after) == sorted(names_before),
              f"preset list restored to the snapshot ({names_after})")
    ctx.check(d.cmd("GET_PRESET_NAMES").get("startup") == BASELINE_PRESET,
              "startup preset back on the baseline")


@test("serial-fuzz-garbage",
      "Garbage, binary junk, runaway lines and malformed args never wedge the protocol")
def t_serial_fuzz(ctx):
    """serial-cmd-flood proves the channel under LOAD; nothing probed malformed
    INPUT — a broken web page or a user typing into a terminal monitor. Plain
    garbage and binary junk must be ignored without a response; a >8 KB line
    must trip the runaway-buffer guard and drop cleanly; malformed CMD args must
    each earn exactly one error RSP. The cmds/rsps ledger proves nothing was
    eaten or double-answered."""
    d = ctx.device
    st0 = d.state()
    c0, r0 = st0.get("cmds"), st0.get("rsps")
    n_cmds = 0

    # Non-CMD garbage: ignored, no RSP owed (raw writes bypass cmd() on purpose)
    d.ser.write(b"hello world\r\n")
    d.ser.write(b"RSP:{\"status\":\"ok\"}\n")   # a spoofed response line is not a command
    d.ser.write(b"\x81\xfe\x99 binary junk \xf0\x9f\x8e\x9b\n")
    time.sleep(0.2)

    # Runaway line: 9 KB with no newline trips the 8192 guard mid-stream; the
    # residue flushes at the newline as one ignorable non-CMD line.
    d.ser.write(b"A" * 9000 + b"\n")
    time.sleep(0.5)
    st = d.state()
    n_cmds += 1
    ctx.check(st.get("heap_free", 0) > 50_000,
              f"heap sane after the 9 KB runaway line ({st.get('heap_free')})")

    def expect_error_rsp(what, command):
        nonlocal n_cmds
        try:
            d.cmd(command)
        except DeviceError as e:
            n_cmds += 1
            ctx.log(f"ok: {what} -> error RSP ({e})")
            return
        n_cmds += 1
        raise TestFailed(f"{what} was accepted")

    expect_error_rsp("empty command", "")
    expect_error_rsp("TEST_PAD with no args", "TEST_PAD")
    expect_error_rsp("out-of-range pad", "TEST_RECORD|99")
    expect_error_rsp("GET_PRESET with empty name", "GET_PRESET|")
    expect_error_rsp("unknown command with args", "BOGUS|x|y")
    expect_error_rsp("TEST_DIN with bad hex", "TEST_DIN|XYZ")
    expect_error_rsp("TEST_MENU out of range", "TEST_MENU|99")

    st = d.state()
    n_cmds += 1
    if c0 is not None and r0 is not None:
        ctx.check(st["cmds"] - c0 == n_cmds,
                  f"every real CMD counted once, garbage counted never "
                  f"({st['cmds'] - c0}/{n_cmds})")
        ctx.check(st["rsps"] - r0 == n_cmds,
                  f"exactly one RSP per CMD ({st['rsps'] - r0}/{n_cmds})")
    ctx.heartbeat()


@test("arp-octave-random",
      "'rand oct up' arp stays within ±1 octave of its sources; every step releases (crash cluster #3)")
def t_arp_octave_random(ctx):
    """Octave arp modes are in the historical crash cluster (octave modes
    crashing, memory blowups) and had zero coverage. Under 'rand oct up' each
    step may shift ±1 octave (out-of-range reverts to the source note), so with
    sources {60, 64} every emitted pitch must be in {48,52,60,64,72,76} — an
    OOB pitch or a missing off is the historical failure signature."""
    d = ctx.device
    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.drain_midi()

    d.record(0)
    time.sleep(0.1)
    for n in (60, 64):
        d.send(note_on(n, 100, 0), pause=0.1)
        d.send(note_off(n, 0), pause=0.06)
    d.stop_record()
    d.stop(0)

    d.set_play_mode("encoder")
    d.cmd("TEST_ARP_CONFIG|1|1/32|rand oct up")  # short gates so offs expire in-capture
    try:
        d.inject_pad(0, True)
        time.sleep(0.1)
        d.drain_midi()
        steps = 10
        actions = [(0.1 + 0.15 * i, lambda: d.inject_encoder(1)) for i in range(steps)]
        captured = d.capture_while(0.1 + 0.15 * steps + 0.8, actions)

        ons = [m for _, m in captured if m.type == "note_on" and m.velocity > 0]
        offs = [m for _, m in captured
                if m.type == "note_off" or (m.type == "note_on" and m.velocity == 0)]
        ctx.check(len(ons) == steps, f"every detent produced a step ({len(ons)}/{steps})")
        allowed = {48, 52, 60, 64, 72, 76}
        stray = sorted({m.note for m in ons} - allowed)
        ctx.log(f"steps played: {sorted({m.note for m in ons})}")
        ctx.check(not stray, f"all pitches within ±1 octave of the sources (stray {stray})")
        on_counts = Counter(m.note for m in ons)
        off_counts = Counter(m.note for m in offs)
        unreleased = {n: c for n, c in on_counts.items() if off_counts[n] < c}
        ctx.check(not unreleased, f"every octave-shifted step released (missing offs: {unreleased})")
    finally:
        d.inject_pad(0, False)
        time.sleep(0.1)
        d.cmd("TEST_ARP_CONFIG|1|1/8|up")
        d.set_play_mode("loop")
    ctx.heartbeat()
    d.clear_all()


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


@test("manual-status-strip-tour",
      "Guided OLED tour: sync glyph / BPM '--' / play-triangle states (#276 rework)",
      tags=("manual",))
def t_status_strip_tour(ctx):
    """The OLED has no framebuffer test hook, so the bottom status strip — hotspot #5's
    zone, reworked for #276 (sync glyph never blinks; BPM reads '--' while sync is on
    but ticks are quiet; hollow-vs-filled play triangle) — is verifiable only by eye.
    This drives the REAL states in numbered steps; unlike ask_pass_fail it collects
    EVERY bad step with your notes instead of stopping at the first, so the verdict
    reads "step 2: glyph flickered", not just FAIL. Expectations assume the #276
    rework — on pre-rework firmware step 2 "fails" by design (blinking glyph + stale
    number instead of solid + '--'). Watch the BOTTOM ROW of the screen throughout."""
    d = ctx.device
    failures = []

    def step(n, expect):
        """[p] records a pass, [f] records what looked wrong and continues,
        [a] ends the tour (failing if anything was already recorded)."""
        while True:
            a = input(f"\n  >>> STEP {n} — {expect}\n"
                      f"      [p]ass / [f]ail / [a]bort tour: ").strip().lower()
            if a in ("p", "pass"):
                return
            if a in ("f", "fail"):
                detail = input("      What looked wrong? ").strip()
                failures.append(f"step {n}: {detail or 'looked wrong'}")
                return
            if a in ("a", "abort"):
                if failures:
                    raise TestFailed("aborted after: " + "; ".join(failures))
                raise TestSkipped(f"tour aborted at step {n}")

    d.set_midi_sync(False)
    d.set_loop_type("loop")
    d.clear_all()
    d.set_menu(MENU_PLAY)
    d.drain_midi()
    try:
        time.sleep(0.5)
        step(1, "Sync OFF, idle: quarter-note glyph + a steady tempo number, "
                "NO circular-arrows sync glyph, NO play triangle")

        d.set_midi_sync(True)
        time.sleep(1.5)  # past the 1 s clock-quiet window
        step(2, "Sync ON, no clock: tempo reads '--', sync glyph shown SOLID "
                "(never blinking), still no triangle, nothing flickers")

        d.start_clock(bpm=120, send_start=True)
        time.sleep(2.5)  # let the measured BPM settle
        step(3, "Clock rolling: tempo near 120, sync glyph solid, "
                "HOLLOW (outline-only) play triangle")

        d.record(0)
        d.send(note_on(60, 100, 0), pause=0.3)
        d.send(note_off(60, 0), pause=0.3)
        d.stop_record()  # finalize -> playback under the rolling clock
        time.sleep(1.0)
        step(4, "Loop playing under the clock (give it a bar to start): "
                "triangle now FILLED")

        d.stop_clock(send_stop=True)  # Stop halts synced loops; ticks cease
        time.sleep(1.8)
        step(5, "Clock stopped: tempo back to '--' within ~1 s, triangle gone, "
                "sync glyph still solid")

        d.set_midi_sync(False)
        d.clear_all()
        d.record(1)
        d.send(note_on(64, 100, 0), pause=0.3)
        step(6, "Recording, sync off: REC dot solid, quarter-note glyph blinks "
                "on the beat, tempo is a number again (no '--', no sync glyph)")
        d.send(note_off(64, 0), pause=0.2)
        d.stop_record()

        ctx.check(not failures, "status strip verdicts: " + "; ".join(failures))
    finally:
        d.stop_clock()
        d.set_midi_sync(False)
        d.stop_all()
        d.clear_all()
        d.drain_midi()


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
