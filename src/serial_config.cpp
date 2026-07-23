#include "serial_config.h"
#include <ArduinoJson.h>
#include <LittleFS.h>
#include <vector>
#include <algorithm>
#include "constants.h"
#include "ticks.h"
#include "settings.h"
#include "test_hooks.h"
#include "loop_storage.h"
#include "fw_version.h"
#include "display.h"

SerialConfigHandler serial_handler;

static const uint32_t PING_TIMEOUT_MS = 6000;
static const size_t CHUNK_SIZE = 512;
static const char *PRESETS_FILE = "/presets.json";
static const char *PRESETS_TMP = "/presets_tmp.json";
static const char *SC_LOOPS_DIR = "/loops";
static const size_t NAME_MAX = 10;

// Keys never shown to or written by the UI
static bool is_reserved(const String &name) {
    return name == "STARTUP_PRESET" || name == "next_loop_id" || name == "*NEW*";
}

// Keys stripped from incoming SET_PRESET data — recomputed on boot or read-only
static const char *STRIP_ON_WRITE[] = {
    "settings_menu_option_indices",
    "midi_settings_page_indices",
    "loops_to_load",   // runtime variable, never in file
    "velocity_mapped", // runtime state, never in file
};

static bool load_presets_doc(JsonDocument &doc) {
    File f = LittleFS.open(PRESETS_FILE, "r");
    if (!f) {
        return false;
    }
    bool ok = !deserializeJson(doc, f);
    f.close();
    return ok;
}

// Write via temp file to protect against interrupted writes.
// Serialize to RAM first, then ONE bulk f.write() — serializeJson(doc, file)
// streams a byte at a time and stalls the whole device for many seconds
// (same fix as settings.cpp write_presets_file).
static bool save_presets_doc(const JsonDocument &doc) {
    String out;
    serializeJson(doc, out);

    // Runs in one loop() pass under the 8.3 s watchdog — keep the feeds even
    // though LittleFS ops are ~ms (they were ~0.5-2 s each on FatFS).
    rp2040.wdt_reset();
    File f = LittleFS.open(PRESETS_TMP, "w");
    if (!f) {
        return false;
    }
    size_t written = f.write((const uint8_t *)out.c_str(), out.length());
    f.close();
    rp2040.wdt_reset();
    if (written != out.length()) {
        // Same rule as settings.cpp write_presets_file: never leave a truncated tmp
        // behind — boot-side recovery promotes any tmp it finds when presets.json is
        // missing, and a half-written one must not be a candidate.
        LittleFS.remove(PRESETS_TMP);
        return false;
    }
    LittleFS.remove(PRESETS_FILE);
    rp2040.wdt_reset();
    return LittleFS.rename(PRESETS_TMP, PRESETS_FILE);
}

