'use strict';
// Readiness charts: every plotted point must trace back to the engine's report
// (the page draws geometry only), the SVG must never carry NaN, and display
// selection (cleared count, lead sleeve) must follow the honesty rules.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

const RC = require('../public/assets/readiness-charts.js');
const RL = require('../public/assets/readiness-logic.js');
const REPORT = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'data', 'readiness_report.json'), 'utf8'));

const noNaN = (svg) => assert.equal(/NaN|undefined|Infinity/.test(svg), false, 'svg carries NaN/undefined');

test('funnel: model points are the report series verbatim, for every sleeve that has one', () => {
    let seen = 0;
    for (const s of REPORT.sleeves) {
        const e = s.series && s.series.edge;
        if (!e || e.dates.length < 2) continue;
        seen++;
        const r = RC.funnel(e, { width: 640, height: 240 });
        noNaN(r.svg);
        assert.equal(r.model.n, e.dates.length);
        r.model.points.forEach((p, i) => {
            assert.equal(p.date, e.dates[i]);
            assert.equal(p.lower, e.lower[i]);
            assert.equal(p.upper, e.upper[i]);
            assert.equal(p.point, e.point[i]);
        });
        // The last bound plotted IS the decision bound reported for the sleeve.
        assert.ok(Math.abs(e.lower[e.lower.length - 1] - s.edge.cs_lower) < 1e-4, `${s.id} lower bound`);
        assert.ok(Math.abs(e.upper[e.upper.length - 1] - s.edge.cs_upper) < 1e-4, `${s.id} upper bound`);
        assert.equal(r.model.cleared, e.lower[e.lower.length - 1] > 0);
    }
    assert.ok(seen >= 1, 'the report carries at least one edge trajectory');
});

test('funnel: huge early bands are clamped to the frame and flagged, never drawn off-canvas', () => {
    const n = 40, dates = Array.from({ length: n }, (_, i) => `2026-0${1 + Math.floor(i / 20)}-${String(1 + (i % 20)).padStart(2, '0')}`);
    const lower = dates.map((_, i) => -8 / (i + 1) - 0.1), upper = dates.map((_, i) => 8 / (i + 1) + 0.1);
    const r = RC.funnel({ dates, lower, upper, point: dates.map(() => 0.01) }, { width: 600, height: 240 });
    noNaN(r.svg);
    assert.equal(r.model.clamped, true);
    const ys = [...r.svg.matchAll(/[ML](-?[\d.]+) (-?[\d.]+)/g)].map((m) => Number(m[2]));
    assert.ok(ys.every((y) => y >= r.model.frame.t - 0.5 && y <= r.model.frame.h - r.model.frame.b + 0.5), 'every vertex inside the plot');
});

test('funnel / lines / underwater: empty input renders nothing rather than a fake chart', () => {
    assert.equal(RC.funnel({ dates: ['2026-10-22'], lower: [0], upper: [0], point: [0] }).svg, '');
    assert.equal(RC.funnel(null).svg, '');
    assert.equal(RC.lines([], []).svg, '');
    assert.equal(RC.underwater(['2026-10-22'], [0], []).svg, '');
});

test('book series: lines and drawdown carry the report values, worst drawdown matches the book', () => {
    for (const [pid, b] of Object.entries(REPORT.books)) {
        const s = b.series;
        if (!s || s.dates.length < 2) continue;
        const l = RC.lines(s.dates, [{ key: 'b', label: pid, values: s.cum_return }, { key: 's', label: 'SPY', values: s.benchmark_cum }], { width: 500 });
        noNaN(l.svg);
        assert.deepEqual(l.model.lines[0].values, s.cum_return);
        assert.deepEqual(l.model.lines[1].values, s.benchmark_cum);
        const u = RC.underwater(s.dates, s.drawdown, [{ value: -0.15, label: 'gate' }], { width: 500 });
        noNaN(u.svg);
        assert.equal(u.model.worst, Math.min(0, ...s.drawdown));
        // The engine's whole-period max drawdown and the plotted worst point agree.
        assert.ok(Math.abs(-u.model.worst - b.max_drawdown_paper_period) < 1e-3, `${pid} max drawdown`);
    }
});

test('labels: percentages are signed with a true minus and bidi-isolated for Arabic', () => {
    assert.equal(RC.pct(0.0458, 1), '+4.6%');
    assert.equal(RC.pct(-0.589, 1), '−58.9%');
    assert.equal(RC.pct(0), '0%');
    assert.equal(RC.pct(null), '—');
    assert.equal(RC.iso('+4.6%'), '⁦+4.6%⁩');
    const r = RC.lines(['2026-10-21', '2026-10-22'], [{ key: 'b', label: 'P2', values: [0, 0.01] }], { width: 400 });
    assert.ok(r.svg.includes('⁦+1.0%⁩'));
});

test('hover: nearest index is exact at each plotted x', () => {
    const r = RC.lines(['2026-10-20', '2026-10-21', '2026-10-22'], [{ key: 'b', label: 'P', values: [0, 0.01, 0.02] }], { width: 400 });
    r.model.xs.forEach((x, i) => assert.equal(RC.indexAt(r.model, x), i));
});

test('ring: progress is clamped and never exceeds the circle', () => {
    assert.match(RC.ring(200, 90), /class="rc-ring-fg done"/);
    assert.doesNotMatch(RC.ring(10, 90), /done/);
    assert.match(RC.ring(null, 90), /stroke-dasharray="0 /);
});

test('cleared count counts only the exact verdict GO', () => {
    const c = RL.clearedCount({ sleeves: [{ verdict: 'GO' }, { verdict: 'go' }, { verdict: 'FORWARD_TEST_PASS' }, { verdict: 'NOT_READY' }] });
    assert.deepEqual(c, { cleared: 1, total: 4 });
    assert.deepEqual(RL.clearedCount(null), { cleared: 0, total: 0 });
    assert.equal(RL.clearedCount(REPORT).total, REPORT.sleeves.length);
});

test('lead sleeve: accruing, edge-claiming, series-owning, most evidence — never an inactive one', () => {
    const mk = (id, status, n, extra) => Object.assign({ id, status, claims_edge: true, owns_edge_test: true, gates_passed: 1,
        series: { edge: { dates: Array.from({ length: n }, (_, i) => String(i)) } } }, extra || {});
    const rep = { sleeves: [mk('q', 'quarantined', 90), mk('a', 'active', 40), mk('f', 'forward_test', 50),
                             mk('shared', 'active', 99, { owns_edge_test: false }), mk('beta', 'active', 99, { claims_edge: false })] };
    assert.equal(RL.leadSleeve(rep).id, 'f');
    assert.equal(RL.leadSleeve({ sleeves: [mk('q', 'quarantined', 90)] }), null);
    const lead = RL.leadSleeve(REPORT);
    if (lead) assert.ok(['active', 'forward_test'].includes(lead.status) && lead.claims_edge !== false && lead.owns_edge_test !== false);
});
