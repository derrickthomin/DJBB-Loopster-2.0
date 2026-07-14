#include "loop_storage.h"
#include <LittleFS.h>
#include "settings.h"
#include "display.h"
#include "serial_config.h" // cdc_log (Q1 bounded prints)

namespace loop_storage {

// Refuse a save that would leave the partition this close to full — leaves margin for FS
// metadata and avoids writing right up to the last byte (item 16).
static constexpr uint64_t SAVE_HEADROOM_BYTES = 8 * 1024;

// Free bytes on the LittleFS partition. Returns 0 if the query fails, so a failed query is
// treated as "no room" and the save is refused rather than risking a truncated file.
static uint64_t fs_free_bytes() {
    FSInfo info;
    if (!LittleFS.info(info)) {
        return 0;
    }
    rp2040.wdt_reset(); // free-space scan can be slow; don't let it eat the budget
    return info.totalBytes - info.usedBytes;
}

// CRC-32 (IEEE/zlib polynomial, reflected), nibble-table variant — matches Python's
// zlib.crc32 and the JS implementations the web UI can check against.
static uint32_t crc32_update(uint32_t crc, const uint8_t *data, size_t len) {
    static const uint32_t table[16] = {
        0x00000000, 0x1DB71064, 0x3B6E20C8, 0x26D930AC,
        0x76DC4190, 0x6B6B51F4, 0x4DB26158, 0x5005713C,
        0xEDB88320, 0xF00F9344, 0xD6D6A3E8, 0xCB61B38C,
        0x9B64C2B0, 0x86D3D2D4, 0xA00AE278, 0xBDBDF21C};
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        crc = (crc >> 4) ^ table[crc & 0x0F];
        crc = (crc >> 4) ^ table[crc & 0x0F];
    }
    return crc;
}

uint8_t loop_type_to_code(const String &loop_type) {
    if (loop_type == "oneshot") return 1;
    if (loop_type == "hold") return 2;
    return 0;
}

const char *loop_type_name(uint8_t code) {
    switch (code) {
    case 1: return "oneshot";
    case 2: return "hold";
    default: return "loop";
    }
}

static String loop_file_name(int loop_id) {
    char buf[24];
    snprintf(buf, sizeof(buf), "loop_%04d.bin", loop_id);
    return String(buf);
}

String get_loop_path(int loop_id) { return String(LOOPS_DIR) + "/" + loop_file_name(loop_id); }

// -1 if filename is not the v2 pattern loop_<digits>.bin
int parse_loop_filename(const String &filename) {
    if (!filename.startsWith("loop_") || !filename.endsWith(".bin")) {
        return -1;
    }
    int start = 5;                        // after "loop_"
    int end = filename.length() - 4;      // before ".bin"
    if (end <= start) {
        return -1;
    }
    for (int i = start; i < end; i++) {
        if (!isDigit(filename[i])) {
            return -1;
        }
    }
    return filename.substring(start, end).toInt();
}

void ensure_loops_folder() {
    LittleFS.mkdir(LOOPS_DIR); // no-op if it already exists
}

int cleanup_orphan_loops(const std::vector<int> &valid_loop_ids) {
    ensure_loops_folder();
    int deleted_count = 0;

    Dir dir = LittleFS.openDir(LOOPS_DIR);
    std::vector<String> to_delete;
    while (dir.next()) {
        String filename = dir.fileName();
        if (filename.endsWith(".tmp")) {
            // .tmp files belong to boot recovery, never the sweep: one may be the kept
            // survivor of a failed rename (save_loop_to_flash) awaiting promotion.
            continue;
        }
        int file_loop_id = parse_loop_filename(filename);
        if (file_loop_id < 0) {
            // Not a v2 loop file: legacy 3-part names (loop_XXXX_notes/_cc/_at.bin) are
            // dead by decision, stray junk has no owner — sweep it all.
            to_delete.push_back(filename);
            continue;
        }
        bool valid = false;
        for (int id : valid_loop_ids) {
            if (id == file_loop_id) {
                valid = true;
                break;
            }
        }
        if (!valid) {
            to_delete.push_back(filename);
        }
    }
    for (const String &f : to_delete) {
        rp2040.wdt_reset(); // cheap insurance: many orphan removes in one loop() pass
        if (LittleFS.remove(String(LOOPS_DIR) + "/" + f)) {
            deleted_count++;
        }
    }
    return deleted_count;
}

