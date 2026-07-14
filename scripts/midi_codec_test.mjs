#!/usr/bin/env node
// Node test harness for the web UI's MIDI codecs (web_interface/index.html).
//
// The page's "MIDI codecs (pure functions)" section is extracted from index.html AT
// RUNTIME and evaluated here, so these tests always exercise the live page code —
// there is no copied-out snapshot to drift. A prior session's scratch version of this
// harness was lost; this one lives in scripts/ on purpose.
//
// Run:  node scripts/midi_codec_test.mjs
// Fixtures: every .mid in scripts/fixtures/ is auto-discovered (real DAW exports;
// used as ground truth for parse + discarded-event counting).
//
// No dependencies. Node >= 18.

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const INDEX_HTML = join(HERE, '..', 'web_interface', 'index.html');
const FIXTURES_DIR = join(HERE, 'fixtures');

// ---------------------------------------------------------------
// Extract + evaluate the page's codec section
// ---------------------------------------------------------------
const html = readFileSync(INDEX_HTML, 'utf8');
const START_MARK = '// MIDI codecs (pure functions)';
const END_MARK = '// MIDI import (drag .mid onto a pad)';
const startIdx = html.indexOf(START_MARK);
const endIdx = html.indexOf(END_MARK);
if (startIdx < 0 || endIdx < 0 || endIdx <= startIdx) {
    console.error('FATAL: codec section markers not found in index.html — the section was');
    console.error('renamed or reorganized. Update START_MARK/END_MARK in this harness.');
    process.exit(2);
}
const codecSrc = html.slice(startIdx, endIdx);

// btoa/atob shims (Node >= 16 has globals; keep the shim for portability)
if (typeof globalThis.btoa === 'undefined') {
    globalThis.btoa = (s) => Buffer.from(s, 'binary').toString('base64');
}
if (typeof globalThis.atob === 'undefined') {
    globalThis.atob = (b) => Buffer.from(b, 'base64').toString('binary');
}

const page = new Function(codecSrc + `
    return { crc32, bytesToBase64, parseSmf, smfToLoopBin, decodeLoopBin, loopBinToSmf,
             DEVICE_PPQN, TICKS_PER_BAR, LOOP_NOTES_LIMIT };
`)();

// ---------------------------------------------------------------
// Independent reference implementations (NOT copied from the page)
// ---------------------------------------------------------------

// Bitwise (table-free) CRC-32, so a shared table-generation bug can't hide.
function refCrc32(bytes) {
    let crc = 0xFFFFFFFF;
    for (const b of bytes) {
        crc ^= b;
        for (let k = 0; k < 8; k++) crc = (crc >>> 1) ^ (0xEDB88320 & -(crc & 1));
    }
    return (crc ^ 0xFFFFFFFF) >>> 0;
}

