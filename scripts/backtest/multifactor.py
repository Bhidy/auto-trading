"""
Full multi-factor portfolio backtester (point-in-time, no look-ahead).

Unlike the single-symbol engine.py (a transparent trend/momentum/RSI replay),
this reuses the EXACT production scoring pipeline from analyst_v2 —
detect_regime, rank_by_relative_strength, analyze_symbol_v2 — so the backtest
reflects the real strategy (regime multiplier, relative-strength ranking, MACD,
Bollinger, the full composite score and adaptive thresholds).

Exit modeling (Phase-0 profit-program fix): in addition to target-set rotation,
each held position is now managed by the SAME exit semantics the live system
intends — an entry-anchored ATR stop that trails up, a breakeven lock once in
profit, an ATR take-profit that trims, and an optional time-stop. Every knob is
read from ``params`` (defaults reproduce current production), so a candidate exit
configuration can be walk-forward validated. Before this, the backtester modeled
NO exits, so the live disposition error (cut winners, run losers) was invisible
to validation. See ``_position_exit`` — a pure, unit-tested function.

Anti-look-ahead contract:
  * the signal for day t is computed from bars[:t+1] (through day t's close);
  * the resulting rebalance executes at day t+1's OPEN with slippage;
  * intraday exits for day t use only day t's OHLC (known at t, no future);
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


def _atr(bars, end_idx, period=14):
    """ATR through day ``end_idx`` (inclusive) from OHLC; point-in-time (no future
    bars). Returns None if there isn't enough history."""
    if end_idx < 1:
        return None
    lo = max(1, end_idx - period + 1)
    trs = []
    for i in range(lo, end_idx + 1):
        h, low, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs.append(max(h - low, abs(h - pc), abs(low - pc)))
    return (sum(trs) / len(trs)) if trs else None


def _exit_params(params):
    """Exit knobs with defaults that reproduce current production behavior."""
    return {
        "trailing_stop_atr_mult": float(params.get("trailing_stop_atr_mult", 2.5)),
        "take_profit_atr_mult": float(params.get("take_profit_atr_mult", 4.0)),
        "breakeven_trigger_pct": float(params.get("breakeven_trigger_pct", 0.03)),
        "breakeven_lock_pct": float(params.get("breakeven_lock_pct", 0.005)),
        "take_profit_trim": float(params.get("take_profit_trim", 0.5)),
        # 0/None disables the time-stop (current production has none).
        "time_stop_days": int(params.get("time_stop_days", 0) or 0),
        "time_stop_min_gain_pct": float(params.get("time_stop_min_gain_pct", 0.01)),
    }


def _position_exit(state, bar, atr, t, ep):
    """Decide intraday exits for one held position on day ``t``.

    state: {shares, entry, stop, hwm, trimmed, entry_t}
    bar:   {o,h,l,c}  (day t OHLC)   atr: entry-anchored ATR   ep: _exit_params()
    Returns (events, new_state). events is a list of (shares, price, reason).
    Resolution order is conservative: stop first (use the worse fill on a gap),
    then take-profit, then time-stop. Pure function — no I/O, deterministic.
    """
    shares = state["shares"]
    entry = state["entry"]
    stop = state["stop"]
    hwm = max(state["hwm"], bar["h"])
    trimmed = state["trimmed"]
    o, h, low = bar["o"], bar["h"], bar["l"]

    if atr and atr > 0:
        # Trail the stop up toward the high-water mark; never loosen it.
        stop = max(stop, hwm - atr * ep["trailing_stop_atr_mult"])
    # Breakeven lock once the high has tagged the trigger gain.
    if entry > 0 and (h / entry - 1.0) >= ep["breakeven_trigger_pct"]:
        stop = max(stop, entry * (1.0 + ep["breakeven_lock_pct"]))

    new_state = {"shares": shares, "entry": entry, "stop": stop, "hwm": hwm,
                 "trimmed": trimmed, "entry_t": state["entry_t"]}

    # 1) Stop: if the low pierced the stop, exit the full remaining lot. On a gap
    #    open below the stop, fill at the (worse) open, not the stop.
    if low <= stop:
        fill = o if o < stop else stop
        new_state["shares"] = 0.0
        return [(shares, fill, "stop")], new_state

    # 2) Take-profit: first time the high tags entry + N*ATR, trim a fraction.
    if not trimmed and atr and atr > 0:
        tp = entry + atr * ep["take_profit_atr_mult"]
        if h >= tp:
            trim = shares * ep["take_profit_trim"]
            new_state["shares"] = shares - trim
            new_state["trimmed"] = True
            return [(trim, tp, "take_profit")], new_state

    # 3) Time-stop: held too long without working out -> exit at the close.
    if ep["time_stop_days"] and (t - state["entry_t"]) >= ep["time_stop_days"]:
        if (bar["c"] / entry - 1.0) < ep["time_stop_min_gain_pct"]:
            new_state["shares"] = 0.0
            return [(shares, bar["c"], "time_stop")], new_state

    return [], new_state


