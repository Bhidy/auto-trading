"""Readiness Engine v2 — pure, pre-registered live-readiness statistics (T1).

Pure stdlib (plus the pure-Python ``scripts/backtest/metrics.py``) so it runs on
the requests-only cloud path. No I/O, no network, no clock: every input is
passed in, which is what makes it unit-testable and reproducible.

What it replaces (audit 2026-10-23 of dashboard/public/readiness.html): a P1
Sharpe gate hard-coded PASS from a stale constant, calendar days counted as
"trading days" that never reset on a strategy change, no live Sharpe at all, a
"% ready" gauge that was just the share of gates passed, and an absolute
Sharpe >= 1.0 hurdle that is the wrong test (SPY itself is ~0.66 this year).

v2 measures each SLEEVE-VERSION from its registry ``start_date`` on a real
session calendar and asks one statistical question about edge: is the
benchmark-relative alpha (OLS on SPY, Newey-West HAC t-stat) positive and does
the appraisal ratio survive deflation for the honest number of trials
(DSR >= 0.95)? Everything else is a risk, sample, regime or operational gate.
Verdicts: GO only when EVERY hard gate passes; NOT_ELIGIBLE for sleeves that
accrue no new evidence (exits_only / quarantined); otherwise NOT_READY. There
is deliberately no percentage score.

Gate status vocabulary: pass | fail | insufficient | not_measured |
not_applicable. Only ``pass`` counts; ``not_measured`` never passes by default.
"""
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest import metrics as M  # noqa: E402
from shared.portfolio_risk import conditional_var  # noqa: E402

METHODOLOGY_VERSION = "2.0.0"
PERIODS_PER_YEAR = 252

# --- PRE-REGISTERED THRESHOLDS (docs/LIVE_READINESS.md §2, v2) ---------------
# Changing any value is a methodology change: bump METHODOLOGY_VERSION and add a
# changelog entry in docs/LIVE_READINESS.md. Never tune these to a result.
THRESHOLDS = {
    "min_track_sessions": 90,          # trading sessions in the version window
    "min_edge_sessions": 60,           # daily returns before an edge verdict
    "dsr_min": 0.95,                   # deflated appraisal ratio at honest N
    "psr_confidence": 0.95,            # one-sided level behind z_req
    "hac_lag": 5,                      # Newey-West lag (one trading week)
    "max_drawdown": 0.15,              # peak-to-trough over the window
    "kill_switch_drawdown": 0.18,      # config/risk_limits.json kill switch
    "min_kill_headroom": 0.06,         # STRATEGY_EVIDENCE §8.3: 6 pts of margin
    "daily_stop": 0.04,                # max daily loss halt
    "cvar_confidence": 0.95,
    "max_cvar": 0.03,                  # 75% of the 4% daily stop
    "min_cvar_sessions": 60,
    "min_round_trips": 50,             # trade-based sleeves only
    "min_profit_factor": 1.3,          # trade-based sleeves only
    "regime_min_groups": 2,
    "regime_min_sessions_per_group": 5,
    "regime_max_group_loss": 0.08,     # "controlled loss" = within the weekly halt
    "max_avg_slippage_bps": 15.0,
    "max_duplicate_orders": 0,
    "max_stale_sessions": 1,
    "min_exception_free_sessions": 30,
    "min_sessions_for_eta": 20,        # below this an alpha estimate is noise
    "eta_cap_sessions": 2520,          # 10 years: beyond this = not converging
    "rf_fallback_annual": 0.04,        # used ONLY if T-bill (BIL) returns are missing
}

REGIME_GROUPS = {
    "STRONG_BULL": "bull", "BULL": "bull",
    "CORRECTION": "correction", "RECOVERY": "correction",
    "BEAR": "bear", "STRONG_BEAR": "bear",
}

# Order used to break ties for the binding gate (earliest = most fundamental).
GATE_PRIORITY = [
    "edge", "track_record", "sample", "profit_factor", "max_drawdown",
    "kill_switch_headroom", "worst_day", "cvar95", "regime_coverage",
    "reconciliation", "duplicate_orders", "slippage", "data_freshness",
    "exception_free",
]