static String base64_encode(const uint8_t *data, size_t len) {
    static const char tbl[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    String out;
    out.reserve(((len + 2) / 3) * 4);
    for (size_t i = 0; i < len; i += 3) {
        uint32_t n = data[i] << 16;
        if (i + 1 < len) n |= data[i + 1] << 8;
        if (i + 2 < len) n |= data[i + 2];
        out += tbl[(n >> 18) & 63];
        out += tbl[(n >> 12) & 63];
        out += (i + 1 < len) ? tbl[(n >> 6) & 63] : '=';
        out += (i + 2 < len) ? tbl[n & 63] : '=';
    }
    return out;
}

// Inverse of base64_encode for the upload path (PUT_LOOP_FILE_CHUNK). Returns the
// decoded byte count, or -1 on any malformed input (bad char, bad length, data after
// padding). max_out bounds the write; input longer than that is rejected, not clipped.
static int base64_decode(const String &b64, uint8_t *out, size_t max_out) {
    auto val = [](char c) -> int {
        if (c >= 'A' && c <= 'Z') return c - 'A';
        if (c >= 'a' && c <= 'z') return c - 'a' + 26;
        if (c >= '0' && c <= '9') return c - '0' + 52;
        if (c == '+') return 62;
        if (c == '/') return 63;
        return -1;
    };
    size_t len = b64.length();
    if (len == 0 || (len & 3) != 0) {
        return -1;
    }
    size_t pad = (b64[len - 1] == '=') ? ((b64[len - 2] == '=') ? 2 : 1) : 0;
    size_t out_len = (len / 4) * 3 - pad;
    if (out_len > max_out) {
        return -1;
    }
    size_t o = 0;
    for (size_t i = 0; i < len; i += 4) {
        int v[4];
        for (int j = 0; j < 4; j++) {
            char c = b64[i + j];
            if (c == '=') {
                // '=' only legal in the final group's last two slots
                v[j] = 0;
                if (i + 4 < len || j < 2 || (j == 2 && b64[i + 3] != '=')) {
                    return -1;
                }
            } else {
                v[j] = val(c);
                if (v[j] < 0) {
                    return -1;
                }
            }
        }
        uint32_t n = (v[0] << 18) | (v[1] << 12) | (v[2] << 6) | v[3];
        if (o < out_len) out[o++] = (n >> 16) & 0xFF;
        if (o < out_len) out[o++] = (n >> 8) & 0xFF;
        if (o < out_len) out[o++] = n & 0xFF;
    }
    return (int)out_len;
}

bool SerialConfigHandler::is_locked() {
    if (_locked && (uint32_t)(ticks::ticks_ms() - _last_ping) > PING_TIMEOUT_MS) {
        _locked = false;
    }
    return _locked;
}

bool SerialConfigHandler::update() {
    // Check ping timeout
    if (_locked && (uint32_t)(ticks::ticks_ms() - _last_ping) > PING_TIMEOUT_MS) {
        _locked = false;
    }

    if (!Serial.available()) {
        return false;
    }

    R18_MARK(2); // CDC RX parse
    while (Serial.available()) {
        char c = (char)Serial.read();
        _buf += c;
        if (c == '\n' || c == '\r') {
            String line = _buf;
            line.trim();
            _buf = "";
            if (line.startsWith("CMD:")) {
                _handle(line.substring(4));
                // Deferred reboot into the UF2 bootloader: _handle() has queued+flushed the
                // ack (via _ok -> _rsp -> Serial.flush), so it's safe to yank USB now. A short
                // extra delay lets the host's read loop actually receive it before the port
                // vanishes. rebootToBootloader() never returns.
                if (_bootsel_pending) {
                    // Clear the frozen UI frame and show an "updating" takeover so the
                    // panel isn't stuck on the last screen for the whole flash. The new
                    // firmware fully redraws on its next boot. Delay covers both the ack
                    // reaching the host AND core 1 pushing this frame before USB drops.
                    display.show_fullscreen_message("Updating FW...", "Do not unplug");
                    Serial.flush();
                    delay(300);
                    rp2040.rebootToBootloader();
                }
                // Same deferred pattern for the plain REBOOT (web "Restart Now"):
                // soft reset, so the freshly saved preset loads. reboot() never returns.
                if (_reboot_pending) {
                    Serial.flush();
                    delay(100);
                    rp2040.reboot();
                }
                return true;
            }
        } else if (_buf.length() > 8192) { // runaway line guard
            _buf = "";
        }
    }
    return false;
}

void SerialConfigHandler::_handle(const String &cmd) {
    R18_MARK(3); // CMD dispatch/execution (incl. TEST_STATE JSON build)
#ifdef LOOPSTER_TEST_HOOKS
    test_hooks::count_cmd();
#endif
    if (cmd == "PING") {
        _locked = true;
        _last_ping = ticks::ticks_ms();
        // {"status":"ok","device":"loopster"} — the documented protocol always had the
        // device field but no implementation (Python included) ever sent it, leaving the
        // web UI's Connected badge stuck on "Connecting…" (W2). Built inline: PING is the
        // only command that identifies itself.
        JsonDocument d;
        d["status"] = "ok";
        d["device"] = "loopster";
        d["built"] = FW_BUILD_DATE; // "Mmm dd yyyy" — web UI compares to the GitHub release date
        String out;
        serializeJson(d, out);
        _rsp(out);
    } else if (cmd == "DISCONNECT") {
        _locked = false;
        _ok();
    } else if (cmd == "REBOOT") {
        // Clean soft reset requested by the web UI after a preset save, so the user
        // doesn't have to plug-cycle. Unlock, ack, then defer the reset to update()
        // so the ack flushes first (same dance as ENTER_BOOTSEL above).
        _locked = false;
        _ok();
        _reboot_pending = true;
    } else if (cmd == "ENTER_BOOTSEL") {
        // Reboot into the RP2040 UF2 bootloader (RPI-RP2 drive) so the user can drag on a new
        // firmware .uf2. Unlock first, ack, then defer the actual reboot to update() (see above)
        // so the ack flushes before USB drops. The web UI tears down its connection right after.
        _locked = false;
        _ok();
        _bootsel_pending = true;
    } else if (cmd == "GET_PRESET_NAMES") {
        _get_names();
    } else if (cmd.startsWith("GET_PRESET|")) {
        _get_preset(cmd.substring(11));
    } else if (cmd.startsWith("SET_PRESET|")) {
        String rest = cmd.substring(11);
        int sep = rest.indexOf('|');
        if (sep < 0) {
            _err("Malformed command", "internal_error");
            return;
        }
        _set_preset(rest.substring(0, sep), rest.substring(sep + 1));
    } else if (cmd.startsWith("RENAME_PRESET|")) {
        String rest = cmd.substring(14);
        int sep = rest.indexOf('|');
        if (sep < 0) {
            _err("Malformed command", "internal_error");
            return;
        }
        _rename(rest.substring(0, sep), rest.substring(sep + 1));
    } else if (cmd.startsWith("DELETE_PRESET|")) {
        _delete(cmd.substring(14));
    } else if (cmd.startsWith("SET_STARTUP|")) {
        _set_startup(cmd.substring(12));
    } else if (cmd == "LIST_LOOP_FILES") {
        _list_loops();
    } else if (cmd.startsWith("GET_LOOP_FILE_CHUNK|")) {
        String rest = cmd.substring(20);
        int sep = rest.lastIndexOf('|');
        if (sep < 0) {
            _err("Malformed command", "internal_error");
            return;
        }
        String fname = rest.substring(0, sep);
        // Reject path traversal / escapes out of /loops (item 21).
        if (fname.indexOf('/') >= 0 || fname.indexOf('\\') >= 0 || fname.indexOf("..") >= 0) {
            _err("Invalid filename", "invalid_name");
            return;
        }
        _get_chunk(String(SC_LOOPS_DIR) + "/" + fname, rest.substring(sep + 1).toInt());
    } else if (cmd.startsWith("PUT_LOOP_FILE_CHUNK|")) {
        // PUT_LOOP_FILE_CHUNK|<name>|<offset>|<done 0/1>|<base64> — the write inverse of
        // GET_LOOP_FILE_CHUNK, added for the web UI's .mid-to-pad import. Chunks stream
        // to <name>.tmp; done=1 validates (magic/size/CRC) then installs atomically.
        String rest = cmd.substring(20);
        int s1 = rest.indexOf('|');
        int s2 = (s1 < 0) ? -1 : rest.indexOf('|', s1 + 1);
        int s3 = (s2 < 0) ? -1 : rest.indexOf('|', s2 + 1);
        if (s3 < 0) {
            _err("Malformed command", "internal_error");
            return;
        }
        _put_chunk(rest.substring(0, s1), rest.substring(s1 + 1, s2).toInt(),
                   rest.substring(s2 + 1, s3).toInt() != 0, rest.substring(s3 + 1));
    } else if (cmd.startsWith("GET_PRESETS_RAW_CHUNK|")) {
        _get_chunk(PRESETS_FILE, cmd.substring(22).toInt());
#ifdef LOOPSTER_TEST_HOOKS
    } else if (cmd.startsWith("TEST_")) {
        _rsp(test_hooks::handle(cmd));
        test_hooks::after_response(); // deferred reboot, after RSP is out
#endif
    } else {
        _err("Unknown command", "unknown_command");
    }
}

// Bounded CDC TX (R18). Adafruit_USBD_CDC::write() busy-waits in a yield() loop —
// with no watchdog feed — whenever the TX FIFO is full and the port still counts as
// connected. Under heavy USB-MIDI RX the FIFO can stop draining long enough to trip
// the 8 s watchdog (proven on-device: flood deaths always land on a CDC exchange,
// reboot back-computed from uptime_ms). Write only what already fits in the FIFO,
// feed the watchdog while waiting for space, and give up after a no-progress
// deadline — a truncated RSP (host-side timeout, retryable) beats a rebooted
// instrument mid-performance.
static const uint32_t TX_STALL_DEADLINE_MS = 500;

static bool cdc_write_bounded(const char *buf, size_t len) {
    size_t sent = 0;
    uint32_t last_progress = ticks::ticks_ms();
    while (sent < len) {
        if (!Serial) {
            return false; // host closed the port mid-response
        }
        int fifo_space = Serial.availableForWrite();
        if (fifo_space > 0) {
            size_t n = min((size_t)fifo_space, len - sent);
            Serial.write((const uint8_t *)buf + sent, n); // fits -> returns without waiting
            sent += n;
            last_progress = ticks::ticks_ms();
        } else {
            rp2040.wdt_reset(); // waiting on the host, not hung
            yield();            // let TinyUSB run and drain the FIFO
            if ((uint32_t)(ticks::ticks_ms() - last_progress) > TX_STALL_DEADLINE_MS) {
                return false; // host stopped draining; drop the tail rather than hang
            }
        }
    }
    return true;
}

// Q1 companion to cdc_write_bounded: fire-and-forget log prints never wait at all —
// not even the 500 ms deadline — because unlike an RSP there is no host retry
// protocol; a dropped log line costs nothing, a stalled pass costs jitter on stage.
void cdc_log(const char *fmt, ...) {
    if (!Serial) {
        return; // no host (or port closed): writes would buffer/block pointlessly
    }
    int fifo_space = Serial.availableForWrite();
    if (fifo_space <= 0) {
        return; // FIFO full (host not draining): drop the line, never wait
    }
    char buf[192];
    va_list args;
    va_start(args, fmt);
    int len = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    if (len <= 0) {
        return;
    }
    size_t n = min((size_t)len, sizeof(buf) - 1);
    Serial.write((const uint8_t *)buf, min(n, (size_t)fifo_space)); // fits -> returns without waiting
}

void SerialConfigHandler::_rsp(const String &json_line) {
#ifdef LOOPSTER_TEST_HOOKS
    uint32_t t0 = micros();
#endif
    R18_MARK(4); // RSP TX header
    bool complete = cdc_write_bounded("RSP:", 4);
    if (complete) {
        R18_MARK(5); // RSP TX body
        complete = cdc_write_bounded(json_line.c_str(), json_line.length());
    }
    if (complete) {
        R18_MARK(6); // RSP TX newline
        complete = cdc_write_bounded("\n", 1);
    }
    R18_MARK(7); // RSP flush
    // Hand the FIFO to the endpoint (tud_cdc_n_write_flush — non-blocking). Keeps the
    // 2026-07-05 truncation fix: responses written while USB MIDI traffic is in flight
    // otherwise get truncated/corrupted around the FIFO boundary.
    Serial.flush();
    R18_MARK(2); // back to CDC RX context
#ifdef LOOPSTER_TEST_HOOKS
    test_hooks::note_rsp_tx(micros() - t0, !complete);
    test_hooks::count_rsp();
#else
    (void)complete;
#endif
}

void SerialConfigHandler::_ok(bool with_restart, bool needs_restart) {
    JsonDocument d;
    d["status"] = "ok";
    if (with_restart) {
        d["needs_restart"] = needs_restart;
    }
    String out;
    serializeJson(d, out);
    _rsp(out);
}

void SerialConfigHandler::_err(const String &msg, const char *code) {
    JsonDocument d;
    d["error"] = msg;
    d["code"] = code;
    String out;
    serializeJson(d, out);
    _rsp(out);
}

String SerialConfigHandler::_validate_name(const String &name) {
    if (name.length() == 0) {
        return "Name cannot be empty";
    }
    if (name.length() > NAME_MAX) {
        return "Max " + String(NAME_MAX) + " chars";
    }
    if (is_reserved(name)) {
        return "Reserved name";
    }
    for (size_t i = 0; i < name.length(); i++) {
        unsigned char ch = (unsigned char)name[i];
        if (!(isalpha(ch) || isdigit(ch) || ch == '_')) {
            return "Use A-Z, 0-9, _ only";
        }
    }
    return "";
}

void SerialConfigHandler::_get_names() {
    JsonDocument doc;
    if (!load_presets_doc(doc)) {
        _err("Cannot read presets", "io_error");
        return;
    }
    std::vector<String> names;
    for (JsonPairConst kv : doc.as<JsonObjectConst>()) {
        String k = kv.key().c_str();
        if (!is_reserved(k)) {
            names.push_back(k);
        }
    }
    std::sort(names.begin(), names.end(), [](const String &a, const String &b) {
        return strcmp(a.c_str(), b.c_str()) < 0;
    });

    JsonDocument out_doc;
    JsonArray arr = out_doc["names"].to<JsonArray>();
    for (const String &n : names) {
        arr.add(n);
    }
    out_doc["startup"] = doc["STARTUP_PRESET"] | "";
    String out;
    serializeJson(out_doc, out);
    _rsp(out);
}

void SerialConfigHandler::_get_preset(const String &name) {
    JsonDocument doc;
    if (!load_presets_doc(doc)) {
        _err("Cannot read presets", "io_error");
        return;
    }
    if (doc[name].isNull()) {
        _err("Preset not found", "not_found");
        return;
    }
    String out;
    serializeJson(doc[name], out);
    _rsp(out);
}

void SerialConfigHandler::_set_preset(const String &name, const String &json_str) {
    String err = _validate_name(name);
    if (err.length()) {
        _err(err, "invalid_preset_name");
        return;
    }

    // Secondary heap guard (item 1): refuse below the floor instead of risking an allocation
    // panic — the web UI gets a clear error and can retry.
    if (rp2040.getFreeHeap() < C::HEAP_FLOOR_BYTES) {
        _err("Low memory", "low_memory");
        return;
    }

    JsonDocument all_p;
    if (!load_presets_doc(all_p)) {
        _err("Cannot read presets", "io_error");
        return;
    }

    // Preset-count cap (item 18): a genuinely NEW preset past the cap is refused; overwriting
    // an existing preset is always allowed.
    if (all_p[name].isNull()) {
        int preset_count = 0;
        for (JsonPairConst kv : all_p.as<JsonObjectConst>()) {
            if (!is_reserved(kv.key().c_str())) {
                preset_count++;
            }
        }
        if (preset_count >= C::MAX_PRESETS) {
            _err("Preset limit reached", "preset_limit");
            return;
        }
    }

    // Parse the incoming preset DIRECTLY into its slot (item 17b) — the old code held a
    // separate `incoming` JsonDocument AND copied it into all_p via `all_p[name] = incoming`,
    // doubling peak RAM. deserializeJson() into a variant destination replaces the slot's
    // contents, so an existing preset is overwritten cleanly. next_loop_id stays at root.
    if (deserializeJson(all_p[name].to<JsonVariant>(), json_str)) {
        _err("Invalid JSON", "invalid_json");
        return;
    }

    // Strip derived/read-only fields from the freshly-parsed slot
    JsonObject slot = all_p[name].as<JsonObject>();
    for (const char *key : STRIP_ON_WRITE) {
        slot.remove(key);
    }

    if (!save_presets_doc(all_p)) {
        _err("Cannot write presets", "io_error");
        return;
    }
    _ok(true, true);
}

void SerialConfigHandler::_rename(const String &old_name, const String &new_name) {
    String err = _validate_name(new_name);
    if (err.length()) {
        _err(err, "invalid_preset_name");
        return;
    }
    if (is_reserved(old_name)) {
        _err("Cannot rename reserved key", "invalid_preset_name");
        return;
    }

    JsonDocument all_p;
    if (!load_presets_doc(all_p)) {
        _err("Cannot read presets", "io_error");
        return;
    }
    if (all_p[old_name].isNull()) {
        _err("Preset not found", "not_found");
        return;
    }

    // Case-insensitive uniqueness check
    String new_lower = new_name;
    new_lower.toLowerCase();
    for (JsonPairConst kv : all_p.as<JsonObjectConst>()) {
        String k = kv.key().c_str();
        if (is_reserved(k) || k == old_name) {
            continue;
        }
        String kl = k;
        kl.toLowerCase();
        if (kl == new_lower) {
            _err("Name already taken", "name_taken");
            return;
        }
    }

    // Rebuild object preserving key order
    JsonDocument new_p;
    for (JsonPairConst kv : all_p.as<JsonObjectConst>()) {
        String k = kv.key().c_str();
        new_p[(k == old_name) ? new_name : k] = kv.value();
    }
    if ((new_p["STARTUP_PRESET"] | String("")) == old_name) {
        new_p["STARTUP_PRESET"] = new_name;
    }

    if (!save_presets_doc(new_p)) {
        _err("Cannot write presets", "io_error");
        return;
    }
    _ok(true, true);
}

void SerialConfigHandler::_delete(const String &name) {
    if (is_reserved(name)) {
        _err("Cannot delete reserved key", "invalid_preset_name");
        return;
    }

    JsonDocument all_p;
    if (!load_presets_doc(all_p)) {
        _err("Cannot read presets", "io_error");
        return;
    }
    if (all_p[name].isNull()) {
        _err("Preset not found", "not_found");
        return;
    }
    // The boot path loads STARTUP_PRESET; deleting it would strand boot on a
    // missing preset. The web UI explains this instead of offering Delete.
    if ((all_p["STARTUP_PRESET"] | String("")) == name) {
        _err("Set another preset as startup first", "startup_preset");
        return;
    }

    all_p.remove(name);
    if (!save_presets_doc(all_p)) {
        _err("Cannot write presets", "io_error");
        return;
    }
    rp2040.wdt_reset();
    settings.cleanup_orphan_loops(); // reclaim the deleted preset's loop .bin files
    rp2040.wdt_reset();
    _ok(true, false);
}

void SerialConfigHandler::_set_startup(const String &name) {
    JsonDocument all_p;
    if (!load_presets_doc(all_p)) {
        _err("Cannot read presets", "io_error");
        return;
    }
    if (all_p[name].isNull() || is_reserved(name)) {
        _err("Preset not found", "not_found");
        return;
    }
    all_p["STARTUP_PRESET"] = name;
    if (!save_presets_doc(all_p)) {
        _err("Cannot write presets", "io_error");
        return;
    }
    _ok(true, false);
}

void SerialConfigHandler::_list_loops() {
    JsonDocument out_doc;
    JsonArray files = out_doc["files"].to<JsonArray>();
    Dir dir = LittleFS.openDir(SC_LOOPS_DIR);
    while (dir.next()) {
        JsonObject f = files.add<JsonObject>();
        f["name"] = dir.fileName();
        f["size"] = (uint32_t)dir.fileSize();
    }
    String out;
    serializeJson(out_doc, out);
    _rsp(out);
}

void SerialConfigHandler::_get_chunk(const String &filepath, int offset) {
    if (offset < 0) {
        offset = 0; // clamp negative offset (item 21)
    }
    File f = LittleFS.open(filepath, "r");
    if (!f) {
        _err("File not found", "not_found");
        return;
    }
    f.seek(offset);
    uint8_t chunk[CHUNK_SIZE];
    size_t n = f.read(chunk, CHUNK_SIZE);
    f.close();

    JsonDocument out_doc;
    out_doc["data"] = base64_encode(chunk, n);
    out_doc["done"] = n < CHUNK_SIZE;
    out_doc["offset"] = offset;
    String out;
    serializeJson(out_doc, out);
    _rsp(out);
}

// Upload one chunk of a v2 loop file (web .mid import). Chunks stream in order to
// /loops/<name>.tmp; the final chunk (done) validates the whole file with the loader's
// own checks and installs it with the save path's remove+rename dance, so a torn or
// garbage upload can never land under a name the loader trusts. The ack carries
// put_offset so the web dispatcher can tell it apart from a PING ack.
void SerialConfigHandler::_put_chunk(const String &fname, int offset, bool done, const String &b64) {
    // Same traversal guard as GET_LOOP_FILE_CHUNK, plus the strict v2 naming rule:
    // cleanup_orphan_loops sweeps anything in /loops that isn't loop_<digits>.bin,
    // so accepting another name would just feed the GC.
    if (fname.indexOf('/') >= 0 || fname.indexOf('\\') >= 0 || fname.indexOf("..") >= 0 ||
        loop_storage::parse_loop_filename(fname) <= 0) {
        _err("Invalid filename", "invalid_name");
        return;
    }
    if (offset < 0) {
        _err("Bad offset", "bad_offset");
        return;
    }
    if (rp2040.getFreeHeap() < C::HEAP_FLOOR_BYTES) {
        _err("Low memory", "low_memory");
        return;
    }

    uint8_t data[CHUNK_SIZE];
    int n = base64_decode(b64, data, sizeof(data));
    if (n < 0 || (n == 0 && !done)) {
        _err("Invalid base64", "invalid_data");
        return;
    }

    loop_storage::ensure_loops_folder();
    String tmppath = String(SC_LOOPS_DIR) + "/" + fname + ".tmp";

    // Free-space check before every write (mirrors save_loop_to_flash's item-16 guard):
    // a full FS silently truncates, and the host has no other way to know.
    FSInfo info;
    rp2040.wdt_reset();
    if (!LittleFS.info(info) || info.totalBytes - info.usedBytes < (uint64_t)n + 8 * 1024) {
        LittleFS.remove(tmppath);
        _err("Flash full", "flash_full");
        return;
    }

    File f = LittleFS.open(tmppath, offset == 0 ? "w" : "a");
    if (!f) {
        _err("Cannot open file", "io_error");
        return;
    }
    // Chunks must arrive in order; a resent/skipped chunk shows up as a size mismatch.
    // The tmp is kept — the host recovers by restarting the upload at offset 0.
    if (offset > 0 && (int)f.size() != offset) {
        f.close();
        _err("Bad offset", "bad_offset");
        return;
    }
    bool wrote = (n == 0) || ((int)f.write(data, n) == n);
    f.close();
    rp2040.wdt_reset();
    if (!wrote) {
        LittleFS.remove(tmppath);
        _err("Write failed", "io_error");
        return;
    }

    if (done) {
        if (!loop_storage::verify_loop_file(tmppath)) {
            LittleFS.remove(tmppath);
            _err("Invalid loop file", "invalid_loop");
            return;
        }
        String finalpath = String(SC_LOOPS_DIR) + "/" + fname;
        LittleFS.remove(finalpath); // rename won't reliably overwrite an existing destination
        rp2040.wdt_reset();
        if (!LittleFS.rename(tmppath, finalpath)) {
            // Keep the tmp: the final is already gone, and "final missing + tmp valid"
            // is exactly what boot-side recovery promotes (same rule as save_loop_to_flash).
            _err("Install failed", "io_error");
            return;
        }
    }

    JsonDocument d;
    d["status"] = "ok";
    d["put_offset"] = offset;
    d["received"] = n;
    if (done) {
        d["installed"] = true;
    }
    String out;
    serializeJson(d, out);
    _rsp(out);
}