// Validate a v2 loop file: magic + file size exactly matching the header-implied size.
// (CRC is checked at load; this is the cheap check used by boot-side tmp recovery.)
static bool loop_file_valid(const String &path) {
    File f = LittleFS.open(path, "r");
    if (!f) {
        return false;
    }
    size_t file_size = f.size();
    LoopHeaderV2 header;
    size_t n = f.read((uint8_t *)&header, sizeof(header));
    f.close();
    if (n < sizeof(header) || header.magic != LOOP_MAGIC) {
        return false;
    }
    size_t total = (size_t)header.notes_on_count + header.notes_off_count + header.cc_count + header.at_count;
    return file_size == sizeof(header) + total * sizeof(NotesEvent);
}

bool verify_loop_file(const String &file_path) {
    File f = LittleFS.open(file_path, "r");
    if (!f) {
        return false;
    }
    size_t file_size = f.size();
    LoopHeaderV2 header;
    if (f.read((uint8_t *)&header, sizeof(header)) < sizeof(header) || header.magic != LOOP_MAGIC) {
        f.close();
        return false;
    }
    size_t total = (size_t)header.notes_on_count + header.notes_off_count + header.cc_count + header.at_count;
    if (file_size != sizeof(header) + total * sizeof(NotesEvent)) {
        f.close();
        return false;
    }
    uint32_t crc = 0xFFFFFFFF;
    uint8_t buf[256];
    size_t remaining = total * sizeof(NotesEvent);
    size_t fed = 0;
    while (remaining > 0) {
        size_t n = f.read(buf, min(remaining, sizeof(buf)));
        if (n == 0) {
            f.close();
            return false; // short read despite the size check — treat as corrupt
        }
        crc = crc32_update(crc, buf, n);
        remaining -= n;
        if (((fed += n) & 1023) == 0) {
            rp2040.wdt_reset(); // biggest legal file is ~100 KB of reads in one pass
        }
    }
    f.close();
    return (crc ^ 0xFFFFFFFF) == header.body_crc32;
}

// Boot-side recovery for the atomic save: a power cut between remove(final) and
// rename(tmp->final) leaves only a complete tmp — promote it. Any other stranded tmp
// (incomplete write, or its final exists) is garbage — delete it.
static void recover_interrupted_loop_writes() {
    ensure_loops_folder();
    Dir dir = LittleFS.openDir(LOOPS_DIR);
    std::vector<String> tmps;
    while (dir.next()) {
        if (dir.fileName().endsWith(".tmp")) {
            tmps.push_back(dir.fileName());
        }
    }
    for (const String &fn : tmps) {
        rp2040.wdt_reset();
        String tmppath = String(LOOPS_DIR) + "/" + fn;
        String finalpath = tmppath.substring(0, tmppath.length() - 4);
        if (!LittleFS.exists(finalpath) && loop_file_valid(tmppath)) {
            LittleFS.rename(tmppath, finalpath);
        } else {
            LittleFS.remove(tmppath);
        }
    }
}

static NotesEvent notes_record(const ArrayBasedEventStorage &s, size_t i) {
    return NotesEvent{s.notes[i], s.velocities[i], s.packed_pad_channel[i], s.ticks[i]};
}

static ControllerEvent cc_record(const ArrayBasedCCStorage &s, size_t i) {
    return ControllerEvent{s.cc_nums[i], s.values[i], s.ticks[i], s.midi_channels[i]};
}

// Body CRC over the exact bytes the sections will contain — pure RAM pass, no flash I/O.
static uint32_t compute_body_crc(const MidiLoop &loop) {
    uint32_t crc = 0xFFFFFFFF;
    for (size_t i = 0; i < loop.notes_on.size(); i++) {
        NotesEvent ev = notes_record(loop.notes_on, i);
        crc = crc32_update(crc, (const uint8_t *)&ev, sizeof(ev));
    }
    for (size_t i = 0; i < loop.notes_off.size(); i++) {
        NotesEvent ev = notes_record(loop.notes_off, i);
        crc = crc32_update(crc, (const uint8_t *)&ev, sizeof(ev));
    }
    for (size_t i = 0; i < loop.cc_events.size(); i++) {
        ControllerEvent ev = cc_record(loop.cc_events, i);
        crc = crc32_update(crc, (const uint8_t *)&ev, sizeof(ev));
    }
    for (size_t i = 0; i < loop.aftertouch_events.size(); i++) {
        ControllerEvent ev = cc_record(loop.aftertouch_events, i);
        crc = crc32_update(crc, (const uint8_t *)&ev, sizeof(ev));
    }
    return crc ^ 0xFFFFFFFF;
}

static void write_notes_section(File &f, const ArrayBasedEventStorage &s, size_t &written, bool &ok) {
    for (size_t i = 0; i < s.size() && ok; i++) {
        NotesEvent ev = notes_record(s, i);
        ok = (f.write((const uint8_t *)&ev, sizeof(ev)) == sizeof(ev));
        if ((++written & 63) == 0) {
            rp2040.wdt_reset(); // watchdog stays armed during long event writes
        }
    }
}

