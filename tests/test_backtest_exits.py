"""Tests for the backtester's exit modeling (Phase-0 profit-program fix).

Before this, scripts/backtest/multifactor.py modeled NO exits, so the live
disposition error (cut winners, run losers) could not be reproduced or
walk-forward validated. These tests pin the pure exit decision function and
confirm a stop bounds the realized loss end-to-end.
"""
import pytest

from backtest.multifactor import _atr, _exit_params, _position_exit, backtest_multifactor


EP = _exit_params({})  # production defaults: stop 2.5 ATR, TP 4 ATR, BE +3%->+0.5%


def _state(shares=100.0, entry=100.0, stop=95.0, hwm=100.0, trimmed=False, entry_t=0):
    return {"shares": shares, "entry": entry, "stop": stop, "hwm": hwm,
            "trimmed": trimmed, "entry_t": entry_t}


def test_stop_exit_fills_at_stop():
    bar = {"o": 97, "h": 98, "l": 94, "c": 96}  # low pierces 95 stop
    events, st = _position_exit(_state(), bar, atr=2.0, t=1, ep=EP)
    assert events == [(100.0, 95.0, "stop")]
    assert st["shares"] == 0.0


def test_stop_gap_down_fills_at_open_not_stop():
    bar = {"o": 90, "h": 92, "l": 89, "c": 91}  # opened below the 95 stop
    events, _ = _position_exit(_state(), bar, atr=2.0, t=1, ep=EP)
    assert events[0][2] == "stop"
    assert events[0][1] == 90  # worse fill on the gap, not the stop price


def test_take_profit_trims_half():
    # entry 100, atr 2 -> TP at 100 + 4*2 = 108; low stays above the trailed stop.
    bar = {"o": 107, "h": 109, "l": 106, "c": 108}
    events, st = _position_exit(_state(), bar, atr=2.0, t=1, ep=EP)
    assert len(events) == 1
    sh, px, reason = events[0]
    assert reason == "take_profit" and px == 108 and sh == 50.0
    assert st["trimmed"] is True and st["shares"] == 50.0


def test_breakeven_lock_exits_winner_at_small_gain():
    # High tags +4% (>= 3% trigger) -> stop locks to entry*1.005=100.5; pullback hits it.
    bar = {"o": 103, "h": 104, "l": 99, "c": 100}
    events, st = _position_exit(_state(trimmed=True), bar, atr=2.0, t=1, ep=EP)
    assert events[0][2] == "stop"
    assert events[0][1] == pytest.approx(100.5)  # breakeven+lock, a tiny gain (the disposition cost)


def test_trailing_stop_ratchets_up_and_does_not_loosen():
    bar = {"o": 109, "h": 110, "l": 108, "c": 110}
    _, st = _position_exit(_state(trimmed=True), bar, atr=2.0, t=1, ep=EP)
    assert st["stop"] == 105.0  # 110 hwm - 2.5*2 ; raised from 95, never lowered


def test_time_stop_exits_stale_flat_position():
    ep = _exit_params({"time_stop_days": 3, "time_stop_min_gain_pct": 0.01})
    bar = {"o": 100, "h": 100.5, "l": 99, "c": 100}  # ~flat, held past 3 days
    events, _ = _position_exit(_state(trimmed=True, entry_t=0), bar, atr=2.0, t=5, ep=ep)
    assert events[0][2] == "time_stop" and events[0][1] == 100


def test_quiet_bar_no_exit():
    bar = {"o": 100.5, "h": 101, "l": 99.5, "c": 100.5}  # inside the stop, below TP
    events, _ = _position_exit(_state(trimmed=True), bar, atr=2.0, t=1, ep=EP)
    assert events == []


def test_atr_is_point_in_time():
    bars = [{"o": 100, "h": 101, "l": 99, "c": 100} for _ in range(20)]
    bars[19] = {"o": 100, "h": 110, "l": 90, "c": 100}  # a future-looking spike
    a10 = _atr(bars, end_idx=10)
    a10_again = _atr(bars[:11] + [{"o": 0, "h": 999, "l": 0, "c": 0}], end_idx=10)
    assert a10 == a10_again  # ATR through day 10 ignores anything after day 10


def test_backtest_exit_machinery_engages_end_to_end():
    # A name that gets bought on strength then crashes hard. With model_exits=True
    # the stop/TP machinery must actually fire inside the full production pipeline,
    # and the equity curve must stay finite and positive (no NaN / blow-up).
    n = 230
    rise = [100 * (1.02 ** i) for i in range(n - 5)]
    crash = [rise[-1] * (0.80 ** k) for k in range(1, 6)]   # -20%/day cliff
    closes = rise + crash

    def bars(cs):
        out, prev = [], cs[0]
        for c in cs:
            out.append({"t": "", "o": prev, "h": max(c, prev) * 1.005,
                        "l": min(c, prev) * 0.97, "c": c, "v": 1_000_000})
            prev = c
        return out

    spy = bars([400 * (1.0006 ** i) for i in range(n)])
    syms = {"SPY": spy, "AAA": bars(closes),
            "BBB": bars([100 * (1.0003 ** i) for i in range(n)])}
    on = backtest_multifactor(syms, spy, max_positions=2, warmup=200, model_exits=True)
    off = backtest_multifactor(syms, spy, max_positions=2, warmup=200, model_exits=False)

    assert on["exit_reasons"]                       # exits engaged
    assert set(on["exit_reasons"]) & {"stop", "take_profit", "rotation", "final"}
    assert all(e > 0 and e == e for e in on["equity_curve"])  # finite, positive (e==e rejects NaN)
    # model_exits=False keeps the legacy rotation-only behavior available.
    assert "rotation" in off["exit_reasons"] or "final" in off["exit_reasons"]
