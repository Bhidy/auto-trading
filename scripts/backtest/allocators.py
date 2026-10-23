"""Pure target-weight allocators for the pre-registered ETF allocation specs.

Specs: ``docs/specs/matf_v1.json`` (S1), ``docs/specs/secmom_v1.json`` (S2),
``docs/specs/crisis_core_v1.json`` (S3).

Every allocator has the signature::

    target_weights(closes_by_sym, as_of_index, params) -> {symbol: weight}

* ``closes_by_sym``: ``{symbol: [close_0, ..., close_n]}`` aligned to one session
  calendar; ``None`` where the symbol had not listed yet. Dividend-adjusted closes.
* ``as_of_index``: the signal session ``t``. Allocators read ONLY ``closes[0..t]``
  (the backtester additionally truncates the lists, so look-ahead is impossible).
* returned weights are fractions of equity, long-only, each <= ``params['cap']``,
  summing to <= 1; the remainder is uninvested cash. The T-bill basket is part of
  the returned vector.

Pure stdlib by design (T1-compatible): this module is on the scripts/ import
path, so ``tests/test_trading_path_purity.py`` keeps it free of heavy deps and
the live engine can import it directly later.
"""
import math

TBILL_BASKET = ("BIL", "SHV", "SGOV", "USFR")
DEFAULT_CAP = 0.114
ANNUALIZATION = 252


# ---------------------------------------------------------------------------
# Series helpers (all strictly bounded by t)
# ---------------------------------------------------------------------------

def first_valid(series, t):
    """Index of the first non-None value in series[0..t], or None."""
    for i in range(0, min(t, len(series) - 1) + 1):
        if series[i] is not None:
            return i
    return None


def history_len(series, t):
    """Number of sessions of own history up to and including t (0 if unlisted)."""
    if series is None or t >= len(series) or series[t] is None:
        return 0
    fv = first_valid(series, t)
    return 0 if fv is None else t - fv + 1


def total_return(series, t, k):
    """Total return over k sessions ending at t, or None without enough history."""
    if k <= 0 or t - k < 0 or t >= len(series):
        return None
    a, b = series[t - k], series[t]
    if a is None or b is None or a <= 0:
        return None
    return b / a - 1.0


def sma(series, t, n):
    if n <= 0 or t - n + 1 < 0:
        return None
    window = series[t - n + 1:t + 1]
    if any(v is None for v in window):
        return None
    return sum(window) / n


def _std(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def realized_vol(series, t, n, floor=0.02):
    """Annualized stdev of daily LOG returns over the last n returns, floored."""
    if t - n < 0:
        return None
    window = series[t - n:t + 1]
    if any(v is None or v <= 0 for v in window):
        return None
    rets = [math.log(window[i] / window[i - 1]) for i in range(1, len(window))]
    return max(_std(rets) * math.sqrt(ANNUALIZATION), floor)


def simple_returns(series, t, n):
    if t - n < 0:
        return None
    window = series[t - n:t + 1]
    if any(v is None or v <= 0 for v in window):
        return None
    return [window[i] / window[i - 1] - 1.0 for i in range(1, len(window))]


def portfolio_vol(weights, closes_by_sym, t, n):
    """Annualized sqrt(w' S w) from the n-session sample covariance of simple returns.

    Returns None if any weighted asset lacks n+1 closes."""
    syms = [s for s, w in weights.items() if w > 0]
    if not syms:
        return 0.0
    rets = {}
    for s in syms:
        r = simple_returns(closes_by_sym[s], t, n)
        if r is None:
            return None
        rets[s] = r
    means = {s: sum(r) / len(r) for s, r in rets.items()}
    var = 0.0
    for a in syms:
        for b in syms:
            ra, rb, ma, mb = rets[a], rets[b], means[a], means[b]
            cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n)) / (n - 1)
            var += weights[a] * weights[b] * cov
    return math.sqrt(max(var, 0.0) * ANNUALIZATION)


