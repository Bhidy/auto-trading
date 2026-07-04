"""
Risk-adjusted performance metrics — institutional standard.

Pure functions (no dependencies beyond the stdlib) so they can run anywhere:
in the backtester, in CI, or against the LIVE equity curve to report real
Sharpe/Sortino/drawdown instead of just win-rate.

All return-series inputs are *periodic simple returns* (e.g. daily). Annualized
metrics use `periods_per_year` (252 for daily US equities).
"""
import math
from itertools import combinations

TRADING_DAYS = 252
_EULER_MASCHERONI = 0.5772156649015329


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _negligible(sd, values):
    """True if ``sd`` is FP residue, not real dispersion.

    A (near-)constant series should have std exactly 0.0, but floating-point
    accumulation can leave it as a tiny non-zero (~1e-11) that varies by
    Python/platform. If callers then divide by it (Sharpe/Sortino), the ratio
    blows up to ~1e16 — a garbage number that could falsely clear a DSR gate.
    Treat any std negligible relative to the data scale (or below an absolute
    floor) as zero. Real daily-return std (~1e-3) is never anywhere near this.
    """
    scale = max((abs(v) for v in values), default=0.0)
    return sd <= 1e-12 or sd <= scale * 1e-9


def _std(xs, sample=True):
    n = len(xs)
    if n < 2:
        return 0.0
    m = _mean(xs)
    denom = (n - 1) if sample else n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / denom)
    return 0.0 if _negligible(sd, xs) else sd


def returns_from_equity(equity_curve):
    """Convert an equity curve [v0, v1, ...] to simple periodic returns."""
    out = []
    for prev, cur in zip(equity_curve, equity_curve[1:]):
        if prev and prev != 0:
            out.append(cur / prev - 1.0)
    return out


def total_return(equity_curve):
    if len(equity_curve) < 2 or not equity_curve[0]:
        return 0.0
    return equity_curve[-1] / equity_curve[0] - 1.0


def cagr(equity_curve, periods_per_year=TRADING_DAYS):
    """Compound annual growth rate from an equity curve."""
    n = len(equity_curve) - 1
    if n < 1 or not equity_curve[0] or equity_curve[-1] <= 0:
        return 0.0
    years = n / periods_per_year
    if years <= 0:
        return 0.0
    return (equity_curve[-1] / equity_curve[0]) ** (1 / years) - 1.0


def annualized_volatility(returns, periods_per_year=TRADING_DAYS):
    return _std(returns) * math.sqrt(periods_per_year)


def sharpe_ratio(returns, risk_free_rate=0.0, periods_per_year=TRADING_DAYS):
    """Annualized Sharpe. risk_free_rate is an annual rate."""
    if len(returns) < 2:
        return 0.0
    rf_per_period = risk_free_rate / periods_per_year
    excess = [r - rf_per_period for r in returns]
    sd = _std(excess)
    if sd == 0:
        return 0.0
    return (_mean(excess) / sd) * math.sqrt(periods_per_year)


def sortino_ratio(returns, risk_free_rate=0.0, periods_per_year=TRADING_DAYS):
    """Annualized Sortino — penalizes only downside deviation."""
    if len(returns) < 2:
        return 0.0
    rf_per_period = risk_free_rate / periods_per_year
    excess = [r - rf_per_period for r in returns]
    downside = [min(e, 0.0) for e in excess]
    dd = math.sqrt(sum(d * d for d in downside) / len(downside))
    if _negligible(dd, downside):
        return 0.0
    return (_mean(excess) / dd) * math.sqrt(periods_per_year)


def max_drawdown(equity_curve):
    """Largest peak-to-trough decline as a fraction (e.g. 0.18 = -18%)."""
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def calmar_ratio(equity_curve, periods_per_year=TRADING_DAYS):
    """CAGR / max drawdown."""
    mdd = max_drawdown(equity_curve)
    if mdd == 0:
        return 0.0
    return cagr(equity_curve, periods_per_year) / mdd


def win_rate(trade_pnls):
    if not trade_pnls:
        return None
    wins = sum(1 for p in trade_pnls if p > 0)
    return wins / len(trade_pnls)


def profit_factor(trade_pnls):
    gross_win = sum(p for p in trade_pnls if p > 0)
    gross_loss = -sum(p for p in trade_pnls if p < 0)
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


# ---------------------------------------------------------------------------
# OVERFITTING STATISTICS (V1) — guard the self-learning loop against noise.
#
# Standard holdout Sharpe is not enough in finance: with enough parameter trials
# an impressive backtest appears by chance. These functions implement the two
# screens the audit cited (Bailey & López de Prado): the Deflated Sharpe Ratio
# (penalizes a selected Sharpe for the number of trials) and the Probability of
# Backtest Overfitting via combinatorially-symmetric cross-validation (CSCV).
# ---------------------------------------------------------------------------

