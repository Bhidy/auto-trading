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
session calendar (halted sessions excluded) and asks one statistical question
about edge: is the benchmark-relative alpha (OLS on SPY, Newey-West HAC
scale) positive with ALWAYS-VALID confidence? v2.1 decides edge with a
normal-mixture confidence sequence (Robbins / Howard et al.) so the daily
re-evaluation cannot manufacture a GO by repeated looks, at a family error
alpha / K across the live sleeve-versions. DSR at the backtest trial count is
kept as an informational number, not the gate (selection bias inflates
backtests, not post-selection live returns). Everything else is a risk,
sample, regime or operational gate. Verdicts: GO only when EVERY hard gate
passes; FORWARD_TEST_PASS caps forward tests (their parent spec failed
promotion); BETA_SLEEVE for sleeves that claim no edge; NOT_ELIGIBLE for
sleeves that accrue no new evidence (exits_only / quarantined); otherwise
NOT_READY. There is deliberately no percentage score.

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

METHODOLOGY_VERSION = "2.2.0"
PERIODS_PER_YEAR = 252

# --- PRE-REGISTERED THRESHOLDS (docs/LIVE_READINESS.md §2, v2) ---------------
# Changing any value is a methodology change: bump METHODOLOGY_VERSION and add a
# changelog entry in docs/LIVE_READINESS.md. Never tune these to a result.
THRESHOLDS = {
    "min_track_sessions": 90,          # trading sessions in the version window
    "min_edge_sessions": 60,           # daily returns before an edge verdict
    "alpha_family": 0.05,              # family-wise type-I error of the live edge decision
    "k_family_floor": 6,               # Bonferroni K floor (3 books x 2 live versions)
    "cs_rho_sessions": 252,            # normal-mixture parameter (intrinsic time, sessions)
    "max_abs_daily_return": 0.25,      # |r| above this = data fault, excluded + warned
    "dsr_min": 0.95,                   # INFORMATIONAL since 2.1 (DSR @ backtest trials)
    "psr_confidence": 0.95,            # INFORMATIONAL: level behind z_required
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
    "cs_burn_in": 20,                  # returns used only to seed the predictable plug-ins
    # v2.2 two-stage path (Stage A research proof + Stage B live incubation)
    "research_max_backtest_drawdown": 0.12,  # STRATEGY_EVIDENCE §8.3: 6 pts under the kill switch
    "incubation_min_returns": 60,      # halt-free daily returns before consistency is judged
    "incubation_sharpe_haircut": 0.5,  # live may run at half the backtest Sharpe (decay)
    "incubation_alpha": 0.05,          # always-valid level of the contradiction test
    "incubation_vol_ratio_min": 0.5,   # live vol / backtest vol band
    "incubation_vol_ratio_max": 1.5,
    "incubation_dd_multiple": 1.5,     # live max DD <= 1.5 x backtest max DD
}

REGIME_GROUPS = {
    "STRONG_BULL": "bull", "BULL": "bull",
    "CORRECTION": "correction", "RECOVERY": "correction",
    "BEAR": "bear", "STRONG_BEAR": "bear",
}