def tbill_basket(residual, closes_by_sym, t, basket=TBILL_BASKET, cap=DEFAULT_CAP):
    """Fill ``residual`` into the T-bill basket in priority order, each <= cap.

    An ETF is available only if it has a close at t (listed). Overflow is cash."""
    out = {}
    left = max(0.0, residual)
    for s in basket:
        if left <= 1e-12:
            break
        series = closes_by_sym.get(s)
        if series is None or t >= len(series) or series[t] is None:
            continue
        w = min(cap, left)
        out[s] = w
        left -= w
    return out


def _finish(risky, closes_by_sym, t, cap):
    risky = {s: w for s, w in risky.items() if w > 1e-12}
    out = dict(risky)
    for s, w in tbill_basket(1.0 - sum(risky.values()), closes_by_sym, t, cap=cap).items():
        out[s] = out.get(s, 0.0) + w
    return out


# ---------------------------------------------------------------------------
# S1 — matf-v1: multi-asset long-only trend, inverse-vol, 8% vol cap
# ---------------------------------------------------------------------------

MATF_DEFAULTS = {
    "risky": ["SPY", "IWM", "EFA", "EEM", "VNQ", "IEF", "TLT", "TIP", "DBC", "GLD"],
    "lookbacks": [63, 126, 252], "sma": 200, "vol_window": 63, "cov_window": 126,
    "vol_target": 0.08, "vol_floor": 0.02, "cap": DEFAULT_CAP, "hurdle": "BIL",
}


def trend_score(closes_by_sym, sym, t, p):
    """S1 trend score T_i in {0, .25, .5, .75, 1}; None if history is insufficient."""
    series = closes_by_sym.get(sym)
    hurdle = closes_by_sym.get(p["hurdle"])
    if series is None or hurdle is None:
        return None
    votes = []
    for k in p["lookbacks"]:
        r, rb = total_return(series, t, k), total_return(hurdle, t, k)
        if r is None or rb is None:
            return None
        votes.append(1.0 if r - rb > 0 else 0.0)
    m = sma(series, t, p["sma"])
    if m is None:
        return None
    votes.append(1.0 if series[t] > m else 0.0)
    return sum(votes) / len(votes)


def matf_target_weights(closes_by_sym, as_of_index, params=None):
    p = dict(MATF_DEFAULTS)
    p.update(params or {})
    t, cap = as_of_index, p["cap"]
    scores, inv_vol = {}, {}
    for s in p["risky"]:
        series = closes_by_sym.get(s)
        if series is None:
            continue
        sc = trend_score(closes_by_sym, s, t, p)
        vol = realized_vol(series, t, p["vol_window"], p["vol_floor"])
        if sc is None or vol is None:
            continue
        scores[s], inv_vol[s] = sc, 1.0 / vol
    denom = sum(inv_vol.values())
    raw = {}
    if denom > 0:
        for s, sc in scores.items():
            raw[s] = min(cap, sc * inv_vol[s] / denom)
    raw = {s: w for s, w in raw.items() if w > 0}
    sigma = portfolio_vol(raw, closes_by_sym, t, p["cov_window"]) if raw else 0.0
    if sigma is None:  # cannot measure risk => do not take it
        raw = {}
    elif sigma > 0:
        k = min(1.0, p["vol_target"] / sigma)
        raw = {s: w * k for s, w in raw.items()}
    return _finish(raw, closes_by_sym, t, cap)


# ---------------------------------------------------------------------------
# S2 — secmom-v1: sector/region relative momentum + absolute filter + 12% vol cap
# ---------------------------------------------------------------------------

SECMOM_DEFAULTS = {
    "risky": ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLRE", "XLC", "EFA", "EEM"],
    "long": 252, "short": 126, "skip": 21, "abs_lookback": 252, "sma": 200,
    "vol_window": 63, "cov_window": 126, "vol_cap": 0.12, "top_n": 6, "buffer_rank": 8,
    "min_history": 273, "vol_floor": 0.02, "cap": DEFAULT_CAP, "hurdle": "BIL",
    "prev_held": [],
}


def percentile_ranks(values):
    """{key: (avg_rank - 1)/(n - 1)} ascending (higher value -> higher pct); ties averaged."""
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 0:
        return {}
    if n == 1:
        return {items[0][0]: 1.0}
    out, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for m in range(i, j + 1):
            out[items[m][0]] = (avg_rank - 1.0) / (n - 1.0)
        i = j + 1
    return out