static void write_cc_section(File &f, const ArrayBasedCCStorage &s, size_t &written, bool &ok) {
    for (size_t i = 0; i < s.size() && ok; i++) {
        ControllerEvent ev = cc_record(s, i);
        ok = (f.write((const uint8_t *)&ev, sizeof(ev)) == sizeof(ev));
        if ((++written & 63) == 0) {
            rp2040.wdt_reset();
        }
    }
}

String save_loop_to_flash(const MidiLoop &loop, int loop_id) {
    ensure_loops_folder();

    size_t total_count =
        loop.notes_on.size() + loop.notes_off.size() + loop.cc_events.size() + loop.aftertouch_events.size();
    if (total_count == 0) {
        return "";
    }

    String filename = loop_file_name(loop_id);
    String filepath = get_loop_path(loop_id);

    // Free-space check BEFORE writing (item 16): a full FS silently writes a truncated file
    // whose header count then lies to the load path (header says N events, file has fewer).
    size_t needed = sizeof(LoopHeaderV2) + total_count * sizeof(NotesEvent);
    if (fs_free_bytes() < needed + SAVE_HEADROOM_BYTES) {
        display.show_notification("Flash Full!");
        return "";
    }

    LoopHeaderV2 header = {};
    header.magic = LOOP_MAGIC;
    header.loop_type = loop_type_to_code(loop.loop_type);
    header.notes_on_count = (uint16_t)loop.notes_on.size();
    header.notes_off_count = (uint16_t)loop.notes_off.size();
    header.cc_count = (uint16_t)loop.cc_events.size();
    header.at_count = (uint16_t)loop.aftertouch_events.size();
    // total_midi_ticks can legitimately exceed u16: event ticks are clamped at 65535 in
    // add_event, but the loop LENGTH is not — a long silent tail never trips the event
    // clamp, and quantize_loop rounds the length UP to the next bar. Clamp instead of
    // wrapping to a near-zero length that corrupts playback after a save/load round-trip.
    int32_t ticks_clamped = loop.total_midi_ticks;
    if (ticks_clamped < 0) ticks_clamped = 0;
    if (ticks_clamped > 65535) ticks_clamped = 65535;
    header.total_ticks = (uint16_t)ticks_clamped;
    header.bpm_x10 = (uint16_t)(loop.recording_bpm * 10);
    header.body_crc32 = compute_body_crc(loop);

    // ATOMIC: write to a tmp file, then remove(final)+rename(tmp->final) — mirrors
    // settings.cpp's presets.json pattern. Power loss mid-write leaves the old final
    // intact; boot-side recovery in init() promotes a complete tmp whose final is gone.
    String tmppath = filepath + ".tmp";
    File f = LittleFS.open(tmppath, "w");
    if (!f) {
        cdc_log("[ERROR] Loop flash save failed\n");
        return "";
    }

    bool ok = (f.write((const uint8_t *)&header, sizeof(header)) == sizeof(header));
    size_t written = 0;
    write_notes_section(f, loop.notes_on, written, ok);
    write_notes_section(f, loop.notes_off, written, ok);
    write_cc_section(f, loop.cc_events, written, ok);
    write_cc_section(f, loop.aftertouch_events, written, ok);
    f.close();
    if (!ok) {
        LittleFS.remove(tmppath); // short write: drop the tmp; the old final survives
        display.show_notification("Save failed (flash)");
        return "";
    }
    LittleFS.remove(filepath); // rename won't reliably overwrite an existing destination
    rp2040.wdt_reset();
    if (!LittleFS.rename(tmppath, filepath)) {
        // KEEP the tmp: the final was already removed above, so deleting the tmp here
        // would lose both copies. "Final missing + tmp valid" is exactly the case boot
        // recovery promotes. Accumulation is bounded: a re-save of the same id opens the
        // same tmp name with "w" (truncates), and recovery promotes/purges every tmp at
        // boot — orphan cleanup deliberately skips .tmp files for this reason.
        display.show_notification("Save failed (flash)");
        return "";
    }
    return filename;
}

LoopHeaderInfo load_loop_header(const String &file_path) {
    LoopHeaderInfo info;
    File f = LittleFS.open(file_path, "r");
    if (!f) {
        return info;
    }
    size_t file_size = f.size();
    LoopHeaderV2 header;
    size_t n = f.read((uint8_t *)&header, sizeof(header));
    f.close();
    if (n < sizeof(header) || header.magic != LOOP_MAGIC) {
        return info;
    }
    size_t total = (size_t)header.notes_on_count + header.notes_off_count + header.cc_count + header.at_count;
    // Truncation check: header counts must match the actual file size, or a short file
    // would silently load fewer events than the header promises.
    if (file_size != sizeof(header) + total * sizeof(NotesEvent)) {
        return info;
    }
    info.valid = true;
    info.loop_type = header.loop_type;
    info.notes_on_count = header.notes_on_count;
    info.notes_off_count = header.notes_off_count;
    info.cc_count = header.cc_count;
    info.at_count = header.at_count;
    info.total_ticks = header.total_ticks;
    info.bpm = header.bpm_x10 / 10.0f;
    return info;
}