NOT_ELIGIBLE_STATUSES = ("exits_only", "quarantined")


# ---------------------------------------------------------------------------
# Session calendar
# ---------------------------------------------------------------------------

def _d(x):
    if isinstance(x, date) and not isinstance(x, datetime):
        return x
    if isinstance(x, datetime):
        return x.date()
    return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()


def _iso(d):
    return d.isoformat() if d else None


def _easter(year):
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month, day = divmod(h + ll - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year, month, weekday, n):
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year, month, weekday):
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d, saturday_to_friday=True):
    if d.weekday() == 5:
        return d - timedelta(days=1) if saturday_to_friday else None
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def nyse_holidays(year):
    """Full-day NYSE closures from the standing rules (no ad-hoc closures such as
    national days of mourning — the broker calendar overrides when available)."""
    days = {
        _observed(date(year, 1, 1), saturday_to_friday=False),
        _nth_weekday(year, 1, 0, 3),            # MLK
        _nth_weekday(year, 2, 0, 3),            # Presidents
        _easter(year) - timedelta(days=2),      # Good Friday
        _last_weekday(year, 5, 0),              # Memorial
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),            # Labor
        _nth_weekday(year, 11, 3, 4),           # Thanksgiving
        _observed(date(year, 12, 25)),
    }
    if year >= 2022:
        days.add(_observed(date(year, 6, 19)))  # Juneteenth
    return {d for d in days if d is not None}


def nyse_sessions(start, end, broker_sessions=None):
    """Sorted ISO session dates in [start, end]. Inside the span covered by
    ``broker_sessions`` (Alpaca calendar), the broker list is authoritative;
    outside it the standing NYSE rules are used (needed to project ETAs)."""
    s, e = _d(start), _d(end)
    if e < s:
        return []
    broker = sorted({_iso(_d(x)) for x in (broker_sessions or [])})
    lo = broker[0] if broker else None
    hi = broker[-1] if broker else None
    out, hol_cache, cur = [], {}, s
    while cur <= e:
        iso = _iso(cur)
        if lo and lo <= iso <= hi:
            pass  # filled from broker list below
        elif cur.weekday() < 5:
            hol = hol_cache.setdefault(cur.year, nyse_holidays(cur.year))
            if cur not in hol:
                out.append(iso)
        cur += timedelta(days=1)
    if broker:
        out.extend(x for x in broker if _iso(s) <= x <= _iso(e))
    return sorted(set(out))


def count_sessions(sessions, start, end):
    """Sessions in [start, end] (inclusive) — trading days, never calendar days."""
    a, b = _iso(_d(start)), _iso(_d(end))
    return sum(1 for x in sessions if a <= x <= b)


def session_after(sessions, anchor, k):
    """The k-th session strictly after ``anchor`` (k >= 1), or None if the list
    is too short."""
    a = _iso(_d(anchor))
    later = [x for x in sessions if x > a]
    return later[k - 1] if 0 < k <= len(later) else None


def previous_session(sessions, anchor):
    a = _iso(_d(anchor))
    earlier = [x for x in sessions if x < a]
    return earlier[-1] if earlier else None


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

def window_returns(values_by_date, sessions, start, end):
    """Daily simple returns for each session in [start, end], computed from the
    value on that session and the value on the PREVIOUS session (which may be
    before ``start`` — it is only the base of the first in-window return).
    Returns before ``start`` are excluded (strategy-version reset); a session
    whose value or base is missing is skipped and counted in ``missing``.

    Returns {"dates": [...], "returns": [...], "missing": [...]}"""
    vals = {(_iso(_d(k))): v for k, v in (values_by_date or {}).items()
            if v is not None and v > 0}
    a, b = _iso(_d(start)), _iso(_d(end))
    dates, rets, missing = [], [], []
    prev = None
    for s in sessions:
        if s > b:
            break
        if s >= a:
            if prev is not None and prev in vals and s in vals:
                dates.append(s)
                rets.append(vals[s] / vals[prev] - 1.0)
            else:
                missing.append(s)
        prev = s
    return {"dates": dates, "returns": rets, "missing": missing}


