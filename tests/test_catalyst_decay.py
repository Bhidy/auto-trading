"""Tests for P3 catalyst-decay time stop (T10).

A news/event trade's edge is the catalyst surprise; held past its short window it
is just unmanaged risk. These tests prove catalyst trades decay (force-exit) on
schedule while core fundamental positions do not.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P3_SCRIPTS = os.path.join(REPO_ROOT, "event-driven-bot", "scripts")
for _p in (REPO_ROOT, P3_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from event_driven_bot import (  # noqa: E402
    catalyst_decayed,
    is_catalyst_trade,
    trade_age_days,
)


def _trade(days_ago, tranche="event_driven", signal="NEWS_BUY"):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {"symbol": "AAPL", "timestamp": ts, "tranche": tranche,
            "signal_type": signal, "status": "open"}


# --- Classification ---------------------------------------------------------

def test_event_tranche_is_catalyst():
    assert is_catalyst_trade(_trade(0)) is True


def test_news_signal_is_catalyst():
    assert is_catalyst_trade({"tranche": "core_swing", "signal": "NEWS_BUY"}) is True


def test_core_fundamental_is_not_catalyst():
    assert is_catalyst_trade({"tranche": "core_swing", "signal": "BREAKOUT"}) is False


# --- Age --------------------------------------------------------------------

def test_trade_age_days():
    assert trade_age_days(_trade(3)) in (2, 3, 4)


def test_trade_age_unparseable():
    assert trade_age_days({"timestamp": "garbage"}) is None
    assert trade_age_days({}) is None


def test_trade_age_from_date_only():
    d = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
    assert trade_age_days({"date": d}) in (4, 5, 6)


# --- Decay ------------------------------------------------------------------

def test_fresh_catalyst_not_decayed():
    assert catalyst_decayed(_trade(0), max_hold_days=2) is False


def test_old_catalyst_is_decayed():
    assert catalyst_decayed(_trade(3), max_hold_days=2) is True


def test_catalyst_decayed_at_exact_window():
    assert catalyst_decayed(_trade(2), max_hold_days=2) is True


def test_core_position_never_decays():
    old_core = _trade(30, tranche="core_swing", signal="BREAKOUT")
    assert catalyst_decayed(old_core, max_hold_days=2) is False


def test_unknown_age_does_not_force_exit():
    bad = {"tranche": "event_driven", "signal_type": "NEWS_BUY",
           "timestamp": "not-a-date", "status": "open"}
    assert catalyst_decayed(bad, max_hold_days=2) is False
