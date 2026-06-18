"""Challenger benchmark (V2) — the dumb strategy the adaptive book must beat.

A self-learning change that cannot out-perform a fixed, naive benchmark out-of-
sample is not an improvement; it is noise-fitting. This module provides that
benchmark: a regime-filtered equal-weight buy-and-hold of the same universe
(fully invested when SPY is above its long moving average, in cash otherwise).
It deliberately uses no adaptive parameters, so it is a stable yardstick.

Pure except for reusing the same cost/slippage model as the real backtester so
the comparison is apples-to-apples.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest import metrics  # noqa: E402


def _sma(values, period):
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def challenger_backtest(symbol_bars, spy_bars, starting_equity=100_000.0,
                        cost_bps=5.0, slippage_bps=5.0, warmup=200,
                        regime_ma=200):
    """Regime-filtered equal-weight buy-and-hold over the aligned window.

    Holds an equal-weight basket of all symbols while SPY closes above its
    `regime_ma`-day SMA; moves fully to cash otherwise. Rebalances at the next
    day's open (no look-ahead), marks to close. Returns equity_curve + metrics.
    """
    symbols = sorted(symbol_bars.keys())  # deterministic iteration (no hash-order dependence)
    n = len(spy_bars)
    for s in symbols:
        if len(symbol_bars[s]) != n:
            raise ValueError(f"Bars for {s} not aligned to SPY ({len(symbol_bars[s])} vs {n})")
    if n <= warmup + 2:
        raise ValueError(f"Need > warmup+2 ({warmup + 2}) bars; got {n}")

    cost = cost_bps / 10_000.0
    slip = slippage_bps / 10_000.0
    spy_closes = [b["c"] for b in spy_bars]
    sym_closes = {s: [b["c"] for b in symbol_bars[s]] for s in symbols}
    sym_opens = {s: [b.get("o", b["c"]) for b in symbol_bars[s]] for s in symbols}

    cash = starting_equity
    holdings = {}
    pending_invested = None
    equity_curve = [starting_equity]
    trade_pnls = []
    entry_px = {}

    def portfolio_value(t):
        v = cash
        for s, sh in holdings.items():
            v += sh * sym_closes[s][t]
        return v

    for t in range(warmup, n - 1):
        if pending_invested is not None:
            want_invested = pending_invested
            if not want_invested and holdings:
                for s in sorted(holdings.keys()):
                    fill = sym_opens[s][t] * (1 - slip)
                    proceeds = holdings[s] * fill * (1 - cost)
                    trade_pnls.append(proceeds - holdings[s] * entry_px[s])
                    cash += proceeds
                    del holdings[s]
                    del entry_px[s]
            elif want_invested and not holdings and symbols:
                per = cash / len(symbols)
                for s in symbols:
                    fill = sym_opens[s][t] * (1 + slip)
                    shares = (per * (1 - cost)) / fill if fill else 0
                    if shares > 0:
                        holdings[s] = shares
                        entry_px[s] = fill
                        cash -= per
            pending_invested = None

        ma = _sma(spy_closes[: t + 1], regime_ma)
        bullish = ma is not None and spy_closes[t] > ma
        pending_invested = bool(bullish)
        equity_curve.append(portfolio_value(t))

    last = n - 1
    for s in sorted(holdings.keys()):
        proceeds = holdings[s] * sym_closes[s][last] * (1 - cost)
        trade_pnls.append(proceeds - holdings[s] * entry_px[s])
        cash += proceeds
    equity_curve.append(cash)

    return {
        "equity_curve": equity_curve,
        "trade_pnls": trade_pnls,
        "metrics": metrics.summary(equity_curve, trade_pnls),
    }
