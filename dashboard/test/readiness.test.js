// Readiness Engine v2 endpoint: the dashboard serves the engine's report verbatim,
// never recomputes it, and is honest when the report is absent or malformed.
// Offline: no broker keys, no live-state fetch.
process.env.DASHBOARD_ACCESS_TOKEN = 'test-token-0123456789';
process.env.DASHBOARD_LIVE_STATE = '0';
for (const k of Object.keys(process.env)) {
    if (/^PORTFOLIO_\d+_API_(KEY|SECRET)$/.test(k)) delete process.env[k];
}

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const app = require('../server.js');

const I = app._internals;
let server;

test.before(async () => {
    server = http.createServer(app);
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
});

test.after(() => new Promise((resolve) => server.close(resolve)));

function get(rawPath) {
    return new Promise((resolve, reject) => {
        const { port } = server.address();
        const req = http.request({ host: '127.0.0.1', port, path: rawPath, method: 'GET' }, (res) => {
            let body = '';
            res.on('data', (c) => { body += c; });
            res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body }));
        });
        req.setTimeout(8000, () => req.destroy(new Error(`timeout: GET ${rawPath}`)));
        req.on('error', reject);
        req.end();
    });
}

test('readiness: GET /api/readiness serves the committed engine report, no-store', async () => {
    const r = await get('/api/readiness');
    assert.equal(r.headers['cache-control'], 'no-store');
    if (!fs.existsSync(I.READINESS_REPORT_PATH)) {
        // No report on disk: the honest answer is 404 unavailable.
        assert.equal(r.status, 404);
        assert.equal(JSON.parse(r.body).unavailable, true);
        return;
    }
    assert.equal(r.status, 200);
    const body = JSON.parse(r.body);
    const onDisk = JSON.parse(fs.readFileSync(I.READINESS_REPORT_PATH, 'utf-8'));
    assert.deepEqual(body, onDisk, 'served verbatim — no server-side recomputation');
    assert.ok(Array.isArray(body.sleeves) && body.sleeves.length > 0);
    for (const s of body.sleeves) {
        assert.ok(['GO', 'NOT_READY', 'NOT_ELIGIBLE'].includes(s.verdict), `${s.id} verdict ${s.verdict}`);
        assert.equal(typeof s.gates_passed, 'number');
        assert.equal(typeof s.gates_total, 'number');
        assert.equal('score' in s || 'readiness_pct' in s, false, 'no percentage score in the report');
    }
});

test('readiness: absent report is an honest 404 unavailable, never a fabricated verdict', () => {
    const r = I.readinessResponse(null);
    assert.equal(r.status, 404);
    assert.equal(r.body.unavailable, true);
    assert.equal('sleeves' in r.body, false);
});

test('readiness: malformed report is 503 unavailable', () => {
    const bad = [
        {},
        [],
        'x',
        { generated_at: 'not-a-date', sleeves: [] },
        { generated_at: '2026-10-23T15:40:15Z' },
        { generated_at: '2026-10-23T15:40:15Z', sleeves: [{ id: 'a', book: 'portfolio_1', verdict: 'GO' }] },
        { generated_at: '2026-10-23T15:40:15Z', sleeves: [null] },
    ];
    for (const b of bad) {
        const r = I.readinessResponse(b);
        assert.equal(r.status, 503, JSON.stringify(b));
        assert.equal(r.body.unavailable, true);
    }
});

test('readiness: a well-formed report passes through unchanged', () => {
    const rep = { generated_at: '2026-10-23T15:40:15Z', sleeves: [{ id: 'a', book: 'portfolio_1', verdict: 'NOT_READY', gates: [] }] };
    const r = I.readinessResponse(rep);
    assert.equal(r.status, 200);
    assert.equal(r.body, rep);
});

test('readiness: report is seeded into the live-state overlay refresh set', () => {
    assert.ok(I.hotStatePaths.has(path.resolve(I.READINESS_REPORT_PATH)));
});
