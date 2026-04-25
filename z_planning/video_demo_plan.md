# Loopster CC Modulation Demo — Recording Plan

**Target length:** ~8 minutes  
**Format:** Single video, 6 sections  
**Synth:** Novation Summit (initialized patch)  
**DAW:** Ableton Live  

---

## 🔧 PREP CHECKLIST (do all of this BEFORE hitting record)

### Ableton
- [ ] Turn ON **"Reduce Latency When Monitoring"** setting
- [ ] Create MIDI channel: **MIDI In** from USB / U6 MIDI Pro Port 1 → **MIDI Out** to Loopster
- [ ] Create MIDI channel: **MIDI In** from Loopster → **MIDI Out** on U6 MIDI Pro Port 1
- [ ] Confirm bidirectional MIDI is working (play a note on Loopster, hear it on Summit and vice versa)
- [ ] Have a simple tempo set (something moderate, ~100-110 BPM)
- [ ] Transport **stopped** at start of each demo unless otherwise noted

### Novation Summit
- [ ] Go into settings → set **CC / NRPR** to **Receive and Transmit**
- [ ] Initialize a fresh patch before each demo section
- [ ] Default init patch setup every time:
  - All 3 oscillators set to **sine waves**
  - Oscillator 1, 2, 3 levels all at **~75%**
  - Filter frequency at **~90**
  - Amp envelope release **turned up** (long-ish tail)
  - No LFOs active — **emphasize on camera that the synth has NO modulation sources running; the Loopster does everything**

### Loopster
- [ ] Fresh plug-in (power cycle before filming)
- [ ] Confirm CC recording is enabled (Settings → CC Recording = True)
- [ ] Confirm Quantize CC = True (default)
- [ ] Know where the oneshot mode and "oneshot all at once" settings are so you can navigate quickly on camera

### General
- [ ] Do NOT use NRPN parameters (wave type buttons, filter shape) — they don't work reliably yet. Stick to standard CC knobs.
- [ ] For fast knob changes, plan to record **short loops** — otherwise long CC loops all restart together and lose the drift/competition effect
- [ ] Have a rough idea of which Summit knobs you'll use per pad so you're not fumbling on camera

---

## SECTION 1 — Intro (~45 sec)

**Goal:** Briefly explain what the Loopster is and what this video demonstrates.

- Quick shot of the Loopster + Summit setup
- Explain the concept in ~2-3 sentences:
  > "The Loopster is a MIDI loop controller. You can record MIDI notes and CC messages onto its 16 pads and play them back in loops. Today I'm going to show how you can use it as a modulation source — instead of using LFOs on your synth, the Loopster records and loops your knob movements to create evolving, layered textures."
- Mention the synth has **zero modulation active** — everything you hear changing is coming from the Loopster
- Briefly flash the MIDI routing (Ableton screen) so people understand the signal path

---

## SECTION 2 — Freeform Evolving Pad (~2 min)

**Goal:** Show slow, unquantized CC layering to create an organic, evolving pad sound.

**Loopster Settings:**
- MIDI Sync: **OFF**
- Quantize Loop: **OFF**
- Quantization amount: **N/A** (off)

**Steps:**

1. Play a chord or sustained notes on the Summit so there's sound to modulate
2. **Pad 1 — Filter sweep (slow):** Arm recording on a pad. Slowly sweep the filter from ~90 up to ~130, back down to ~70, back to ~90. Stop recording. ~5-8 seconds of movement.
3. Hit play — demonstrate the filter modulating on its own while you play keys
4. **Pad 2 — Fine pitch of Osc 2 (slow drift):** Record a slow downward drift of the fine pitch. Stop. Now two loops are running and drifting against each other.
5. **Pad 3 — Osc 3 FM amount:** Record gentle bumps of FM — mostly at zero, occasional quick rises and falls. Stop.
6. Play all three together while playing keys — let it breathe for a few seconds so viewers hear the evolving texture
7. **On camera, note:** "None of this is quantized — every loop is a different length, so the modulation never repeats the same way twice."

---

## SECTION 3 — Quantized Rhythmic CC (~2 min)

**Goal:** Show how quantizing CC messages adds rhythmic pulse to modulation. Contrast with the freeform section.

**Loopster Settings:**
- MIDI Sync: **ON**
- Quantize Loop: **1 bar**
- Start with Quantize amount: **OFF** for the first layer, then switch

**Steps:**

1. Start Ableton transport so Loopster gets clock
2. Initialize fresh Summit patch (same sine wave setup)
3. **Pad 1 — Unquantized filter baseline:** Record a slow filter sweep (~90 → ~130 → ~90) over one bar. Stop. This is the smooth foundation.
4. **Turn quantization to 1/4 notes**
5. **Pad 2 — Quantized filter jumps (1/4):** Set filter back to ~90. Arm recording, press play. Do deliberate jumps: snap up to ~120, back to 90, down to ~75, back to 90. Stop. The snapping should be audible as a rhythmic pulse.
6. Play both — point out the smooth sweep underneath with the rhythmic jumps on top
7. **Change quantization to 1/8 notes**
8. **Pad 3 — Osc 2↔3 FM amount (1/8):** Record quick FM bumps. This adds a grittier rhythmic texture.
9. **Change quantization to 1/16 notes**
10. **Pad 4 — Competing 1/16 noise:** Record another parameter (Osc 3 FM or fine pitch) with fast random movements at 1/16 quantization. Stop.
11. Play everything together — let it run for a few bars so viewers can hear the layered rhythmic modulation
12. **On camera, note:** "By layering different quantization values, you get this polyrhythmic modulation effect — all from recorded knob movements."