def equity_curve(returns, start_value=1.0):
    curve = [start_value]
    for r in returns:
        curve.append(curve[-1] * (1.0 + r))
    return curve


def moments(xs):
    """(skew, kurtosis) — kurtosis NOT excess (normal = 3)."""
    n = len(xs)
    if n < 3:
        return 0.0, 3.0
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / n
    if var <= 0:
        return 0.0, 3.0
    sd = math.sqrt(var)
    return (sum(((x - m) / sd) ** 3 for x in xs) / n,
            sum(((x - m) / sd) ** 4 for x in xs) / n)


# ---------------------------------------------------------------------------
# Edge test: OLS alpha on SPY with Newey-West HAC, deflated appraisal ratio
# ---------------------------------------------------------------------------

def ols_hac(y, x, lag=5):
    """OLS y = a + b*x + e with a Newey-West (Bartlett) HAC covariance and the
    n/(n-2) small-sample factor. Returns None if n < 3."""
    n = len(y)
    if n != len(x) or n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((xi - mx) ** 2 for xi in x)
    beta = (sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / sxx) if sxx > 0 else 0.0
    alpha = my - beta * mx
    e = [yi - alpha - beta * xi for xi, yi in zip(x, y)]
    sum_x, sum_x2 = sum(x), sum(xi * xi for xi in x)
    det = n * sum_x2 - sum_x * sum_x
    if det <= 0:
        return None
    inv = [[sum_x2 / det, -sum_x / det], [-sum_x / det, n / det]]
    # Meat: S = G0 + sum_l w_l (G_l + G_l')
    s00 = sum(ei * ei for ei in e)
    s01 = sum(ei * ei * xi for ei, xi in zip(e, x))
    s11 = sum(ei * ei * xi * xi for ei, xi in zip(e, x))
    L = max(0, min(int(lag), n - 1))
    for lg in range(1, L + 1):
        w = 1.0 - lg / (L + 1.0)
        g00 = g01 = g10 = g11 = 0.0
        for t in range(lg, n):
            ee = e[t] * e[t - lg]
            g00 += ee
            g01 += ee * x[t - lg]      # z_t[0] * z_{t-l}[1]
            g10 += ee * x[t]           # z_t[1] * z_{t-l}[0]
            g11 += ee * x[t] * x[t - lg]
        s00 += w * 2 * g00
        s01 += w * (g01 + g10)
        s11 += w * 2 * g11
    S = [[s00, s01], [s01, s11]]

    def mm(A, B):
        return [[A[i][0] * B[0][j] + A[i][1] * B[1][j] for j in range(2)] for i in range(2)]

    V = mm(mm(inv, S), inv)
    adj = n / (n - 2.0)
    var_a = max(0.0, V[0][0] * adj)
    se_a = math.sqrt(var_a)
    sigma_resid = math.sqrt(sum(ei * ei for ei in e) / (n - 2)) if n > 2 else 0.0
    if M._negligible(sigma_resid, y):
        sigma_resid = 0.0
    return {
        "n": n, "alpha": alpha, "beta": beta, "resid": e,
        "se_alpha_hac": se_a,
        "t_alpha_hac": (alpha / se_a) if se_a > 0 else None,
        "sigma_resid": sigma_resid,
    }


def z_required(trial_count, confidence=0.95):
    """Statistic an alpha must reach for DSR >= confidence at ``trial_count``:
    the one-sided normal quantile plus the expected max of N null z-scores."""
    return M.inverse_normal_cdf(confidence) + M.expected_max_null_z(trial_count)