def backtest_multifactor(symbol_bars, spy_bars, params=None, instrument_types=None,
                         starting_equity=100_000.0, max_positions=10,
                         buy_threshold=None, cost_bps=5.0, slippage_bps=5.0,
                         warmup=200, model_exits=True):
    """Long-only, equal-weight top-N backtest using the production multi-factor
    score, with intraday stop/take-profit/breakeven/time-stop exit modeling
    (``model_exits=True``). Returns equity_curve, trade_pnls, exit_reasons,
    signals_per_day, and metrics.
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
    ep = _exit_params(params)

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
    pos = {}                 # sym -> exit state {atr, stop, hwm, trimmed, entry_t}
    pending = None           # desired target set decided at t, executed at t+1
    equity_curve = [starting_equity]
    trade_pnls = []
    exit_reasons = []
    signals_per_day = []

    def portfolio_value(t):
        v = cash
        for s, sh in holdings.items():
            v += sh * sym_closes[s][t]
        return v

    def _open_position(s, shares, fill, t):
        prev_sh = holdings.get(s, 0)
        entry_px[s] = ((prev_sh * entry_px.get(s, fill)) + shares * fill) / (prev_sh + shares)
        holdings[s] = prev_sh + shares
        atr = _atr(symbol_bars[s], t)
        st = pos.get(s)
        if st is None:
            stop0 = entry_px[s] - (atr * ep["trailing_stop_atr_mult"]) if atr else 0.0
            pos[s] = {"atr": atr, "stop": stop0, "hwm": entry_px[s],
                      "trimmed": False, "entry_t": t}
        else:  # add to existing lot: re-anchor ATR/stop to the new avg entry, keep age
            st["atr"] = atr
            if atr:
                st["stop"] = max(st["stop"], entry_px[s] - atr * ep["trailing_stop_atr_mult"])

    def _close_chunk(s, shares, price):
        nonlocal cash
        fill = price * (1 - slip)
        proceeds = shares * fill * (1 - cost)
        trade_pnls.append(proceeds - shares * entry_px[s])
        cash += proceeds

    def _drop(s):
        for d in (holdings, entry_px, pos):
            d.pop(s, None)

    for t in range(warmup, n - 1):
        # 1) Execute the rebalance decided yesterday, at today's open.
        if pending is not None:
            target = pending
            for s in list(holdings.keys()):           # sell holdings not in target
                if s not in target:
                    _close_chunk(s, holdings[s], sym_opens[s][t])
                    exit_reasons.append("rotation")
                    _drop(s)
            if target:                                # equal-weight buy/adjust targets
                equity_now = cash + sum(holdings[s] * sym_opens[s][t] for s in holdings)
                target_val = equity_now / len(target)
                for s in target:
                    cur_val = holdings.get(s, 0) * sym_opens[s][t]
                    if cur_val < target_val and cash > 0:
                        spend = min(target_val - cur_val, cash)
                        fill = sym_opens[s][t] * (1 + slip)
                        shares = (spend * (1 - cost)) / fill
                        if shares > 0:
                            _open_position(s, shares, fill, t)
                            cash -= spend
            pending = None

        # 1b) Intraday exit management (stop / take-profit / breakeven / time-stop).
        if model_exits:
            for s in list(holdings.keys()):
                st = pos[s]
                state = {"shares": holdings[s], "entry": entry_px[s], "stop": st["stop"],
                         "hwm": st["hwm"], "trimmed": st["trimmed"], "entry_t": st["entry_t"]}
                # Trail on CURRENT ATR (point-in-time), not a frozen entry ATR — a
                # frozen absolute ATR is meaningless once a position re-rates.
                atr_now = _atr(symbol_bars[s], t) or st["atr"]
                events, new_state = _position_exit(state, symbol_bars[s][t], atr_now, t, ep)
                st["stop"], st["hwm"], st["trimmed"] = new_state["stop"], new_state["hwm"], new_state["trimmed"]
                for sh, px, reason in events:
                    _close_chunk(s, sh, px)
                    exit_reasons.append(reason)
                holdings[s] = new_state["shares"]
                if holdings[s] <= 1e-9:
                    _drop(s)

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
        _close_chunk(s, holdings[s], sym_closes[s][last])
        exit_reasons.append("final")
        _drop(s)
    equity_curve.append(cash)

    return {
        "equity_curve": equity_curve,
        "trade_pnls": trade_pnls,
        "exit_reasons": exit_reasons,
        "signals_per_day": signals_per_day,
        "metrics": metrics.summary(equity_curve, trade_pnls),
    }
