// Regression tests for the 2026-10-23 POST-DEPLOY production audit (D1-D11):
// day-P/L basis, real sectors, live-state consistent pairs, asset paging,
// crypto pair normalisation, equity seed anchors, trimmed /api/health, CSP.
// Offline: the live-state fetch is disabled and every Alpaca / Supabase call is
// answered by an in-process stub, so nothing leaves the machine.
process.env.DASHBOARD_ACCESS_TOKEN = 'test-token-0123456789';
process.env.DASHBOARD_LIVE_STATE = '0';
process.env.PORTFOLIO_1_API_KEY = 'k1'; process.env.PORTFOLIO_1_API_SECRET = 's1';
process.env.PORTFOLIO_2_API_KEY = 'k2'; process.env.PORTFOLIO_2_API_SECRET = 's2';
process.env.PORTFOLIO_3_API_KEY = 'k3'; process.env.PORTFOLIO_3_API_SECRET = 's3';
process.env.SUPABASE_URL = 'https://stub.supabase.co';
process.env.SUPABASE_ANON_KEY = 'anon-stub';

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const https = require('node:https');
const { EventEmitter } = require('node:events');
const { Readable } = require('node:stream');

// ── Stub upstreams (installed BEFORE the app loads) ─────────────────────────
const etToday = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date());
function weekdaysBefore(dateStr, n) {
    const [y, m, d] = dateStr.split('-').map(Number);
    const out = [];
    let t = Date.UTC(y, m - 1, d);
    while (out.length < n) {
        t -= 86400000;
        const day = new Date(t).getUTCDay();
        if (day !== 0 && day !== 6) out.unshift(new Date(t).toISOString().slice(0, 10));
    }
    return out;
}
const SESSIONS = weekdaysBefore(etToday, 30);
const PREV_SESSION = SESSIONS[SESSIONS.length - 1];
const OLDER_SESSION = SESSIONS[SESSIONS.length - 2];

const ACCOUNTS = {
    k1: { equity: '97254.40', last_equity: '98066.40', cash: '10000', buying_power: '20000', balance_asof: OLDER_SESSION },
    k2: { equity: '101000.00', last_equity: '100500.00', cash: '5000', buying_power: '10000', balance_asof: PREV_SESSION },
    k3: { equity: '99155.66', last_equity: '99000.00', cash: '8000', buying_power: '16000', balance_asof: PREV_SESSION },
};
const POSITIONS = {
    k1: [], k2: [],
    k3: ['ANET', 'DG', 'KO', 'MRK', 'ZZZZ'].map(sym => ({
        symbol: sym, qty: '10', avg_entry_price: '100', current_price: '101', market_value: '1010',
        unrealized_pl: '10', unrealized_plpc: '0.01', lastday_price: '100.5', asset_class: 'us_equity',
    })),
};
const ASSETS = Array.from({ length: 1234 }, (_, i) => ({ symbol: `T${i}`, name: `Test Asset ${i}` }))
    .concat([{ symbol: 'AAPL', name: 'Apple Inc.' }, { symbol: 'AAPLW', name: 'Not Apple' }]);
const SUPABASE_ROWS = [
    { date: '2026-04-01', equity: 100000, cash: null },
    { date: '2026-04-02', equity: 100000, cash: null },
    { date: '2026-04-03', equity: 100120.5, cash: 9000 },
    { date: '2026-04-06', equity: 100000, cash: null },   // after the first real point: kept, not an anchor
];
let assetFetches = 0;