def edge_test(book_rets, spy_rets, rf_rets, trial_count, thresholds=None):
    """Benchmark-relative edge on aligned daily series (same length/dates).

    PASS iff n >= min_edge_sessions AND alpha > 0 AND DSR >= dsr_min AND the HAC
    t-stat >= z_req (the HAC condition guards the iid DSR against serial
    correlation; it can only make the test stricter). Otherwise 'insufficient'
    (n too small) or 'fail'."""
    th = thresholds or THRESHOLDS
    n = len(book_rets)
    zr = z_required(trial_count, th["psr_confidence"])
    out = {"n": n, "trial_count": trial_count, "z_required": round(zr, 3),
           "alpha_daily": None, "alpha_annual": None, "beta": None, "t_hac": None,
           "ir_annual": None, "psr": None, "dsr": None, "sigma_resid_daily": None,
           "sigma_eff_daily": None, "status": "insufficient"}
    if n < 3 or len(spy_rets) != n or len(rf_rets) != n:
        out["detail"] = f"only {n} aligned daily returns"
        return out
    y = [b - r for b, r in zip(book_rets, rf_rets)]
    x = [s - r for s, r in zip(spy_rets, rf_rets)]
    reg = ols_hac(y, x, th["hac_lag"])
    if reg is None:
        out["detail"] = "regression undefined (degenerate benchmark series)"
        return out
    a, sr = reg["alpha"], reg["sigma_resid"]
    active = [a + e for e in reg["resid"]]
    skew, kurt = moments(active)
    ir_d = (a / sr) if sr > 0 else 0.0
    psr = M.probabilistic_sharpe_ratio(ir_d, 0.0, n, skew, kurt) if sr > 0 else 0.0
    dsr = M.deflated_sharpe_at_trial_count(ir_d, n, trial_count, skew, kurt) if sr > 0 else 0.0
    sig_eff = max(sr, reg["se_alpha_hac"] * math.sqrt(n))
    t = reg["t_alpha_hac"]
    out.update({
        "alpha_daily": a, "alpha_annual": a * PERIODS_PER_YEAR, "beta": reg["beta"],
        "t_hac": t, "ir_annual": ir_d * math.sqrt(PERIODS_PER_YEAR), "psr": psr,
        "dsr": dsr, "sigma_resid_daily": sr, "sigma_eff_daily": sig_eff,
        "skew": skew, "kurtosis": kurt,
    })
    if n < th["min_edge_sessions"]:
        out["status"] = "insufficient"
        out["detail"] = f"n={n} < {th['min_edge_sessions']} pre-registered minimum"
    elif a > 0 and dsr >= th["dsr_min"] and t is not None and t >= zr:
        out["status"] = "pass"
    else:
        out["status"] = "fail"
    return out


def edge_eta(edge, thresholds=None):
    """Honest power projection: sessions needed for the alpha t-stat to reach
    z_req at the CURRENT alpha and effective (HAC) residual vol:
    n_req = (z_req * sigma_eff / alpha)^2. An ESTIMATE that moves as alpha does."""
    th = thresholds or THRESHOLDS
    n = edge.get("n") or 0
    a, sig = edge.get("alpha_daily"), edge.get("sigma_eff_daily")
    if edge.get("status") == "pass":
        return {"state": "met", "sessions_remaining": 0}
    if n < th["min_sessions_for_eta"] or a is None or sig is None:
        return {"state": "too_early", "sessions_remaining": None,
                "detail": f"needs >= {th['min_sessions_for_eta']} daily returns to estimate"}
    if a <= 0 or sig <= 0:
        return {"state": "not_converging", "sessions_remaining": None,
                "detail": "alpha <= 0: more time cannot produce a positive significant alpha"}
    n_req = math.ceil((edge["z_required"] * sig / a) ** 2)
    n_req = max(n_req, th["min_edge_sessions"])
    remaining = max(0, n_req - n)
    if n_req > th["eta_cap_sessions"]:
        return {"state": "not_converging", "sessions_remaining": None, "n_required": n_req,
                "detail": f"n_required {n_req} > cap {th['eta_cap_sessions']} sessions"}
    if remaining == 0:
        # Enough data already yet not passing: the estimate is noise-limited.
        return {"state": "not_converging", "sessions_remaining": None, "n_required": n_req,
                "detail": "sample already exceeds the projected requirement without passing"}
    return {"state": "estimate", "sessions_remaining": remaining, "n_required": n_req}


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def gate(gid, name, threshold, value, status, detail="", eta_sessions=None, hard=True):
    return {"id": gid, "name": name, "threshold": threshold, "value": value,
            "status": status, "detail": detail, "eta_sessions": eta_sessions, "hard": hard}


def _r(x, nd=4):
    return None if x is None else round(x, nd)


