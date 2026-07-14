#!/usr/bin/env python3
"""R18 probe v2: flood CCs while recording; on a TEST_STATE timeout, DON'T declare
death — keep retrying on the same port, then reconnect if needed, and read
uptime_ms + tx_bails + rsp_tx_max_us to discriminate:
  - uptime_ms small (< flood elapsed)  -> REAL watchdog reboot (fix failed)
  - uptime continuous + tx_bails > 0   -> device alive, RSP dropped by design (fix worked)
"""
import sys, time, json
sys.path.insert(0, "/Users/derrickthomin/\U0001F4DCDocuments Local/\U0001F4DDProject Writeups/DJBB Midi Loopster SMD RGB/Code - C Conversion/scripts")
from loopster_test import Device, DeviceError, cc

d = Device()
d.connect()
t_boot_probe = time.time()
st = d.state()
print(f"connected. uptime_ms={st['uptime_ms']} heap={st['heap_free']} "
      f"tx_bails={st.get('tx_bails')} rsp_tx_max_us={st.get('rsp_tx_max_us')}")
start_uptime = st["uptime_ms"]
t_start = time.time()

d.set_midi_sync(False)
d.clear_all()
d.drain_midi()

PADS = int(sys.argv[1]) if len(sys.argv) > 1 else 4
PER_PAD = 1600

for pad in range(PADS):
    d.record(pad)
    for i in range(PER_PAD):
        d.send(cc(1 + (i % 8), i % 128, 0))
        if i % 16 == 15:
            time.sleep(0.002)
        if i and i % 400 == 0:
            try:
                st = d.state()
                print(f"  pad {pad} @{i}: heap={st['heap_free']} loop_max_us={st['loop_max_us']} "
                      f"rsp_tx_max_us={st.get('rsp_tx_max_us')} tx_bails={st.get('tx_bails')}")
            except DeviceError as e:
                print(f"  !! pad {pad} @{i}: TEST_STATE timeout ({e}) — probing survival...")
                alive = False
                # retry on the SAME connection a few times
                for attempt in range(6):
                    time.sleep(2.0)
                    try:
                        st = d.state()
                        alive = True
                        break
                    except DeviceError:
                        continue
                if not alive:
                    print("  same-port retries failed; reconnecting...")
                    d.reconnect(timeout=20.0)
                    st = d.state()
                elapsed_ms = (time.time() - t_start) * 1000 + start_uptime
                up = st["uptime_ms"]
                print(f"  POST-TIMEOUT: uptime_ms={up} (expected ~{int(elapsed_ms)} if no reboot) "
                      f"tx_bails={st.get('tx_bails')} rsp_tx_max_us={st.get('rsp_tx_max_us')} "
                      f"heap={st['heap_free']}")
                if up < (time.time() - t_start) * 1000 * 0.5:
                    print("  ==> VERDICT: REAL REBOOT (watchdog) — hang NOT fixed")
                else:
                    print("  ==> VERDICT: device stayed up — dropped RSP only (bounded TX engaged)")
                sys.exit(2)
    # stop recording (auto-stop likely already happened at the 1024 cap)
    try:
        st = d.state()
        if st["recording"]:
            d.stop_record()
    except DeviceError:
        pass
    d.cmd("TEST_STOP_ALL")
    st = d.state(full=False)
    print(f"pad {pad} done: heap={st['heap_free']} tx_bails={st.get('tx_bails')} "
          f"rsp_tx_max_us={st.get('rsp_tx_max_us')}")

st = d.state()
print(f"SURVIVED {PADS} pads. uptime_ms={st['uptime_ms']} tx_bails={st.get('tx_bails')}")
d.cmd("TEST_CLEAR_ALL")