# Order used to break ties for the binding gate (earliest = most fundamental).
GATE_PRIORITY = [
    "edge", "research", "incubation_consistency", "track_record", "sample", "profit_factor", "max_drawdown",
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

def window_returns(values_by_date, sessions, start, end, exclude=None, max_abs=None):
    """Daily simple returns for each session in [start, end], computed from the
    value on that session and the value on the PREVIOUS session (which may be
    before ``start`` — it is only the base of the first in-window return).
    Returns before ``start`` are excluded (strategy-version reset); a session
    whose value or base is missing is skipped and counted in ``missing``.
    Sessions in ``exclude`` (halted, cash-flow days) are dropped into
    ``excluded``; a return with |r| > ``max_abs`` is a DATA FAULT (phantom
    equity read, unrecorded flow) — dropped into ``faults``, never used.

    Returns {"dates", "returns", "missing", "excluded", "faults"}"""
    vals = {(_iso(_d(k))): v for k, v in (values_by_date or {}).items()
            if v is not None and v > 0}
    a, b = _iso(_d(start)), _iso(_d(end))
    ex = set(exclude or ())
    dates, rets, missing, excluded, faults = [], [], [], [], []
    prev = None
    for s in sessions:
        if s > b:
            break
        if s >= a:
            if prev is not None and prev in vals and s in vals:
                r = vals[s] / vals[prev] - 1.0
                if max_abs is not None and abs(r) > max_abs:
                    faults.append(s)
                elif s in ex:
                    excluded.append(s)
                else:
                    dates.append(s)
                    rets.append(r)
            else:
                missing.append(s)
        prev = s
    return {"dates": dates, "returns": rets, "missing": missing,
            "excluded": excluded, "faults": faults}


def chart_series(dates, returns, bench_by_date=None, nd=5):
    """Compounded cumulative return and drawdown for charting (rounded). The
    benchmark is compounded over the SAME dates only (a missing benchmark day
    contributes 0), so the two lines are always comparable."""
    cum, b_cum, dd = [], [], []
    v = bv = peak = 1.0
    for d, r in zip(dates, returns):
        v *= 1.0 + r
        peak = max(peak, v)
        cum.append(round(v - 1.0, nd))
        dd.append(round(v / peak - 1.0, nd))
        if bench_by_date is not None:
            bv *= 1.0 + bench_by_date.get(d, 0.0)
            b_cum.append(round(bv - 1.0, nd))
    out = {"dates": list(dates), "cum_return": cum, "drawdown": dd}
    if bench_by_date is not None:
        out["benchmark_cum"] = b_cum
    return out


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
    """INFORMATIONAL (v2.0 rule): statistic an alpha needs for DSR >= confidence
    at ``trial_count`` in ONE fixed-sample look."""
    return M.inverse_normal_cdf(confidence) + M.expected_max_null_z(trial_count)


# --- always-valid sequential test (v2.1) --------------------------------------
#
# One-sided normal-mixture (Robbins) martingale for a standardized sum S after
# intrinsic time V (= number of daily returns once each increment is scaled by
# its long-run sd): mixing exp(lam*S - lam^2 V/2) over lam ~ half-normal with
# precision rho gives
#     M(S, V) = 2 sqrt(rho/(V+rho)) exp(S^2 / (2(V+rho))) Phi(S / sqrt(V+rho)).
# Ville's inequality: P(exists V: M >= 1/a) <= a. The crossing boundary b(V)
# therefore holds uniformly over EVERY look, so the engine may re-evaluate daily
# forever without inflating the false-GO rate (Howard, Ramdas, McAuliffe &
# Sekhon 2021, "Time-uniform, nonparametric, nonasymptotic confidence sequences").

def _log_phi(z):
    if z < -30:
        return -0.5 * z * z - math.log(-z * math.sqrt(2 * math.pi))
    return math.log(0.5 * math.erfc(-z / math.sqrt(2.0)))


def _log_mixture(s, v, rho):
    return (math.log(2.0) + 0.5 * math.log(rho / (v + rho)) + s * s / (2.0 * (v + rho))
            + _log_phi(s / math.sqrt(v + rho)))


_BOUNDARY_CACHE = {}


def cs_boundary(v, rho, a):
    """Smallest standardized sum S with M(S, v) >= 1/a (one-sided, level a)."""
    key = (int(v), float(rho), float(a))
    if key in _BOUNDARY_CACHE:
        return _BOUNDARY_CACHE[key]
    target = math.log(1.0 / a)
    lo, hi = 0.0, max(1.0, math.sqrt(v + rho))
    while _log_mixture(hi, v, rho) < target:
        hi *= 2.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _log_mixture(mid, v, rho) < target:
            lo = mid
        else:
            hi = mid
    _BOUNDARY_CACHE[key] = hi
    return hi


def family_alpha_level(k, th=None):
    """Per-sleeve level after Bonferroni across the K live sleeve-versions."""
    th = th or THRESHOLDS
    return th["alpha_family"] / max(int(k or 1), int(th["k_family_floor"]))


def confidence_sequence(alpha_hat, sigma, n, rho, a):
    """Always-valid (lower, upper) bounds on the daily alpha, each one-sided at
    level ``a``: alpha_hat -/+ sigma * b(n) / n."""
    if n < 1 or sigma is None or sigma <= 0:
        return None, None
    half = sigma * cs_boundary(n, rho, a) / n
    return alpha_hat - half, alpha_hat + half


def predictable_cs(y, x, rho, a, lag=5, burn_in=20, fit_beta=True, fast_window=21, path=False):
    """Always-valid bounds on the daily alpha of y = alpha + beta*x + e, built
    from PREDICTABLE plug-ins (v2.2; replaces the full-sample plug-in of 2.1).

    Increment t uses only returns before t: u_t = y_t - beta_{t-1} x_t, scaled
    by sigma_{t-1} = max(sd of all past u, sd of the last ``fast_window`` u)
    x (Bartlett long-run factor of past u, lag ``lag``, floored at 1). The
    fast window absorbs a volatility RISE within days; the expanding sd alone
    lagged it and over-stated significance after a low->high vol regime shift
    (stress simulation 2026-10-23: 3.0% false GO vs 0.83% target). Under alpha = a0 the standardized increments
    (u_t - a0)/sigma_{t-1} are a martingale-difference sequence with ~unit
    conditional variance, so the normal-mixture boundary b(m) on their sum
    holds at every look (Ville). With weights w_t = 1/sigma_{t-1}:
        S(a0) = sum w_t u_t - a0 sum w_t;  bounds = (sum w u -/+ b(m)) / sum w.
    The first ``burn_in`` returns only seed the estimates. Volatility that
    changes over time is tracked by the expanding estimate instead of being
    averaged retrospectively, and beta error enters only through
    beta-prediction noise (mean-zero up to the small market drift).
    Returns dict(lower, upper, point, m) — daily units; None bounds if m < 1.
    ``path=True`` adds "path": [(t, lower, upper, point)] for every input index
    t that produced an increment — the SAME bounds the decision would have
    seen had the engine stopped at t (the time-uniform guarantee covers every
    one of them), for charting the evidence trajectory."""
    n = len(y)
    sx = sy = sxx = sxy = 0.0
    k = 0                                  # points in the OLS sums
    mu = m2 = 0.0                          # Welford on past u
    ku = 0
    hist = []                              # past centred u (last lag+1) for autocovariances
    recent = []                            # last fast_window raw u (fast scale)
    gam = [0.0] * (lag + 1)                # running sums of u_t*u_{t-l} (centred at update)
    A = B = 0.0
    m = 0
    trail = [] if path else None
    for t in range(n):
        xt, yt = (x[t] if fit_beta else 0.0), y[t]
        beta = 0.0
        if fit_beta and k >= 2:
            vx = sxx - sx * sx / k
            beta = ((sxy - sx * sy / k) / vx) if vx > 0 else 0.0
        u = yt - beta * xt
        if t >= burn_in and ku >= 2:
            var = m2 / (ku - 1)
            if len(recent) >= 5:
                rm = sum(recent) / len(recent)
                var = max(var, sum((r - rm) ** 2 for r in recent) / (len(recent) - 1))
            if var > 0:
                lr = gam[0]
                for lg in range(1, lag + 1):
                    lr += 2.0 * (1.0 - lg / (lag + 1.0)) * gam[lg]
                factor = math.sqrt(max(1.0, lr / gam[0])) if gam[0] > 0 else 1.0
                sig = math.sqrt(var) * factor
                w = 1.0 / sig
                A += w * u
                B += w
                m += 1
                if trail is not None:
                    bt = cs_boundary(m, rho, a)
                    trail.append((t, (A - bt) / B, (A + bt) / B, A / B))
        # update the plug-ins with u_t (after it was used)
        ku += 1
        d = u - mu
        mu += d / ku
        m2 += d * (u - mu)
        recent.append(u)
        if len(recent) > fast_window:
            recent.pop(0)
        c = u - mu
        hist.append(c)
        if len(hist) > lag + 1:
            hist.pop(0)
        for lg in range(0, min(lag, len(hist) - 1) + 1):
            gam[lg] += hist[-1] * hist[-1 - lg]
        if fit_beta:
            k += 1
            sx += xt
            sy += yt
            sxx += xt * xt
            sxy += xt * yt
    if m < 1 or B <= 0:
        out = {"lower": None, "upper": None, "point": None, "m": m}
    else:
        b = cs_boundary(m, rho, a)
        out = {"lower": (A - b) / B, "upper": (A + b) / B, "point": A / B, "m": m}
    if trail is not None:
        out["path"] = trail
    return out


def sessions_to_cross(alpha_daily, sigma, rho, a, cap):
    """Expected sessions until the lower bound clears 0 if the TRUE alpha were
    ``alpha_daily`` (drift alpha*n/sigma meets the boundary b(n)); None if not
    within ``cap`` or alpha <= 0."""
    if alpha_daily is None or sigma is None or alpha_daily <= 0 or sigma <= 0:
        return None
    d = alpha_daily / sigma

    def ok(n):
        return d * n >= cs_boundary(n, rho, a)

    if not ok(cap):
        return None
    lo, hi = 1, cap               # boundary ~ sqrt(n log n): one crossing for d > 0
    while lo < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def edge_test(book_rets, spy_rets, rf_rets, trial_count, thresholds=None, alpha_level=None):
    """Benchmark-relative edge on aligned daily series (same length/dates).

    Decision (v2.2): an always-valid one-sided confidence sequence on the daily
    alpha built from PREDICTABLE plug-ins (``predictable_cs``: beta and the
    HAC-inflated scale estimated only from earlier returns). PASS iff
    n >= min_edge_sessions AND the lower bound > 0. The full-sample OLS alpha,
    beta and sigma_eff are reported (and drive the ETA projection) only.
    'fail' iff the UPPER bound < 0 (alpha significantly negative); otherwise
    'insufficient' (still accruing). t_HAC / PSR / DSR@trial_count / z_required
    are reported for information only."""
    th = thresholds or THRESHOLDS
    a_lvl = alpha_level if alpha_level is not None else family_alpha_level(0, th)
    rho = th["cs_rho_sessions"]
    n = len(book_rets)
    zr = z_required(trial_count, th["psr_confidence"])
    out = {"n": n, "trial_count": trial_count, "z_required": round(zr, 3),
           "alpha_daily": None, "alpha_annual": None, "beta": None, "t_hac": None,
           "ir_annual": None, "psr": None, "dsr": None, "sigma_resid_daily": None,
           "sigma_eff_daily": None, "se_alpha_hac_daily": None,
           "cs_lower_daily": None, "cs_upper_daily": None, "cs_lower": None, "cs_upper": None,
           "alpha_level": a_lvl, "rho": rho, "decision_rule": "confidence_sequence",
           "status": "insufficient"}
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
    pcs = predictable_cs(y, x, rho, a_lvl, lag=th["hac_lag"], burn_in=th["cs_burn_in"], path=True)
    lo, hi = pcs["lower"], pcs["upper"]
    out.update({
        "alpha_daily": a, "alpha_annual": a * PERIODS_PER_YEAR, "beta": reg["beta"],
        "t_hac": reg["t_alpha_hac"], "ir_annual": ir_d * math.sqrt(PERIODS_PER_YEAR), "psr": psr,
        "dsr": dsr, "sigma_resid_daily": sr, "sigma_eff_daily": sig_eff,
        "se_alpha_hac_daily": reg["se_alpha_hac"], "skew": skew, "kurtosis": kurt,
        "cs_lower_daily": lo, "cs_upper_daily": hi, "cs_increments": pcs["m"],
        "alpha_predictive_daily": pcs["point"], "cs_path": pcs.get("path") or [],
        "cs_lower": None if lo is None else lo * PERIODS_PER_YEAR,
        "cs_upper": None if hi is None else hi * PERIODS_PER_YEAR,
    })
    if n < th["min_edge_sessions"]:
        out["status"] = "insufficient"
        out["detail"] = f"n={n} < {th['min_edge_sessions']} pre-registered minimum"
    elif lo is not None and lo > 0:
        out["status"] = "pass"
    elif hi is not None and hi < 0:
        out["status"] = "fail"
    else:
        out["status"] = "insufficient"
    return out


def edge_eta(edge, thresholds=None):
    """ETA as a RANGE under the sequential boundary (sessions from now).

    For a true daily alpha a, the expected first passage is the n where the
    drift a*n/sigma meets the boundary b(n). median = at the estimate;
    pessimistic / optimistic = at estimate -/+ 1 HAC s.e. (None = not within the
    10-year cap). 'not_converging' only if the always-valid UPPER bound is <= 0
    or even at that upper bound the passage lies beyond the cap; 'too_early'
    below min_sessions_for_eta returns; 'uncertain' when no central projection
    exists (estimate <= 0 or beyond the cap) but the upper bound keeps it open."""
    th = thresholds or THRESHOLDS
    n = edge.get("n") or 0
    a, sig = edge.get("alpha_daily"), edge.get("sigma_eff_daily")
    rho, cap = th["cs_rho_sessions"], th["eta_cap_sessions"]
    lvl = edge.get("alpha_level") or family_alpha_level(0, th)
    base = {"median_sessions": None, "pessimistic_sessions": None, "optimistic_sessions": None,
            "n_required": None}
    if edge.get("status") == "pass":
        return {**base, "state": "met", "sessions_remaining": 0, "median_sessions": 0}
    if n < th["min_sessions_for_eta"] or a is None or sig is None or sig <= 0:
        return {**base, "state": "too_early", "sessions_remaining": None,
                "detail": f"needs >= {th['min_sessions_for_eta']} daily returns to estimate"}
    hi = edge.get("cs_upper_daily")
    if hi is None or hi <= 0:
        return {**base, "state": "not_converging", "sessions_remaining": None,
                "detail": "always-valid upper bound on alpha <= 0"}
    if sessions_to_cross(hi, sig, rho, lvl, cap) is None:
        return {**base, "state": "not_converging", "sessions_remaining": None,
                "detail": f"even at the upper bound the boundary is not reached within {cap} sessions"}

    def remaining(alpha):
        k = sessions_to_cross(alpha, sig, rho, lvl, cap)
        return None if k is None else max(1, k - n)

    se = edge.get("se_alpha_hac_daily") or 0.0
    med, pes, opt = remaining(a), remaining(a - se), remaining(a + se)
    out = {"state": "estimate" if med is not None else "uncertain",
           "sessions_remaining": med, "median_sessions": med, "pessimistic_sessions": pes,
           "optimistic_sessions": opt, "n_required": None if med is None else n + med}
    if med is None:
        out["detail"] = ("alpha estimate <= 0" if a <= 0 else f"crossing beyond {cap} sessions at the estimate") \
            + "; the upper bound keeps it open — no central projection"
    return out


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
           "dsr": _r(edge.get("dsr")), "n": edge.get("n"),
           "cs_lower": _r(edge.get("cs_lower")), "cs_upper": _r(edge.get("cs_upper"))}
    if edge.get("detail"):
        detail = edge["detail"]
    else:
        detail = (f"alpha {edge['alpha_annual'] * 100:+.2f}%/yr (beta {edge['beta']:.2f}); "
                  f"always-valid bounds [{edge['cs_lower'] * 100:+.2f}%, {edge['cs_upper'] * 100:+.2f}%]/yr "
                  f"at level {edge['alpha_level']:.4f}; info: t_HAC "
                  f"{'n/a' if edge.get('t_hac') is None else round(edge['t_hac'], 2)}, "
                  f"DSR@{edge['trial_count']} {edge['dsr']:.3f}")
    eta_s = eta.get("sessions_remaining") if eta.get("state") in ("estimate", "met") else None
    if edge.get("status") == "insufficient" and eta_s is not None:
        eta_s = max(eta_s, th["min_edge_sessions"] - (edge.get("n") or 0))
    return gate("edge", "Benchmark-relative edge (always-valid alpha bound vs SPY)",
                f"lower confidence-sequence bound on alpha > 0 (level {th['alpha_family']}/K), "
                f"n >= {th['min_edge_sessions']}",
                val, edge.get("status"), detail, eta_sessions=eta_s)


