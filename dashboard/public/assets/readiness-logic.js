/* readiness-logic.js — pure display decisions for readiness.html (no DOM, no I/O).
   Shared by the page (window.ReadinessLogic) and the node tests (module.exports),
   so the honesty rules below are unit-tested against fixtures:
   - only the exact verdict "GO" is ever treated as GO; an unknown verdict is shown
     raw and neutral, never promoted;
   - a point estimate (alpha) is sign-coloured only when its significance gate
     PASSES — otherwise it is neutral and qualified ("not significant", ...);
   - ETA ranges / confidence-sequence fields are read when the engine adds them,
     and ignored (never invented) when it does not. */
(function (root, factory) {
    var api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.ReadinessLogic = api;
})(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    var KNOWN_VERDICTS = ['GO', 'NOT_READY', 'NOT_ELIGIBLE', 'BETA_SLEEVE', 'FORWARD_TEST_PASS'];
    var KNOWN_GATE_STATUS = ['pass', 'fail', 'insufficient', 'not_measured', 'not_applicable'];

    function num(v) { return typeof v === 'number' && isFinite(v); }
    function obj(v) { return v && typeof v === 'object' && !Array.isArray(v) ? v : null; }

    /** { known, cls, isGo, raw } — cls is a safe CSS suffix; unknown ⇒ 'UNKNOWN'. */
    function verdictInfo(verdict) {
        var known = typeof verdict === 'string' && KNOWN_VERDICTS.indexOf(verdict) >= 0;
        return {
            known: known,
            cls: known ? verdict : 'UNKNOWN',
            isGo: verdict === 'GO',
            raw: verdict == null ? '' : String(verdict)
        };
    }

    function gateStatusKnown(status) { return KNOWN_GATE_STATUS.indexOf(status) >= 0; }

    /** Status of the significance test behind the edge point estimate. */
    function edgeStatus(sleeve) {
        var gates = (sleeve && sleeve.gates) || [];
        for (var i = 0; i < gates.length; i++) if (gates[i] && gates[i].id === 'edge') return gates[i].status || null;
        var e = (sleeve && sleeve.edge) || {};
        return e.status || null;
    }

    /** Qualifier for an edge point estimate given its test status (null ⇒ significant). */
    function edgeQualifier(status) {
        if (status === 'pass') return null;
        if (status === 'not_applicable') return 'not_assessed';
        if (status === 'insufficient' || status === 'not_measured') return 'insufficient';
        return 'not_significant';   // fail, unknown or missing: never imply significance
    }

    /** How to show annual alpha: sign colour only when the edge test passes. */
    function alphaDisplay(sleeve) {
        var e = (sleeve && sleeve.edge) || {};
        if (!num(e.alpha)) return { show: false };
        var st = edgeStatus(sleeve), q = edgeQualifier(st);
        return { show: true, value: e.alpha, signColored: q === null, qualifier: q,
                 t: num(e.t_hac) ? e.t_hac : null, n: num(e.n) ? e.n : null };
    }

    /** Confidence-sequence lower bound on alpha, when the engine provides one. */
    function confidenceBound(edge) {
        edge = edge || {};
        if (!num(edge.cs_lower)) return null;
        return {
            lower: edge.cs_lower,
            upper: num(edge.cs_upper) ? edge.cs_upper : null,
            level: (num(edge.alpha_level) && edge.alpha_level > 0 && edge.alpha_level < 1) ? 1 - edge.alpha_level : null,
            k: num(edge.k_live) ? edge.k_live : null
        };
    }

    var MEDIAN_KEYS = ['median', 'p50', 'expected', 'central'];
    var PESSIMISTIC_KEYS = ['pessimistic', 'p90', 'p95', 'slow', 'upper'];
    var DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

    function point(x) {
        if (typeof x === 'string' && DATE_RE.test(x)) return { date: x, sessions: null };
        if (num(x)) return { date: null, sessions: x };
        var o = obj(x);
        if (!o) return null;
        var d = [o.projected_date, o.date].filter(function (v) { return typeof v === 'string' && DATE_RE.test(v); })[0] || null;
        var s = [o.sessions_remaining, o.sessions].filter(num)[0];
        return (d || num(s)) ? { date: d, sessions: num(s) ? s : null } : null;
    }
    function merge(a, b) {
        if (!a) return b; if (!b) return a;
        return { date: a.date || b.date, sessions: a.sessions != null ? a.sessions : b.sessions };
    }
    function role(ov, keys) {
        var sources = [obj(ov.range), obj(ov.eta_range), obj(ov.projected_date), obj(ov.sessions_remaining), ov];
        var p = null;
        keys.forEach(function (k) {
            sources.forEach(function (src) { if (src) p = merge(p, point(src[k])); });
            p = merge(p, point(ov['projected_date_' + k]));
            if (num(ov['sessions_remaining_' + k])) p = merge(p, { date: null, sessions: ov['sessions_remaining_' + k] });
        });
        return p;
    }

    /** { median, pessimistic } (each { date, sessions } or null) when the engine
        reports an ETA range; null when it reports a single point or nothing. */
    function etaRange(overall) {
        var ov = obj(overall);
        if (!ov) return null;
        var m = role(ov, MEDIAN_KEYS), p = role(ov, PESSIMISTIC_KEYS);
        return (m || p) ? { median: m, pessimistic: p } : null;
    }

    return {
        KNOWN_VERDICTS: KNOWN_VERDICTS, verdictInfo: verdictInfo, gateStatusKnown: gateStatusKnown,
        edgeStatus: edgeStatus, edgeQualifier: edgeQualifier, alphaDisplay: alphaDisplay,
        confidenceBound: confidenceBound, etaRange: etaRange
    };
});
