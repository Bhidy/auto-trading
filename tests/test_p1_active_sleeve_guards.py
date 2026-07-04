"""P1 active-sleeve exit guards + regime brake (audit 2026-07-04, chief-expert
recs #2 and #3). Both are risk-REDUCING and dormant while the active satellite
is disabled; these pin the behavior for when it is re-enabled.

Rec #2 — the satellite's 0.42 win/loss ratio came from losers riding to
-5..-10.8% over 4-15 days. A hard per-trade max-loss exit and a loser time-stop
cap that, scoped to ACTIVE positions only so the passive core (which is
rebalanced, never stop-managed) is never force-sold.

Rec #3 — the engine bought high-beta into the 6/4-6/10 selloff because SPY-only
regime detection lagged. A regime brake blocks new LONG entries when the
short-horizon market is adverse.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from portfolio_manager import (  # noqa: E402
    active_sleeve_exit_triggers, regime_gate_active_entries)

NOW = datetime(2026, 6, 20, 16, 0, tzinfo=timezone.utc)


def _stop(sym, pnl, side="long", current=100.0):
    return {sym: {"side": side, "current": current, "unrealized_pnl_pct": pnl}}


def _open(sym, days_ago=1, order_class="active"):
    return {"symbol": sym, "status": "open", "order_class": order_class,
            "timestamp": (NOW - timedelta(days=days_ago)).isoformat()}


# --------------------------------------------------------------------------
# Rec #2 — hard max-loss + loser time-stop, active-scoped
# --------------------------------------------------------------------------

def test_hard_max_loss_exits_active_loser():
    trig = active_sleeve_exit_triggers(_stop("TSLA", -4.5), [_open("TSLA", 2)], now=NOW)
    assert len(trig) == 1
    assert trig[0]["action"] == "HARD_STOP_SELL"


def test_loser_time_stop_exits_underwater_after_threshold():
    trig = active_sleeve_exit_triggers(_stop("AMZN", -2.0), [_open("AMZN", 5)],
                                       time_stop_days=4, now=NOW)
    assert len(trig) == 1 and trig[0]["action"] == "TIME_STOP_SELL"


def test_passive_core_is_never_force_sold():
    # A core ETF at -6% and held 30d must NOT trigger — it is rebalanced, not
    # stop-managed. This is the safety invariant.
    trig = active_sleeve_exit_triggers(
        _stop("TLT", -6.0), [_open("TLT", 30, order_class="passive_core")], now=NOW)
    assert trig == []


def test_young_small_loser_is_left_alone():
    trig = active_sleeve_exit_triggers(_stop("META", -1.0), [_open("META", 1)],
                                       max_loss_pct=4.0, time_stop_days=4, now=NOW)
    assert trig == []                                   # -1%, 1 day: neither gate


def test_winner_is_never_time_stopped():
    trig = active_sleeve_exit_triggers(_stop("NVDA", 3.0), [_open("NVDA", 10)],
                                       time_stop_days=4, now=NOW)
    assert trig == []                                   # up 3% -> not underwater


def test_position_without_open_lot_is_skipped():
    trig = active_sleeve_exit_triggers(_stop("XYZ", -9.0), [], now=NOW)
    assert trig == []                                   # unattributed -> not touched


def test_max_loss_takes_precedence_over_time_stop():
    trig = active_sleeve_exit_triggers(_stop("F", -5.0), [_open("F", 10)], now=NOW)
    assert len(trig) == 1 and trig[0]["action"] == "HARD_STOP_SELL"


def test_unparseable_timestamp_fails_open():
    bad = {"symbol": "GE", "status": "open", "order_class": "active",
           "timestamp": "not-a-date"}
    trig = active_sleeve_exit_triggers(_stop("GE", -2.0), [bad], time_stop_days=4, now=NOW)
    assert trig == []                                   # unknown age never exits


# --------------------------------------------------------------------------
# Rec #3 — regime brake on new active LONG entries
# --------------------------------------------------------------------------

BUYS = [{"symbol": "NVDA", "signal": "BUY"}, {"symbol": "AMZN", "signal": "BUY"}]
MIXED = BUYS + [{"symbol": "TLT", "signal": "SHORT"}, {"symbol": "AAPL", "signal": "SELL"}]


def test_bull_regime_passes_entries_through():
    kept, blocked = regime_gate_active_entries(BUYS, {"market_regime": "BULL"})
    assert kept == BUYS and blocked == []


def test_bear_regime_blocks_new_longs_keeps_exits_and_shorts():
    kept, blocked = regime_gate_active_entries(MIXED, {"market_regime": "STRONG_BEAR"})
    assert {o["symbol"] for o in blocked} == {"NVDA", "AMZN"}      # longs blocked
    assert {o["symbol"] for o in kept} == {"TLT", "AAPL"}         # short + exit survive


def test_adverse_short_horizon_spy_momentum_blocks_longs_even_in_bull():
    sig = {"market_regime": "BULL",
           "signals": [{"symbol": "SPY", "momentum": {"5d": -3.5}}]}
    kept, blocked = regime_gate_active_entries(BUYS, sig)
    assert {o["symbol"] for o in blocked} == {"NVDA", "AMZN"}     # SPY -3.5% 5d < -2% floor


def test_mild_spy_pullback_does_not_block():
    sig = {"market_regime": "BULL",
           "signals": [{"symbol": "SPY", "momentum": {"5d": -1.0}}]}
    kept, blocked = regime_gate_active_entries(BUYS, sig)
    assert blocked == []                                # -1% > -2% floor -> fine
