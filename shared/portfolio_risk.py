"""Cross-portfolio aggregate risk + portfolio heat (R1).

Each book (P1/P2/P3) enforces its own limits in isolation, but nothing caps the
COMBINED exposure to a single name or sector across the three $100K accounts —
exactly the concentration the audit's Example 4 warns about. These pure helpers
aggregate the books so a cross-portfolio reporter can flag (and a soft cap can
veto) correlated stacking. Read-only; places no orders.
"""
from datetime import datetime, timezone
from math import log


def _abs_float(x):
    try:
        return abs(float(x))
    except (TypeError, ValueError):
        return 0.0


def aggregate_exposure(books, single_name_cap_pct=10.0, sector_cap_pct=30.0):
    """Combine positions across books into single-name and sector exposure as a
    percentage of TOTAL equity, and flag soft-cap breaches.

    `books`: list of {"portfolio_id", "equity", "positions": [{"symbol",
    "market_value", "sector"}]}. Returns a report with per-symbol / per-sector
    aggregates, breach lists, and an overall `ok` flag.
    """
    total_equity = sum(_abs_float(b.get("equity")) for b in books) or 0.0
    by_symbol = {}
    by_sector = {}
    for b in books:
        pid = b.get("portfolio_id", "?")
        for p in b.get("positions", []):
            sym = p.get("symbol")
            if not sym:
                continue
            mv = _abs_float(p.get("market_value"))
            entry = by_symbol.setdefault(sym, {"market_value": 0.0, "books": set()})
            entry["market_value"] += mv
            entry["books"].add(pid)
            sec = p.get("sector") or "Unknown"
            by_sector[sec] = by_sector.get(sec, 0.0) + mv

    def pct(v):
        return round(v / total_equity * 100, 3) if total_equity else 0.0

    sym_report = {
        s: {"market_value": round(d["market_value"], 2),
            "pct_of_total": pct(d["market_value"]),
            "books": sorted(d["books"])}
        for s, d in by_symbol.items()
    }
    sector_report = {s: {"market_value": round(v, 2), "pct_of_total": pct(v)}
                     for s, v in by_sector.items()}

    single_name_breaches = sorted(
        [s for s, d in sym_report.items() if d["pct_of_total"] > single_name_cap_pct])
    sector_breaches = sorted(
        [s for s, d in sector_report.items() if d["pct_of_total"] > sector_cap_pct])

    gross = sum(d["market_value"] for d in by_symbol.values())
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_equity": round(total_equity, 2),
        "gross_exposure_pct": pct(gross),
        "by_symbol": sym_report,
        "by_sector": sector_report,
        "single_name_cap_pct": single_name_cap_pct,
        "sector_cap_pct": sector_cap_pct,
        "single_name_breaches": single_name_breaches,
        "sector_breaches": sector_breaches,
        "ok": not single_name_breaches and not sector_breaches,
    }


def exceeds_aggregate_cap(books, symbol, add_market_value, single_name_cap_pct=10.0):
    """Would adding `add_market_value` of `symbol` push its COMBINED exposure
    across all books above the single-name cap? A soft pre-trade check the bots
    can call before stacking a name they may already hold elsewhere."""
    total_equity = sum(_abs_float(b.get("equity")) for b in books) or 0.0
    if not total_equity:
        return False
    current = 0.0
    for b in books:
        for p in b.get("positions", []):
            if p.get("symbol") == symbol:
                current += _abs_float(p.get("market_value"))
    projected_pct = (current + _abs_float(add_market_value)) / total_equity * 100
    return projected_pct > single_name_cap_pct


def cluster_of(symbol, clusters):
    """Return the correlated-cluster name containing `symbol`, or None.

    `clusters`: {cluster_name: [member symbols]}. First match wins; a symbol in
    no cluster is uncorrelated for this purpose.
    """
    for name, members in (clusters or {}).items():
        if symbol in members:
            return name
    return None


def cluster_exposure_pct(positions, clusters, equity):
    """% of equity held in each correlated cluster.

    `positions`: [{"symbol", "market_value"}]. Returns {cluster_name: pct}. Used
    by the de-correlation add-gate and the cross-portfolio monitor so a basket of
    names that move together is visible as one bet, not many small ones.
    """
    equity = _abs_float(equity)
    if not equity:
        return {}
    raw = {}
    for p in positions or []:
        name = cluster_of(p.get("symbol"), clusters)
        if name:
            raw[name] = raw.get(name, 0.0) + _abs_float(p.get("market_value"))
    return {k: round(v / equity * 100, 3) for k, v in raw.items()}


