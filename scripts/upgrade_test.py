#!/usr/bin/env python3
"""Real firmware-upgrade test: flash an OLDER release, seed it the way a customer would,
update to the candidate exactly the way the web page does, and prove nothing was lost.

    scripts/.venv/bin/python scripts/upgrade_test.py                 # v3.0 -> loopster.uf2
    scripts/.venv/bin/python scripts/upgrade_test.py --to .pio/build/loopster-release/firmware.uf2
    scripts/.venv/bin/python scripts/upgrade_test.py --from v3.1     # any release tag, or a .uf2 path
    scripts/.venv/bin/python scripts/upgrade_test.py --python        # CircuitPython leg (see below)

Run it from the repo root before cutting a release (notes/upgrade_test.sh wraps it and
reflashes the dev build afterwards). It is NOT part of the --auto gate: it reflashes the
unit several times and leaves it on RELEASE firmware (no TEST_* hooks).

What the default leg does, in order:
  1. Puts the connected unit into BOOTSEL (CMD:ENTER_BOOTSEL if it runs Loopster firmware,
     otherwise waits for the RP2 Boot device), wipes the whole flash (same 16 MB image as
     flash_customer.sh), flashes the CANDIDATE and lets it create presets.json with one
     throwaway preset (v3.0 on a fresh unit answers every preset command with io_error — the
     Aug 2026 RMA bug, fixed in v3.1 — so the file has to exist first; real v3.0 customers
     have one because they saved on the device, which release firmware can't be told to do),
     then flashes the OLD release over it WITHOUT a wipe so the filesystem carries over.
  2. Waits for it to boot, then seeds state through the PUBLIC web protocol only — release
     firmware has no test hooks, and this is the customer surface anyway: two presets from
     scripts/fixtures/presets_v3.0.json (one references loop_0007.bin), a CRC-valid v2 loop
     file via PUT_LOOP_FILE_CHUNK, the startup pointer, and deletes the throwaway preset so
     everything left on flash was written by the OLD firmware's serializer. Reboots once so
     the old firmware itself loads that state, then snapshots everything: raw presets.json
     bytes, preset list, every preset body, the loop file list, the loop file bytes, the PING
     build date.
  3. Updates like the browser: PING, CMD:ENTER_BOOTSEL, wait for the RPI-RP2 drive, copy the
     candidate .uf2 onto it, wait for the unit to re-enumerate as "Loopster".
  4. Re-reads everything through the same protocol and diffs it against the snapshot. The
     headline assertion is that presets.json is BYTE-IDENTICAL: an update must never rewrite
     customer presets unless the user saves (Derrick, 2026-09-14).

--python: the legacy leg. Flashes the stock CircuitPython image the v2.4 release shipped
(pulled from git tag v2.4), drops the v2.4 presets.json on its CIRCUITPY drive, reboots it
into BOOTSEL through the CircuitPython REPL, copies the candidate on, and asserts the new
firmware boots CLEAN: PING answers with device:"loopster", no presets, no loop files. That
is the documented outcome (the FAT filesystem is unreadable to v3.x, which formats its
LittleFS region on first boot) — the web page warns about it in red. Best-effort: if the
REPL trick fails the script asks you to hold BOOT.

Needs: picotool (PlatformIO's bundled one is found automatically), pyserial (the suite's
venv has it), macOS (ioreg + /Volumes). Nothing else — no MIDI.
"""
import argparse
import base64
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial missing — run via notes/upgrade_test.sh or scripts/.venv/bin/python")

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
from loop_v2 import loop_filename, sample_loop  # noqa: E402


def fw_id(ping):
    """Firmware identity from a PING ack: "v3.2" on version-reporting firmware, else the
    build date older releases (v3.0, first v3.1 image) sent, else "?"."""
    if ping.get("version"):
        return "v%s" % ping["version"]
    return ping.get("built") or "?"