function fakeResponse(cb, status, body) {
    const res = Readable.from([Buffer.from(typeof body === 'string' ? body : JSON.stringify(body))]);
    res.statusCode = status;
    setImmediate(() => cb(res));
}
function fakeRequest() {
    const req = new EventEmitter();
    req.write = () => true; req.end = () => {}; req.destroy = () => {}; req.setTimeout = () => req;
    return req;
}
const realRequest = https.request, realGet = https.get;
https.request = function (options, cb) {
    if (!options || !/alpaca\.markets$/.test(options.hostname || '')) return realRequest.apply(this, arguments);
    const key = options.headers['APCA-API-KEY-ID'];
    const p = options.path.split('?')[0];
    const req = fakeRequest();
    req.end = () => {
        if (p === '/v2/account') return fakeResponse(cb, 200, ACCOUNTS[key]);
        if (p === '/v2/positions') return fakeResponse(cb, 200, POSITIONS[key] || []);
        if (p === '/v2/orders') return fakeResponse(cb, 200, []);
        if (p === '/v2/clock') return fakeResponse(cb, 200, { is_open: false, timestamp: new Date().toISOString() });
        if (p === '/v2/calendar') return fakeResponse(cb, 200, SESSIONS.map(d => ({ date: d, open: '09:30', close: '16:00' })));
        if (p === '/v2/assets') { assetFetches++; return fakeResponse(cb, 200, ASSETS); }
        return fakeResponse(cb, 404, { message: 'not stubbed' });
    };
    return req;
};
https.get = function (options, cb) {
    if (options && options.hostname === 'stub.supabase.co') {
        const req = fakeRequest();
        fakeResponse(cb, 200, SUPABASE_ROWS);
        return req;
    }
    return realGet.apply(this, arguments);
};

const app = require('../server.js');
const I = app._internals;

let server;
test.before(async () => {
    server = http.createServer(app);
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
});
test.after(() => new Promise((resolve) => server.close(resolve)));

function request(method, rawPath) {
    return new Promise((resolve, reject) => {
        const { port } = server.address();
        const req = http.request({ host: '127.0.0.1', port, path: rawPath, method }, (res) => {
            let body = '';
            res.on('data', (c) => { body += c; });
            res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body }));
        });
        req.setTimeout(8000, () => req.destroy(new Error(`timeout: ${method} ${rawPath}`)));
        req.on('error', reject);
        req.end();
    });
}
const getJson = async (p) => { const r = await request('GET', p); return { ...r, json: JSON.parse(r.body) }; };

// ── D1: day-P/L basis ────────────────────────────────────────────────────────

test('D1 basis: "today" only when the market is open AND basis = previous session', () => {
    const open = { market_open: true, previous_session_date: '2026-10-22' };
    const closed = { market_open: false, previous_session_date: '2026-10-22' };
    assert.equal(I.dayPnlBasis('2026-10-22', open).day_pnl_is_today, true);
    assert.equal(I.dayPnlBasis('2026-10-21', open).day_pnl_is_today, false, 'two sessions back is not today');
    assert.equal(I.dayPnlBasis('2026-10-22', closed).day_pnl_is_today, false, 'closed market is never today');
    assert.equal(I.dayPnlBasis(null, open).day_pnl_is_today, false, 'unknown basis is never today');
    assert.equal(I.dayPnlBasis('2026-10-22T00:00:00Z', open).day_pnl_basis_date, '2026-10-22');
    const agg = I.aggregateDayPnlBasis(['2026-10-22', '2026-10-21'], open);
    assert.equal(agg.day_pnl_basis_mixed, true);
    assert.equal(agg.day_pnl_basis_date, null);
    assert.equal(agg.day_pnl_is_today, false);
    const same = I.aggregateDayPnlBasis(['2026-10-22', '2026-10-22'], open);
    assert.equal(same.day_pnl_basis_mixed, false);
    assert.equal(same.day_pnl_is_today, true);
    assert.equal(I.aggregateDayPnlBasis(['2026-10-22', null], open).day_pnl_basis_mixed, true, 'a stale book makes the basis mixed');
    assert.equal(I.aggregateDayPnlBasis([null, null], open).day_pnl_basis_mixed, false);
});

test('D1 /summary + /details state the basis; closed market is not "today"', async () => {
    const s = (await getJson('/api/portfolio/portfolio_1/summary')).json;
    assert.equal(s.live_connected, true);
    assert.equal(s.day_pnl_basis_date, OLDER_SESSION);
    assert.equal(s.previous_session_date, PREV_SESSION);
    assert.equal(s.market_open, false);
    assert.equal(s.day_pnl_is_today, false);
    assert.equal(Math.round(s.day_pnl * 100) / 100, -812, 'day P/L is still equity − last_equity');
    const d = (await getJson('/api/portfolio/portfolio_2/details')).json;
    assert.equal(d.day_pnl_basis_date, PREV_SESSION);
    assert.equal(d.day_pnl_is_today, false);
});