---

## SECTION 4 — Chaos Mode / Sound Design Explorer (~1.5 min)

**Goal:** Go full chaos. One knob per pad, short unquantized loops, all drifting. Use this as a sound design discovery tool.

**Loopster Settings:**
- MIDI Sync: **ON** (so loops start on beat)
- Quantize Loop: **OFF** (so loops are all different lengths — this is key)
- Quantization amount: **OFF**

**Steps:**

1. Initialize fresh Summit patch (same setup)
2. Explain the concept: "I'm going to record one knob per pad — short, fast, random movements — and let them all drift against each other."
3. Rapid-fire record across pads, ~2-4 seconds each, fast knob twists:
   - Pad 1: Filter (wide sweeps)
   - Pad 2: Filter again (fast random)
   - Pad 3: Amp attack
   - Pad 4: Amp release
   - Pad 5: Osc 1 volume
   - Pad 6: Osc 2 volume
   - Pad 7: Osc 3 volume
   - Pad 8: Osc 1 FM
   - (and more if it's going well — up to 16)
4. Play everything at once while holding notes/chords — let the chaos wash over
5. **Transition directly into Section 5** by stopping playback here

---

## SECTION 5 — Play / Stop / Freeze Technique (~1 min)

**Goal:** Demonstrate that stopping CC playback "freezes" the synth at whatever state it landed on — and restarting gives you a different frozen snapshot every time.

**Loopster Settings:** Same as Section 4 (keep the chaos pads loaded)

**Steps:**

1. Coming off Section 4 with all the chaotic CC loops running:
2. **Stop all clips** (stop Ableton transport or stop all pads). The synth goes silent or holds a static tone.
3. **On camera:** "When I stop, the synth freezes wherever the CC values happened to land. Every time I stop, it's a different sound."
4. **Press play** — chaos resumes for 2-3 seconds
5. **Stop** — different frozen sound
6. **Press play** — 2-3 seconds — **Stop** — another frozen sound
7. Do this 4-5 times quickly, playing a chord each time you freeze to demonstrate the different timbres
8. **On camera:** "This is basically a randomized preset generator. You could freeze it, tweak from there, save it — it's a sound design tool."

---

## SECTION 6 — Oneshot Modes & Chords (~1.5 min)

**Goal:** Show that pads don't have to loop. Demonstrate oneshot mode and oneshot-all-at-once for firing off recorded CC gestures or chords as one-time events.

**Steps:**

1. Brief explanation: "Everything so far has been looping. But you can also set pads to oneshot mode — they play once and stop."
2. **Oneshot single pad demo:**
   - Record a dramatic filter sweep on one pad (e.g., big sweep up and back down over ~2 sec)
   - Switch it to oneshot mode
   - Play a chord, tap the pad — the filter sweep fires once as a performative gesture
   - Tap it again — fires again. Show it's like a triggerable envelope.
3. **Chord recording demo:**
   - Record a chord (3-4 notes) onto a pad from the Loopster keys
   - Set to oneshot mode
   - Tap the pad — chord fires once
   - **On camera:** "You can record notes too, not just CC. Set it to oneshot and you've got triggerable chords."
4. **Oneshot all at once demo:**
   - Enable the "oneshot all at once" setting
   - Have a few pads loaded with different oneshot CC gestures
   - Hit one button — all fire simultaneously
   - **On camera:** "With oneshot-all-at-once, one tap fires every pad. Instant macro gesture."

---

## Outro (~15 sec)

- Quick recap: "So that's CC looping, quantized rhythmic modulation, chaos mode, and oneshot gestures — all from the Loopster."
- Point to links / more info / other videos
- Done

---

## ROUGH TIMING

| Section | Duration |
|---|---|
| 1 — Intro | 0:45 |
| 2 — Freeform Pad | 2:00 |
| 3 — Quantized Rhythmic | 2:00 |
| 4 — Chaos Mode | 1:30 |
| 5 — Play/Stop/Freeze | 1:00 |
| 6 — Oneshot & Chords | 1:30 |
| Outro | 0:15 |
| **Total** | **~8:00** |

---

## NOTES FOR EDITING

- Sections 4 → 5 should flow directly (don't cut between them)
- Sections 2 and 3 can be standalone — if one take is bad, reshoot just that section
- The "no LFOs" point should be hammered early (Intro + beginning of Section 2) so it's clear throughout
- Consider a small text overlay each time Loopster settings change (e.g., "Quantize: 1/4 notes") so viewers can follow