def normal_cdf(x):
    """Standard normal CDF via the error function (pure stdlib)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def inverse_normal_cdf(p):
    """Inverse standard normal CDF (Acklam's rational approximation)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
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
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def probabilistic_sharpe_ratio(observed_sr, benchmark_sr, n_obs,
                               skew=0.0, kurtosis=3.0):
    """Probability that the true (per-period) Sharpe exceeds `benchmark_sr`,
    given a finite sample with non-normal returns. `observed_sr`/`benchmark_sr`
    are per-period (not annualized). Returns a probability in [0, 1]."""
    if n_obs < 2:
        return 0.0
    denom = 1.0 - skew * observed_sr + ((kurtosis - 1.0) / 4.0) * observed_sr ** 2
    if denom <= 0:
        return 0.0
    z = (observed_sr - benchmark_sr) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return normal_cdf(z)


def deflated_sharpe_ratio(trial_sharpes, n_obs, skew=0.0, kurtosis=3.0):
    """Deflated Sharpe Ratio: the probability the BEST observed (per-period)
    Sharpe across `len(trial_sharpes)` trials is truly > 0 after deflating for
    multiple testing. Inputs are per-period Sharpes. Returns a probability in
    [0, 1]; treat > 0.95 as significant, near 0.5 as noise."""
    trials = [s for s in trial_sharpes if s is not None]
    n = len(trials)
    if n == 0 or n_obs < 2:
        return 0.0
    sr_best = max(trials)
    if n == 1:
        return probabilistic_sharpe_ratio(sr_best, 0.0, n_obs, skew, kurtosis)
    mean = sum(trials) / n
    var_sr = sum((s - mean) ** 2 for s in trials) / (n - 1)
    if var_sr <= 0:
        return probabilistic_sharpe_ratio(sr_best, 0.0, n_obs, skew, kurtosis)
    z1 = inverse_normal_cdf(1.0 - 1.0 / n)
    z2 = inverse_normal_cdf(1.0 - 1.0 / (n * math.e))
    sr0 = math.sqrt(var_sr) * ((1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2)
    return probabilistic_sharpe_ratio(sr_best, sr0, n_obs, skew, kurtosis)


def probability_of_backtest_overfitting(perf_matrix, n_splits=None):
    """Probability of Backtest Overfitting (CSCV, Bailey et al.).

    `perf_matrix`: rows = strategy configurations/trials, cols = time slices,
    cells = a performance score per slice (e.g. per-slice return or Sharpe).
    The method forms all balanced train/test splits of the time slices, selects
    the best configuration in-sample, and measures how often it lands below the
    median out-of-sample. PBO ≈ that frequency. Returns a probability in [0, 1];
    < 0.5 is the acceptance region. Returns None if there isn't enough data.
    """
    rows = [r for r in perf_matrix if r]
    n_trials = len(rows)
    if n_trials < 2:
        return None
    n_cols = min(len(r) for r in rows)
    if n_cols < 4:
        return None
    cols = list(range(n_cols))
    s = n_splits or (n_cols if n_cols % 2 == 0 else n_cols - 1)
    half = s // 2 if s else n_cols // 2
    half = max(1, min(half, n_cols // 2))

    logits = []
    for train_cols in combinations(cols, half):
        train_set = set(train_cols)
        test_cols = [c for c in cols if c not in train_set]
        if not test_cols:
            continue
        is_perf = [sum(rows[t][c] for c in train_cols) / len(train_cols)
                   for t in range(n_trials)]
        oos_perf = [sum(rows[t][c] for c in test_cols) / len(test_cols)
                    for t in range(n_trials)]
        best = max(range(n_trials), key=lambda t: is_perf[t])
        # Rank of the IS-best config out-of-sample (1 = worst .. n = best).
        order = sorted(range(n_trials), key=lambda t: oos_perf[t])
        rank = order.index(best) + 1
        w = rank / (n_trials + 1)
        w = min(max(w, 1e-6), 1 - 1e-6)
        logits.append(math.log(w / (1 - w)))

    if not logits:
        return None
    return sum(1 for x in logits if x <= 0) / len(logits)


def summary(equity_curve, trade_pnls=None, risk_free_rate=0.0,
            periods_per_year=TRADING_DAYS):
    """One-call institutional performance report from an equity curve."""
    rets = returns_from_equity(equity_curve)
    wr = win_rate(trade_pnls) if trade_pnls is not None else None
    return {
        "total_return": round(total_return(equity_curve), 4),
        "cagr": round(cagr(equity_curve, periods_per_year), 4),
        "annual_volatility": round(annualized_volatility(rets, periods_per_year), 4),
        "sharpe": round(sharpe_ratio(rets, risk_free_rate, periods_per_year), 3),
        "sortino": round(sortino_ratio(rets, risk_free_rate, periods_per_year), 3),
        "max_drawdown": round(max_drawdown(equity_curve), 4),
        "calmar": round(calmar_ratio(equity_curve, periods_per_year), 3),
        "win_rate": round(wr, 4) if wr is not None else None,
        "profit_factor": (round(profit_factor(trade_pnls), 3)
                          if trade_pnls else None),
        "num_periods": len(equity_curve),
        "num_trades": len(trade_pnls) if trade_pnls is not None else None,
    }