def would_breach_cluster_cap(symbol, positions, equity, clusters,
                             max_cluster_pct, add_market_value=0.0):
    """Would adding `add_market_value` of `symbol` push its correlated cluster
    above `max_cluster_pct` of equity? Returns
    ``(breach, cluster_name, projected_pct, cap)``.

    A symbol in no cluster, or absent config, never breaches. This is an ADVISORY
    constraint layered INSIDE the hardcoded caps — it only ever REJECTS a new add
    (tightens); it never relaxes a hard limit.
    """
    name = cluster_of(symbol, clusters)
    equity = _abs_float(equity)
    if not name or not equity or not max_cluster_pct:
        return (False, name, 0.0, max_cluster_pct)
    current = 0.0
    for p in positions or []:
        if cluster_of(p.get("symbol"), clusters) == name:
            current += _abs_float(p.get("market_value"))
    projected = (current + _abs_float(add_market_value)) / equity * 100
    return (projected > max_cluster_pct, name, round(projected, 3), max_cluster_pct)


def portfolio_heat(positions, equity):
    """Portfolio 'heat' = total open risk to predefined stops, as a % of equity.

    For each position, open risk = qty × max(0, entry/current − stop) for a long
    (mirror for a short). High heat means a cluster of stops could be hit at once.
    `positions`: [{"qty","stop_loss","entry_price"|"avg_price"|"current_price","side"}].
    """
    equity = _abs_float(equity)
    if not equity:
        return {"open_risk": 0.0, "heat_pct": 0.0, "positions_at_risk": 0}
    open_risk = 0.0
    at_risk = 0
    for p in positions or []:
        qty = _abs_float(p.get("qty"))
        stop = p.get("stop_loss")
        ref = (p.get("current_price") if p.get("current_price") is not None
               else p.get("entry_price", p.get("avg_price")))
        if not qty or stop is None or ref is None:
            continue
        ref = float(ref)
        stop = float(stop)
        is_long = str(p.get("side", "long")).lower() in ("long", "buy")
        per_share = max(0.0, (ref - stop) if is_long else (stop - ref))
        risk = per_share * qty
        if risk > 0:
            open_risk += risk
            at_risk += 1
    return {
        "open_risk": round(open_risk, 2),
        "heat_pct": round(open_risk / equity * 100, 3),
        "positions_at_risk": at_risk,
    }


# --- Tail risk: VaR / CVaR / Marginal Contribution to Risk (advisory) -------
# These are ADVISORY analytics layered INSIDE the hardcoded caps in
# config/risk_limits.json — they never relax a limit and place no orders. The
# live kill-switch in risk_officer remains the sole authority that liquidates.
# Pure-Python (no numpy/scipy) so they run on the requests-only cloud path.