def secmom_eligible(series, t, p):
    need = max(p["min_history"], p["long"] + 1, p["abs_lookback"] + 1, p["sma"])
    return history_len(series, t) >= need


def secmom_select(closes_by_sym, t, p):
    """Return (ranked list, passes_filter dict, selected list, held list)."""
    hurdle = closes_by_sym.get(p["hurdle"])
    mom_l, mom_s, passes = {}, {}, {}
    for s in p["risky"]:
        series = closes_by_sym.get(s)
        if series is None or not secmom_eligible(series, t, p):
            continue
        base = series[t - p["skip"]]
        a, b = series[t - p["long"]], series[t - p["short"]]
        if base is None or a is None or b is None:
            continue
        mom_l[s], mom_s[s] = base / a - 1.0, base / b - 1.0
        r, rb = total_return(series, t, p["abs_lookback"]), total_return(hurdle, t, p["abs_lookback"])
        m = sma(series, t, p["sma"])
        passes[s] = (r is not None and rb is not None and m is not None
                     and r - rb > 0 and series[t] > m)
    pl, ps = percentile_ranks(mom_l), percentile_ranks(mom_s)
    score = {s: (pl[s] + ps[s]) / 2.0 for s in mom_l}
    ranked = sorted(score, key=lambda s: (-score[s], s))
    rank = {s: i + 1 for i, s in enumerate(ranked)}
    prev = set(p.get("prev_held") or [])
    kept = [s for s in ranked if s in prev and rank[s] <= p["buffer_rank"] and passes[s]]
    selected = list(kept)
    for s in ranked:
        if len(selected) >= p["top_n"]:
            break
        if s not in selected:
            selected.append(s)
    held = [s for s in selected if passes[s]]
    return ranked, passes, selected, held


def secmom_target_weights(closes_by_sym, as_of_index, params=None):
    p = dict(SECMOM_DEFAULTS)
    p.update(params or {})
    t, cap = as_of_index, p["cap"]
    _, _, _, held = secmom_select(closes_by_sym, t, p)
    inv = {}
    for s in held:
        vol = realized_vol(closes_by_sym[s], t, p["vol_window"], p["vol_floor"])
        if vol is not None:
            inv[s] = 1.0 / vol
    raw = {}
    denom = sum(inv.values())
    if denom > 0:
        budget = len(inv) * cap
        raw = {s: min(cap, budget * v / denom) for s, v in inv.items()}
    sigma = portfolio_vol(raw, closes_by_sym, t, p["cov_window"]) if raw else 0.0
    if sigma is None:
        raw = {}
    elif sigma > 0:
        k = min(1.0, p["vol_cap"] / sigma)
        raw = {s: w * k for s, w in raw.items()}
    return _finish(raw, closes_by_sym, t, cap)


def secmom_held(weights, params=None):
    """Names held (risky, weight > 0) — the incumbent set for the next snapshot."""
    p = dict(SECMOM_DEFAULTS)
    p.update(params or {})
    return sorted(s for s, w in weights.items() if s in p["risky"] and w > 0)


# ---------------------------------------------------------------------------
# S3 — crisis-core-v1: static balanced core + managed-futures sleeve
# ---------------------------------------------------------------------------

CRISIS_DEFAULTS = {
    "equity": ["SPY", "QQQ", "IWM", "EFA"],
    "managed_futures": ["DBMF", "KMLM", "CTA"],
    "ballast": ["IEF"],
    "cap": DEFAULT_CAP,
}


def crisis_core_target_weights(closes_by_sym, as_of_index, params=None):
    p = dict(CRISIS_DEFAULTS)
    p.update(params or {})
    t, cap = as_of_index, p["cap"]
    risky = {}
    for s in list(p["equity"]) + list(p["managed_futures"]) + list(p["ballast"]):
        series = closes_by_sym.get(s)
        if series is not None and t < len(series) and series[t] is not None:
            risky[s] = cap
    return _finish(risky, closes_by_sym, t, cap)


ALLOCATORS = {
    "matf-v1": matf_target_weights,
    "secmom-v1": secmom_target_weights,
    "crisis-core-v1": crisis_core_target_weights,
}
