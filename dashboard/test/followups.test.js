// Regression tests for the 2026-10-23 audit follow-ups (guardian secret,
// CDN caching, corporate-actions paging, bars-batch, engine safety state).
// Offline: no broker keys and no live-state fetch; the one outbound call
// (GitHub dispatch) is stubbed, so nothing leaves the machine.
process.env.DASHBOARD_ACCESS_TOKEN = 'test-token-0123456789';
process.env.DASHBOARD_LIVE_STATE = '0';
for (const k of Object.keys(process.env)) {
    if (/^PORTFOLIO_\d+_API_(KEY|SECRET)$/.test(k)) delete process.env[k];
}
delete process.env.CRON_SECRET;
delete process.env.GITHUB_DISPATCH_PAT;

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const https = require('node:https');
const { EventEmitter } = require('node:events');
const { Readable } = require('node:stream');
const app = require('../server.js');

let server;

test.before(async () => {
    server = http.createServer(app);
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
});

test.after(() => new Promise((resolve) => server.close(resolve)));

function request(method, rawPath, headers = {}) {
    return new Promise((resolve, reject) => {
        const { port } = server.address();
        const req = http.request({ host: '127.0.0.1', port, path: rawPath, method, headers }, (res) => {
            let body = '';
            res.on('data', (c) => { body += c; });
            res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body }));
        });
        req.setTimeout(8000, () => req.destroy(new Error(`timeout: ${method} ${rawPath}`)));
        req.on('error', reject);
        req.end();
    });
}

// ── Item 2: /api/guardian-trigger ────────────────────────────────────────────

test('guardian: fail-closed 503 when unconfigured', async () => {
    const r = await request('GET', '/api/guardian-trigger', { authorization: 'Bearer x' });
    assert.equal(r.status, 503);
});

test('guardian: wrong secret (same or different length) is 401, never a 500', async () => {
    process.env.CRON_SECRET = 'cron-secret-abcdef';
    process.env.GITHUB_DISPATCH_PAT = 'pat-not-real';
    try {
        for (const auth of ['Bearer cron-secret-abcdeX', 'Bearer short', '', 'Bearer cron-secret-abcdef-and-more']) {
            const r = await request('GET', '/api/guardian-trigger', auth ? { authorization: auth } : {});
            assert.equal(r.status, 401, `auth=${JSON.stringify(auth)} -> ${r.status}`);
        }
    } finally {
        delete process.env.CRON_SECRET;
        delete process.env.GITHUB_DISPATCH_PAT;
    }
});

test("guardian: GitHub's error body is never echoed to the caller", async () => {
    process.env.CRON_SECRET = 'cron-secret-abcdef';
    process.env.GITHUB_DISPATCH_PAT = 'pat-not-real';
    const realRequest = https.request;
    let dispatched = 0;
    https.request = function (options, cb) {
        if (!options || options.hostname !== 'api.github.com') return realRequest.apply(this, arguments);
        dispatched++;
        const req = new EventEmitter();
        req.write = () => true;
        req.setTimeout = () => req;
        req.destroy = () => {};
        req.end = () => {
            const res = Readable.from([Buffer.from('{"message":"Bad credentials LEAKY-INTERNAL-DETAIL"}')]);
            res.statusCode = 401;
            setImmediate(() => cb(res));
        };
        return req;
    };
    try {
        const r = await request('GET', '/api/guardian-trigger', { authorization: 'Bearer cron-secret-abcdef' });
        assert.equal(dispatched, 1, 'the matching secret reaches the dispatch');
        assert.equal(r.status, 502);
        assert.ok(!r.body.includes('LEAKY'), 'upstream body leaked to caller');
        assert.ok(!r.body.includes('github_status'), 'upstream status leaked to caller');
    } finally {
        https.request = realRequest;
        delete process.env.CRON_SECRET;
        delete process.env.GITHUB_DISPATCH_PAT;
    }
});

// ── Item 3: caching + corporate-actions paging ───────────────────────────────

const MARKET_CACHE = 'public, s-maxage=15, stale-while-revalidate=30';

test('cache: pure market-data GETs carry the CDN cache header', async () => {
    for (const p of [
        '/api/market/bars/SPY?timeframe=5Min&limit=10&start=2026-10-20',
        '/api/market/bars-batch?symbols=SPY,QQQ&timeframe=5Min&limit=10&start=2026-10-20',
        '/api/market/quotes?symbols=SPY',
    ]) {
        const r = await request('GET', p);
        assert.equal(r.status, 200, `${p} -> ${r.status}`);
        assert.equal(r.headers['cache-control'], MARKET_CACHE, `${p} cache-control`);
    }
});

test('cache: portfolio/account/order/health/intelligence endpoints are no-store', async () => {
    for (const p of [
        '/api/health',
        '/api/portfolios',
        '/api/portfolio/portfolio_1/summary',
        '/api/portfolio/portfolio_1/details',
        '/api/portfolio/portfolio_1/intelligence',
        '/api/portfolio/portfolio_1/orders',
        '/api/portfolio/portfolio_1/positions',
        '/api/intelligence/cross-portfolio',
        '/api/corporate-actions',
    ]) {
        const r = await request('GET', p);
        assert.equal(r.headers['cache-control'], 'no-store', `${p} (${r.status}) cache-control=${r.headers['cache-control']}`);
    }
});

