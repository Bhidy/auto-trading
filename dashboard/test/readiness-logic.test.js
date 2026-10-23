// Display-honesty rules of the readiness page, tested on fixtures (pure module —
// the same file the page loads as /assets/readiness-logic.js).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const RL = require('../public/assets/readiness-logic.js');

const sleeve = (over = {}) => ({
    id: 'x', book: 'portfolio_1', verdict: 'NOT_READY', status: 'active',
    gates: [{ id: 'edge', status: 'fail', hard: true }],
    edge: { alpha: 0.0283, t_hac: 0.37, n: 78, status: 'fail' },
    ...over,
});

test('verdict: only the exact string GO is GO; new verdicts known; unknown is raw + neutral', () => {
    assert.equal(RL.verdictInfo('GO').isGo, true);
    for (const v of ['NOT_READY', 'NOT_ELIGIBLE', 'BETA_SLEEVE', 'FORWARD_TEST_PASS']) {
        const i = RL.verdictInfo(v);
        assert.equal(i.known, true, v);
        assert.equal(i.isGo, false, v);
        assert.equal(i.cls, v);
    }
    for (const v of ['go', 'GO ', 'READY', 'GO_LIVE', '', null, undefined, 1, { v: 'GO' }]) {
        const i = RL.verdictInfo(v);
        assert.equal(i.isGo, false, JSON.stringify(v));
        assert.equal(i.known, false, JSON.stringify(v));
        assert.equal(i.cls, 'UNKNOWN', 'unknown verdict never reuses a known style');
    }
    assert.equal(RL.verdictInfo('<img src=x>').cls, 'UNKNOWN', 'raw value never becomes a class name');
});

test('alpha: sign-coloured only when the edge gate passes; otherwise qualified', () => {
    const failed = RL.alphaDisplay(sleeve());
    assert.equal(failed.signColored, false);
    assert.equal(failed.qualifier, 'not_significant');
    assert.equal(failed.t, 0.37);

    const insufficient = RL.alphaDisplay(sleeve({ gates: [{ id: 'edge', status: 'insufficient' }], edge: { alpha: -0.71, n: 16 } }));
    assert.equal(insufficient.signColored, false);
    assert.equal(insufficient.qualifier, 'insufficient');

    const beta = RL.alphaDisplay(sleeve({ verdict: 'BETA_SLEEVE', gates: [{ id: 'edge', status: 'not_applicable' }], edge: { alpha: 0.07, status: 'fail' } }));
    assert.equal(beta.signColored, false, 'gate status wins over edge.status');
    assert.equal(beta.qualifier, 'not_assessed');

    const unknownStatus = RL.alphaDisplay(sleeve({ gates: [{ id: 'edge', status: 'pending_review' }] }));
    assert.equal(unknownStatus.signColored, false, 'an unknown test status never implies significance');

    const noGate = RL.alphaDisplay(sleeve({ gates: [], edge: { alpha: 0.05 } }));
    assert.equal(noGate.signColored, false);

    const passed = RL.alphaDisplay(sleeve({ gates: [{ id: 'edge', status: 'pass' }] }));
    assert.equal(passed.signColored, true);
    assert.equal(passed.qualifier, null);

    assert.equal(RL.alphaDisplay(sleeve({ edge: { alpha: null } })).show, false);
});

test('confidence sequence: shown only when the engine provides cs_lower', () => {
    assert.equal(RL.confidenceBound({ alpha: 0.03 }), null);
    assert.equal(RL.confidenceBound(null), null);
    const cb = RL.confidenceBound({ cs_lower: -0.04, cs_upper: 0.09, alpha_level: 0.05, k_live: 3 });
    assert.deepEqual(cb, { lower: -0.04, upper: 0.09, level: 0.95, k: 3 });
    assert.deepEqual(RL.confidenceBound({ cs_lower: 0.01 }), { lower: 0.01, upper: null, level: null, k: null });
});

test('ETA: single-point v2 schema is not a range; range shapes are read when present', () => {
    assert.equal(RL.etaRange({ sessions_remaining: 146, projected_date: '2027-05-24', label: 'estimate' }), null);
    assert.equal(RL.etaRange({ sessions_remaining: null, projected_date: null }), null);
    assert.equal(RL.etaRange(undefined), null);

    assert.deepEqual(RL.etaRange({ median: { projected_date: '2027-05-24', sessions_remaining: 146 }, pessimistic: { projected_date: '2027-11-02', sessions_remaining: 260 } }),
        { median: { date: '2027-05-24', sessions: 146 }, pessimistic: { date: '2027-11-02', sessions: 260 } });
    assert.deepEqual(RL.etaRange({ projected_date: { median: '2027-05-24', pessimistic: '2027-11-02' }, sessions_remaining: { median: 146, pessimistic: 260 } }),
        { median: { date: '2027-05-24', sessions: 146 }, pessimistic: { date: '2027-11-02', sessions: 260 } });
    assert.deepEqual(RL.etaRange({ range: { p50: 120, p90: 300 } }),
        { median: { date: null, sessions: 120 }, pessimistic: { date: null, sessions: 300 } });
    assert.deepEqual(RL.etaRange({ projected_date_median: '2027-05-24', sessions_remaining_pessimistic: 260 }),
        { median: { date: '2027-05-24', sessions: null }, pessimistic: { date: null, sessions: 260 } });
});

test('gate statuses: the five engine statuses are known; anything else is rendered raw', () => {
    for (const st of ['pass', 'fail', 'insufficient', 'not_measured', 'not_applicable']) assert.equal(RL.gateStatusKnown(st), true);
    for (const st of ['PASS', 'passed', '', null, 'ok']) assert.equal(RL.gateStatusKnown(st), false);
});

test('committed report: every sleeve has a known verdict and none of them is coloured as significant without a passing edge gate', () => {
    const p = path.join(__dirname, '..', 'data', 'readiness_report.json');
    if (!fs.existsSync(p)) return;
    const report = JSON.parse(fs.readFileSync(p, 'utf-8'));
    for (const s of report.sleeves) {
        assert.equal(RL.verdictInfo(s.verdict).known, true, `${s.id}: ${s.verdict}`);
        const ad = RL.alphaDisplay(s);
        if (ad.show) assert.equal(ad.signColored, RL.edgeStatus(s) === 'pass', s.id);
    }
});

test('page wiring: readiness.html loads the logic module and keeps no client-side gate math', () => {
    const html = fs.readFileSync(path.join(__dirname, '..', 'public', 'readiness.html'), 'utf-8');
    assert.match(html, /<script src="\/assets\/readiness-logic\.js"><\/script>/);
    assert.match(html, /fetch\('\/api\/readiness'/);
    for (const banned of ['maxDrawdown(', 'profitFactor', 'strokeDashoffset', 'real-money ready', 'sharpePass']) {
        assert.equal(html.includes(banned), false, `legacy client-side readiness logic present: ${banned}`);
    }
});
