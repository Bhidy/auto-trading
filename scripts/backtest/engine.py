"""
Point-in-time backtest engine (long-only, single symbol).

Design priorities, in order: (1) NO look-ahead bias, (2) transparent rules,
(3) realistic costs. It reuses the SAME indicator functions as the live
analyst (`analyst_v2`) so the backtest cannot silently drift from production
math.

Scope & honesty: this replays a transparent composite of the production
building blocks (MA trend + momentum + RSI) on one symbol at a time. It is NOT
the full multi-factor/regime/relative-strength model — that requires
point-in-time regime and cross-sectional ranking and is the next increment.
Every assumption below is explicit; a backtest with hidden look-ahead is worse
than none.

Key anti-look-ahead rule: the signal for day t is computed from bars[:t+1]
(through day t's close); the resulting position change is executed at day
t+1's OPEN with slippage. Equity is marked to each day's close.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyst_v2 import sma, rsi, momentum  # noqa: E402  (reuse production math)


def composite_score(closes, params):
    """Transparent long-only score in [-1, 1] from production indicators.
    Returns None until enough history exists (no look-ahead, no guessing)."""
    ma_fast_p = params.get("ma_fast", 50)
    ma_slow_p = params.get("ma_slow", 200)
    if len(closes) < ma_fast_p + 1:
        return None

    price = closes[-1]
    ma_fast = sma(closes, ma_fast_p)
    ma_slow = sma(closes, min(ma_slow_p, len(closes)))
    r = rsi(closes)
    mom_1m = momentum(closes, 21)

    if ma_fast is None or ma_slow is None or r is None:
        return None

    score = 0.0
    # Trend (0.45): price vs fast/slow MA
    if price > ma_fast:
        score += 0.225
    if ma_fast > ma_slow:
        score += 0.225
    # Momentum (0.30): 1-month return
    if mom_1m is not None:
        score += max(-0.30, min(0.30, mom_1m / 20.0))
    # RSI (0.25): reward oversold-recovery, penalize overbought
    rsi_buy = params.get("rsi_oversold", 35)
    rsi_sell = params.get("rsi_overbought", 70)
    if r < rsi_buy:
        score += 0.25
    elif r > rsi_sell:
        score -= 0.25

    return max(-1.0, min(1.0, score))


def backtest_symbol(bars, params=None, starting_equity=100_000.0,
                    cost_bps=5.0, slippage_bps=5.0):
    """Run a long-only point-in-time backtest on one symbol's daily bars.

    bars: chronological list of dicts with 'o','h','l','c'.
    cost_bps/slippage_bps: per-side commission and slippage in basis points.
    Returns: dict with equity_curve, trade_pnls, signals fired, and metrics.
    """
    from backtest import metrics

    params = params or {}
    buy_threshold = params.get("confidence_buy_threshold", 0.50)
    exit_threshold = params.get("confidence_exit_threshold", 0.0)
    cost = cost_bps / 10_000.0
    slip = slippage_bps / 10_000.0

    closes = [b["c"] for b in bars]
    opens = [b.get("o", b["c"]) for b in bars]

    equity = starting_equity
    cash = starting_equity
    shares = 0.0
    entry_price = None
    pending = None  # signal decided at t, executed at t+1 open
    equity_curve = [starting_equity]
    trade_pnls = []
    n_entries = 0

    for t in range(len(bars) - 1):
        # 1) Execute yesterday's decision at today's open.
        if pending == "enter" and shares == 0:
            fill = opens[t] * (1 + slip)
            shares = (cash * (1 - cost)) / fill
            cash = 0.0
            entry_price = fill
            n_entries += 1
        elif pending == "exit" and shares > 0:
            fill = opens[t] * (1 - slip)
            proceeds = shares * fill * (1 - cost)
            pnl = proceeds - (shares * entry_price)
            trade_pnls.append(pnl)
            cash = proceeds
            shares = 0.0
            entry_price = None
        pending = None

        # 2) Decide today's signal from data through today's close (no look-ahead).
        score = composite_score(closes[: t + 1], params)
        if score is not None:
            if shares == 0 and score >= buy_threshold:
                pending = "enter"
            elif shares > 0 and score <= exit_threshold:
                pending = "exit"

        # 3) Mark equity to today's close.
        equity = cash + shares * closes[t]
        equity_curve.append(equity)

    # Close any open position at the final close (no look-ahead — it's the last bar).
    if shares > 0:
        proceeds = shares * closes[-1] * (1 - cost)
        trade_pnls.append(proceeds - (shares * entry_price))
        cash = proceeds
        shares = 0.0
    equity_curve.append(cash)

    return {
        "equity_curve": equity_curve,
        "trade_pnls": trade_pnls,
        "num_entries": n_entries,
        "metrics": metrics.summary(equity_curve, trade_pnls),
    }