def research_gate(cfg, result, actual_spec_sha256, th=None):
    """Stage A (v2.2): a PRE-REGISTERED research result, machine-checked.

    ``cfg`` is the registry ``research`` block, ``result`` the artifact entry it
    points to (or None), ``actual_spec_sha256`` the hash of the spec file today.
    PASS iff the spec is unchanged since the result (hash match), the
    pre-registered acceptance says overall PASS, and the backtest itself shows
    a positive excess Sharpe and max drawdown <= research_max_backtest_drawdown.
    Returns (gate, profile); profile = the backtest numbers Stage B is judged
    against (None unless the result is usable). The gate is informational
    (hard=False) unless the engine selects the two-stage path."""
    th = th or THRESHOLDS
    name = "Pre-registered research proof (Stage A)"
    thr = (f"acceptance overall PASS on an unchanged spec; backtest max DD <= "
           f"{th['research_max_backtest_drawdown']:.0%}; excess Sharpe > 0")
    if not cfg:
        return gate("research", name, thr, None, "not_measured",
                    "no pre-registered research result on file — only the live-edge path can lead to GO",
                    hard=False), None
    if not isinstance(result, dict):
        return gate("research", name, thr, None, "not_measured",
                    f"registered result {cfg.get('artifact')}#{cfg.get('result_key')} not found", hard=False), None
    recorded = result.get("spec_sha256")
    if not recorded or not actual_spec_sha256:
        return gate("research", name, thr, None, "not_measured",
                    "spec hash unavailable — the result cannot be tied to an unchanged spec", hard=False), None
    if recorded != actual_spec_sha256:
        return gate("research", name, thr, {"spec_sha256": actual_spec_sha256[:12]}, "fail",
                    "spec changed after its result was recorded (sha256 mismatch) — the result is void",
                    hard=False), None
    acc = result.get("acceptance") or {}
    main = result.get("main") or {}
    dd = ((main.get("drawdown") or {}).get("max_drawdown")
          if isinstance(main.get("drawdown"), dict) else main.get("max_drawdown"))
    sr, vol = main.get("sharpe_excess"), main.get("vol")
    profile = None
    if all(isinstance(v, (int, float)) for v in (dd, sr, vol)) and vol > 0:
        profile = {"sharpe_excess": sr, "vol": vol, "max_drawdown": dd,
                   "source": f"{cfg.get('artifact')}#{cfg.get('result_key')}"}
    failed = sorted(k for k, v in acc.items() if k != "overall" and v != "PASS")
    problems = []
    if acc.get("overall") != "PASS":
        problems.append("acceptance " + str(acc.get("overall") or "missing")
                        + (f" ({', '.join(failed)})" if failed else ""))
    if profile is None:
        problems.append("backtest Sharpe/vol/max DD missing")
    else:
        if dd > th["research_max_backtest_drawdown"]:
            problems.append(f"backtest max DD {dd:.1%} > {th['research_max_backtest_drawdown']:.0%}")
        if sr <= 0:
            problems.append(f"backtest excess Sharpe {sr:.2f} <= 0")
    val = {"overall": acc.get("overall"), "sharpe_excess": _r(sr, 3), "max_drawdown": _r(dd),
           "vol": _r(vol), "failed_criteria": failed}
    if problems:
        return gate("research", name, thr, val, "fail", "; ".join(problems), hard=False), profile
    return gate("research", name, thr, val, "pass",
                f"pre-registered result PASS (excess Sharpe {sr:.2f}, max DD {dd:.1%}, spec "
                f"{recorded[:12]} unchanged)", hard=False), profile