def track_record_gate(n_sessions, th=None):
    th = th or THRESHOLDS
    need = th["min_track_sessions"]
    ok = n_sessions >= need
    return gate("track_record", "Paper track record (trading sessions)", f">= {need}",
                n_sessions, "pass" if ok else "insufficient",
                f"{n_sessions} sessions since the version start",
                eta_sessions=0 if ok else need - n_sessions)


def edge_gate(edge, eta, th=None):
    th = th or THRESHOLDS
    val = {"alpha_annual": _r(edge.get("alpha_annual")), "t_hac": _r(edge.get("t_hac"), 3),
           "dsr": _r(edge.get("dsr")), "n": edge.get("n")}
    if edge.get("detail"):
        detail = edge["detail"]
    else:
        t = edge.get("t_hac")
        detail = (f"alpha {edge['alpha_annual'] * 100:+.2f}%/yr, beta {edge['beta']:.2f}, "
                  f"t_HAC {'n/a' if t is None else round(t, 2)} vs z_req {edge['z_required']}, "
                  f"DSR {edge['dsr']:.3f} at N={edge['trial_count']}")
    eta_s = eta.get("sessions_remaining") if eta.get("state") in ("estimate", "met") else None
    if edge.get("status") == "insufficient" and eta_s is not None:
        eta_s = max(eta_s, th["min_edge_sessions"] - (edge.get("n") or 0))
    return gate("edge", "Benchmark-relative edge (alpha vs SPY, HAC t, DSR)",
                f"alpha > 0, DSR >= {th['dsr_min']} at honest N, t_HAC >= z_req, n >= {th['min_edge_sessions']}",
                val, edge.get("status"), detail, eta_sessions=eta_s)


def drawdown_stats(returns):
    curve = equity_curve(returns)
    mdd = M.max_drawdown(curve)
    peak = max(curve)
    cur = (peak - curve[-1]) / peak if peak > 0 else 0.0
    return {"max_drawdown": mdd, "current_drawdown": cur}


def risk_gates(returns, th=None):
    """Max DD, kill-switch headroom, worst day, CVaR95 on the window's daily returns."""
    th = th or THRESHOLDS
    n = len(returns)
    gates = []
    if n < 2:
        msg = f"only {n} daily returns in the window"
        for gid, name, thr in (
                ("max_drawdown", "Max drawdown (window)", f"<= {th['max_drawdown']:.0%}"),
                ("kill_switch_headroom", "Kill-switch headroom", f">= {th['min_kill_headroom']:.0%}"),
                ("worst_day", "Worst day vs daily stop", f"> -{th['daily_stop']:.0%}"),
                ("cvar95", "Daily CVaR 95% (historical)", f"<= {th['max_cvar']:.1%}")):
            gates.append(gate(gid, name, thr, None, "insufficient", msg))
        return gates
    dd = drawdown_stats(returns)
    gates.append(gate("max_drawdown", "Max drawdown (window)", f"<= {th['max_drawdown']:.0%}",
                      _r(dd["max_drawdown"]), "pass" if dd["max_drawdown"] <= th["max_drawdown"] else "fail",
                      f"peak-to-trough {dd['max_drawdown']:.2%} over {n} sessions"))
    head = th["kill_switch_drawdown"] - dd["current_drawdown"]
    gates.append(gate("kill_switch_headroom", "Kill-switch headroom",
                      f">= {th['min_kill_headroom']:.0%} (18% kill switch - current DD)",
                      _r(head), "pass" if head >= th["min_kill_headroom"] else "fail",
                      f"current drawdown {dd['current_drawdown']:.2%}"))
    worst = min(returns)
    gates.append(gate("worst_day", "Worst day vs daily stop", f"> -{th['daily_stop']:.0%}", _r(worst),
                      "pass" if worst > -th["daily_stop"] else "fail", f"worst session {worst:.2%}"))
    if n < th["min_cvar_sessions"]:
        gates.append(gate("cvar95", "Daily CVaR 95% (historical)", f"<= {th['max_cvar']:.1%}", None,
                          "insufficient", f"refused: n={n} < {th['min_cvar_sessions']}",
                          eta_sessions=th["min_cvar_sessions"] - n))
    else:
        cv = conditional_var(returns, th["cvar_confidence"])
        gates.append(gate("cvar95", "Daily CVaR 95% (historical)", f"<= {th['max_cvar']:.1%}", _r(cv),
                          "pass" if cv <= th["max_cvar"] else "fail", f"mean loss in worst 5% of days {cv:.2%}"))
    return gates


