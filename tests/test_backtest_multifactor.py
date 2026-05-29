"""Tests for the full multi-factor backtester + walk-forward gate.

These reuse the production scoring pipeline, so they double as a regression
guard that detect_regime / rank_by_relative_strength / analyze_symbol_v2 stay
backtest-compatible.
"""
import math

import pytest

from backtest.multifactor import backtest_multifactor
from backtest import walk_forward as wf


def _bars(closes):
    bars, prev = [], closes[0]
    for c in closes:
        bars.append({"t": "", "o": prev, "h": max(c, prev) * 1.001,
                     "l": min(c, prev) * 0.999, "c": c, "v": 1_000_000})
        prev = c
    return bars


def _dated_bars(closes, start="2025-01-01"):
    import datetime
    bars = _bars(closes)
    d = datetime.date.fromisoformat(start)
    for b in bars:
        b["t"] = d.isoformat() + "T00:00:00Z"
        d += datetime.timedelta(days=1)
    return bars


def _universe(n=260):
    # SPY uptrend + a few names with varied trends so RS ranking has signal.
    spy = [400 * (1.0007 ** i) for i in range(n)]
    syms = {
        "SPY": _bars(spy),
        "AAA": _bars([100 * (1.0015 ** i) for i in range(n)]),       # strong uptrend
        "BBB": _bars([100 * (1.0005 ** i) for i in range(n)]),       # mild uptrend
        "CCC": _bars([100 * (0.999 ** i) for i in range(n)]),        # downtrend
        "DDD": _bars([100 + 8 * math.sin(i / 9) for i in range(n)]), # choppy
    }
    return syms, syms["SPY"]


def test_multifactor_runs_and_reports_metrics():
    syms, spy = _universe()
    res = backtest_multifactor(syms, spy, max_positions=2, warmup=200)
    assert len(res["equity_curve"]) > 2
    for k in ("sharpe", "sortino", "max_drawdown", "cagr"):
        assert k in res["metrics"]
    assert res["equity_curve"][0] == 100000.0


def test_multifactor_rejects_misaligned_bars():
    syms, spy = _universe()
    syms["AAA"] = syms["AAA"][:-5]  # shorter than SPY
    with pytest.raises(ValueError):
        backtest_multifactor(syms, spy, warmup=200)


def test_multifactor_no_lookahead():
    # Equity path before a future divergence must be identical whether or not
    # bars after that point change.
    syms, spy = _universe(240)
    syms2 = {s: [dict(b) for b in bars] for s, bars in syms.items()}
    for s in syms2:
        for b in syms2[s][210:]:
            b["c"] *= 1.4
            b["o"] *= 1.4
    r1 = backtest_multifactor(syms, syms["SPY"], max_positions=2, warmup=200)
    r2 = backtest_multifactor(syms2, syms2["SPY"], max_positions=2, warmup=200)
    # Curves should match up to the point before divergence (index ~9 into the
    # post-warmup curve, well before bar 210).
    for a, b in zip(r1["equity_curve"][:9], r2["equity_curve"][:9]):
        assert abs(a - b) < 1e-6


def test_walk_forward_aggregates_windows():
    syms, spy = _universe(400)
    out = wf.walk_forward(syms, spy, params={}, test_days=50, warmup=150, max_positions=2)
    assert out["aggregate"] is not None
    assert out["aggregate"]["n_windows"] >= 2
    assert "mean_sharpe" in out["aggregate"]


def test_gate_fails_closed_on_insufficient_data():
    # Too little history -> cannot validate -> not approved.
    syms, spy = _universe(120)
    approved, detail = wf.gate_param_change({}, {"confidence_buy_threshold": 0.4},
                                            syms, spy, test_days=50, warmup=150)
    assert approved is False


def test_gate_approves_equal_params():
    # Identical params -> candidate Sharpe == current -> approved (within margin).
    syms, spy = _universe(400)
    p = {"confidence_buy_threshold": 0.5}
    approved, detail = wf.gate_param_change(p, dict(p), syms, spy,
                                            test_days=50, warmup=150, max_positions=2)
    assert approved is True
    assert detail["candidate_oos_sharpe"] == detail["current_oos_sharpe"]


def test_load_aligned_bars_from_cache(tmp_path):
    import json
    # Two bucket files sharing a date axis with SPY.
    core = {"bars": {"SPY": _dated_bars([400 + i for i in range(80)]),
                     "QQQ": _dated_bars([350 + i for i in range(80)])}}
    growth = {"bars": {"AAA": _dated_bars([100 + i for i in range(80)])}}
    (tmp_path / "core_equity.json").write_text(json.dumps(core))
    (tmp_path / "aggressive_growth.json").write_text(json.dumps(growth))
    # A state file that must be ignored.
    (tmp_path / "signals.json").write_text(json.dumps({"signals": []}))

    symbol_bars, spy_bars = wf.load_aligned_bars(str(tmp_path), min_coverage=0.9)
    assert spy_bars is not None
    assert "SPY" in symbol_bars and "AAA" in symbol_bars
    lengths = {len(v) for v in symbol_bars.values()} | {len(spy_bars)}
    assert len(lengths) == 1  # all aligned to one common axis