def incubation_gate(returns, rf_rets, profile, th=None):
    """Stage B (v2.2): live incubation must NOT CONTRADICT the backtest.

    Incubation cannot prove edge in 60-90 sessions (the s.e. of an annual Sharpe
    is ~2 there); it detects implementation failure. After
    ``incubation_min_returns`` halt-free returns, FAIL if any of:
      * the always-valid upper bound (level incubation_alpha) on the mean daily
        excess return is below haircut x backtest Sharpe x live daily sd —
        live is significantly worse than half the backtest Sharpe;
      * live vol / backtest vol is outside [vol_ratio_min, vol_ratio_max] —
        the book is not running the strategy that was tested;
      * live max DD > dd_multiple x backtest max DD.
    Always-valid bounds keep a daily re-evaluation honest."""
    th = th or THRESHOLDS
    name = "Live incubation consistent with the backtest (Stage B)"
    hc = th["incubation_sharpe_haircut"]
    thr = (f">= {th['incubation_min_returns']} returns; not significantly below {hc:g}x backtest Sharpe; "
           f"vol ratio in [{th['incubation_vol_ratio_min']:g}, {th['incubation_vol_ratio_max']:g}]; "
           f"max DD <= {th['incubation_dd_multiple']:g}x backtest")
    if profile is None:
        return gate("incubation_consistency", name, thr, None, "not_applicable",
                    "no usable research profile to compare against", hard=False)
    n, need = len(returns), th["incubation_min_returns"]
    if n < need or len(rf_rets) != n:
        return gate("incubation_consistency", name, thr, {"n": n}, "insufficient",
                    f"{n} of {need} halt-free returns", eta_sessions=max(1, need - n), hard=False)
    ex = [r - f for r, f in zip(returns, rf_rets)]
    mean = sum(ex) / n
    sd = math.sqrt(sum((e - mean) ** 2 for e in ex) / (n - 1))
    if sd <= 0:
        return gate("incubation_consistency", name, thr, {"n": n}, "fail",
                    "zero-variance live series — not a traded strategy", hard=False)
    rpy = PERIODS_PER_YEAR
    expected = hc * profile["sharpe_excess"] / math.sqrt(rpy) * sd
    hi = predictable_cs(ex, [0.0] * n, th["cs_rho_sessions"], th["incubation_alpha"],
                        lag=th["hac_lag"], burn_in=th["cs_burn_in"], fit_beta=False)["upper"]
    vol_ratio = sd * math.sqrt(rpy) / profile["vol"]
    dd = drawdown_stats(returns)["max_drawdown"]
    dd_cap = th["incubation_dd_multiple"] * profile["max_drawdown"]
    checks = {
        "sharpe_not_contradicted": hi is not None and hi >= expected,
        "vol_ratio_in_band": th["incubation_vol_ratio_min"] <= vol_ratio <= th["incubation_vol_ratio_max"],
        "drawdown_within_multiple": dd <= dd_cap,
    }
    live_sr = mean / sd * math.sqrt(rpy)
    val = {"n": n, "live_sharpe_excess": _r(live_sr, 3), "backtest_sharpe_excess": _r(profile["sharpe_excess"], 3),
           "vol_ratio": _r(vol_ratio, 3), "live_max_drawdown": _r(dd), "drawdown_cap": _r(dd_cap),
           "checks": checks}
    detail = (f"live excess Sharpe {live_sr:+.2f} vs backtest {profile['sharpe_excess']:.2f} "
              f"(upper bound {'ok' if checks['sharpe_not_contradicted'] else 'BELOW'} {hc:g}x); "
              f"vol ratio {vol_ratio:.2f}; max DD {dd:.1%} vs cap {dd_cap:.1%}")
    return gate("incubation_consistency", name, thr, val,
                "pass" if all(checks.values()) else "fail", detail, hard=False)


