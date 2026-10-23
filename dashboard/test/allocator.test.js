// Regression tests for the 2026-10-23 engineering audit (P3 allocator sleeve):
// ETF asset-class sectors (no more "Unclassified" for the allocator universe),
// the read-only allocator status payload, the sleeve tag on P3 positions and the
// live-state overlay seed. Offline: live state disabled, Alpaca answered in-process.
process.env.DASHBOARD_ACCESS_TOKEN = 'test-token-0123456789';
process.env.DASHBOARD_LIVE_STATE = '0';
process.env.PORTFOLIO_1_API_KEY = 'k1'; process.env.PORTFOLIO_1_API_SECRET = 's1';
process.env.PORTFOLIO_2_API_KEY = 'k2'; process.env.PORTFOLIO_2_API_SECRET = 's2';
process.env.PORTFOLIO_3_API_KEY = 'k3'; process.env.PORTFOLIO_3_API_SECRET = 's3';

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const https = require('node:https');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { Readable } = require('node:stream');

const P3_POSITIONS = ['CTA', 'IEF', 'BIL', 'KO'].map(sym => ({
    symbol: sym, qty: '10', avg_entry_price: '100', current_price: '101', market_value: '1010',
    unrealized_pl: '10', unrealized_plpc: '0.01', lastday_price: '100.5', asset_class: 'us_equity',
}));
const realRequest = https.request;
https.request = function (options, cb) {
    if (!options || !/alpaca\.markets$/.test(options.hostname || '')) return realRequest.apply(this, arguments);
    const p = options.path.split('?')[0];
    const key = options.headers['APCA-API-KEY-ID'];
    const req = new EventEmitter();
    req.write = () => true; req.destroy = () => {}; req.setTimeout = () => req;
    const reply = (status, body) => {
        const res = Readable.from([Buffer.from(JSON.stringify(body))]);
        res.statusCode = status;
        setImmediate(() => cb(res));
    };
    req.end = () => {
        if (p === '/v2/account') return reply(200, { equity: '99000', last_equity: '98900', cash: '60000', balance_asof: '2026-10-22' });
        if (p === '/v2/positions') return reply(200, key === 'k3' ? P3_POSITIONS : []);
        if (p === '/v2/orders') return reply(200, []);
        if (p === '/v2/clock') return reply(200, { is_open: false, timestamp: new Date().toISOString() });
        if (p === '/v2/calendar') return reply(200, []);
        return reply(404, { message: 'not stubbed' });
    };
    return req;
};

const app = require('../server.js');
const I = app._internals;

let server;
test.before(async () => {
    server = http.createServer(app);
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
});
test.after(() => new Promise((resolve) => server.close(resolve)));

function getJson(rawPath) {
    return new Promise((resolve, reject) => {
        const { port } = server.address();
        const req = http.request({ host: '127.0.0.1', port, path: rawPath, method: 'GET' }, (res) => {
            let body = '';
            res.on('data', (c) => { body += c; });
            res.on('end', () => resolve({ status: res.statusCode, json: JSON.parse(body) }));
        });
        req.setTimeout(8000, () => req.destroy(new Error(`timeout: ${rawPath}`)));
        req.on('error', reject);
        req.end();
    });
}

const STATE = {
    strategy: 'crisis_core_v1', strategy_tag: 'crisis_core_v1_scaled', mode: 'paper_forward_test',
    note: 'FORWARD TEST — paper only', last_rebalance_month: null,
    targets_month: '2026-10', targets_frozen_at: '2026-10-22',
    targets: { SPY: 0.076, CTA: 0.076, BIL: 0.0586666667, 'bad key': 1 },
    targets_constrained: { SPY: 0.0529, CTA: 0.0556 },
    cap_shortfall_pct: 18.4231, live_cap: 0.076, hard_cap: 0.08, scale: 0.66666667,
    last_run_at: '2026-10-23T14:11:35+00:00', last_trade_session: '2026-10-23',
    residual_tbill: { rule: 'parent-spec T-bill residual', budget: 0.2, added: { SHV: 0.1, SGOV: 0.1 },
        cash_residual: 0.05, legacy_gross_w_at_freeze: 0.1 },
    last_run: {
        at: '2026-10-23T14:11:35+00:00', status: 'month_in_progress', session: '2026-10-23',
        cap_shortfall_pct: 18.4231, buys_blocked: null, deferred: [], skips: [],
        orders: [{ symbol: 'SPY', status: 'filled' }, { symbol: 'CTA', status: 'filled' }, { symbol: 'BIL', status: 'new' }],
    },
};
const TRADE_LOG = [
    { symbol: 'CTA', tranche: 'allocator_forward_test', status: 'open' },
    { symbol: 'IEF', tranche: 'allocator_forward_test', status: 'open' },
    { symbol: 'SPY', tranche: 'allocator_forward_test', status: 'closed' },
    { symbol: 'KO', tranche: 'legacy', status: 'open' },
];

