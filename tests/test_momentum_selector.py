"""Concentrated-momentum selector (audit 2026-07-04, high-return research).

Pins the reusable engine for the proposed high-return PAPER sleeve: 12-1 momentum
scoring, top-K selection, the 8%-cap guarantee (effective K >= 13), determinism,
and the optional market-trend gate.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from momentum_selector import (  # noqa: E402
    market_trend_ok, momentum_score, select_top_momentum)


def _ramp(start, step, n):
    return [start + step * i for i in range(n)]


def test_momentum_score_positive_uptrend():
    closes = _ramp(100, 1, 300)                 # steady rise
    s = momentum_score(closes)
    assert s is not None and s > 0


def test_momentum_score_none_when_insufficient_history():
    assert momentum_score(_ramp(100, 1, 50)) is None
    assert momentum_score([]) is None


def test_momentum_score_skips_recent_month():
    # A pure spike in the last few days must NOT dominate (skip=21 excludes it).
    base = _ramp(100, 0.1, 300)
    spiked = base[:-3] + [900, 950, 1000]
    # score uses close[-1-21]; the spike is inside the skipped window -> ignored
    assert abs(momentum_score(spiked) - momentum_score(base)) < 1e-9


def test_select_respects_8pct_cap_even_if_fewer_requested():
    # Ask for top 5, but the 8% cap forces >=13 names at <=8% each.
    data = {f"S{i}": _ramp(100, i + 1, 300) for i in range(30)}
    w = select_top_momentum(data, k=5, max_weight=0.08)
    assert len(w) >= 13
    assert all(v <= 0.08 + 1e-9 for v in w.values())
    assert abs(sum(w.values()) - 1.0) < 0.02      # ~fully invested


def test_select_picks_highest_momentum_names():
    # S29 has the steepest ramp -> highest momentum -> must be selected.
    data = {f"S{i:02d}": _ramp(100, i + 1, 300) for i in range(30)}
    w = select_top_momentum(data, k=13)
    ranked = sorted(w, reverse=True)
    assert "S29" in w and "S28" in w             # top momentum names present
    assert "S00" not in w                         # weakest excluded


def test_select_is_deterministic_on_ties():
    data = {f"T{i}": _ramp(100, 1, 300) for i in range(20)}  # identical momentum
    w1 = select_top_momentum(data, k=13)
    w2 = select_top_momentum(data, k=13)
    assert w1 == w2                               # tie-break by symbol -> stable


def test_exclude_drops_symbols():
    data = {f"S{i:02d}": _ramp(100, i + 1, 300) for i in range(30)}
    w = select_top_momentum(data, k=13, exclude={"S29", "S28"})
    assert "S29" not in w and "S28" not in w


def test_trend_gate_goes_to_cash_when_market_below_sma():
    data = {f"S{i}": _ramp(100, i + 1, 300) for i in range(30)}
    downtrend = _ramp(300, -0.5, 250)             # falling -> below its SMA
    w = select_top_momentum(data, use_trend=True, market_closes=downtrend)
    assert w == {}                                # risk-off: hold nothing here


def test_trend_gate_invests_when_market_above_sma():
    data = {f"S{i}": _ramp(100, i + 1, 300) for i in range(30)}
    uptrend = _ramp(100, 1, 250)                  # rising -> above its SMA
    w = select_top_momentum(data, use_trend=True, market_closes=uptrend)
    assert len(w) >= 13


def test_market_trend_ok_helper():
    assert market_trend_ok(_ramp(100, 1, 250)) is True
    assert market_trend_ok(_ramp(300, -1, 250)) is False
    assert market_trend_ok([], n=200) is True     # no data -> fail-open
