/* Readiness charts — pure SVG builders for the Live-Readiness page.
 *
 * Every function draws GEOMETRY from series the Readiness Engine already
 * computed (data/readiness_report.json). Nothing here estimates, smooths or
 * projects a statistic. Each builder returns { svg, model }: the model holds
 * the exact report values behind every plotted point, so tests can bind the
 * picture to the report and the hover layer can read values back verbatim.
 *
 * Charts are drawn at the container's real pixel width (the page re-renders on
 * resize), so type never shrinks on a phone. Time runs left-to-right in both
 * languages (financial convention) — the caller wraps charts in dir="ltr".
 * UMD: window.ReadinessCharts in the browser, module.exports under node. */
(function (root, factory) {
    if (typeof module === 'object' && module.exports) module.exports = factory();
    else root.ReadinessCharts = factory();
})(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    function num(v) { return typeof v === 'number' && isFinite(v); }
    function r1(v) { return Math.round(v * 10) / 10; }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function lin(d0, d1, r0, r1_) {
        var k = d1 === d0 ? 0 : (r1_ - r0) / (d1 - d0);
        return function (v) { return r0 + (v - d0) * k; };
    }
    /** A number inside a label, bidi-isolated (LRI…PDI) so an Arabic label
        never reorders its digits or sign. */
    function iso(s) { return '\u2066' + s + '\u2069'; }
    /** Signed percent label: +4.6%, −2.9% (true minus sign), 0%. */
    function pct(v, d) {
        if (!num(v)) return '—';
        var a = Math.abs(v * 100), s = a.toFixed(d == null ? 1 : d);
        if (Number(s) === 0) return '0%';
        return (v > 0 ? '+' : '−') + s + '%';
    }
    /** "Nice" tick values covering [lo, hi] (Heckbert). */
    function ticks(lo, hi, count) {
        if (!(hi > lo)) return [lo];
        var span = hi - lo, step = Math.pow(10, Math.floor(Math.log10(span / Math.max(1, count))));
        var err = (count / span) * step;
        if (err <= 0.15) step *= 10; else if (err <= 0.35) step *= 5; else if (err <= 0.75) step *= 2;
        var out = [], v = Math.ceil(lo / step) * step;
        for (; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
        return out;
    }
    function monthLabel(iso, names) {
        var m = Number(String(iso).slice(5, 7));
        return (names || MONTHS)[m - 1] || '';
    }
    /** Indices where a new calendar month starts (first session of the month). */
    function monthStarts(dates) {
        var out = [];
        for (var i = 0; i < dates.length; i++) {
            if (i === 0 || String(dates[i]).slice(0, 7) !== String(dates[i - 1]).slice(0, 7)) out.push(i);
        }
        return out;
    }
    function polyline(xs, ys) {
        var d = '', pen = false;
        for (var i = 0; i < xs.length; i++) {
            if (ys[i] == null) { pen = false; continue; }          // a gap, never an invented value
            d += (pen ? 'L' : 'M') + r1(xs[i]) + ' ' + r1(ys[i]);
            pen = true;
        }
        return d;
    }
    function lastFinite(vs) { for (var i = vs.length - 1; i >= 0; i--) if (num(vs[i])) return vs[i]; return null; }
    /** Push end labels apart so none overlap (min gap px), within [top, bottom]. */
    function declutter(items, gap, top, bottom) {
        items.sort(function (a, b) { return a.y - b.y; });
        for (var i = 1; i < items.length; i++) if (items[i].y - items[i - 1].y < gap) items[i].y = items[i - 1].y + gap;
        var over = items.length ? items[items.length - 1].y - bottom : 0;
        if (over > 0) for (var j = items.length - 1; j >= 0; j--) {
            items[j].y -= over;
            if (j > 0 && items[j].y - items[j - 1].y >= gap) break;
        }
        items.forEach(function (it) { it.y = Math.max(top, it.y); });
        return items;
    }

    function frame(width, height, pad) {
        return { w: Math.max(200, Math.round(width)), h: height, l: pad.l, r: pad.r, t: pad.t, b: pad.b };
    }
    function open(f, cls, label) {
        return '<svg class="rc ' + cls + '" width="' + f.w + '" height="' + f.h + '" viewBox="0 0 ' + f.w + ' ' + f.h +
            '" role="img" aria-label="' + esc(label) + '" xmlns="http://www.w3.org/2000/svg">';
    }
    function xAxis(f, dates, x, names) {
        var out = '', starts = monthStarts(dates), minGap = 34, last = -1e9;
        starts.forEach(function (i) {
            var px = x(i);
            if (px - last < minGap) return;
            last = px;
            out += '<line class="rc-tick" x1="' + r1(px) + '" x2="' + r1(px) + '" y1="' + (f.h - f.b) + '" y2="' + (f.h - f.b + 4) + '"/>' +
                '<text class="rc-axis" x="' + r1(px) + '" y="' + (f.h - f.b + 16) + '" text-anchor="start">' + esc(monthLabel(dates[i], names)) + '</text>';
        });
        return out;
    }
    function yGrid(f, tv, y, fmt) {
        return tv.map(function (v) {
            var py = r1(y(v));
            return '<line class="rc-grid' + (v === 0 ? ' rc-zero-soft' : '') + '" x1="' + f.l + '" x2="' + (f.w - f.r) + '" y1="' + py + '" y2="' + py + '"/>' +
                '<text class="rc-axis" x="' + (f.l - 8) + '" y="' + (py + 4) + '" text-anchor="end">' + esc(fmt(v)) + '</text>';
        }).join('');
    }

    /**
     * Evidence funnel: the always-valid confidence band on annual alpha at every
     * session the engine could have stopped, the estimate inside it, and the
     * zero line. Edge is proven when the LOWER bound clears zero.
     * series = { dates, lower, upper, point } (annualized, report units).
     */
    function funnel(series, opts) {
        opts = opts || {};
        var L = opts.labels || {};
        var dates = (series && series.dates) || [], lo = (series && series.lower) || [], hi = (series && series.upper) || [],
            pt = (series && series.point) || [];
        var n = Math.min(dates.length, lo.length, hi.length, pt.length);
        var narrow = (opts.width || 640) < 520;
        var f = frame(opts.width || 640, opts.height || 240, { l: narrow ? 44 : 52, r: narrow ? 84 : 96, t: 18, b: 26 });
        if (n < 2) return { svg: '', model: { n: n, points: [], empty: true } };
        // Fit the y-domain to the latter 60% of the path: the earliest bands are
        // enormous (n ~ 20) and would flatten the part of the funnel that matters.
        var from = Math.floor(n * 0.4), ymin = 0, ymax = 0;
        for (var i = from; i < n; i++) {
            if (num(lo[i])) ymin = Math.min(ymin, lo[i]);
            if (num(hi[i])) ymax = Math.max(ymax, hi[i]);
        }
        var padY = (ymax - ymin) * 0.08 || 0.05;
        ymin -= padY; ymax += padY;
        var x = lin(0, n - 1, f.l, f.w - f.r), y = lin(ymin, ymax, f.h - f.b, f.t);
        var clampedTop = false, clampedBottom = false;
        function cy(v) {
            if (v > ymax) { clampedTop = true; return y(ymax); }
            if (v < ymin) { clampedBottom = true; return y(ymin); }
            return y(v);
        }
        var xs = [], ylo = [], yhi = [], ypt = [], points = [];
        for (var k = 0; k < n; k++) {
            xs.push(x(k)); ylo.push(cy(lo[k])); yhi.push(cy(hi[k])); ypt.push(cy(pt[k]));
            points.push({ i: k, date: dates[k], lower: lo[k], upper: hi[k], point: pt[k] });
        }
        var band = polyline(xs, yhi) + polyline(xs.slice().reverse(), ylo.slice().reverse()).replace(/^M/, 'L') + 'Z';
        var y0 = r1(y(0));
        var tv = ticks(ymin, ymax, 4);
        var cleared = lo[n - 1] > 0;
        var ends = declutter([
            { y: yhi[n - 1], t: (L.upper || 'Upper') + ' ' + iso(pct(hi[n - 1], 0)), c: 'rc-lab-band' },
            { y: ypt[n - 1], t: (L.estimate || 'Midpoint') + ' ' + iso(pct(pt[n - 1], 0)), c: 'rc-lab-ink' },
            { y: ylo[n - 1], t: (L.lower || 'Lower') + ' ' + iso(pct(lo[n - 1], 0)), c: cleared ? 'rc-lab-pos' : 'rc-lab-band' }
        ], 15, f.t + 4, f.h - f.b);
        var svg = open(f, 'rc-funnel', opts.aria || 'Evidence funnel') +
            '<defs><clipPath id="' + (opts.id || 'fn') + '-clip"><rect x="' + f.l + '" y="' + f.t + '" width="' + (f.w - f.l - f.r) + '" height="' + (f.h - f.t - f.b) + '"/></clipPath></defs>' +
            // GO zone: everything above the zero line, where the lower bound must arrive.
            '<rect class="rc-gozone" x="' + f.l + '" y="' + f.t + '" width="' + (f.w - f.l - f.r) + '" height="' + Math.max(0, y0 - f.t) + '"/>' +
            yGrid(f, tv, y, function (v) { return pct(v, 0); }) +
            '<g clip-path="url(#' + (opts.id || 'fn') + '-clip)">' +
                '<path class="rc-band" d="' + band + '"/>' +
                '<path class="rc-band-edge" d="' + polyline(xs, yhi) + '"/>' +
                '<path class="rc-band-edge" d="' + polyline(xs, ylo) + '"/>' +
                '<path class="rc-halo" d="' + polyline(xs, ypt) + '"/>' +
                '<path class="rc-est" d="' + polyline(xs, ypt) + '"/>' +
            '</g>' +
            '<line class="rc-zero" x1="' + f.l + '" x2="' + (f.w - f.r) + '" y1="' + y0 + '" y2="' + y0 + '"/>' +
            '<text class="rc-zero-lab" x="' + (f.l + 6) + '" y="' + (y0 - 6) + '">' + esc(L.zero || 'GO line · 0%') + '</text>' +
            (!narrow && (clampedTop || clampedBottom) ? '<text class="rc-axis rc-off" x="' + (f.l + 6) + '" y="' + (f.t + 12) + '">' + esc(L.offscale || 'Earlier bounds off-scale') + '</text>' : '') +
            '<circle class="rc-end ' + (cleared ? 'rc-end-pos' : '') + '" cx="' + r1(xs[n - 1]) + '" cy="' + r1(ylo[n - 1]) + '" r="3.5"/>' +
            ends.map(function (e) { return '<text class="rc-lab ' + e.c + '" x="' + (f.w - f.r + 8) + '" y="' + r1(e.y + 4) + '">' + esc(e.t) + '</text>'; }).join('') +
            xAxis(f, dates.slice(0, n), x, opts.months) +
            '<rect class="rc-hit" x="' + f.l + '" y="' + f.t + '" width="' + (f.w - f.l - f.r) + '" height="' + (f.h - f.t - f.b) + '"/>' +
            '</svg>';
        return { svg: svg, model: { kind: 'funnel', n: n, points: points, xs: xs, frame: f, ymin: ymin, ymax: ymax,
            clamped: clampedTop || clampedBottom, cleared: cleared } };
    }

    /**
     * Cumulative return lines (e.g. book vs SPY) with direct end labels.
     * lines = [{ key, label, values, cls }]  (values: report cum returns)
     */
    function lines(dates, ls, opts) {
        opts = opts || {};
        var n = dates ? dates.length : 0;
        var f = frame(opts.width || 480, opts.height || 180, { l: 46, r: (opts.width || 480) < 520 ? 82 : 92, t: 14, b: 26 });
        ls = (ls || []).filter(function (l) { return l && l.values && l.values.length === n; });
        if (n < 2 || !ls.length) return { svg: '', model: { n: n, empty: true } };
        var lo = 0, hi = 0;
        ls.forEach(function (l) { l.values.forEach(function (v) { if (num(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }); });
        var p = (hi - lo) * 0.1 || 0.01; lo -= p; hi += p;
        var x = lin(0, n - 1, f.l, f.w - f.r), y = lin(lo, hi, f.h - f.b, f.t);
        var xs = []; for (var i = 0; i < n; i++) xs.push(x(i));
        var labs = declutter(ls.filter(function (l) { return num(lastFinite(l.values)); }).map(function (l) {
            var v = lastFinite(l.values), fin = num(l.values[n - 1]);
            // A series that ends in a gap has no current value: label it, don't quote a stale one.
            return { y: y(v), t: l.label + ' ' + iso(fin ? pct(v, 1) : '—'), c: l.cls || '' };
        }), 15, f.t + 4, f.h - f.b);
        var svg = open(f, 'rc-lines', opts.aria || 'Cumulative return') +
            yGrid(f, ticks(lo, hi, 3), y, function (v) { return pct(v, 0); }) +
            ls.map(function (l) {
                var ys = l.values.map(function (v) { return num(v) ? y(v) : null; });
                return '<path class="rc-halo" d="' + polyline(xs, ys) + '"/><path class="rc-line ' + (l.cls || '') + '" d="' + polyline(xs, ys) + '"/>';
            }).join('') +
            labs.map(function (e) { return '<text class="rc-lab ' + e.c + '" x="' + (f.w - f.r + 8) + '" y="' + r1(e.y + 4) + '">' + esc(e.t) + '</text>'; }).join('') +
            xAxis(f, dates, x, opts.months) +
            '<rect class="rc-hit" x="' + f.l + '" y="' + f.t + '" width="' + (f.w - f.l - f.r) + '" height="' + (f.h - f.t - f.b) + '"/>' +
            '</svg>';
        return { svg: svg, model: { kind: 'lines', n: n, xs: xs, frame: f, dates: dates,
            lines: ls.map(function (l) { return { key: l.key, label: l.label, values: l.values }; }) } };
    }

    /**
     * Underwater drawdown (0 at the top, losses below) with labelled limit lines.
     * limits = [{ value: -0.15, label, cls }]
     */
    function underwater(dates, dd, limits, opts) {
        opts = opts || {};
        var n = Math.min(dates ? dates.length : 0, dd ? dd.length : 0);
        var f = frame(opts.width || 480, opts.height || 150, { l: 46, r: (opts.width || 480) < 520 ? 82 : 92, t: 12, b: 26 });
        if (n < 2) return { svg: '', model: { n: n, empty: true } };
        var lo = 0;
        dd.forEach(function (v) { if (num(v)) lo = Math.min(lo, v); });
        (limits || []).forEach(function (l) { lo = Math.min(lo, l.value); });
        lo *= 1.08;
        var x = lin(0, n - 1, f.l, f.w - f.r), y = lin(lo, 0, f.h - f.b, f.t);
        var xs = [], ys = [];
        for (var i = 0; i < n; i++) { xs.push(x(i)); ys.push(y(num(dd[i]) ? dd[i] : 0)); }
        var area = polyline(xs, ys) + 'L' + r1(xs[n - 1]) + ' ' + r1(y(0)) + 'L' + r1(xs[0]) + ' ' + r1(y(0)) + 'Z';
        var worst = 0, wi = 0;
        for (var k = 0; k < n; k++) if (num(dd[k]) && dd[k] < worst) { worst = dd[k]; wi = k; }
        var labs = declutter((limits || []).map(function (l) {
            return { y: y(l.value), t: l.label + ' ' + iso(pct(l.value, 0)), c: l.cls || '' };
        }), 14, f.t + 4, f.h - f.b);
        var svg = open(f, 'rc-under', opts.aria || 'Drawdown') +
            yGrid(f, ticks(lo, 0, 3), y, function (v) { return pct(v, 0); }) +
            '<path class="rc-dd" d="' + area + '"/>' +
            '<path class="rc-dd-edge" d="' + polyline(xs, ys) + '"/>' +
            (limits || []).map(function (l) {
                var py = r1(y(l.value));
                return '<line class="rc-limit ' + (l.cls || '') + '" x1="' + f.l + '" x2="' + (f.w - f.r) + '" y1="' + py + '" y2="' + py + '"/>';
            }).join('') +
            labs.map(function (e) { return '<text class="rc-lab ' + e.c + '" x="' + (f.w - f.r + 8) + '" y="' + r1(e.y + 4) + '">' + esc(e.t) + '</text>'; }).join('') +
            (worst < 0 ? '<circle class="rc-end rc-end-neg" cx="' + r1(xs[wi]) + '" cy="' + r1(ys[wi]) + '" r="3"/>' +
                '<text class="rc-lab rc-lab-neg" x="' + r1(Math.min(xs[wi] + 6, f.w - f.r - 40)) + '" y="' + r1(Math.min(ys[wi] + 14, f.h - f.b - 2)) + '">' + pct(worst, 1) + '</text>' : '') +
            xAxis(f, dates.slice(0, n), x, opts.months) +
            '<rect class="rc-hit" x="' + f.l + '" y="' + f.t + '" width="' + (f.w - f.l - f.r) + '" height="' + (f.h - f.t - f.b) + '"/>' +
            '</svg>';
        return { svg: svg, model: { kind: 'underwater', n: n, xs: xs, frame: f, dates: dates, drawdown: dd.slice(0, n),
            worst: worst, worstDate: dates[wi] } };
    }

    /** Progress ring (sessions accrued vs required). Value is clamped to [0, target]. */
    function ring(value, target, opts) {
        opts = opts || {};
        var size = opts.size || 56, sw = opts.stroke || 5, rr = (size - sw) / 2, c = 2 * Math.PI * rr;
        var frac = target > 0 && num(value) ? Math.max(0, Math.min(1, value / target)) : 0;
        return '<svg class="rc-ring" width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size + '" aria-hidden="true">' +
            '<circle class="rc-ring-bg" cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r1(rr) + '" stroke-width="' + sw + '"/>' +
            '<circle class="rc-ring-fg' + (frac >= 1 ? ' done' : '') + '" cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r1(rr) + '" stroke-width="' + sw +
            '" stroke-dasharray="' + r1(c * frac) + ' ' + r1(c) + '" transform="rotate(-90 ' + size / 2 + ' ' + size / 2 + ')"/></svg>';
    }

    /** Nearest data index for a pointer x (px within the svg). */
    function indexAt(model, px) {
        if (!model || !model.xs || !model.xs.length) return -1;
        var xs = model.xs, best = 0, d = Infinity;
        for (var i = 0; i < xs.length; i++) { var e = Math.abs(xs[i] - px); if (e < d) { d = e; best = i; } }
        return best;
    }

    /**
     * Crosshair + tooltip. ``describe(i)`` returns the tooltip HTML for index i
     * (values read verbatim from the model). Pointer and keyboard (arrow keys)
     * both drive it; the host must be position:relative.
     */
    function attachHover(host, model, describe) {
        if (!host || !model || !model.xs || typeof document === 'undefined') return;
        var svg = host.querySelector('svg.rc'); if (!svg) return;
        var f = model.frame, ns = 'http://www.w3.org/2000/svg';
        var rule = document.createElementNS(ns, 'line');
        rule.setAttribute('class', 'rc-rule'); rule.setAttribute('y1', f.t); rule.setAttribute('y2', f.h - f.b);
        rule.style.display = 'none'; svg.appendChild(rule);
        var tip = document.createElement('div'); tip.className = 'rc-tip'; tip.hidden = true; host.appendChild(tip);
        var cur = -1;
        function show(i) {
            if (i < 0) return hide();
            cur = i;
            var px = model.xs[i];
            rule.setAttribute('x1', px); rule.setAttribute('x2', px); rule.style.display = '';
            tip.innerHTML = describe(i); tip.hidden = false;
            var left = Math.min(Math.max(px - tip.offsetWidth / 2, 4), host.clientWidth - tip.offsetWidth - 4);
            tip.style.left = left + 'px'; tip.style.top = (f.t - 6) + 'px';
        }
        function hide() { cur = -1; rule.style.display = 'none'; tip.hidden = true; }
        svg.addEventListener('pointermove', function (ev) {
            var b = svg.getBoundingClientRect();
            show(indexAt(model, (ev.clientX - b.left) * (f.w / b.width)));
        });
        svg.addEventListener('pointerleave', hide);
        host.addEventListener('keydown', function (ev) {
            if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
            ev.preventDefault();
            var n = model.xs.length, i = cur < 0 ? n - 1 : cur + (ev.key === 'ArrowRight' ? 1 : -1);
            show(Math.max(0, Math.min(n - 1, i)));
        });
        host.addEventListener('blur', hide, true);
    }

    return { funnel: funnel, lines: lines, underwater: underwater, ring: ring, attachHover: attachHover,
             indexAt: indexAt, pct: pct, iso: iso, ticks: ticks, monthStarts: monthStarts, _declutter: declutter };
});