bool load_loop_from_flash(const String &file_path, MidiLoop &loop) {
    File f = LittleFS.open(file_path, "r");
    if (!f) {
        return false; // expected for stale preset metadata
    }

    size_t file_size = f.size();
    LoopHeaderV2 header;
    if (f.read((uint8_t *)&header, sizeof(header)) < sizeof(header) || header.magic != LOOP_MAGIC) {
        f.close();
        return false;
    }
    size_t total = (size_t)header.notes_on_count + header.notes_off_count + header.cc_count + header.at_count;
    if (file_size != sizeof(header) + total * sizeof(NotesEvent)) {
        f.close();
        return false; // truncated/corrupt — reject rather than play a partial loop
    }

    loop.notes_on.reserve(loop.notes_on.size() + header.notes_on_count);
    loop.notes_off.reserve(loop.notes_off.size() + header.notes_off_count);
    loop.cc_events.reserve(loop.cc_events.size() + header.cc_count);
    loop.aftertouch_events.reserve(loop.aftertouch_events.size() + header.at_count);

    uint32_t crc = 0xFFFFFFFF;
    bool ok = true;
    for (uint16_t i = 0; i < header.notes_on_count && ok; i++) {
        NotesEvent ev;
        ok = (f.read((uint8_t *)&ev, sizeof(ev)) == sizeof(ev));
        if (!ok) break;
        crc = crc32_update(crc, (const uint8_t *)&ev, sizeof(ev));
        loop.notes_on.add_event(ev.note, ev.velocity, ev.packed_pad_channel & 0x0F, ev.tick,
                                (ev.packed_pad_channel >> 4) & 0x0F);
    }
    for (uint16_t i = 0; i < header.notes_off_count && ok; i++) {
        NotesEvent ev;
        ok = (f.read((uint8_t *)&ev, sizeof(ev)) == sizeof(ev));
        if (!ok) break;
        crc = crc32_update(crc, (const uint8_t *)&ev, sizeof(ev));
        loop.notes_off.add_event(ev.note, ev.velocity, ev.packed_pad_channel & 0x0F, ev.tick,
                                 (ev.packed_pad_channel >> 4) & 0x0F);
    }
    for (uint16_t i = 0; i < header.cc_count && ok; i++) {
        ControllerEvent ev;
        ok = (f.read((uint8_t *)&ev, sizeof(ev)) == sizeof(ev));
        if (!ok) break;
        crc = crc32_update(crc, (const uint8_t *)&ev, sizeof(ev));
        loop.cc_events.add_event(ev.num, ev.value, ev.tick, ev.channel);
    }
    for (uint16_t i = 0; i < header.at_count && ok; i++) {
        ControllerEvent ev;
        ok = (f.read((uint8_t *)&ev, sizeof(ev)) == sizeof(ev));
        if (!ok) break;
        crc = crc32_update(crc, (const uint8_t *)&ev, sizeof(ev));
        loop.aftertouch_events.add_event(ev.num, ev.value, ev.tick, ev.channel);
    }
    f.close();

    if (!ok || (crc ^ 0xFFFFFFFF) != header.body_crc32) {
        // Bit-rot or short read: discard everything staged so the pad is skipped cleanly.
        loop.notes_on.clear();
        loop.notes_off.clear();
        loop.cc_events.clear();
        loop.aftertouch_events.clear();
        return false;
    }
    return true;
}

void init() {
    recover_interrupted_loop_writes(); // promote/purge stranded .tmp files before any read

    // Floor for next_loop_id: never re-issue an id whose file already exists on disk.
    // A regressed presets.json (corruption fallback, restored backup) would otherwise
    // hand out ids that atomically OVERWRITE loops other presets still reference.
    // Scanned after recovery so promoted tmps count; load_preset applies the floor.
    Dir dir = LittleFS.openDir(LOOPS_DIR);
    int max_id = 0;
    while (dir.next()) {
        int id = parse_loop_filename(dir.fileName());
        if (id > max_id) {
            max_id = id;
        }
    }
    settings.loop_id_floor = max_id + 1;

    settings.set_cleanup_orphans_callback(cleanup_orphan_loops);
}

} // namespace loop_storage
