#!/usr/bin/env node
// Node test harness for the web UI's serial command queue (W1, docs/web_config.html).
//
// The page's "Serial command queue (W1)" section is extracted from index.html AT
// RUNTIME and evaluated here (same pattern as midi_codec_test.mjs), so these tests
// always exercise the live page code. The section is pure transport — no DOM — by
// design; this harness is why it must stay that way.
//
// What's covered: FIFO one-in-flight serialization, expect-shape matching, DeviceError
// on error RSPs, timeout -> drain -> retry, retry exhaustion, straggler suppression
// during the drain window (the no-request-id hazard), shape-mismatch tolerance
// (interleaved keepalive acks), abortAll teardown, and writeLine failure.
//
// Run:  node scripts/serial_queue_test.mjs
// No dependencies. Node >= 18. Uses real timers; whole run ~3 s.

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const INDEX_HTML = join(HERE, '..', 'docs', 'web_config.html');

// ---------------------------------------------------------------
// Extract + evaluate the page's queue section
// ---------------------------------------------------------------
const html = readFileSync(INDEX_HTML, 'utf8');
const START_MARK = '// Serial command queue (W1) — pure transport, no DOM';
const END_MARK = '// Serial I/O wiring';
const startIdx = html.indexOf(START_MARK);
const endIdx = html.indexOf(END_MARK);
if (startIdx < 0 || endIdx < 0 || endIdx <= startIdx) {
    console.error('FATAL: queue section markers not found in index.html — the section was');
    console.error('renamed or reorganized. Update START_MARK/END_MARK in this harness.');
    process.exit(2);
}
// Strip the section-divider comment line the END marker sits under
const queueSrc = html.slice(startIdx, html.lastIndexOf('// ====', endIdx));

const page = new Function(queueSrc + `
    return { DeviceError, PortClosedError, TimeoutError, classifyRsp, createSerialQueue };
`)();

