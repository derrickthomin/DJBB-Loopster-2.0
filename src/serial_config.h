// Port of src/serial_config.py — Web Serial config protocol over USB CDC.
// THE PROTOCOL IS THE CONTRACT with docs/index.html — request/response
// framing (CMD:<cmd>\n -> RSP:<json>\n), command names, and JSON field names are
// kept identical. Device locks MIDI/input processing while connected; auto-unlocks
// 6 s after the last PING.
#pragma once
#include <Arduino.h>

class SerialConfigHandler {
public:
    // True while web UI is actively connected (ping keepalive active)
    bool is_locked();

    // Call from main loop. Reads available serial bytes, processes complete lines.
    // Returns true if a command was handled this call.
    bool update();

private:
    String _buf;
    bool _locked = false;
    uint32_t _last_ping = 0;
    // Set by the ENTER_BOOTSEL command; update() reboots into the UF2 bootloader AFTER the
    // ack has flushed over USB (rebooting inline would truncate the ack). Mirrors the
    // deferred-reboot pattern in test_hooks::after_response().
    bool _bootsel_pending = false;
    // Set by the REBOOT command (web UI "Restart Now" after a preset save); same deferred
    // pattern but a plain soft reset, so the freshly saved preset loads on the way back up.
    bool _reboot_pending = false;

    void _handle(const String &cmd);
    void _rsp(const String &json_line);
    void _ok(bool with_restart = false, bool needs_restart = false);
    void _err(const String &msg, const char *code);
    String _validate_name(const String &name); // "" = valid

    void _get_names();
    void _get_preset(const String &name);
    void _set_preset(const String &name, const String &json_str);
    void _rename(const String &old_name, const String &new_name);
    void _delete(const String &name);
    void _set_startup(const String &name);
    void _list_loops();
    void _get_chunk(const String &filepath, int offset);
    void _put_chunk(const String &fname, int offset, bool done, const String &b64);
};

extern SerialConfigHandler serial_handler;

// Never-blocking CDC print for runtime informational/debug output (Q1). Direct
// Serial.print*() busy-waits — with no watchdog feed — whenever the CDC TX FIFO is
// full but the host still holds the port open (frozen web page, laptop asleep with
// DTR asserted); >8.3 s of that trips the watchdog mid-performance. This formats
// into a stack buffer and writes only what fits in the FIFO right now, dropping the
// rest. Truncated log output beats a rebooted instrument. Safe to call whether or
// not a host is connected. Use for all runtime prints outside _rsp().
void cdc_log(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