// Reference SMF reader: returns EVERY channel event (the page's parseSmf only keeps
// notes), so it can double-check both the export encoder and the discard counters.
function refReadSmf(bytes) {
    const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
    if (dv.getUint32(0) !== 0x4D546864) throw new Error('refReadSmf: no MThd');
    const format = dv.getUint16(8), ntrks = dv.getUint16(10), division = dv.getUint16(12);
    let pos = 8 + dv.getUint32(4);
    const events = [];
    let tempoUsPerQ = null;
    let trackName = null;
    let endTick = 0;
    while (pos + 8 <= b.length) {
        const len = dv.getUint32(pos + 4);
        const end = pos + 8 + len;
        if (dv.getUint32(pos) !== 0x4D54726B) { pos = end; continue; }
        let p = pos + 8, tick = 0, running = 0;
        const rv = () => {
            let v = 0, byte;
            do { byte = b[p++]; v = (v << 7) | (byte & 0x7F); } while (byte & 0x80);
            return v;
        };
        while (p < end) {
            tick += rv();
            let s = b[p];
            if (s & 0x80) { p++; running = s < 0xF0 ? s : 0; }
            else { s = running; if (!s) throw new Error('refReadSmf: dangling data byte'); }
            const kind = s & 0xF0, ch = s & 0x0F;
            if (s === 0xFF) {
                const meta = b[p++], ml = rv();
                if (meta === 0x51 && ml === 3 && tempoUsPerQ === null) {
                    tempoUsPerQ = (b[p] << 16) | (b[p + 1] << 8) | b[p + 2];
                }
                if (meta === 0x03 && trackName === null) {
                    trackName = String.fromCharCode(...b.subarray(p, p + ml));
                }
                if (meta === 0x2F) { endTick = Math.max(endTick, tick); p += ml; break; }
                p += ml;
            } else if (s === 0xF0 || s === 0xF7) { p += rv(); }
            else if (kind === 0x90) {
                const note = b[p++], vel = b[p++];
                events.push({ tick, type: vel > 0 ? 'on' : 'off', ch, note, vel });
            } else if (kind === 0x80) {
                const note = b[p++], vel = b[p++];
                events.push({ tick, type: 'off', ch, note, vel });
            } else if (kind === 0xB0) { events.push({ tick, type: 'cc', ch, num: b[p], value: b[p + 1] }); p += 2; }
            else if (kind === 0xE0) { events.push({ tick, type: 'pb', ch, lsb: b[p], msb: b[p + 1] }); p += 2; }
            else if (kind === 0xA0) { events.push({ tick, type: 'polyAt', ch, note: b[p], value: b[p + 1] }); p += 2; }
            else if (kind === 0xD0) { events.push({ tick, type: 'chanAt', ch, value: b[p] }); p += 1; }
            else if (kind === 0xC0) { events.push({ tick, type: 'prog', ch, num: b[p] }); p += 1; }
            else throw new Error('refReadSmf: unknown status 0x' + s.toString(16));
        }
        pos = end;
    }
    return { format, ntrks, division, tempoUsPerQ, trackName, events, endTick };
}

// Reference SMF writer for synthesizing test inputs. events: {tick, bytes:[...]},
// absolute ticks, pre-sorted by caller.
function buildSmf(division, events, opts = {}) {
    const track = [];
    const pushVar = (v) => {
        const st = [v & 0x7F];
        while ((v >>= 7) > 0) st.push((v & 0x7F) | 0x80);
        for (let i = st.length - 1; i >= 0; i--) track.push(st[i]);
    };
    if (opts.tempoUsPerQ) track.push(0, 0xFF, 0x51, 0x03, (opts.tempoUsPerQ >> 16) & 0xFF, (opts.tempoUsPerQ >> 8) & 0xFF, opts.tempoUsPerQ & 0xFF);
    let last = 0;
    for (const ev of events) {
        pushVar(ev.tick - last);
        last = ev.tick;
        track.push(...ev.bytes);
    }
    if (!opts.omitEot) { pushVar(opts.eotDelta || 0); track.push(0xFF, 0x2F, 0x00); }
    const out = new Uint8Array(22 + track.length);
    const dv = new DataView(out.buffer);
    dv.setUint32(0, 0x4D546864); dv.setUint32(4, 6);
    dv.setUint16(8, 0); dv.setUint16(10, 1); dv.setUint16(12, division);
    dv.setUint32(14, 0x4D54726B); dv.setUint32(18, track.length);
    out.set(track, 22);
    return out.buffer;
}

// Reference v2 loop-file builder (mirrors loop_storage.h independently of the page's
// encoder): header fields written by hand, CRC from the table-free refCrc32.
function buildLoopBin({ loopType = 0, notesOn = [], notesOff = [], cc = [], at = [], totalTicks, bpmX10 }) {
    const body = new Uint8Array((notesOn.length + notesOff.length + cc.length + at.length) * 5);
    const bdv = new DataView(body.buffer);
    let o = 0;
    for (const n of notesOn.concat(notesOff)) {
        body[o] = n.note; body[o + 1] = n.vel;
        body[o + 2] = ((n.ch & 0x0F) << 4) | (n.pad & 0x0F);
        bdv.setUint16(o + 3, n.tick, true); o += 5;
    }
    for (const c of cc.concat(at)) {
        body[o] = c.num; body[o + 1] = c.value;
        bdv.setUint16(o + 2, c.tick, true);
        body[o + 4] = c.ch & 0x0F; o += 5;
    }
    const file = new Uint8Array(20 + body.length);
    const fdv = new DataView(file.buffer);
    fdv.setUint16(0, 0x4C02, true);
    file[2] = loopType;
    fdv.setUint16(4, notesOn.length, true);
    fdv.setUint16(6, notesOff.length, true);
    fdv.setUint16(8, cc.length, true);
    fdv.setUint16(10, at.length, true);
    fdv.setUint16(12, totalTicks, true);
    fdv.setUint16(14, bpmX10, true);
    fdv.setUint32(16, refCrc32(body), true);
    file.set(body, 20);
    return file;
}

