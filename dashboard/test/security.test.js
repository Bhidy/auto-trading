// Regression tests for the dashboard API hardening (audit 2026-10-23).
// Offline: no broker keys and no live-state fetch, so nothing can reach Alpaca
// or GitHub. Run with `node --test test/` from dashboard/.
process.env.DASHBOARD_ACCESS_TOKEN = 'test-token-0123456789';
process.env.DASHBOARD_LIVE_STATE = '0';
for (const k of Object.keys(process.env)) {
    if (/^PORTFOLIO_\d+_API_(KEY|SECRET)$/.test(k)) delete process.env[k];
}

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const app = require('../server.js');

let server;
let base;

test.before(async () => {
    server = http.createServer(app);
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    base = `http://127.0.0.1:${server.address().port}`;
});

test.after(() => new Promise((resolve) => server.close(resolve)));

// Raw request so the client never normalises case or dot segments for us.
function request(method, rawPath, headers = {}) {
    return new Promise((resolve, reject) => {
        const { port } = server.address();
        const req = http.request({ host: '127.0.0.1', port, path: rawPath, method, headers }, (res) => {
            let body = '';
            res.on('data', (c) => { body += c; });
            res.on('end', () => resolve({ status: res.statusCode, body }));
        });
        req.setTimeout(8000, () => req.destroy(new Error(`timeout: ${method} ${rawPath}`)));
        req.on('error', reject);
        req.end();
    });
}

test('D1: every mutating verb on every path variant requires the token', async () => {
    const variants = [
        ['POST', '/api/portfolio/portfolio_1/order'],
        ['POST', '/API/portfolio/portfolio_1/order'],
        ['POST', '/Api/portfolio/portfolio_1/positions/close-all'],
        ['DELETE', '/API/portfolio/portfolio_1/orders'],
        ['PATCH', '/api/portfolio/portfolio_1/orders/abc'],
        ['PUT', '/aPi/portfolio/portfolio_1/watchlists/abc'],
        ['POST', '/not-an-api-path'],
    ];
    for (const [method, p] of variants) {
        const r = await request(method, p);
        assert.equal(r.status, 401, `${method} ${p} -> ${r.status}`);
    }
    const wrong = await request('POST', '/api/portfolio/portfolio_1/order', { 'x-access-token': 'nope' });
    assert.equal(wrong.status, 401);
});

test('D1: case-variant API paths do not reach handlers', async () => {
    const r = await request('GET', '/API/health');
    assert.equal(r.status, 404, `/API/health -> ${r.status}`);
});

test('D1: dot-segment and encoded traversal paths are rejected', async () => {
    for (const p of ['/api/../API/health', '/Portfolio/../API/health', '/api/%2e%2e/health', '/api/x%5c..%5chealth']) {
        const r = await request('GET', p);
        assert.equal(r.status, 400, `${p} -> ${r.status}`);
    }
});

test('D4: malformed bars input returns fast 4xx/clamped result, never hangs', async () => {
    assert.equal((await request('GET', '/api/market/bars/SPY?timeframe=bogus')).status, 400);
    assert.equal((await request('GET', '/api/market/bars/SPY?start=notadate')).status, 400);
    const r = await request('GET', '/api/market/bars/SPY?limit=abc');
    assert.ok(r.status < 500, `limit=abc -> ${r.status}`);
});

test('D6/D7: traversal and smuggling through params/query are rejected', async () => {
    for (const p of [
        '/api/portfolio/portfolio_1/activities?activity_type=..%2F..%2Fclock',
        '/api/portfolio/portfolio_1/watchlist/..%2Fclock',
        '/api/portfolio/portfolio_1/equity-history?period=1M%26foo%3Dbar',
        '/api/portfolio/portfolio_1/orders?status[]=x',
    ]) {
        const r = await request('GET', p);
        assert.equal(r.status, 400, `${p} -> ${r.status}`);
    }
});

test('D6: legitimate encoded crypto pair still routes', async () => {
    const r = await request('GET', '/api/crypto/snapshot/BTC%2FUSD');
    assert.notEqual(r.status, 400);
});

test('D9: prototype keys are not portfolios', async () => {
    for (const id of ['__proto__', 'constructor', 'hasOwnProperty']) {
        const r = await request('GET', `/api/portfolio/${id}/summary`);
        assert.equal(r.status, 404, `${id} -> ${r.status}`);
    }
});

test('D5: no fabricated market data when the broker is unavailable', async () => {
    const movers = await request('GET', '/api/market/movers');
    assert.ok(!movers.body.includes('135.5'), 'fabricated NVDA price leaked');
    const active = await request('GET', '/api/market/most-active');
    assert.ok(!active.body.includes('85000000'), 'fabricated volume leaked');
});

test('unknown API routes return JSON 404', async () => {
    const r = await request('GET', '/api/definitely-not-a-route');
    assert.equal(r.status, 404);
    assert.deepEqual(JSON.parse(r.body), { error: 'Not found.' });
});

// ── Honesty rule regressions (after-audit 2026-10-23 N1/N2/N3/N6) ─────────────
// Offline (no broker keys): every figure must come from committed state or be
// reported unavailable — never a $100K/$0 placeholder or an invented series.

test('N1: combined details never collapse to $0 / -100% when the broker is offline', async () => {
    const r = await request('GET', '/api/portfolio/all/details');
    assert.equal(r.status, 200);
    const d = JSON.parse(r.body);
    const books = (d.stale_portfolios || []).length + (d.missing_portfolios || []).length;
    assert.equal(books, 3, 'every offline book is reported stale or missing');
    if ((d.stale_portfolios || []).length) assert.ok(d.account.equity > 0, 'stale books contribute their committed equity');
});

test('N2: combined equity history is never padded or seeded', async () => {
    const r = await request('GET', '/api/portfolio/all/equity-history?period=1M&timeframe=1D');
    const d = JSON.parse(r.body);
    assert.ok(d.unavailable === true || d.history.length === 0 || d.source !== 'alpaca' || d.history.every(p => p.equity > 0));
    if (d.unavailable) assert.deepEqual(d.history, []);
});

test('N3: intraday equity history is unavailable, not daily points relabelled', async () => {
    const r = await request('GET', '/api/portfolio/portfolio_1/equity-history?period=1D&timeframe=5Min');
    const d = JSON.parse(r.body);
    assert.equal(d.unavailable, true);
    assert.deepEqual(d.history, []);
});

test('N6: summary exposes halt verification fields', async () => {
    const r = await request('GET', '/api/portfolio/portfolio_1/summary');
    const d = JSON.parse(r.body);
    for (const k of ['halt_verified', 'halt_measured_drawdown_pct', 'halt_note', 'stale']) assert.ok(k in d, `missing ${k}`);
    if (d.halted && /Kill switch: 73\.94%/.test(d.halt_reason || '')) {
        assert.equal(d.halt_verified, false, 'phantom 73.94% halt must not present as verified');
    }
});

test('no $100K placeholder equity anywhere offline', async () => {
    for (const id of ['portfolio_1', 'portfolio_2', 'portfolio_3']) {
        const d = JSON.parse((await request('GET', `/api/portfolio/${id}/summary`)).body);
        assert.notEqual(d.equity, 100000, `${id} summary shows a placeholder`);
    }
});
