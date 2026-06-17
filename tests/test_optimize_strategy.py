"""Tests for the offline strategy optimizer (the profit-lever harness): it searches
entry/exit config on real bars and only emits a CANDIDATE (never auto-deploys).
These cover the pure search grid + the candidate evaluator shape."""
import math

from research.optimize_strategy import SEARCH, evaluate, grid


def _bars(closes):
    out, prev = [], closes[0]
    for c in closes:
        out.append({"t": "", "o": prev, "h": max(c, prev) * 1.002,
                    "l": min(c, prev) * 0.998, "c": c, "v": 1_000_000})
        prev = c
    return out


def _universe(n=260):
    spy = [400 * (1.0006 ** i) for i in range(n)]
    syms = {
        "SPY": _bars(spy),
        "AAA": _bars([100 * (1.0012 ** i) for i in range(n)]),
        "BBB": _bars([100 * (1.0004 ** i) for i in range(n)]),
        "CCC": _bars([100 + 6 * math.sin(i / 8) for i in range(n)]),
    }
    return syms, syms["SPY"]


def test_grid_covers_every_knob_combination():
    g = grid()
    expected = 1
    for v in SEARCH.values():
        expected *= len(v)
    assert len(g) == expected
    assert all(set(d.keys()) == set(SEARCH.keys()) for d in g)


def test_evaluate_returns_oos_and_full_metrics():
    syms, spy = _universe()
    res = evaluate(syms, spy, baseline={}, delta={"time_stop_days": 7})
    for k in ("oos_sharpe", "full_sharpe", "full_return", "n_trades", "n_windows"):
        assert k in res
    assert res["delta"] == {"time_stop_days": 7}


def test_evaluate_is_deterministic():
    syms, spy = _universe()
    a = evaluate(syms, spy, {}, {"trailing_stop_atr_mult": 1.8})
    b = evaluate(syms, spy, {}, {"trailing_stop_atr_mult": 1.8})
    assert a["oos_sharpe"] == b["oos_sharpe"] and a["full_sharpe"] == b["full_sharpe"]