const on = (tick, ch, note, vel) => ({ tick, bytes: [0x90 | ch, note, vel] });
const off = (tick, ch, note) => ({ tick, bytes: [0x80 | ch, note, 0] });
const ccEv = (tick, ch, num, value) => ({ tick, bytes: [0xB0 | ch, num, value] });

// ---------------------------------------------------------------
// Tiny test runner
// ---------------------------------------------------------------
let passed = 0, failed = 0;
function test(name, fn) {
    try { fn(); passed++; console.log('  PASS  ' + name); }
    catch (e) { failed++; console.log('  FAIL  ' + name + '\n        ' + (e && e.message ? e.message : e)); }
}
function eq(actual, expected, what) {
    const a = JSON.stringify(actual), b = JSON.stringify(expected);
    if (a !== b) throw new Error((what || 'value') + ': got ' + a + ', want ' + b);
}
function throws(fn, msgPart, what) {
    try { fn(); } catch (e) {
        if (msgPart && !String(e.message).includes(msgPart)) {
            throw new Error((what || 'throw') + ': wrong message "' + e.message + '" (want ~"' + msgPart + '")');
        }
        return;
    }
    throw new Error((what || 'throw') + ': did not throw');
}

// ---------------------------------------------------------------
// 1. CRC-32 + base64 primitives
// ---------------------------------------------------------------
console.log('\n== primitives ==');
test('crc32 matches the IEEE/zlib check value for "123456789"', () => {
    const v = page.crc32(new Uint8Array([0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39]));
    eq(v >>> 0, 0xCBF43926, 'crc32("123456789")');
});
test('crc32 agrees with an independent bitwise implementation on random data', () => {
    for (let n = 0; n < 5; n++) {
        const data = new Uint8Array(257 + n * 31);
        for (let i = 0; i < data.length; i++) data[i] = (i * 7 + n * 13) & 0xFF;
        eq(page.crc32(data), refCrc32(data), 'crc parity, len ' + data.length);
    }
});
test('bytesToBase64 round-trips through atob', () => {
    const data = new Uint8Array(300);
    for (let i = 0; i < data.length; i++) data[i] = (i * 31) & 0xFF;
    const back = Uint8Array.from(atob(page.bytesToBase64(data)), (c) => c.charCodeAt(0));
    eq([...back], [...data], 'base64 round trip');
});

