"""
Full multi-factor portfolio backtester (point-in-time, no look-ahead).

Unlike the single-symbol engine.py (a transparent trend/momentum/RSI replay),
this reuses the EXACT production scoring pipeline from analyst_v2 —
detect_regime, rank_by_relative_strength, analyze_symbol_v2 — so the backtest
reflects the real strategy (regime multiplier, relative-strength ranking, MACD,
Bollinger, the full composite score and adaptive thresholds).

Anti-look-ahead contract:
  * the signal for day t is computed from bars[:t+1] (through day t's close);
  * the resulting rebalance executes at day t+1's OPEN with slippage;
  * equity is marked to each day's close.

Inputs must be date-aligned: symbol_bars[sym] and spy_bars are chronological
lists of equal length covering the same trading days.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyst_v2 import (  # noqa: E402  (path set above; reuse production scoring)
    analyze_symbol_v2,
    detect_regime,
    load_adaptive_params,
    rank_by_relative_strength,
)


def _closes(bars):
    return [b["c"] for b in bars]


def backtest_multifactor(symbol_bars, spy_bars, params=None, instrument_types=None,
                         starting_equity=100_000.0, max_positions=10,
                         buy_threshold=None, cost_bps=5.0, slippage_bps=5.0,
                         warmup=200):
    """Long-only, equal-weight top-N backtest using the production multi-factor
    score. Returns equity_curve, trade_pnls, signals_per_day, and metrics.
    """
    from backtest import metrics

    # Merge any partial param overrides over the full default set so a candidate
    # that only changes a knob or two still has every key analyze_symbol_v2 needs.
    base = load_adaptive_params()
    if params:
        base.update(params)
    params = base
    instrument_types = instrument_types or {}
    if buy_threshold is None:
        buy_threshold = params.get("confidence_buy_threshold", 0.50)
    cost = cost_bps / 10_000.0
    slip = slippage_bps / 10_000.0

    symbols = list(symbol_bars.keys())
    n = len(spy_bars)
    # Defensive: require aligned lengths.
    for s in symbols:
        if len(symbol_bars[s]) != n:
            raise ValueError(f"Bars for {s} ({len(symbol_bars[s])}) not aligned to SPY ({n})")
    if n <= warmup + 2:
        raise ValueError(f"Need > warmup+2 ({warmup + 2}) bars; got {n}")

    spy_closes = _closes(spy_bars)
    sym_closes = {s: _closes(symbol_bars[s]) for s in symbols}
    sym_opens = {s: [b.get("o", b["c"]) for b in symbol_bars[s]] for s in symbols}

    cash = starting_equity
    holdings = {}            # sym -> shares
    entry_px = {}            # sym -> entry price
    pending = None           # desired target set decided at t, executed at t+1
    equity_curve = [starting_equity]
    trade_pnls = []
    signals_per_day = []

    def portfolio_value(t):
        v = cash
        for s, sh in holdings.items():
            v += sh * sym_closes[s][t]
        return v

    for t in range(warmup, n - 1):
        # 1) Execute the rebalance decided yesterday, at today's open.
        if pending is not None:
            target = pending
            # Sell holdings not in target.
            for s in list(holdings.keys()):
                if s not in target:
                    fill = sym_opens[s][t] * (1 - slip)
                    proceeds = holdings[s] * fill * (1 - cost)
                    trade_pnls.append(proceeds - holdings[s] * entry_px[s])
                    cash += proceeds
                    del holdings[s]
                    del entry_px[s]
            # Equal-weight buy/adjust target names.
            if target:
                equity_now = cash + sum(holdings[s] * sym_opens[s][t] for s in holdings)
                target_val = equity_now / len(target)
                for s in target:
                    cur_val = holdings.get(s, 0) * sym_opens[s][t]
                    if cur_val < target_val and cash > 0:
                        spend = min(target_val - cur_val, cash)
                        fill = sym_opens[s][t] * (1 + slip)
                        shares = (spend * (1 - cost)) / fill
                        if shares > 0:
                            prev_sh = holdings.get(s, 0)
                            # Weighted-average entry price.
                            entry_px[s] = ((prev_sh * entry_px.get(s, fill)) + shares * fill) / (prev_sh + shares)
                            holdings[s] = prev_sh + shares
                            cash -= spend
            pending = None

        # 2) Score every symbol point-in-time (through today's close).
        window = {s: symbol_bars[s][: t + 1] for s in symbols}
        regime = detect_regime(spy_closes[: t + 1])
        rs_data = rank_by_relative_strength(window)
        buys = []
        for s in symbols:
            itype = instrument_types.get(s, "stock")
            res = analyze_symbol_v2(window[s], s, itype, regime, rs_data, params)
            if res.get("signal") == "BUY" and res.get("score", 0) >= buy_threshold:
                buys.append((s, res["score"]))
        buys.sort(key=lambda x: x[1], reverse=True)
        target = {s for s, _ in buys[:max_positions]}
        signals_per_day.append({"t": t, "regime": regime, "n_buys": len(buys)})
        pending = target

        # 3) Mark to market at today's close.
        equity_curve.append(portfolio_value(t))

    # Liquidate at the final close (last bar — no look-ahead).
    last = n - 1
    for s in list(holdings.keys()):
        proceeds = holdings[s] * sym_closes[s][last] * (1 - cost)
        trade_pnls.append(proceeds - holdings[s] * entry_px[s])
        cash += proceeds
        del holdings[s]
    equity_curve.append(cash)

    return {
        "equity_curve": equity_curve,
        "trade_pnls": trade_pnls,
        "signals_per_day": signals_per_day,
        "metrics": metrics.summary(equity_curve, trade_pnls),
    }