def drawdown_stats(returns):
    curve = equity_curve(returns)
    mdd = M.max_drawdown(curve)
    peak = max(curve)
    cur = (peak - curve[-1]) / peak if peak > 0 else 0.0
    return {"max_drawdown": mdd, "current_drawdown": cur}


def risk_gates(returns, th=None, book_returns=None, kill=None):
    """Max DD (stricter of the version window and the whole paper period),
    kill-switch headroom (vs the LIVE engine's reference equity when ``kill`` is
    given), worst day and CVaR95 on the window's daily returns.

    ``kill``: {"reference_equity", "current_equity", "kill_drawdown", "source"}."""
    th = th or THRESHOLDS
    n = len(returns)
    gates = []
    if n < 2:
        msg = f"only {n} daily returns in the window"
        for gid, name, thr in (
                ("max_drawdown", "Max drawdown (window and book)", f"<= {th['max_drawdown']:.0%}"),
                ("kill_switch_headroom", "Kill-switch headroom", f">= {th['min_kill_headroom']:.0%}"),
                ("worst_day", "Worst day vs daily stop", f"> -{th['daily_stop']:.0%}"),
                ("cvar95", "Daily CVaR 95% (historical)", f"<= {th['max_cvar']:.1%}")):
            gates.append(gate(gid, name, thr, None, "insufficient", msg))
        if kill:
            gates[1] = _kill_gate(kill, th)
        return gates
    dd = drawdown_stats(returns)
    book_dd = drawdown_stats(book_returns)["max_drawdown"] if book_returns and len(book_returns) >= 2 else None
    worst_dd = max(dd["max_drawdown"], book_dd or 0.0)
    g = gate("max_drawdown", "Max drawdown (window and book)", f"<= {th['max_drawdown']:.0%}",
             _r(worst_dd), "pass" if worst_dd <= th["max_drawdown"] else "fail",
             f"window {dd['max_drawdown']:.2%} over {n} sessions"
             + (f"; whole paper period {book_dd:.2%}" if book_dd is not None else ""))
    g["window_value"], g["book_value"] = _r(dd["max_drawdown"]), _r(book_dd)
    gates.append(g)
    if kill:
        gates.append(_kill_gate(kill, th))
    else:
        head = th["kill_switch_drawdown"] - dd["current_drawdown"]
        gates.append(gate("kill_switch_headroom", "Kill-switch headroom",
                          f">= {th['min_kill_headroom']:.0%} (kill switch - current DD)",
                          _r(head), "pass" if head >= th["min_kill_headroom"] else "fail",
                          f"FALLBACK (no live reference): window drawdown {dd['current_drawdown']:.2%}"))
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