test('D1 aggregate: books on different balance dates report a mixed basis', async () => {
    for (const p of ['/api/portfolio/all/summary', '/api/portfolio/all/details']) {
        const a = (await getJson(p)).json;
        assert.equal(a.day_pnl_basis_mixed, true, p);
        assert.equal(a.day_pnl_basis_date, null, p);
        assert.equal(a.day_pnl_is_today, false, p);
    }
});

test('D1/D7 overview: basis + halt fields, never a $100K placeholder', async () => {
    const list = (await getJson('/api/portfolios/overview')).json;
    assert.equal(list.length, 3);
    for (const b of list) {
        assert.ok('day_pnl_basis_date' in b && 'halted' in b && 'halt_verified' in b, b.id);
        assert.notEqual(b.equity, 100000);
    }
});

// ── D2: sectors ──────────────────────────────────────────────────────────────

test('D2 sectors: GICS from the symbol map, null when unknown, never the book name', async () => {
    assert.equal(I.sectorFor('ANET'), 'Technology');
    assert.equal(I.sectorFor('DG'), 'Consumer Staples');
    assert.equal(I.sectorFor('KO'), 'Consumer Staples');
    assert.equal(I.sectorFor('MRK'), 'Health Care');
    assert.equal(I.sectorFor('XLE'), 'Energy');
    assert.equal(I.sectorFor('BTCUSD', 'crypto'), 'Crypto');
    assert.equal(I.sectorFor('ZZZZ'), null);
    assert.equal(I.sectorFor('constructor'), null, 'prototype keys are not sectors');
    const d = (await getJson('/api/portfolio/portfolio_3/details')).json;
    const bySym = Object.fromEntries(d.positions.map(p => [p.symbol, p.sector]));
    assert.deepEqual(bySym, { ANET: 'Technology', DG: 'Consumer Staples', KO: 'Consumer Staples', MRK: 'Health Care', ZZZZ: null });
    const x = (await getJson('/api/intelligence/cross-portfolio')).json;
    assert.ok(!x.by_sector.some(s => s.sector === 'Other'), 'unknown names are "Unclassified", not "Other"');
    assert.ok(x.by_sector.some(s => s.sector === 'Unclassified'));
});

// ── D3: live-state consistent pairs ──────────────────────────────────────────

test('D3 overlay: a book\'s state + trade log are only ever updated together', () => {
    const pairs = [{ id: 'p1', state: '/s1', tradeLog: '/t1' }, { id: 'p2', state: '/s2', tradeLog: '/t2' }];
    const ok = (v) => ({ ok: true, value: v });
    const fail = { ok: false, absent: false };
    // p1: state failed but trade log refreshed -> NEITHER written; p2 both ok.
    let plan = I.planOverlayUpdate(new Map([['/s1', fail], ['/t1', ok(1)], ['/s2', ok(2)], ['/t2', ok(3)], ['/x', ok(4)]]), pairs);
    assert.equal(plan.coreOk, false);
    assert.deepEqual([...plan.writes.keys()].sort(), ['/s2', '/t2', '/x']);
    // All core ok -> everything written, refresh counts as ok.
    plan = I.planOverlayUpdate(new Map([['/s1', ok(1)], ['/t1', ok(1)], ['/s2', ok(2)], ['/t2', ok(3)]]), pairs);
    assert.equal(plan.coreOk, true);
    assert.equal(plan.writes.size, 4);
    // One side absent on main (404) -> serve the bundled pair, still ok.
    plan = I.planOverlayUpdate(new Map([['/s1', { ok: false, absent: true }], ['/t1', ok(1)], ['/s2', ok(2)], ['/t2', ok(3)]]), pairs);
    assert.equal(plan.coreOk, true);
    assert.ok(!plan.writes.has('/t1') && !plan.writes.has('/s1'));
});

// ── D9: assets paging + crypto pairs ─────────────────────────────────────────

test('D9 assets: paged (default 500), total header, server-side search, 1 h edge cache', async () => {
    const r1 = await request('GET', '/api/assets?status=active&asset_class=us_equity');
    assert.equal(r1.status, 200);
    assert.equal(JSON.parse(r1.body).length, 500);
    assert.equal(r1.headers['x-total-count'], String(ASSETS.length));
    assert.match(r1.headers['cache-control'], /s-maxage=3600/);
    const r3 = await request('GET', '/api/assets?status=active&asset_class=us_equity&page=3&limit=500');
    assert.equal(JSON.parse(r3.body).length, ASSETS.length - 1000);
    const q = await request('GET', '/api/assets?status=active&asset_class=us_equity&q=aapl');
    const rows = JSON.parse(q.body);
    assert.equal(q.headers['x-total-count'], '2');
    assert.equal(rows[0].symbol, 'AAPL', 'exact symbol match ranks first');
    assert.equal(assetFetches, 1, 'the asset master is fetched once per filter combination');
    const big = await request('GET', '/api/assets?status=active&asset_class=us_equity&limit=999999');
    assert.equal(JSON.parse(big.body).length, ASSETS.length, 'limit is capped at 2000 (all 1236 fit)');
});

