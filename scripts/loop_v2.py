"""Loop storage v2 (.bin) builder — shared by the on-device harness and the upgrade
script so both seed byte-identical, CRC-valid loop files without a device-side
recording (release firmware has no TEST_* hooks to record with).

Format (src/loop_storage.h, single source of truth):
  20-byte packed LE header  <HBBHHHHHHI>
    magic 0x4C02, loop_type (0 loop/1 oneshot/2 hold), reserved, notes_on_count,
    notes_off_count, cc_count, at_count, total_ticks, bpm_x10, body_crc32
  body: notes_on × <BBBH>, notes_off × <BBBH>, cc × <BBHB>, at × <BBHB>
  CRC-32 = zlib.crc32 over the body bytes.
"""
import struct
import zlib

LOOP_MAGIC = 0x4C02
LOOP_TYPES = {"loop": 0, "oneshot": 1, "hold": 2}


def note_event(note, velocity, tick, pad=0, channel=0):
    """NotesEvent <BBBH>: packed_pad_channel = (channel << 4) | pad."""
    return struct.pack("<BBBH", note, velocity, ((channel & 0x0F) << 4) | (pad & 0x0F), tick)


def controller_event(num, value, tick, channel=0):
    """ControllerEvent <BBHB>."""
    return struct.pack("<BBHB", num, value, tick, channel)


def build_loop_v2(notes_on, notes_off, ccs=(), ats=(), total_ticks=96, bpm=120.0, loop_type="loop"):
    """Return the bytes of a complete, CRC-valid v2 loop file."""
    body = b"".join(notes_on) + b"".join(notes_off) + b"".join(ccs) + b"".join(ats)
    header = struct.pack("<HBBHHHHHHI", LOOP_MAGIC, LOOP_TYPES[loop_type], 0,
                         len(notes_on), len(notes_off), len(ccs), len(ats),
                         total_ticks, int(round(bpm * 10)), zlib.crc32(body) & 0xFFFFFFFF)
    return header + body


def sample_loop(pad=0):
    """The canonical seed loop: 2 note-ons + 2 note-offs + 1 CC, one bar (96 ticks)
    @ 120 bpm on the given pad, channel 0. Deterministic — the same bytes every run."""
    return build_loop_v2(
        notes_on=[note_event(60, 100, 0, pad), note_event(64, 90, 24, pad)],
        notes_off=[note_event(60, 0, 24, pad), note_event(64, 0, 36, pad)],
        ccs=[controller_event(1, 64, 12)],
        total_ticks=96, bpm=120.0)


def loop_filename(loop_id):
    return f"loop_{loop_id:04d}.bin"