def trade_gates(pnls, sessions_elapsed, source_detail="", th=None):
    """Sample (>= 50 whole round trips) and profit factor (>= 1.3) for
    trade-based sleeves. PF is only judged once the sample is adequate."""
    th = th or THRESHOLDS
    if pnls is None:
        return [gate("sample", "Closed round trips (whole trades)", f">= {th['min_round_trips']}", None,
                     "not_measured", source_detail or "no trade source"),
                gate("profit_factor", "Profit factor", f">= {th['min_profit_factor']}", None,
                     "not_measured", source_detail or "no trade source")]
    n = len(pnls)
    need = th["min_round_trips"]
    eta = None
    if n < need and sessions_elapsed and n > 0:
        eta = math.ceil((need - n) / (n / float(sessions_elapsed)))
    sample = gate("sample", "Closed round trips (whole trades)", f">= {need}", n,
                  "pass" if n >= need else "insufficient",
                  (source_detail + f"; {n} in window").strip("; "),
                  eta_sessions=0 if n >= need else eta)
    pf = M.profit_factor(pnls) if pnls else None
    pf_val = None if pf is None else ("inf" if pf == float("inf") else round(pf, 3))
    if n < need:
        pf_status, pf_detail = "insufficient", f"PF not judged below {need} round trips (value shown)"
    else:
        pf_status = "pass" if pf >= th["min_profit_factor"] else "fail"
        pf_detail = f"gross wins / gross losses over {n} round trips"
    return [sample, gate("profit_factor", "Profit factor", f">= {th['min_profit_factor']}", pf_val,
                         pf_status, pf_detail, eta_sessions=sample["eta_sessions"] if n < need else None)]


def regime_gate(dates, returns, labels_by_date, th=None):
    """>= 2 coarse regime groups (bull / correction / bear), each observed on
    >= 5 return sessions, and no group's compounded return below -8%."""
    th = th or THRESHOLDS
    groups = {}
    for d, r in zip(dates, returns):
        g = REGIME_GROUPS.get(str(labels_by_date.get(d) or "").upper())
        if g:
            groups.setdefault(g, []).append(r)
    summary = {}
    for g, rs in groups.items():
        comp = 1.0
        for r in rs:
            comp *= 1.0 + r
        summary[g] = {"sessions": len(rs), "return": round(comp - 1.0, 4)}
    qualifying = {g: s for g, s in summary.items() if s["sessions"] >= th["regime_min_sessions_per_group"]}
    losers = [g for g, s in qualifying.items() if s["return"] < -th["regime_max_group_loss"]]
    if not summary:
        status, detail = "not_measured", "no regime tags inside the window"
    elif losers:
        status, detail = "fail", f"uncontrolled loss in: {', '.join(sorted(losers))}"
    elif len(qualifying) >= th["regime_min_groups"]:
        status, detail = "pass", "observed: " + ", ".join(sorted(qualifying))
    else:
        status = "insufficient"
        detail = "observed: " + (", ".join(f"{g} ({s['sessions']}d)" for g, s in sorted(summary.items())))
    return gate("regime_coverage", "Regime coverage", f">= {th['regime_min_groups']} regime groups "
                f"x >= {th['regime_min_sessions_per_group']} sessions, none < -{th['regime_max_group_loss']:.0%}",
                summary, status, detail)


# --- operational (book-level) -------------------------------------------------