// ---------------------------------------------------------------
// 2. Import path: parseSmf + smfToLoopBin
// ---------------------------------------------------------------
console.log('\n== import (parseSmf -> smfToLoopBin -> decodeLoopBin) ==');
test('notes-only SMF: parse, rescale 480->24 PPQN, encode, decode', () => {
    const buf = buildSmf(480, [
        on(0, 0, 60, 100), off(480, 0, 60),      // quarter note at tick 0
        on(480, 1, 64, 90), off(960, 1, 64),     // quarter note at beat 2, other channel
    ], { tempoUsPerQ: 500000 });                  // 120 bpm
    const smf = page.parseSmf(buf);
    eq(smf.tpq, 480, 'tpq');
    eq(Math.round(smf.bpm), 120, 'bpm');
    eq(smf.notes.length, 2, 'note pairs');
    eq(smf.skipped, { cc: 0, pb: 0, at: 0 }, 'skipped counts (clean file)');

    const built = page.smfToLoopBin(smf, 5, 2, 100);
    const loop = page.decodeLoopBin(built.bytes);
    eq(loop.notesOn.length, 2, 'ons');
    eq(loop.notesOff.length, 2, 'offs');
    eq(loop.cc.length, 0, 'cc empty on import');
    eq(loop.at.length, 0, 'at empty on import');
    eq(loop.notesOn.map(n => n.tick), [0, 24], 'on ticks rescaled to 24 PPQN');
    eq(loop.notesOff.map(n => n.tick), [24, 48], 'off ticks rescaled');
    eq(loop.notesOn.map(n => n.ch), [2, 2], 'events re-stamped to target channel');
    eq(built.bytes[20 + 2] & 0x0F, 5, 'pad index in packed byte');
    eq(loop.totalTicks, page.TICKS_PER_BAR, 'length rounded up to one bar');
    eq(loop.bpm, 120, 'bpm from SMF tempo, not fallback');
});
test('CC / pitch-bend / aftertouch are discarded but counted', () => {
    const buf = buildSmf(96, [
        on(0, 0, 60, 100),
        ccEv(10, 0, 1, 64), ccEv(20, 0, 74, 100), ccEv(30, 2, 71, 5),
        { tick: 40, bytes: [0xE0, 0x00, 0x40] },              // pitch bend
        { tick: 50, bytes: [0xD0, 0x55] },                    // channel pressure
        { tick: 55, bytes: [0xA0, 60, 33] },                  // poly aftertouch
        { tick: 60, bytes: [0xC0, 7] },                       // program change (silent)
        off(96, 0, 60),
    ]);
    const smf = page.parseSmf(buf);
    eq(smf.notes.length, 1, 'note kept');
    eq(smf.skipped, { cc: 3, pb: 1, at: 2 }, 'skipped counts (prog change NOT counted)');
});
test('running status + velocity-0 note-off pairing', () => {
    // Hand-rolled track: status 0x90 once, then running-status on/on-vel0 pairs
    const track = [
        0x00, 0x90, 60, 100,   // on
        0x30, 62, 90,          // running status: on
        0x30, 60, 0,           // running status: vel 0 = off for 60
        0x30, 62, 0,           // off for 62
        0x00, 0xFF, 0x2F, 0x00,
    ];
    const out = new Uint8Array(22 + track.length);
    const dv = new DataView(out.buffer);
    dv.setUint32(0, 0x4D546864); dv.setUint32(4, 6);
    dv.setUint16(8, 0); dv.setUint16(10, 1); dv.setUint16(12, 96);
    dv.setUint32(14, 0x4D54726B); dv.setUint32(18, track.length);
    out.set(track, 22);
    const smf = page.parseSmf(out.buffer);
    eq(smf.notes.length, 2, 'two pairs via running status');
    eq(smf.notes.map(n => [n.note, n.onTick, n.offTick]).sort((a, b) => a[0] - b[0]),
       [[60, 0, 0x60], [62, 0x30, 0x90]], 'pairing ticks');
});
test('rejections: SMPTE, non-MIDI, too long, too many notes', () => {
    throws(() => page.parseSmf(buildSmf(0xE250, [on(0, 0, 60, 100), off(1, 0, 60)])),
           'SMPTE', 'SMPTE division');
    throws(() => page.parseSmf(new Uint8Array([1, 2, 3, 4]).buffer), 'not a MIDI', 'garbage');
    // 24 PPQN in = 1:1 out; u16 tick ceiling is 65535
    throws(() => page.smfToLoopBin(page.parseSmf(buildSmf(24, [on(0, 0, 60, 100), off(66000, 0, 60)])), 0, 0, 120),
           'too long', 'u16 tick ceiling');
    const many = [];
    for (let i = 0; i < page.LOOP_NOTES_LIMIT + 1; i++) {
        many.push(on(i, 0, 60, 100), off(i, 0, 60));
    }
    many.sort((a, b) => a.tick - b.tick);
    throws(() => page.smfToLoopBin(page.parseSmf(buildSmf(24, many)), 0, 0, 120),
           'too many notes', 'note cap');
});
test('CC-only file parses to zero notes with counted skips (no throw — the UI refuses it)', () => {
    // 2026-07-11: parseSmf no longer throws 'no notes' — importMidiToPad checks
    // notes.length===0 and shows a banner naming the skipped events instead of a
    // generic "Import failed". The codec's job is just to report what it saw.
    const smf = page.parseSmf(buildSmf(96, [ccEv(0, 0, 1, 1), ccEv(10, 0, 7, 100)]));
    eq(smf.notes.length, 0, 'no notes parsed');
    eq(smf.skipped.cc, 2, 'both CCs counted for the disclosure banner');
});

