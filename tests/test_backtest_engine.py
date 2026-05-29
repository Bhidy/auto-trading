"""Backtest engine behavioral tests: profitability in trends, cost impact,
capital preservation, and absence of look-ahead bias."""
import math

from backtest.engine import backtest_symbol, composite_score


def _bars(closes):
    """Build OHLC bars from a close series (open = prior close)."""
    bars = []
    prev = closes[0]
    for c in closes:
        bars.append({"o": prev, "h": max(c, prev) * 1.001,
                     "l": min(c, prev) * 0.999, "c": c, "v": 1_000_000})
        prev = c
    return bars


def test_uptrend_is_profitable():
    # Steady uptrend: long-only strategy should enter and end ahead.
    closes = [100 * (1.004 ** i) for i in range(260)]
    res = backtest_symbol(_bars(closes), cost_bps=0, slippage_bps=0)
    assert res["num_entries"] >= 1
    assert res["equity_curve"][-1] > res["equity_curve"][0]
    assert res["metrics"]["total_return"] > 0


def test_costs_reduce_returns():
    closes = [100 * (1.003 ** i) for i in range(260)]
    bars = _bars(closes)
    free = backtest_symbol(bars, cost_bps=0, slippage_bps=0)
    costly = backtest_symbol(bars, cost_bps=20, slippage_bps=20)
    assert costly["equity_curve"][-1] <= free["equity_curve"][-1]


def test_downtrend_preserves_capital_vs_buyhold():
    # Long-only with trend filter should lose less than buy-and-hold in a crash.
    closes = [100 * (0.99 ** i) for i in range(260)]
    bars = _bars(closes)
    res = backtest_symbol(bars, cost_bps=5, slippage_bps=5)
    buy_hold = closes[-1] / closes[0]
    strat = res["equity_curve"][-1] / res["equity_curve"][0]
    assert strat >= buy_hold  # avoided some/all of the decline


def test_no_lookahead_future_bar_does_not_change_past_equity():
    # The equity path up to bar k must be identical whether or not bars after k
    # change. If it differs, the engine is peeking into the future.
    base = [100 + 10 * math.sin(i / 5) + i * 0.2 for i in range(200)]
    altered = list(base)
    altered[150:] = [v * 1.5 for v in altered[150:]]  # change only the future

    r1 = backtest_symbol(_bars(base), cost_bps=1, slippage_bps=1)
    r2 = backtest_symbol(_bars(altered), cost_bps=1, slippage_bps=1)
    # Compare equity curves up to index 140 (before the divergence at 150).
    for a, b in zip(r1["equity_curve"][:141], r2["equity_curve"][:141]):
        assert abs(a - b) < 1e-6


def test_composite_score_none_until_warmup():
    closes = [100.0] * 10
    assert composite_score(closes, {"ma_fast": 50, "ma_slow": 200}) is None


def test_composite_score_bounded():
    closes = [100 * (1.01 ** i) for i in range(120)]
    s = composite_score(closes, {})
    assert s is None or (-1.0 <= s <= 1.0)


def test_deterministic():
    closes = [100 + (i % 7) for i in range(160)]
    bars = _bars(closes)
    a = backtest_symbol(bars)
    b = backtest_symbol(bars)
    assert a["equity_curve"] == b["equity_curve"]