def _kill_gate(kill, th):
    ref, eq, kd = kill.get("reference_equity"), kill.get("current_equity"), kill.get("kill_drawdown")
    thr = f">= {th['min_kill_headroom']:.0%} (live kill switch - drawdown from its reference)"
    if not ref or eq is None or kd is None:
        return gate("kill_switch_headroom", "Kill-switch headroom", thr, None, "not_measured",
                    "live kill-switch reference or current equity unavailable")
    cur = max(0.0, (ref - eq) / ref)
    head = kd - cur
    g = gate("kill_switch_headroom", "Kill-switch headroom", thr, _r(head),
             "pass" if head >= th["min_kill_headroom"] else "fail",
             f"{kd:.0%} kill switch; drawdown {cur:.2%} from ${ref:,.0f} ({kill.get('source')})")
    g["reference_equity"], g["current_drawdown"] = ref, _r(cur)
    return g


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

def verdict(sleeve_status, gates, sessions, as_of, claims_edge=True):
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
    note = None
    if sleeve_status in NOT_ELIGIBLE_STATUSES:
        v = "NOT_ELIGIBLE"
    elif not claims_edge:
        v, note = "BETA_SLEEVE", "BETA_SLEEVE — no edge claim; readiness = risk/ops only"
    elif sleeve_status == "forward_test":
        v = "NOT_READY" if open_ else "FORWARD_TEST_PASS"
        note = ("forward test: the parent spec failed promotion; a pass never means GO — "
                "promotion needs a new registry version")
    elif not open_:
        v = "GO"
    else:
        v = "NOT_READY"
    eta = None
    if evidence and all(g.get("eta_sessions") is not None for g in evidence):
        k = max(g["eta_sessions"] for g in evidence)
        eta = {"sessions_remaining": k,
               "projected_date": session_after(sessions, as_of, k) if k else as_of,
               "label": "estimate (current alpha / trade / clean-session rates held constant)"}
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
            "measurement_gaps": gaps, "eta": eta, "verdict_note": note}


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
    elif v in ("BETA_SLEEVE", "FORWARD_TEST_PASS"):
        parts.append(f"{entry.get('verdict_note')}. {gp}/{gt} hard gates pass.")
    else:
        parts.append(f"NOT READY: {gp}/{gt} hard gates pass.")
    w = entry.get("window") or {}
    parts.append(f"{w.get('trading_days', 0)} sessions since {w.get('start')}.")
    if entry.get("path") == "two_stage":
        parts.append("Path: two-stage (pre-registered research PASS + live incubation).")
    if edge.get("alpha_annual") is not None and edge.get("cs_lower") is not None:
        parts.append(f"Alpha vs SPY {edge['alpha_annual'] * 100:+.1f}%/yr (beta {edge['beta']:.2f}, n={edge['n']}); "
                     f"always-valid bounds [{edge['cs_lower'] * 100:+.1f}%, {edge['cs_upper'] * 100:+.1f}%]/yr.")
    if b:
        g = next((x for x in entry["gates"] if x["id"] == b), {})
        parts.append(f"Binding: {g.get('name', b)} — {g.get('detail', '')}.")
    eta = entry.get("eta") or {}
    if v in ("NOT_READY", "BETA_SLEEVE") and eta:
        parts.append(f"ETA {eta.get('projected_date')} ({eta.get('label')})." if eta.get("projected_date")
                     else f"ETA: {eta.get('label', 'n/a')}.")
    if entry.get("measurement_gaps"):
        parts.append("Not yet measured (blocks GO): " + ", ".join(entry["measurement_gaps"]) + ".")
    if entry.get("attribution") == "book_level":
        parts.append("Returns are BOOK-level (whole account).")
    elif entry.get("attribution") == "book_level_shared":
        parts.append("Returns are BOOK-level and SHARED with another sleeve: no edge credit.")
    return " ".join(parts)