test('allocator universe + T-bill basket are classified, never "Unclassified"', () => {
    const want = {
        SPY: 'US Equity (Broad)', QQQ: 'US Equity (Broad)', IWM: 'US Equity (Broad)',
        EFA: 'International Equity',
        DBMF: 'Managed Futures', KMLM: 'Managed Futures', CTA: 'Managed Futures',
        IEF: 'US Treasuries',
        BIL: 'Cash & T-Bills', SHV: 'Cash & T-Bills', SGOV: 'Cash & T-Bills', USFR: 'Cash & T-Bills',
    };
    for (const [sym, sector] of Object.entries(want)) assert.equal(I.sectorFor(sym), sector, sym);
    assert.equal(I.sectorFor('ief'), 'US Treasuries', 'case-insensitive');
});

test('allocator status payload: shape, counts and sleeve universe', () => {
    const a = I.buildAllocatorStatus(STATE, TRADE_LOG);
    assert.equal(a.available, true);
    assert.equal(a.tranche, 'allocator_forward_test');
    assert.equal(a.strategy_tag, 'crisis_core_v1_scaled');
    assert.equal(a.status, 'month_in_progress');
    assert.equal(a.session, '2026-10-23');
    assert.equal(a.last_run_at, '2026-10-23T14:11:35+00:00');
    assert.equal(a.targets_month, '2026-10');
    assert.equal(a.cap_shortfall_pct, 18.4231);
    assert.equal(a.buys_blocked, null);
    assert.deepEqual(a.last_run_orders, { count: 3, filled: 2, unfilled: 1, deferred: 0, skipped: 0 });
    assert.deepEqual(a.targets.map(t => t.symbol), ['CTA', 'SPY', 'BIL'], 'malformed keys dropped, sorted by weight');
    assert.equal(a.targets.find(t => t.symbol === 'BIL').constrained_w, null, 'unknown constrained weight is null, not 0');
    assert.equal(a.open_lots, 2);
    assert.deepEqual(a.open_symbols, ['CTA', 'IEF']);
    assert.deepEqual(a.universe, ['BIL', 'CTA', 'IEF', 'SPY']);
    assert.deepEqual(a.residual_tbill, {
        rule: 'parent-spec T-bill residual', budget: 0.2, cash_residual: 0.05, legacy_gross_w_at_freeze: 0.1,
        added: [{ symbol: 'SHV', weight: 0.1 }, { symbol: 'SGOV', weight: 0.1 }],
    });
});

test('allocator status is honest when state is missing or partial', () => {
    assert.deepEqual(I.buildAllocatorStatus(null, TRADE_LOG), { available: false });
    assert.deepEqual(I.buildAllocatorStatus([], TRADE_LOG), { available: false });
    const a = I.buildAllocatorStatus({ strategy: 'crisis_core_v1' }, null);
    assert.equal(a.available, true);
    assert.equal(a.status, null);
    assert.equal(a.last_run_at, null);
    assert.equal(a.cap_shortfall_pct, null);
    assert.equal(a.residual_tbill, null, 'no residual block => null, never a fabricated one');
    assert.deepEqual(a.targets, []);
    assert.deepEqual(a.universe, []);
    assert.equal(I.buildAllocatorStatus({ last_run: { buys_blocked: { reason: 'gross' } } }, []).buys_blocked,
        '{"reason":"gross"}');
});

test('allocator_state.json is P3-only and seeded into the live-state overlay', () => {
    assert.equal(I.getIntelligencePaths('portfolio_1').allocatorState, null);
    assert.equal(I.getIntelligencePaths('portfolio_2').allocatorState, null);
    const p3 = I.getIntelligencePaths('portfolio_3').allocatorState;
    assert.match(p3, /event-driven-bot[\\/]data[\\/]allocator_state\.json$/);
    assert.ok(I.hotStatePaths.has(path.resolve(p3)), 'overlay seed list includes allocator_state.json');
});

test('P3 intelligence exposes the allocator block; other books do not', async () => {
    const p3 = await getJson('/api/portfolio/portfolio_3/intelligence');
    assert.equal(p3.status, 200);
    assert.ok(p3.json.allocator && typeof p3.json.allocator.available === 'boolean');
    const p1 = await getJson('/api/portfolio/portfolio_1/intelligence');
    assert.equal('allocator' in p1.json, false);
});

test('P3 details: sectors filled and allocator positions tagged with the sleeve', async () => {
    const r = await getJson('/api/portfolio/portfolio_3/details');
    assert.equal(r.status, 200);
    const bySym = Object.fromEntries(r.json.positions.map(p => [p.symbol, p]));
    assert.equal(bySym.CTA.sector, 'Managed Futures');
    assert.equal(bySym.IEF.sector, 'US Treasuries');
    assert.equal(bySym.BIL.sector, 'Cash & T-Bills');
    assert.equal(bySym.KO.sleeve, null, 'legacy names are never tagged');
    const a = r.json.allocator;
    assert.ok(a && typeof a.available === 'boolean');
    if (a.available) {
        for (const sym of ['CTA', 'IEF', 'BIL']) {
            if (a.universe.includes(sym)) assert.equal(bySym[sym].sleeve, 'allocator_forward_test', sym);
        }
    }
    const p1 = await getJson('/api/portfolio/portfolio_1/details');
    assert.equal('allocator' in p1.json, false);
});