def _inv_norm_cdf(p):
    """Inverse standard-normal CDF via Acklam's rational approximation
    (|abs error| < 1.15e-9). Used for parametric (Gaussian) VaR z-scores."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = (-2 * log(p)) ** 0.5
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = (-2 * log(1 - p)) ** 0.5
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def _quantile(sorted_xs, q):
    """Linear-interpolated quantile of an already-sorted list; q in [0, 1]."""
    if not sorted_xs:
        return 0.0
    if q <= 0:
        return sorted_xs[0]
    if q >= 1:
        return sorted_xs[-1]
    pos = q * (len(sorted_xs) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 < len(sorted_xs):
        return sorted_xs[lo] * (1 - frac) + sorted_xs[lo + 1] * frac
    return sorted_xs[lo]


def value_at_risk(returns, confidence=0.99, method="historical", horizon_days=1):
    """One-period (or horizon-day) Value at Risk as a POSITIVE loss fraction.

    `returns`: per-period simple returns. method "historical" (empirical quantile)
    or "parametric" (Gaussian −(μ + z·σ)). Horizon scales by √days. Returns 0.0 on
    insufficient data. Multiply by equity for a dollar VaR.
    """
    rs = [float(r) for r in (returns or []) if r is not None]
    if len(rs) < 2:
        return 0.0
    alpha = 1.0 - confidence
    if method == "parametric":
        mu = sum(rs) / len(rs)
        variance = sum((r - mu) ** 2 for r in rs) / (len(rs) - 1)
        sigma = variance ** 0.5
        z = _inv_norm_cdf(alpha)                       # negative for alpha < 0.5
        loss = -(mu * horizon_days + z * sigma * (horizon_days ** 0.5))
    else:
        q = _quantile(sorted(rs), alpha)               # typically negative
        loss = -q * (horizon_days ** 0.5)
    return round(max(0.0, loss), 6)


def conditional_var(returns, confidence=0.99):
    """Expected Shortfall (CVaR): mean loss in the worst (1−confidence) tail, as a
    POSITIVE fraction (historical/empirical). CVaR ≥ VaR by construction. 0.0 on
    insufficient data."""
    rs = sorted(float(r) for r in (returns or []) if r is not None)
    if len(rs) < 2:
        return 0.0
    alpha = 1.0 - confidence
    q = _quantile(rs, alpha)
    tail = [r for r in rs if r <= q] or [rs[0]]
    return round(max(0.0, -sum(tail) / len(tail)), 6)


def covariance_matrix(returns_by_asset):
    """Sample covariance matrix from {asset: [returns]}, aligned to the shortest
    series (most-recent observations). Returns (symbols_sorted, matrix)."""
    syms = sorted(returns_by_asset.keys())
    series = [[float(x) for x in returns_by_asset[s]] for s in syms]
    if not series:
        return [], []
    n = min(len(s) for s in series)
    if n < 2:
        return syms, [[0.0] * len(syms) for _ in syms]
    series = [s[-n:] for s in series]
    means = [sum(s) / n for s in series]
    cov = [[0.0] * len(syms) for _ in syms]
    for i in range(len(syms)):
        for j in range(i, len(syms)):
            c = sum((series[i][t] - means[i]) * (series[j][t] - means[j])
                    for t in range(n)) / (n - 1)
            cov[i][j] = cov[j][i] = c
    return syms, cov


def marginal_risk_contributions(weights, cov):
    """Risk decomposition for weights `w` and covariance `cov` (nested list).

    component_i = w_i·(cov·w)_i / σ_p, and Σ component_i == σ_p (Euler allocation).
    Returns {portfolio_vol, marginal, component, pct}. Identifies which book/name
    actually drives portfolio risk — diversification's blind spot.
    """
    w = [float(x) for x in weights]
    n_a = len(w)
    if n_a == 0 or len(cov) != n_a:
        return {"portfolio_vol": 0.0, "marginal": [], "component": [], "pct": []}
    cw = [sum(cov[i][j] * w[j] for j in range(n_a)) for i in range(n_a)]
    var_p = sum(w[i] * cw[i] for i in range(n_a))
    sigma = var_p ** 0.5 if var_p > 0 else 0.0
    if sigma == 0:
        return {"portfolio_vol": 0.0, "marginal": [0.0] * n_a,
                "component": [0.0] * n_a, "pct": [0.0] * n_a}
    marginal = [cw[i] / sigma for i in range(n_a)]
    component = [w[i] * marginal[i] for i in range(n_a)]
    pct = [component[i] / sigma for i in range(n_a)]
    return {
        "portfolio_vol": round(sigma, 6),
        "marginal": [round(m, 6) for m in marginal],
        "component": [round(c, 6) for c in component],
        "pct": [round(p, 6) for p in pct],
    }


def var_circuit_breaker(returns, *, confidence=0.99, max_var_pct=None,
                        max_cvar_pct=None, current_drawdown_pct=None,
                        max_drawdown_pct=None):
    """ADVISORY tail-risk monitor. Computes VaR/CVaR (% loss) and compares to
    optional ceilings + a trailing-drawdown ceiling. Returns a RECOMMENDATION only:

        {"var_pct", "cvar_pct", "breach": bool, "reasons": [...],
         "recommended_action": "FLATTEN" | "OK"}

    It places NO orders and relaxes NO hardcoded limit — wire it to alerting first.
    Auto-liquidation must be a separate, explicitly-approved step; the kill-switch
    in risk_officer remains the sole authority that liquidates.
    """
    var_pct = value_at_risk(returns, confidence=confidence, method="historical") * 100
    cvar_pct = conditional_var(returns, confidence=confidence) * 100
    reasons = []
    if max_var_pct is not None and var_pct > max_var_pct:
        reasons.append(f"{confidence:.0%} VaR {var_pct:.2f}% > limit {max_var_pct:.2f}%")
    if max_cvar_pct is not None and cvar_pct > max_cvar_pct:
        reasons.append(f"{confidence:.0%} CVaR {cvar_pct:.2f}% > limit {max_cvar_pct:.2f}%")
    if (current_drawdown_pct is not None and max_drawdown_pct is not None
            and current_drawdown_pct >= max_drawdown_pct):
        reasons.append(f"drawdown {current_drawdown_pct:.2f}% ≥ limit {max_drawdown_pct:.2f}%")
    breach = bool(reasons)
    return {
        "var_pct": round(var_pct, 4),
        "cvar_pct": round(cvar_pct, 4),
        "breach": breach,
        "reasons": reasons,
        "recommended_action": "FLATTEN" if breach else "OK",
    }