// ---------------------------------------------------------------
// Tiny test kit
// ---------------------------------------------------------------
let passed = 0, failed = 0;
const fails = [];
function check(name, cond, detail) {
    if (cond) { passed++; console.log('  PASS  ' + name); }
    else { failed++; fails.push(name); console.log('  FAIL  ' + name + (detail ? ' — ' + detail : '')); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// A fake wire: records written lines, lets tests answer them.
function makeWire(opts = {}) {
    const wire = {
        tx: [],            // every line written, in order
        failWrites: false, // simulate a dead port
        stray: [],         // data objects handed to onStray
        every: [],         // data objects handed to onEvery
    };
    wire.q = page.createSerialQueue({
        writeLine: (line) => {
            if (wire.failWrites) return Promise.reject(new page.PortClosedError());
            wire.tx.push(line.trim());
            return Promise.resolve();
        },
        onEvery: (d) => wire.every.push(d),
        onStray: (d) => wire.stray.push(d),
        ...opts,
    });
    return wire;
}
// Result wrapper so awaits never throw out of a test
const settle = (p) => p.then((v) => ({ ok: true, v }), (e) => ({ ok: false, e }));

// ---------------------------------------------------------------
// Tests
// ---------------------------------------------------------------
console.log('== classifyRsp ==');
{
    const c = page.classifyRsp;
    check('error shape', c({ error: 'x', code: 'io_error' }) === 'error');
    check('put ack shape (status ok + put_offset -> put, not ok)', c({ status: 'ok', put_offset: 512 }) === 'put');
    check('names shape', c({ names: [], startup: '' }) === 'names');
    check('files shape', c({ files: [] }) === 'files');
    check('chunk shape', c({ data: 'AA==', offset: 0, done: false }) === 'chunk');
    check('plain ok shape', c({ status: 'ok', device: 'loopster' }) === 'ok');
    check('needs_restart ack is still ok', c({ status: 'ok', needs_restart: true }) === 'ok');
    check('bare preset object', c({ default_bpm: 120, loops: {} }) === 'object');
}

console.log('== happy path + FIFO ==');
await (async () => {
    const w = makeWire();
    const a = w.q.send('PING', { expect: 'ok' });
    const b = w.q.send('GET_PRESET_NAMES', { expect: 'names' });
    await sleep(10);
    check('first command TXed', w.tx.length === 1 && w.tx[0] === 'CMD:PING', JSON.stringify(w.tx));
    check('second command held until first settles', w.tx.length === 1);
    w.q.onLine({ status: 'ok', device: 'loopster' });
    const ra = await settle(a);
    check('PING resolved with the ack', ra.ok && ra.v.device === 'loopster');
    await sleep(10);
    check('second command TXed after first resolved', w.tx.length === 2 && w.tx[1] === 'CMD:GET_PRESET_NAMES', JSON.stringify(w.tx));
    w.q.onLine({ names: ['A'], startup: 'A' });
    const rb = await settle(b);
    check('names resolved', rb.ok && rb.v.names[0] === 'A');
    check('depth back to 0', w.q.depth === 0);
    check('onEvery saw both lines', w.every.length === 2);
    check('nothing was stray', w.stray.length === 0);
})();

console.log('== device error ==');
await (async () => {
    const w = makeWire();
    const p = w.q.send('GET_PRESET|nope', { expect: 'object' });
    await sleep(5);
    w.q.onLine({ error: 'Preset not found', code: 'not_found' });
    const r = await settle(p);
    check('rejects with DeviceError', !r.ok && r.e.name === 'DeviceError');
    check('code preserved', !r.ok && r.e.code === 'not_found');
    check('message preserved', !r.ok && r.e.message === 'Preset not found');
})();

console.log('== shape mismatch tolerated (interleaved ok ack) ==');
await (async () => {
    const w = makeWire();
    const p = w.q.send('GET_PRESETS_RAW_CHUNK|0', { expect: 'chunk', timeout: 500 });
    await sleep(5);
    w.q.onLine({ status: 'ok' }); // e.g. an ack that outlived its exchange
    await sleep(5);
    check('mismatched ok did not resolve the chunk wait', w.q.depth === 1);
    check('mismatch went to onStray', w.stray.length === 1);
    w.q.onLine({ data: 'AA==', offset: 0, done: true });
    const r = await settle(p);
    check('chunk still resolved after the noise', r.ok && r.v.data === 'AA==');
})();

console.log('== bare preset object matching (expect object) ==');
await (async () => {
    const w = makeWire();
    const p = w.q.send('GET_PRESET|Live', { expect: 'object' });
    await sleep(5);
    w.q.onLine({ default_bpm: 98, loops: { 0: { loop_id: 4 } } });
    const r = await settle(p);
    check('preset payload resolved', r.ok && r.v.default_bpm === 98);
})();

console.log('== timeout -> drain -> retry succeeds ==');
await (async () => {
    const w = makeWire();
    const p = w.q.send('GET_PRESET_NAMES', { expect: 'names', timeout: 60, retries: 1 });
    await sleep(30);
    check('one TX before timeout', w.tx.length === 1);
    await sleep(60 + 200 + 30); // timeout + drain quiet window + slack
    check('retransmitted after drain', w.tx.length === 2, 'tx=' + w.tx.length);
    w.q.onLine({ names: [], startup: '' });
    const r = await settle(p);
    check('retry answer resolves the original promise', r.ok);
})();

console.log('== retries exhausted -> TimeoutError, queue moves on ==');
await (async () => {
    const w = makeWire();
    const p = w.q.send('LIST_LOOP_FILES', { expect: 'files', timeout: 40, retries: 0 });
    const nxt = w.q.send('PING', { expect: 'ok', timeout: 500, retries: 0 });
    const r = await settle(p);
    check('rejects with TimeoutError', !r.ok && r.e.name === 'TimeoutError');
    check('timeout message names the command', !r.ok && /LIST_LOOP_FILES/.test(r.e.message));
    await sleep(200 + 60); // drain, then the queued PING should go out
    check('next command TXed after the drain', w.tx.length === 2 && w.tx[1] === 'CMD:PING', JSON.stringify(w.tx));
    w.q.onLine({ status: 'ok' });
    const rn = await settle(nxt);
    check('queued command unaffected by the failure', rn.ok);
})();

console.log('== straggler in the drain window is never matched ==');
await (async () => {
    const w = makeWire();
    const a = w.q.send('GET_PRESETS_RAW_CHUNK|0', { expect: 'chunk', timeout: 40, retries: 0 });
    const b = w.q.send('GET_PRESETS_RAW_CHUNK|512', { expect: 'chunk', timeout: 800, retries: 0 });
    const ra = await settle(a); // times out at ~40ms
    check('first chunk request timed out', !ra.ok && ra.e.name === 'TimeoutError');
    // The late answer to request A arrives DURING the drain window…
    w.q.onLine({ data: 'STRAGGLER', offset: 0, done: false });
    await sleep(50);
    check('straggler swallowed, not matched to the next request', w.stray.some((d) => d.data === 'STRAGGLER'));
    check('B not TXed while draining', w.tx.length === 1, JSON.stringify(w.tx));
    await sleep(200 + 60); // quiet window restarted by the straggler, then B goes out
    check('B TXed after quiet', w.tx.length === 2 && w.tx[1] === 'CMD:GET_PRESETS_RAW_CHUNK|512');
    w.q.onLine({ data: 'REAL', offset: 512, done: true });
    const rb = await settle(b);
    check('B resolved with ITS answer, not the straggler', rb.ok && rb.v.data === 'REAL');
})();

console.log('== abortAll (teardown) ==');
await (async () => {
    const w = makeWire();
    const a = w.q.send('GET_PRESET|X', { expect: 'object', timeout: 5000 });
    const b = w.q.send('PING', { expect: 'ok', timeout: 5000 });
    await sleep(10);
    w.q.abortAll(new page.PortClosedError());
    const ra = await settle(a), rb = await settle(b);
    check('in-flight rejected with PortClosedError', !ra.ok && ra.e.name === 'PortClosedError');
    check('queued rejected with PortClosedError', !rb.ok && rb.e.name === 'PortClosedError');
    check('depth 0 after abort', w.q.depth === 0);
    // Queue is reusable after a teardown (reconnect case)
    const c = w.q.send('PING', { expect: 'ok' });
    await sleep(10);
    w.q.onLine({ status: 'ok' });
    check('queue usable again after abortAll', (await settle(c)).ok);
})();

console.log('== writeLine failure (dead port) ==');
await (async () => {
    const w = makeWire();
    w.failWrites = true;
    const a = w.q.send('PING', { expect: 'ok', timeout: 5000 });
    const ra = await settle(a);
    check('write failure rejects with PortClosedError', !ra.ok && ra.e.name === 'PortClosedError');
    w.failWrites = false;
    const b = w.q.send('PING', { expect: 'ok' });
    await sleep(10);
    w.q.onLine({ status: 'ok' });
    check('queue recovers once writes work again', (await settle(b)).ok);
})();

console.log('== idle stray lines ==');
await (async () => {
    const w = makeWire();
    w.q.onLine({ error: 'spontaneous', code: 'io_error' });
    w.q.onLine({ status: 'ok' });
    check('idle lines go to onStray', w.stray.length === 2);
    check('idle lines still hit onEvery', w.every.length === 2);
})();

console.log('');
console.log(passed + ' passed, ' + failed + ' failed');
if (failed) { console.log('Failed: ' + fails.join(', ')); process.exit(1); }
