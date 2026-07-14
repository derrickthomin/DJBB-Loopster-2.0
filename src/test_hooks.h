// Serial test hooks for the host-side test harness (scripts/loopster_test.py).
// Adds TEST_* commands to the CMD:/RSP: web-config protocol (serial_config.cpp).
// Every action delegates to the same public entry points the physical buttons
// call (add_remove_loop / handle_fn_press / toggle_loop_playstate / load_preset)
// — no synthetic input events, no private state access. Commands never PING, so
// the device keeps processing MIDI normally while under test.
// Compiled only when LOOPSTER_TEST_HOOKS is defined (see platformio.ini;
// delete that flag for a hookless release build).
#pragma once
#include <Arduino.h>

#ifdef LOOPSTER_TEST_HOOKS
namespace test_hooks {

// Handle a TEST_* command; returns the JSON to send as RSP: (never empty).
String handle(const String &cmd);

// Runs deferred actions (preset load + reboot) AFTER the response has been
// written, so the harness sees the ack before the CDC port drops.
void after_response();

// Call at the top of loop(): tracks worst iteration-to-iteration time so
// TEST_STATE can report loop_max_us / loop_iters (reset on each read).
// A starved main loop starves tud_task() and kills USB — this finds it.
void loop_heartbeat();

// CDC diagnostics, called by serial_config: count every CMD line handled and
// every RSP written. Reported (not reset) in TEST_STATE as cmds/rsps.
void count_cmd();
void count_rsp();

// R18 instrumentation: worst _rsp() TX time since last TEST_STATE (reset on read,
// reported as rsp_tx_max_us) + lifetime count of bounded-TX bail-outs (tx_bails).
void note_rsp_tx(uint32_t us, bool bailed);

// R18 hang localization: call once at the very top of setup() with "was this boot a
// genuine watchdog timeout". Captures the R18_MARK breadcrumb the dying pass left in
// watchdog scratch[0] (scratch registers survive watchdog resets); TEST_STATE reports
// it as hang_phase (0 = clean boot / no breadcrumb).
void capture_hang_phase(bool wdt_reset);

} // namespace test_hooks
#endif

// R18_MARK(phase): stamp the current hot-path section into watchdog scratch[0]
// (survives a watchdog reboot; scratch[0-3] are application-free, SDK uses [4-7]).
// One register write — cheap enough for every pass. Test builds only; release
// builds compile to nothing. Phases:
//   1=main loop  2=CDC RX parse  3=CMD handle  4/5/6=RSP TX hdr/body/nl
//   7=RSP flush  8=USB/UART MIDI RX drain
#ifdef LOOPSTER_TEST_HOOKS
#include "hardware/watchdog.h"
#define R18_MARK(phase) (watchdog_hw->scratch[0] = (0x18BEEF00u | (uint32_t)(phase)))
#else
#define R18_MARK(phase) ((void)0)
#endif
