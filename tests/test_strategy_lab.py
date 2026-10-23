"""Engine tests for scripts/research/strategy_lab.py — synthetic, deterministic."""
import os
import sys
from datetime import date, timedelta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from research import strategy_lab as L  # noqa: E402
from backtest.allocators import matf_target_weights  # noqa: E402


def _weekdays(n, start=date(2020, 1, 6)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _flat(syms, n, px=100.0):
    return {s: [px] * n for s in syms}, {s: [px] * n for s in syms}


def _fixed(target):
    def fn(closes, t, params):
        return dict(target)
    return fn


def _run(target_fn, opens, closes, dates, **kw):
    args = dict(schedule="weekly", tranches=1, band=0.0, cost_bps_per_side=0.0, start_index=5)
    args.update(kw)
    return L.run_backtest(dates, opens, closes, target_fn, {}, **args)


def test_snapshot_schedule():
    dates = _weekdays(30)  # starts Monday 2020-01-06
    assert [i for i in range(len(dates)) if L.is_snapshot(dates, i, "weekly")][:3] == [4, 9, 14]
    assert not L.is_snapshot(dates, len(dates) - 1, "weekly")
    m = ["2020-01-30", "2020-01-31", "2020-02-03"]
    assert L.is_snapshot(m, 1, "monthly") and not L.is_snapshot(m, 0, "monthly")


def test_tranching_ramps_in_over_four_weeks():
    dates = _weekdays(40)
    opens, closes = _flat(["A", "BIL"], 40)
    r = _run(_fixed({"A": 0.10}), opens, closes, dates, tranches=4, start_index=5)
    # snapshot at i=4 (Fri) -> trade Monday i=5; the book target is the mean of the last 4
    # snapshots with missing ones = cash, so A is bought in 4 equal 2.5% steps.
    assert r["curve"][-1] == 100000.0
    assert abs(r["max_close_weight"] - 0.10) < 1e-9
    assert r["n_orders"] == 4
    # weight after the first Monday (close of session 5 = curve[1]) is exactly one tranche
    r1 = _run(_fixed({"A": 0.10}), opens, closes, dates[:7], tranches=4, start_index=5)
    assert abs(r1["max_close_weight"] - 0.025) < 1e-9


def test_band_blocks_small_changes_but_not_sell_to_zero():
    dates = _weekdays(30)
    opens, closes = _flat(["A", "B", "BIL"], 30)
    seq = iter([{"A": 0.10, "B": 0.05}, {"A": 0.11, "B": 0.0}, {"A": 0.11, "B": 0.0},
                {"A": 0.11, "B": 0.0}, {"A": 0.11, "B": 0.0}])

    def fn(closes_, t, p):
        return next(seq)

    r = _run(fn, opens, closes, dates, band=0.015)
    # week 1: 2 buys; week 2: A +1% is inside the band (no trade), B 5% -> 0 is a sell to zero
    assert r["n_orders"] == 3


def test_costs_charged_per_side_on_notional():
    dates = _weekdays(12)
    opens, closes = _flat(["A", "BIL"], 12)
    r = _run(_fixed({"A": 0.10}), opens, closes, dates, cost_bps_per_side=10.0, band=0.015)
    assert abs(r["curve"][-1] - (100000.0 - 10000.0 * 0.001)) < 1e-6
    assert r["n_orders"] == 1


def test_cap_drift_guard_trims_next_open():
    dates = _weekdays(12)
    opens, closes = _flat(["A", "BIL"], 12)
    for i in range(6, 12):  # A doubles after Monday's buy (i=5)
        opens["A"][i] = closes["A"][i] = 250.0
    r = _run(_fixed({"A": 0.114}), opens, closes, dates)
    assert r["drift_guard_events"] >= 1
    assert r["max_post_trade_weight"] <= 0.114 + 1e-9


def test_max_twelve_orders_then_queue():
    syms = [f"S{i}" for i in range(14)] + ["BIL"]
    dates = _weekdays(12)
    opens, closes = _flat(syms, 12)
    r = _run(_fixed({s: 0.05 for s in syms[:14]}), opens, closes, dates)
    assert r["n_orders"] == 14 and r["queued_sessions"] == 1


def test_no_leverage_buys_scaled_to_cash():
    syms = [f"S{i}" for i in range(9)] + ["BIL"]
    dates = _weekdays(12)
    opens, closes = _flat(syms, 12)
    r = _run(_fixed({s: 0.114 for s in syms[:9]}), opens, closes, dates, cost_bps_per_side=50.0)
    assert r["avg_cash_weight"] >= -1e-9


def test_engine_no_look_ahead_poisoned_future():
    import math
    n = 420
    dates = _weekdays(n)
    syms = ["SPY", "IWM", "EFA", "EEM", "VNQ", "IEF", "TLT", "TIP", "DBC", "GLD", "BIL", "SHV", "SGOV", "USFR"]
    closes = {}
    for k, s in enumerate(syms):
        closes[s] = [100 * math.exp(0.0003 * i + 0.02 * math.sin(i / (7 + k))) for i in range(n)]
    opens = {s: [v * 0.999 for v in closes[s]] for s in syms}
    start, T = 300, 380
    base = L.run_backtest(dates, opens, closes, matf_target_weights, {}, schedule="weekly", tranches=4,
                          band=0.015, cost_bps_per_side=10.0, start_index=start)
    pc = {s: v[:T + 1] + [v[T] * (5.0 if i % 2 else 0.2) for i in range(n - T - 1)] for s, v in closes.items()}
    po = {s: v[:T + 1] + [v[T] * 7.0 for i in range(n - T - 1)] for s, v in opens.items()}
    pois = L.run_backtest(dates, po, pc, matf_target_weights, {}, schedule="weekly", tranches=4,
                          band=0.015, cost_bps_per_side=10.0, start_index=start)
    k = T - start + 2  # curve[0] = initial, curve[j] = close of session start+j-1
    assert base["curve"][:k] == pois["curve"][:k]
    assert base["curve"][k:] != pois["curve"][k:]


def test_buy_and_hold_and_stats_helpers():
    dates = _weekdays(10)
    opens = {"SPY": [100.0] * 10}
    closes = {"SPY": [100.0 + i for i in range(10)]}
    bh = L.buy_and_hold(dates, opens, closes, "SPY", 1, 10.0)
    assert abs(bh["curve"][1] - 100000 / 1.001 / 100 * 101) < 1e-6
    cal = L.calendar_returns([100, 110, 121], ["2020-12-31", "2021-12-31", "2022-12-30"])
    assert cal["2021"] == 0.1 and cal["2022"] == 0.1
    assert L.expected_max_sharpe([0.01]) == 0.0
    assert L.expected_max_sharpe([0.01, 0.02, 0.03]) > 0