// ---------------------------------------------------------------
// 3. Export path: decodeLoopBin + loopBinToSmf carry CC and aftertouch
// ---------------------------------------------------------------
console.log('\n== export (v2 bin -> loopBinToSmf), CC/AT fidelity ==');
const RICH_LOOP = {
    notesOn:  [{ tick: 0, ch: 3, pad: 7, note: 60, vel: 100 }, { tick: 24, ch: 3, pad: 7, note: 64, vel: 90 }],
    notesOff: [{ tick: 24, ch: 3, pad: 7, note: 60, vel: 0 }, { tick: 48, ch: 3, pad: 7, note: 64, vel: 0 }],
    cc: [{ tick: 6, ch: 3, num: 1, value: 32 }, { tick: 12, ch: 3, num: 74, value: 90 }, { tick: 40, ch: 5, num: 71, value: 7 }],
    at: [{ tick: 18, ch: 3, num: 0, value: 66 }, { tick: 30, ch: 3, num: 0, value: 20 }],  // device AT = channel pressure, num 0
    totalTicks: 96,
    bpmX10: 1234,
};
test('decodeLoopBin accepts an independently-built v2 file (CRC cross-check)', () => {
    const bin = buildLoopBin(RICH_LOOP);
    const loop = page.decodeLoopBin(bin);
    eq(loop.notesOn.length, 2, 'ons');
    eq(loop.cc.map(c => [c.tick, c.num, c.value, c.ch]), [[6, 1, 32, 3], [12, 74, 90, 3], [40, 71, 7, 5]], 'cc decoded');
    eq(loop.at.map(a => [a.tick, a.value, a.ch]), [[18, 66, 3], [30, 20, 3]], 'at decoded');
    eq(loop.totalTicks, 96, 'totalTicks');
    eq(loop.bpm, 123.4, 'bpm');
});
test('loopBinToSmf emits every CC (0xBn) and channel-pressure (0xDn) event faithfully', () => {
    const smfBytes = page.loopBinToSmf(page.decodeLoopBin(buildLoopBin(RICH_LOOP)));
    const ref = refReadSmf(smfBytes);
    eq(ref.format, 0, 'format 0');
    eq(ref.division, page.DEVICE_PPQN, 'division = device 24 PPQN (ticks 1:1)');
    eq(ref.tempoUsPerQ, Math.round(60000000 / 123.4), 'tempo meta from header bpm');
    const ccs = ref.events.filter(e => e.type === 'cc').map(e => [e.tick, e.ch, e.num, e.value]);
    eq(ccs, [[6, 3, 1, 32], [12, 3, 74, 90], [40, 5, 71, 7]], 'all CCs present, correct tick/ch/num/value');
    const ats = ref.events.filter(e => e.type === 'chanAt').map(e => [e.tick, e.ch, e.value]);
    eq(ats, [[18, 3, 66], [30, 3, 20]], 'all aftertouch present as channel pressure');
    eq(ref.events.filter(e => e.type === 'polyAt').length, 0, 'no spurious poly-AT');
    eq(ref.events.filter(e => e.type === 'on').length, 2, 'note-ons');
    eq(ref.events.filter(e => e.type === 'off').length, 2, 'note-offs');
    eq(ref.endTick, 96, 'end-of-track at totalTicks (loop boundary)');
});
test('same-tick ordering: note-off sorts before note-on so back-to-back notes do not overlap', () => {
    const ref = refReadSmf(page.loopBinToSmf(page.decodeLoopBin(buildLoopBin(RICH_LOOP))));
    const at24 = ref.events.filter(e => e.tick === 24 && (e.type === 'on' || e.type === 'off'));
    eq(at24.map(e => e.type), ['off', 'on'], 'off before on at tick 24');
});
test('full circle: exported .mid re-imports with identical note timing and zero discards', () => {
    const smfBytes = page.loopBinToSmf(page.decodeLoopBin(buildLoopBin(RICH_LOOP)));
    const smf = page.parseSmf(smfBytes.buffer.slice(smfBytes.byteOffset, smfBytes.byteOffset + smfBytes.byteLength));
    eq(smf.skipped, { cc: 3, pb: 0, at: 2 }, 're-import discloses the CC/AT it would drop');
    const rebuilt = page.decodeLoopBin(page.smfToLoopBin(smf, 7, 3, 123.4).bytes);
    eq(rebuilt.notesOn.map(n => [n.tick, n.note]), [[0, 60], [24, 64]], 'on ticks survive (24 PPQN is 1:1)');
    eq(rebuilt.notesOff.map(n => [n.tick, n.note]), [[24, 60], [48, 64]], 'off ticks survive');
});
test('trackName becomes the FF 03 meta so DAWs name the clip (not "Track 0")', () => {
    const loop = page.decodeLoopBin(buildLoopBin(RICH_LOOP));
    const named = refReadSmf(page.loopBinToSmf(loop, 'MyPreset_pad7'));
    eq(named.trackName, 'MyPreset_pad7', 'FF 03 track name');
    eq(named.events.filter(e => e.type === 'cc').length, 3, 'events unaffected by the name meta');
    const anon = refReadSmf(page.loopBinToSmf(loop));
    eq(anon.trackName, null, 'no meta when no name given');
    // and a named export still re-imports cleanly (meta is skipped by parseSmf)
    const smfBytes = page.loopBinToSmf(loop, 'MyPreset_pad7');
    const smf = page.parseSmf(smfBytes.buffer.slice(smfBytes.byteOffset, smfBytes.byteOffset + smfBytes.byteLength));
    eq(smf.notes.length, 2, 're-import note pairs');
});
test('decodeLoopBin rejects corruption (magic, size, CRC)', () => {
    const good = buildLoopBin(RICH_LOOP);
    const badMagic = good.slice(); badMagic[0] = 0x00;
    throws(() => page.decodeLoopBin(badMagic), 'not a v2', 'magic');
    throws(() => page.decodeLoopBin(good.slice(0, good.length - 3)), 'size mismatch', 'size');
    const badCrc = good.slice(); badCrc[25] ^= 0xFF;
    throws(() => page.decodeLoopBin(badCrc), 'CRC', 'crc');
});