test('cache: a failed market request is never cached at the edge', async () => {
    const r = await request('GET', '/api/market/bars/SPY?timeframe=bogus');
    assert.equal(r.status, 400);
    assert.equal(r.headers['cache-control'], 'no-store');
    // Offline the movers feeds are honestly unavailable (non-200): not cacheable.
    for (const p of ['/api/market/movers', '/api/market/most-active']) {
        const m = await request('GET', p);
        assert.equal(m.headers['cache-control'], m.status === 200 ? MARKET_CACHE : 'no-store', `${p} (${m.status})`);
    }
});

test('corporate-actions: paged array with total header; bad page_token rejected', async () => {
    const r = await request('GET', '/api/corporate-actions?limit=5');
    assert.equal(r.status, 200);
    assert.ok(Array.isArray(JSON.parse(r.body)));
    assert.ok(Number(r.headers['x-total-count']) >= 0);
    assert.equal((await request('GET', '/api/corporate-actions?page_token=bm9wZQ')).status, 400);
});

// ── Item 4: /api/market/bars-batch ───────────────────────────────────────────

test('bars-batch: input validated like the single-symbol route', async () => {
    assert.equal((await request('GET', '/api/market/bars-batch')).status, 400, 'symbols required');
    assert.equal((await request('GET', '/api/market/bars-batch?symbols=SPY&timeframe=bogus')).status, 400);
    assert.equal((await request('GET', '/api/market/bars-batch?symbols=SPY&start=notadate')).status, 400);
    assert.equal((await request('GET', '/api/market/bars-batch?symbols=SPY,TOOLONGSYMBOL1')).status, 400);
    assert.equal((await request('GET', '/api/market/bars-batch?symbols=SPY,..%2Fclock')).status, 400);
    assert.equal((await request('GET', '/api/market/bars-batch?symbols[]=SPY')).status, 400);
    const r = await request('GET', '/api/market/bars-batch?symbols=SPY&limit=abc');
    assert.ok(r.status < 500, `limit=abc -> ${r.status}`);
});

test('bars-batch: 50-symbol cap (50 ok, 51 rejected); offline returns {} not fabricated bars', async () => {
    const syms = Array.from({ length: 51 }, (_, i) => 'S' + String.fromCharCode(65 + (i % 26)) + String.fromCharCode(65 + Math.floor(i / 26)));
    const ok = await request('GET', '/api/market/bars-batch?symbols=' + syms.slice(0, 50).join(',') + '&timeframe=5Min');
    assert.equal(ok.status, 200, ok.body);
    assert.deepEqual(JSON.parse(ok.body), {});
    const tooMany = await request('GET', '/api/market/bars-batch?symbols=' + syms.join(',') + '&timeframe=5Min');
    assert.equal(tooMany.status, 400);
    assert.match(tooMany.body, /50 symbols/);
});

// ── Item 1: engine safety state on the intelligence endpoint ────────────────

test('intelligence: safety block has an honest, complete shape offline', async () => {
    const r = await request('GET', '/api/portfolio/portfolio_1/intelligence');
    assert.equal(r.status, 200);
    const sf = JSON.parse(r.body).safety;
    assert.ok(sf, 'safety block missing');
    assert.equal(sf.engine_managed, true);
    for (const k of ['halt_governance', 'pending_exits', 'pending_entries', 'booked_fills']) {
        assert.equal(typeof sf.files[k], 'boolean', `files.${k}`);
    }
    assert.equal(typeof sf.halt.halted, 'boolean');
    for (const k of ['reason', 'verified', 'unverified_reason', 'set_at', 'evidence', 'observations_count']) {
        assert.ok(k in sf.halt, `halt.${k}`);
    }
    assert.ok('peak_equity' in sf);
    assert.ok(sf.peak_equity === null || Number.isFinite(sf.peak_equity.value));
    assert.ok('last_clear' in sf.halt_governance && 'total_clears' in sf.halt_governance);
    assert.equal(sf.pending.total, sf.pending.exits + sf.pending.entries);
    assert.ok(Array.isArray(sf.pending.orders));
    assert.equal(typeof sf.booked_fills.count, 'number');
    assert.ok(Array.isArray(sf.booked_fills.latest));
    if (sf.halt.halted && !sf.halt.evidence) {
        assert.equal(sf.halt.verified, false, 'a halt with no evidence must not present as verified');
        assert.ok(sf.halt.unverified_reason);
    }
});

test('intelligence: books without the P1 engine ledgers report them absent, not empty-as-fact', async () => {
    const sf = JSON.parse((await request('GET', '/api/portfolio/portfolio_2/intelligence')).body).safety;
    assert.equal(sf.engine_managed, false);
    assert.equal(sf.pending.total, 0);
    assert.equal(sf.booked_fills.count, 0);
});

test('health reports the journal overlay', async () => {
    const d = JSON.parse((await request('GET', '/api/health')).body);
    assert.ok(d.liveState && d.liveState.journals, 'liveState.journals missing');
    assert.equal(d.liveState.journals.lookbackDays, 10);
});