test('D9 calendar carries the reference-data edge cache', async () => {
    const r = await request('GET', '/api/market/calendar?start=2026-10-01&end=2026-10-31');
    assert.equal(r.status, 200);
    assert.match(r.headers['cache-control'], /s-maxage=3600/);
});

test('D9 crypto pairs: BTCUSD normalised, unknown pairs rejected', async () => {
    assert.equal(I.normalizeCryptoPair('BTCUSD'), 'BTC/USD');
    assert.equal(I.normalizeCryptoPair('btc/usd'), 'BTC/USD');
    assert.equal(I.normalizeCryptoPair('ETHUSDT'), 'ETH/USDT');
    assert.equal(I.normalizeCryptoPair('BTC'), null);
    assert.equal(I.normalizeCryptoPair('NOTAPAIR'), null);
    for (const route of ['bars', 'snapshot', 'quotes', 'trades', 'orderbook']) {
        assert.equal((await request('GET', `/api/crypto/${route}/BTC`)).status, 400, route);
        assert.notEqual((await request('GET', `/api/crypto/${route}/BTCUSD`)).status, 400, route);
    }
});

// ── D10: equity seed anchors ─────────────────────────────────────────────────

test('D10 supabase equity: pre-account seed rows are flagged anchors', async () => {
    const rows = (await getJson('/api/supabase/equity?portfolio_id=portfolio_1&start=2026-01-01')).json;
    assert.deepEqual(rows.map(r => !!r.anchor), [true, true, false, false]);
    const all = (await getJson('/api/supabase/equity?portfolio_id=all&start=2026-01-01')).json;
    assert.ok(!all.some(r => r.date < '2026-04-03'), 'anchors never enter the combined series');
});

// ── D8: structured halt fields ───────────────────────────────────────────────

test('D8 halt assessment exposes structured fields for client-side i18n', () => {
    const h = I.haltAssessment({ halted: true, halt_reason: 'Kill switch: 73.94% drawdown', peak_equity: 100000 }, 97254.4, 100000);
    assert.equal(h.halt_verified, false);
    assert.equal(h.halt_note_code, 'contradicted');
    assert.equal(h.halt_recorded_drawdown_pct, 73.94);
    assert.equal(h.halt_measured_drawdown_pct, 2.75);
    assert.equal(I.haltAssessment({}, 1, 1).halt_note_code, null);
});

// ── D11: health + CSP ────────────────────────────────────────────────────────

test('D11 health: smoke-test fields only, no absolute paths', async () => {
    const r = await getJson('/api/health');
    for (const k of ['apiDir', 'cwd', 'pf1']) assert.ok(!(k in r.json), `${k} must not be exposed`);
    assert.ok(r.json.rootDir, 'rootDir is kept for the CLAUDE.md deploy check');
    for (const f of ['tradeLog', 'signals', 'state']) {
        assert.equal(typeof r.json.files[f].exists, 'boolean');
        assert.ok(!('path' in r.json.files[f]));
    }
    assert.ok(r.json.liveState && typeof r.json.liveState.files === 'object', 'per-file overlay status');
    const leaked = JSON.stringify(r.json.liveState.files);
    assert.ok(!leaked.includes(r.json.rootDir), 'per-file status uses repo-relative names');
});

test('D11 CSP pins script hosts', async () => {
    const r = await request('GET', '/portfolio-detail.html');
    const csp = r.headers['content-security-policy'] || '';
    assert.match(csp, /script-src 'self' 'unsafe-inline' https:\/\/cdn\.jsdelivr\.net https:\/\/s3\.tradingview\.com/);
    assert.match(csp, /object-src 'none'/);
    assert.ok(!/default-src/.test(csp), 'styles/fonts/images/frames stay unrestricted');
});
