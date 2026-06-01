"""
Triple-Barrier labeling (T1, pure-Python).

Fixed-horizon labels ("did price rise over the next N bars?") ignore HOW the move
happened and use a horizon unrelated to volatility. The triple-barrier method
(López de Prado, *Advances in Financial Machine Learning*, ch. 3) labels each event
by which of three barriers price touches FIRST:

  * upper (profit-take) = p0 · (1 + pt · σ)
  * lower (stop-loss)   = p0 · (1 − sl · σ)
  * vertical (time)     = t0 + max_horizon bars

with σ a rolling volatility estimate, so the barriers breathe with the regime.
Label = +1 (upper first), −1 (lower first), 0 (time barrier first / no touch). This
is the correct supervised target for a meta-labeler and for honest hit-rate
accounting; it is a research formalization of — and consistent with — the live
ATR stop/target exits. Pure-Python; no third-party dependencies.
"""


def returns_from_prices(prices):
    """Simple period returns r_t = p_t/p_{t-1} − 1 (length len(prices)−1)."""
    out = []
    for i in range(1, len(prices)):
        prev = prices[i - 1]
        out.append((prices[i] / prev - 1.0) if prev else 0.0)
    return out


def ewma_vol_series(returns, span=20):
    """RiskMetrics-style trailing EWMA volatility series (per-period std), one value
    per return. λ = 1 − 2/(span+1); σ²_t = λ·σ²_{t-1} + (1−λ)·r_t². σ_t = √σ²_t.

    Returns [] for empty input. Each σ_t uses only returns up to and including t
    (strictly trailing — no look-ahead).
    """
    if not returns:
        return []
    lam = 1.0 - 2.0 / (span + 1.0)
    out = []
    s2 = returns[0] ** 2
    out.append(s2 ** 0.5)
    for r in returns[1:]:
        s2 = lam * s2 + (1 - lam) * r * r
        out.append(s2 ** 0.5)
    return out


def triple_barrier_labels(prices, *, pt=2.0, sl=2.0, max_horizon=10, vol_span=20,
                          events=None, min_vol=1e-6):
    """Label events on a close-price series with the triple-barrier method.

    `prices`: list of close prices. `events`: iterable of event indices t0 to label
    (default: every index with a prior return and room before the series end).
    pt/sl: profit/stop barrier widths in units of the trailing EWMA volatility at
    t0. max_horizon: vertical (time) barrier in bars. Events whose σ < min_vol are
    skipped (no meaningful barrier). Returns a list of dicts:

        {"t0", "t1", "entry", "exit", "ret", "label", "touch", "sigma"}

    label ∈ {+1, −1, 0}; touch ∈ {"upper", "lower", "vertical"}. The scan is strictly
    forward from t0+1 (no look-ahead) and stops at the first barrier touched.
    """
    n = len(prices)
    rets = returns_from_prices(prices)             # rets[i] = return into prices[i+1]
    vol = ewma_vol_series(rets, span=vol_span)     # vol[i] trailing through prices[i+1]
    out = []
    if events is None:
        events = range(n)
    for t0 in events:
        if t0 < 1 or t0 >= n - 1:                  # need a prior return and room ahead
            continue
        sigma = vol[t0 - 1] if (t0 - 1) < len(vol) else 0.0
        if sigma < min_vol:
            continue
        p0 = prices[t0]
        upper = p0 * (1 + pt * sigma)
        lower = p0 * (1 - sl * sigma)
        t_end = min(n - 1, t0 + max_horizon)
        label, touch, t1 = 0, "vertical", t_end
        for t in range(t0 + 1, t_end + 1):
            p = prices[t]
            if p >= upper:
                label, touch, t1 = 1, "upper", t
                break
            if p <= lower:
                label, touch, t1 = -1, "lower", t
                break
        exit_price = prices[t1]
        out.append({
            "t0": t0, "t1": t1, "entry": p0, "exit": exit_price,
            "ret": (exit_price / p0 - 1.0) if p0 else 0.0,
            "label": label, "touch": touch, "sigma": round(sigma, 6),
        })
    return out