// ---------------------------------------------------------------
// 4. Real-file fixtures (scripts/fixtures/*.mid)
// ---------------------------------------------------------------
console.log('\n== fixtures ==');
if (!existsSync(FIXTURES_DIR)) {
    console.log('  (no scripts/fixtures/ directory — skipping)');
} else {
    const mids = readdirSync(FIXTURES_DIR).filter(f => /\.midi?$/i.test(f));
    if (mids.length === 0) console.log('  (no .mid files in scripts/fixtures/ — skipping)');
    for (const name of mids) {
        const raw = readFileSync(join(FIXTURES_DIR, name));
        const buf = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
        test('fixture "' + name + '": parse + discard counts match reference reader', () => {
            const ref = refReadSmf(buf);
            const smf = page.parseSmf(buf);
            eq(smf.tpq, ref.division, 'division');
            eq(smf.notes.length, ref.events.filter(e => e.type === 'on').length, 'note pairs = reference note-ons');
            eq(smf.skipped.cc, ref.events.filter(e => e.type === 'cc').length, 'cc discard count');
            eq(smf.skipped.pb, ref.events.filter(e => e.type === 'pb').length, 'pb discard count');
            eq(smf.skipped.at, ref.events.filter(e => e.type === 'polyAt' || e.type === 'chanAt').length, 'at discard count');
        });
        test('fixture "' + name + '": notes survive encode -> decode round trip', () => {
            const smf = page.parseSmf(buf);
            const loop = page.decodeLoopBin(page.smfToLoopBin(smf, 3, 0, 120).bytes);
            eq(loop.notesOn.length, smf.notes.length, 'on count');
            eq(loop.notesOff.length, smf.notes.length, 'off count');
            eq(loop.cc.length + loop.at.length, 0, 'import emits no cc/at sections');
        });
    }
}

// ---------------------------------------------------------------
console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