def reconciliation_gate(report, as_of, sessions, th=None):
    th = th or THRESHOLDS
    name, thr = "Broker vs ledger reconciliation", "in_sync = true, report <= 1 session old"
    if not isinstance(report, dict):
        return gate("reconciliation", name, thr, None, "not_measured", "no reconciliation report")
    if "in_sync" not in report:
        return gate("reconciliation", name, thr, None, "not_measured",
                    "this book writes a working-orders report only (no drift audit)")
    age = stale_sessions(_iso_date_et(report.get("timestamp")), as_of, sessions)
    if report.get("in_sync") is False:
        return gate("reconciliation", name, thr, False, "fail", "broker and ledger have diverged")
    if age is None or age > th["max_stale_sessions"]:
        return gate("reconciliation", name, thr, True, "not_measured",
                    f"report is {age if age is not None else '?'} sessions old")
    return gate("reconciliation", name, thr, True, "pass", "in sync")


def duplicate_gate(n_duplicates, n_checked, extra_detail="", th=None):
    th = th or THRESHOLDS
    thr = f"<= {th['max_duplicate_orders']}"
    if n_duplicates is None or not n_checked:
        return gate("duplicate_orders", "Duplicate orders", thr, None, "not_measured",
                    extra_detail or "no entry orders in the window to check")
    ok = n_duplicates <= th["max_duplicate_orders"]
    return gate("duplicate_orders", "Duplicate orders", thr, n_duplicates, "pass" if ok else "fail",
                f"{n_checked} entry orders checked (one order per symbol/side/session)"
                + (f"; {extra_detail}" if extra_detail else ""))


def slippage_gate(adverse_bps, th=None):
    th = th or THRESHOLDS
    thr = f"avg <= {th['max_avg_slippage_bps']:.0f} bps"
    xs = [x for x in (adverse_bps or []) if x is not None]
    if not xs:
        return gate("slippage", "Average adverse slippage", thr, None, "not_measured",
                    "no fills with a recorded reference price in the window")
    avg = sum(xs) / len(xs)
    return gate("slippage", "Average adverse slippage", thr, round(avg, 2),
                "pass" if avg <= th["max_avg_slippage_bps"] else "fail", f"{len(xs)} fills measured")


def stale_sessions(last_date, as_of, sessions):
    """Sessions between ``last_date`` and ``as_of`` (0 = same session)."""
    if not last_date:
        return None
    if last_date >= _iso(_d(as_of)):
        return 0
    return count_sessions(sessions, (_d(last_date) + timedelta(days=1)).isoformat(), as_of)


def freshness_gate(last_activity, as_of, sessions, th=None):
    th = th or THRESHOLDS
    thr = f"state updated within {th['max_stale_sessions']} session"
    age = stale_sessions(last_activity, as_of, sessions)
    if age is None:
        return gate("data_freshness", "Data freshness", thr, None, "not_measured", "no activity stamp")
    return gate("data_freshness", "Data freshness", thr, age,
                "pass" if age <= th["max_stale_sessions"] else "fail",
                f"last activity {last_activity}")


def exception_gate(failures_by_session, as_of, sessions, th=None):
    """Consecutive sessions (ending at as_of) whose workflow runs had zero
    failures. ``failures_by_session`` None => not measurable here."""
    th = th or THRESHOLDS
    need = th["min_exception_free_sessions"]
    thr = f">= {need} consecutive sessions with zero failed runs"
    if failures_by_session is None:
        return gate("exception_free", "Unhandled-exception-free sessions", thr, None, "not_measured",
                    "workflow run history not available to this run (needs GITHUB_TOKEN)")
    a = _iso(_d(as_of))
    streak = 0
    for s in reversed([x for x in sessions if x <= a]):
        if s not in failures_by_session:
            break  # beyond the measured horizon
        if failures_by_session[s] > 0:
            break
        streak += 1
    ok = streak >= need
    return gate("exception_free", "Unhandled-exception-free sessions", thr, streak,
                "pass" if ok else "insufficient",
                f"{streak} consecutive clean sessions", eta_sessions=0 if ok else need - streak)


