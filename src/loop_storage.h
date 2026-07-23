// Loop storage v2 — one self-contained binary file per loop in LittleFS.
//
//   /loops/loop_%04d.bin
//   Header — 20 bytes, packed, little-endian:
//     u16  magic            = 0x4C02  ("L", v2 — old 3-file format rejected + swept)
//     u8   loop_type        0=loop, 1=oneshot, 2=hold
//     u8   reserved         = 0
//     u16  notes_on_count
//     u16  notes_off_count
//     u16  cc_count
//     u16  at_count
//     u16  total_ticks
//     u16  bpm_x10
//     u32  body_crc32       CRC-32 (IEEE/zlib poly) over all body bytes
//   Body — four back-to-back sections, 5-byte records (byte-identical to v1):
//     [notes_on × NotesEvent][notes_off × NotesEvent][cc × ControllerEvent][at × ControllerEvent]
//
// The file header is the single source of truth for loop_type/ticks/bpm — the
// preset JSON carries only {"loop_id": N} per pad. Saves are atomic
// (tmp + remove + rename, with boot-side tmp recovery in init()).
#pragma once
#include <Arduino.h>
#include <vector>
#include "looper.h"

namespace loop_storage {

constexpr const char *LOOPS_DIR = "/loops";

constexpr uint16_t LOOP_MAGIC = 0x4C02; // "L" + version 2

#pragma pack(push, 1)
struct LoopHeaderV2 {
    uint16_t magic;
    uint8_t loop_type; // 0=loop, 1=oneshot, 2=hold
    uint8_t reserved;
    uint16_t notes_on_count;
    uint16_t notes_off_count;
    uint16_t cc_count;
    uint16_t at_count;
    uint16_t total_ticks;
    uint16_t bpm_x10;
    uint32_t body_crc32;
};
struct ControllerEvent { // '<BBHB'
    uint8_t num;   // cc number (or 0 for channel pressure)
    uint8_t value; // cc value / pressure
    uint16_t tick;
    uint8_t channel;
};
struct NotesEvent { // '<BBBH'
    uint8_t note;
    uint8_t velocity;
    uint8_t packed_pad_channel;
    uint16_t tick;
};
#pragma pack(pop)

static_assert(sizeof(LoopHeaderV2) == 20, "v2 header must be 20 packed bytes");
static_assert(sizeof(ControllerEvent) == 5, "event record must stay 5 bytes");
static_assert(sizeof(NotesEvent) == 5, "event record must stay 5 bytes");

// loop_type codes <-> the "loop"/"oneshot"/"hold" strings used everywhere else
uint8_t loop_type_to_code(const String &loop_type);
const char *loop_type_name(uint8_t code);

// Header peek (valid=false on missing/bad-magic/truncated file)
struct LoopHeaderInfo {
    bool valid = false;
    uint8_t loop_type = 0;
    uint16_t notes_on_count = 0;
    uint16_t notes_off_count = 0;
    uint16_t cc_count = 0;
    uint16_t at_count = 0;
    uint16_t total_ticks = 0;
    float bpm = 0;
    uint32_t total_events() const {
        return (uint32_t)notes_on_count + notes_off_count + cc_count + at_count;
    }
};

String get_loop_path(int loop_id);

// -1 if filename is not the v2 pattern loop_<digits>.bin
int parse_loop_filename(const String &filename);

void ensure_loops_folder();
int cleanup_orphan_loops(const std::vector<int> &valid_loop_ids);

// Full validation of a v2 loop file: magic + exact size + body CRC-32. Used by the
// web-upload path (PUT_LOOP_FILE_CHUNK) before installing an uploaded file — the same
// checks load_loop_from_flash applies, but without staging events into RAM.
bool verify_loop_file(const String &file_path);

// Save all of a loop's event streams + metadata; returns filename ("" on failure / empty loop)
String save_loop_to_flash(const MidiLoop &loop, int loop_id);

LoopHeaderInfo load_loop_header(const String &file_path);

// Load all event streams into the loop's storages; false = invalid file (magic/size/CRC),
// storages left empty. Metadata (type/ticks/bpm) comes from load_loop_header — the caller
// needs loop_type before constructing the MidiLoop anyway.
bool load_loop_from_flash(const String &file_path, MidiLoop &loop);

void init(); // tmp-file recovery + registers orphan-cleanup callback with settings

} // namespace loop_storage