REPO = "derrickthomin/DJBB-Loopster-2.0"
CACHE_DIR = REPO_ROOT / "notes" / ".cache"
REPORT_DIR = SCRIPT_DIR / "test_reports"
FIXTURES_DIR = SCRIPT_DIR / "fixtures"
CP_UF2_IN_GIT = "v2.4:uf2 current/adafruit-circuitpython-raspberry_pi_pico-en_US-8.2.6.uf2"
CP_UF2_CACHE = CACHE_DIR / "v2.4_circuitpython-8.2.6.uf2"
RPI_RP2 = Path("/Volumes/RPI-RP2")
CIRCUITPY = Path("/Volumes/CIRCUITPY")
UF2_MAGIC = 0x0A324655
CHUNK = 384  # raw bytes per base64 chunk (512 chars) — the firmware's buffer size


# --------------------------------------------------------------------------
# Small host helpers
# --------------------------------------------------------------------------

class Fail(Exception):
    pass


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def usb_has(product):
    try:
        out = subprocess.run(["ioreg", "-p", "IOUSB", "-l", "-w0"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        return False
    return f'"USB Product Name" = "{product}"' in out


def wait_for(what, pred, timeout, hint=None):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        time.sleep(1)
    if hint:
        log(hint)
    return False


def find_picotool():
    home = Path.home()
    for cand in ("picotool",
                 home / ".platformio/packages/tool-picotool-rp2040-earlephilhower/picotool",
                 home / ".platformio/packages/tool-rp2040tools/picotool"):
        p = shutil.which(str(cand)) if isinstance(cand, str) else (str(cand) if cand.exists() else None)
        if p:
            return p
    raise Fail("picotool not found (install PlatformIO's RP2040 platform, or brew install picotool)")


def validate_uf2(path):
    data = path.read_bytes()
    if len(data) < 512 or struct.unpack_from("<I", data, 0)[0] != UF2_MAGIC:
        raise Fail(f"{path} is not a UF2 file")
    return path


def blank_image():
    """16 MB of 0xFF as a UF2 — the same wipe image flash_customer.sh generates."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    blank = CACHE_DIR / "blank_16mb.uf2"
    if blank.exists() and blank.stat().st_size == 33554432:
        return blank
    log("generating the 16 MB wipe image (one-time) ...")
    flash_base, flash_size, payload = 0x10000000, 16 * 1024 * 1024, 256
    nblocks = flash_size // payload
    body = b"\xff" * payload + b"\x00" * (476 - payload)
    end = struct.pack("<I", 0x0AB16F30)
    with open(str(blank) + ".part", "wb") as f:
        for i in range(nblocks):
            f.write(struct.pack("<8I", UF2_MAGIC, 0x9E5D5157, 0x2000, flash_base + i * payload,
                                payload, i, nblocks, 0xE48BFF56) + body + end)
    os.rename(str(blank) + ".part", blank)
    return blank


def gh_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "loopster-upgrade-test"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def resolve_old_image(spec):
    """A release tag (v3.0) -> notes/.cache/<tag>_<asset>.uf2 (downloaded once), or a path."""
    p = Path(spec)
    if p.suffix.lower() == ".uf2" and p.exists():
        return validate_uf2(p)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = sorted(CACHE_DIR.glob(f"{spec}_*.uf2"))
    if cached:
        return validate_uf2(cached[0])
    log(f"downloading release {spec} from GitHub ...")
    rel = gh_json(f"https://api.github.com/repos/{REPO}/releases/tags/{spec}")
    asset = next((a for a in rel.get("assets", []) if a["name"].lower().endswith(".uf2")), None)
    if not asset:
        raise Fail(f"release {spec} has no .uf2 asset")
    dest = CACHE_DIR / f"{spec}_{asset['name']}"
    urllib.request.urlretrieve(asset["browser_download_url"], str(dest) + ".part")
    os.rename(str(dest) + ".part", dest)
    if dest.stat().st_size != asset["size"]:
        dest.unlink()
        raise Fail("downloaded size does not match what GitHub reports")
    return validate_uf2(dest)


def circuitpython_image():
    if CP_UF2_CACHE.exists():
        return validate_uf2(CP_UF2_CACHE)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    log("extracting the v2.4 CircuitPython image from git ...")
    with open(CP_UF2_CACHE, "wb") as f:
        subprocess.run(["git", "show", CP_UF2_IN_GIT], cwd=REPO_ROOT, stdout=f, check=True)
    return validate_uf2(CP_UF2_CACHE)


def find_port(product_words=("loopster",)):
    for p in list_ports.comports():
        text = " ".join(filter(None, (p.product, p.description, p.manufacturer))).lower()
        if any(w in text for w in product_words):
            return p.device
    return None


# --------------------------------------------------------------------------
# Minimal CMD:/RSP: client (public protocol only — works on every v3.x release)
# --------------------------------------------------------------------------

class Proto:
    def __init__(self, port):
        self.ser = serial.Serial(port, 115200, timeout=0.2)
        self.buf = b""
        time.sleep(0.3)
        self.ser.reset_input_buffer()

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def cmd(self, command, timeout=10.0):
        try:
            return self._cmd(command, timeout)
        except (serial.SerialException, OSError) as e:
            # REBOOT / ENTER_BOOTSEL acks routinely lose the race with the port dropping.
            raise Fail(f"serial I/O failed during {command.split('|')[0]}: {e}") from e

    def _cmd(self, command, timeout):
        self.ser.write(f"CMD:{command}\n".encode())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            chunk = self.ser.read(4096)
            if chunk:
                self.buf += chunk
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                text = line.decode(errors="replace").strip()
                if text.startswith("RSP:"):
                    rsp = json.loads(text[4:])
                    if "error" in rsp:
                        raise Fail(f"{command.split('|')[0]} -> {rsp['error']} ({rsp.get('code')})")
                    return rsp
        raise Fail(f"timeout waiting for RSP to {command.split('|')[0]}")

    # -- file-level helpers over the chunk commands --
    def read_presets_raw(self):
        raw, offset = b"", 0
        while True:
            rsp = self.cmd(f"GET_PRESETS_RAW_CHUNK|{offset}")
            data = base64.b64decode(rsp["data"])
            raw += data
            offset += len(data)
            if rsp.get("done") or not data:
                return raw

    def read_loop_file(self, name):
        raw, offset = b"", 0
        while True:
            rsp = self.cmd(f"GET_LOOP_FILE_CHUNK|{name}|{offset}")
            data = base64.b64decode(rsp["data"])
            raw += data
            offset += len(data)
            if rsp.get("done") or not data:
                return raw

    def put_loop_file(self, name, blob):
        chunks = [blob[i:i + CHUNK] for i in range(0, len(blob), CHUNK)]
        offset = 0
        for i, c in enumerate(chunks):
            self.cmd(f"PUT_LOOP_FILE_CHUNK|{name}|{offset}|{1 if i == len(chunks) - 1 else 0}|"
                     f"{base64.b64encode(c).decode()}")
            offset += len(c)

    def get_preset(self, name):
        rsp = self.cmd(f"GET_PRESET|{name}", timeout=30)
        rsp = rsp.get("preset", rsp)
        return json.loads(rsp) if isinstance(rsp, str) else rsp

    def loop_files(self):
        return sorted((f["name"], f["size"]) for f in self.cmd("LIST_LOOP_FILES").get("files", []))

    def snapshot(self):
        names = self.cmd("GET_PRESET_NAMES")
        snap = {
            "fw": fw_id(self.cmd("PING")),
            "names": sorted(names.get("names", [])),
            "startup": names.get("startup"),
            "raw": self.read_presets_raw(),
            "presets": {n: self.get_preset(n) for n in names.get("names", [])},
            "loop_files": self.loop_files(),
        }
        snap["loops"] = {n: self.read_loop_file(n) for n, _ in snap["loop_files"]}
        return snap


# --------------------------------------------------------------------------
# Device state transitions
# --------------------------------------------------------------------------

def in_bootsel():
    return usb_has("RP2 Boot") or RPI_RP2.exists()


def enter_bootsel_from_loopster(port):
    log(f"CMD:ENTER_BOOTSEL via {port}")
    p = Proto(port)
    try:
        p.cmd("PING")
        try:
            p.cmd("ENTER_BOOTSEL", timeout=2.0)  # ack may be beaten by the reboot — fine
        except Fail:
            pass
    finally:
        p.close()


def enter_bootsel_from_circuitpython(port):
    """CircuitPython REPL: microcontroller.on_next_reset(BOOTLOADER) + reset()."""
    log(f"asking CircuitPython on {port} to reboot into the bootloader")
    s = serial.Serial(port, 115200, timeout=0.2)
    try:
        s.write(b"\x03\x03")          # interrupt code.py
        time.sleep(0.5)
        s.write(b"\r\n")
        time.sleep(0.3)
        for line in (b"import microcontroller\r\n",
                     b"microcontroller.on_next_reset(microcontroller.RunMode.BOOTLOADER)\r\n",
                     b"microcontroller.reset()\r\n"):
            s.write(line)
            time.sleep(0.4)
    finally:
        try:
            s.close()
        except Exception:
            pass


def get_into_bootsel():
    if in_bootsel():
        return
    port = find_port(("loopster",))
    if port:
        enter_bootsel_from_loopster(port)
    else:
        cp = find_port(("circuitpython", "pico"))
        if cp:
            enter_bootsel_from_circuitpython(cp)
    if not wait_for("bootsel", in_bootsel, 30):
        log("!! No bootloader seen. Unplug the unit, hold BOOT while plugging it back in.")
        if not wait_for("bootsel", in_bootsel, 180):
            raise Fail("never saw the RP2 Boot device / RPI-RP2 drive")
    time.sleep(1.5)


def picotool_load(picotool, image, execute=False):
    args = [picotool, "load", "-f"] + (["-x"] if execute else []) + [str(image)]
    log("picotool load " + ("-x " if execute else "") + Path(image).name)
    r = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise Fail(f"picotool failed: {r.stdout[-400:]} {r.stderr[-400:]}")


def copy_uf2_like_the_browser(image):
    """The web page writes the .uf2 onto the mounted RPI-RP2 drive through the File System
    Access API; cp onto the same mount is the closest host analog."""
    if not wait_for("RPI-RP2", RPI_RP2.exists, 90, "!! RPI-RP2 never mounted"):
        raise Fail("RPI-RP2 drive never appeared")
    time.sleep(1.0)
    log(f"copying {Path(image).name} onto {RPI_RP2}")
    # The board reboots mid-copy, so cp can report an error even on success — the drive
    # vanishing right after IS the success signal.
    subprocess.run(["cp", "-X", str(image), str(RPI_RP2) + "/"], capture_output=True)
    if not wait_for("drive gone", lambda: not RPI_RP2.exists(), 30):
        raise Fail("the copy didn't take (RPI-RP2 still mounted)")


def wait_for_loopster(timeout):
    log("waiting for the unit to come back as 'Loopster' ...")
    if not wait_for("Loopster", lambda: usb_has("Loopster") and find_port(("loopster",)), timeout):
        raise Fail("unit never re-enumerated as Loopster")
    time.sleep(3.0)  # CDC settle
    return find_port(("loopster",))


# --------------------------------------------------------------------------
# Legs
# --------------------------------------------------------------------------

def fixture_doc(name):
    doc = json.loads((FIXTURES_DIR / name).read_text())
    return {k: v for k, v in doc.items() if not k.startswith("_")}


class Checker:
    def __init__(self):
        self.results = []

    def check(self, cond, what):
        self.results.append((bool(cond), what))
        log(("PASS  " if cond else "FAIL  ") + what)
        return bool(cond)

    @property
    def failed(self):
        return [w for ok, w in self.results if not ok]


def leg_release_upgrade(args, picotool, ck):
    old = resolve_old_image(args.old)
    new = validate_uf2(Path(args.to))
    log(f"OLD image: {old}")
    log(f"NEW image: {new}")

    v30 = fixture_doc("presets_v3.0.json")
    presets = {k: v for k, v in v30.items() if k not in ("STARTUP_PRESET", "next_loop_id")}
    loop_id = v30["V30_A"]["loops"]["0"]["loop_id"]
    BOOTSTRAP = "UPG_BOOT"

    # 1a. wipe, then let the CANDIDATE create presets.json (v3.0 can't on a fresh unit)
    get_into_bootsel()
    if not args.no_wipe:
        picotool_load(picotool, blank_image())
    picotool_load(picotool, new, execute=True)
    port = wait_for_loopster(90)
    p = Proto(port)
    try:
        ping = p.cmd("PING")
        ck.check(ping.get("device") == "loopster",
                 f"candidate boots on a wiped unit and identifies itself ({fw_id(ping)})")
        p.cmd(f"SET_PRESET|{BOOTSTRAP}|{json.dumps(presets['V30_B'], separators=(',', ':'))}", timeout=30)
        ck.check(BOOTSTRAP in p.cmd("GET_PRESET_NAMES").get("names", []),
                 "candidate creates presets.json on a fresh unit (bootstrap preset saved)")
        try:
            p.cmd("ENTER_BOOTSEL", timeout=2.0)
        except Fail:
            pass
    finally:
        p.close()
    # 1b. the OLD release goes on WITHOUT a wipe — the filesystem carries over
    if not wait_for("bootsel", in_bootsel, 30):
        raise Fail("candidate did not reboot into the bootloader")
    time.sleep(1.5)
    picotool_load(picotool, old, execute=True)
    port = wait_for_loopster(90)

    # 2. seed through the public protocol, then reboot so the OLD firmware loads it
    p = Proto(port)
    try:
        ping = p.cmd("PING")
        ck.check(ping.get("device") == "loopster", f"old firmware identifies itself ({fw_id(ping)})")
        p.put_loop_file(loop_filename(loop_id), sample_loop(pad=0))
        for name, body in presets.items():
            p.cmd(f"SET_PRESET|{name}|{json.dumps(body, separators=(',', ':'))}", timeout=30)
        p.cmd(f"SET_STARTUP|{v30['STARTUP_PRESET']}", timeout=30)
        p.cmd(f"DELETE_PRESET|{BOOTSTRAP}", timeout=30)  # leaves only what the OLD firmware wrote
        ck.check(BOOTSTRAP not in p.cmd("GET_PRESET_NAMES").get("names", []),
                 "bootstrap preset removed — presets.json now holds only old-firmware writes")
        log("seeded; rebooting the old firmware onto the seeded state")
        try:
            p.cmd("REBOOT", timeout=2.0)
        except Fail:
            pass
    finally:
        p.close()
    port = wait_for_loopster(60)
    p = Proto(port)
    try:
        before = p.snapshot()
        ck.check(before["names"] == sorted(presets), f"old firmware lists the seeded presets {before['names']}")
        ck.check(before["startup"] == v30["STARTUP_PRESET"], "old firmware honours the startup pointer")
        ck.check(any(n == loop_filename(loop_id) for n, _ in before["loop_files"]),
                 f"old firmware holds {loop_filename(loop_id)} ({before['loop_files']})")
        # 3. update exactly like the browser
        log("updating: PING -> ENTER_BOOTSEL -> RPI-RP2 -> copy -> reboot")
        p.cmd("PING")
        try:
            p.cmd("ENTER_BOOTSEL", timeout=2.0)
        except Fail:
            pass
    finally:
        p.close()
    copy_uf2_like_the_browser(new)
    port = wait_for_loopster(90)

    # 4. verify
    p = Proto(port)
    try:
        after = p.snapshot()
    finally:
        p.close()
    log(f"firmware: {before['fw']} -> {after['fw']}")
    ck.check(after["fw"] != before["fw"] or old.read_bytes() == new.read_bytes(),
             "new firmware identifies differently (or the images are identical)")
    ck.check(after["raw"] == before["raw"],
             f"presets.json BYTE-IDENTICAL across the update ({len(before['raw'])} B)")
    ck.check(after["names"] == before["names"], f"preset list unchanged {after['names']}")
    ck.check(after["startup"] == before["startup"], f"startup pointer unchanged ({after['startup']})")
    for name in before["presets"]:
        ck.check(after["presets"].get(name) == before["presets"][name], f"preset {name} body unchanged")
    ck.check(after["loop_files"] == before["loop_files"], f"loop file list unchanged {after['loop_files']}")
    for name, blob in before["loops"].items():
        ck.check(after["loops"].get(name) == blob, f"loop file {name} bytes unchanged ({len(blob)} B)")


def leg_python_upgrade(args, picotool, ck):
    cp = circuitpython_image()
    new = validate_uf2(Path(args.to))
    log(f"CircuitPython image: {cp}")
    get_into_bootsel()
    picotool_load(picotool, blank_image())
    picotool_load(picotool, cp, execute=True)
    if not wait_for("CIRCUITPY", CIRCUITPY.exists, 120, "!! CIRCUITPY drive never mounted"):
        raise Fail("CircuitPython never brought up its CIRCUITPY drive")
    time.sleep(2.0)
    v24 = fixture_doc("presets_v2.4.json")
    (CIRCUITPY / "presets.json").write_text(json.dumps(v24, indent=4))
    subprocess.run(["sync"])
    ck.check((CIRCUITPY / "presets.json").exists(), "v2.4 presets.json placed on the CIRCUITPY drive")
    time.sleep(1.0)
    # into BOOTSEL via the REPL, then the candidate goes on like any other update
    port = find_port(("circuitpython", "pico"))
    if port:
        enter_bootsel_from_circuitpython(port)
    if not wait_for("bootsel", in_bootsel, 30):
        log("!! CircuitPython didn't reboot into the bootloader. Unplug, hold BOOT, plug back in.")
        if not wait_for("bootsel", in_bootsel, 180):
            raise Fail("never saw the bootloader after CircuitPython")
    copy_uf2_like_the_browser(new)
    port = wait_for_loopster(120)  # first boot formats the 14 MB LittleFS region
    p = Proto(port)
    try:
        ping = p.cmd("PING")
        ck.check(ping.get("device") == "loopster", f"new firmware answers PING ({fw_id(ping)})")
        names = p.cmd("GET_PRESET_NAMES")
        ck.check(names.get("names", []) == [], f"no presets carried over from the FAT era ({names.get('names')})")
        files = p.loop_files()
        ck.check(files == [], f"no loop files carried over ({files})")
        try:
            p.cmd("DISCONNECT")
        except Fail:
            pass
    finally:
        p.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="old", default="v3.0", help="release tag or .uf2 path to start from (default v3.0)")
    ap.add_argument("--to", default=str(REPO_ROOT / "loopster.uf2"), help="candidate .uf2 (default: root loopster.uf2)")
    ap.add_argument("--python", action="store_true", help="run the CircuitPython (v2.4) leg instead")
    ap.add_argument("--no-wipe", action="store_true", help="skip the 16 MB wipe before flashing the old image")
    args = ap.parse_args()

    if sys.platform != "darwin":
        sys.exit("this script relies on ioreg and /Volumes — macOS only")
    picotool = find_picotool()
    ck = Checker()
    REPORT_DIR.mkdir(exist_ok=True)
    report = REPORT_DIR / f"upgrade_{datetime.now():%Y%m%d_%H%M%S}.txt"
    status = 1
    try:
        if args.python:
            leg_python_upgrade(args, picotool, ck)
        else:
            leg_release_upgrade(args, picotool, ck)
        status = 0 if not ck.failed else 1
    except Fail as e:
        ck.check(False, f"ABORTED: {e}")
    except KeyboardInterrupt:
        ck.check(False, "ABORTED: interrupted")
    finally:
        lines = [f"upgrade_test {datetime.now():%Y-%m-%d %H:%M:%S}  "
                 f"leg={'python' if args.python else 'release'} from={args.old} to={args.to}"]
        lines += [("PASS  " if ok else "FAIL  ") + w for ok, w in ck.results]
        n_ok = sum(1 for ok, _ in ck.results if ok)
        lines.append(f"{n_ok}/{len(ck.results)} passed")
        report.write_text("\n".join(lines) + "\n")
        print()
        print(f"==> {n_ok}/{len(ck.results)} passed" + ("" if not ck.failed else f" — FAILED: {ck.failed}"))
        print(f"    report: {report}")
        print("    The unit now runs RELEASE firmware (no TEST_* hooks): ./notes/flash.sh puts the dev build back.")
    sys.exit(status)


if __name__ == "__main__":
    main()