def _iso_date_et(ts):
    """ET session date of an ISO timestamp (naive => UTC)."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return ts[:10]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("America/New_York")).date().isoformat()


iso_date_et = _iso_date_et


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def verdict(sleeve_status, gates, sessions, as_of):
    """GO only if every hard gate passes; NOT_ELIGIBLE when the sleeve accrues no
    new evidence; else NOT_READY. No percentage score.

    Binding gate = among open EVIDENCE gates (status fail/insufficient) the one
    with the longest ETA (no ETA = unbounded), ties broken by GATE_PRIORITY.
    ``not_measured`` gates are reported separately as measurement gaps: they
    still block GO, but a missing instrument is not the evidence bottleneck.
    The ETA projects the evidence gates only and lists the gaps it excludes."""
    hard = [g for g in gates if g.get("hard") and g["status"] != "not_applicable"]
    passed = sum(1 for g in hard if g["status"] == "pass")
    open_ = [g for g in hard if g["status"] != "pass"]
    evidence = [g for g in open_ if g["status"] != "not_measured"]
    gaps = [g["id"] for g in open_ if g["status"] == "not_measured"]

    def key(g):
        e = g.get("eta_sessions")
        pri = GATE_PRIORITY.index(g["id"]) if g["id"] in GATE_PRIORITY else len(GATE_PRIORITY)
        return (-(e if e is not None else math.inf), pri)

    pool = evidence or open_
    binding = sorted(pool, key=key)[0] if pool else None
    if sleeve_status in NOT_ELIGIBLE_STATUSES:
        v = "NOT_ELIGIBLE"
    elif not open_:
        v = "GO"
    else:
        v = "NOT_READY"
    eta = None
    if evidence and all(g.get("eta_sessions") is not None for g in evidence):
        k = max(g["eta_sessions"] for g in evidence)
        eta = {"sessions_remaining": k,
               "projected_date": session_after(sessions, as_of, k) if k else as_of,
               "label": "estimate (current alpha / trade rate held constant)"}
    elif evidence:
        blockers = [g["id"] for g in evidence if g.get("eta_sessions") is None]
        eta = {"sessions_remaining": None, "projected_date": None,
               "label": "no projection — no convergence path for: " + ", ".join(blockers)}
    elif gaps:
        eta = {"sessions_remaining": None, "projected_date": None,
               "label": "evidence gates met; blocked only by measurement gaps"}
    if eta is not None:
        eta["excludes_measurement_gaps"] = gaps
    return {"verdict": v, "gates_passed": passed, "gates_total": len(hard),
            "binding_gate": binding["id"] if binding else None,
            "measurement_gaps": gaps, "eta": eta}


def narrative(entry):
    """Short, data-generated English summary (no hand-written status prose)."""
    v, b = entry["verdict"], entry.get("binding_gate")
    gp, gt = entry["gates_passed"], entry["gates_total"]
    edge = entry.get("edge") or {}
    parts = []
    if v == "NOT_ELIGIBLE":
        parts.append(f"NOT ELIGIBLE: sleeve is {entry['status']} (no new evidence accrues).")
    elif v == "GO":
        parts.append("All hard gates pass — eligible for a human go-live review (never automatic).")
    else:
        parts.append(f"NOT READY: {gp}/{gt} hard gates pass.")
    w = entry.get("window") or {}
    parts.append(f"{w.get('trading_days', 0)} sessions since {w.get('start')}.")
    if edge.get("alpha_annual") is not None and edge.get("t_hac") is not None:
        parts.append(f"Alpha vs SPY {edge['alpha_annual'] * 100:+.1f}%/yr (beta {edge['beta']:.2f}, "
                     f"t_HAC {edge['t_hac']:.2f} vs {edge['z_required']} needed, DSR {edge['dsr']:.2f}, "
                     f"n={edge['n']}).")
    if b:
        g = next((x for x in entry["gates"] if x["id"] == b), {})
        parts.append(f"Binding: {g.get('name', b)} — {g.get('detail', '')}.")
    eta = entry.get("eta") or {}
    if v == "NOT_READY":
        parts.append(f"ETA {eta.get('projected_date')} ({eta.get('label')})." if eta.get("projected_date")
                     else f"ETA: {eta.get('label', 'n/a')}.")
    if entry.get("measurement_gaps"):
        parts.append("Not yet measured (blocks GO): " + ", ".join(entry["measurement_gaps"]) + ".")
    if entry.get("attribution") == "book_level":
        parts.append("Returns are BOOK-level (sleeve shares the account).")
    return " ".join(parts)
