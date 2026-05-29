"""
Risk-adjusted performance metrics — institutional standard.

Pure functions (no dependencies beyond the stdlib) so they can run anywhere:
in the backtester, in CI, or against the LIVE equity curve to report real
Sharpe/Sortino/drawdown instead of just win-rate.

All return-series inputs are *periodic simple returns* (e.g. daily). Annualized
metrics use `periods_per_year` (252 for daily US equities).
"""
import math

TRADING_DAYS = 252


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs, sample=True):
    n = len(xs)
    if n < 2:
        return 0.0
    m = _mean(xs)
    denom = (n - 1) if sample else n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / denom)


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
    if dd == 0:
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
