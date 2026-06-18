"""P3 per-symbol re-entry cooldown (2026-06-18 backtest fix).

The faithful breakout backtest fired only 17 trades and 14 were ONE name (INTC,
bought -> stopped -> rebought repeatedly), turning a deteriorating stock into the
bulk of activity. The cooldown blocks re-entry of a name exited within the window,
capping that single-name churn. It is an additive guardrail and must never relax a
limit (a missing/blank exit timestamp is simply not on cooldown — fail-open).
"""
import os
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P3_SCRIPTS = os.path.join(REPO_ROOT, "event-driven-bot", "scripts")
for _p in (REPO_ROOT, P3_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from event_driven_bot import symbols_on_reentry_cooldown  # noqa: E402

NOW = datetime(2026, 6, 18, 16, 0, tzinfo=timezone.utc)


def _closed(symbol, days_ago):
    return {"symbol": symbol, "status": "closed",
            "exit_timestamp": (NOW - timedelta(days=days_ago)).isoformat()}


def test_recent_exit_is_on_cooldown_old_one_is_not():
    log = [_closed("INTC", 2), _closed("AAPL", 20)]
    on_cd = symbols_on_reentry_cooldown(log, cooldown_days=10, now=NOW)
    assert "INTC" in on_cd        # exited 2d ago -> blocked
    assert "AAPL" not in on_cd    # exited 20d ago -> free to re-enter


def test_disabled_or_zero_cooldown_blocks_nothing():
    log = [_closed("INTC", 1)]
    assert symbols_on_reentry_cooldown(log, cooldown_days=0, now=NOW) == set()
    assert symbols_on_reentry_cooldown(log, cooldown_days=None, now=NOW) == set()


def test_open_trades_and_blank_timestamps_are_ignored_failopen():
    log = [
        {"symbol": "TSLA", "status": "open"},                 # not closed
        {"symbol": "NVDA", "status": "closed", "exit_timestamp": None},  # no exit ts
        {"symbol": "MSFT", "status": "closed_reconciled", "exit_timestamp": ""},
    ]
    assert symbols_on_reentry_cooldown(log, cooldown_days=10, now=NOW) == set()


def test_reconciled_status_with_recent_exit_is_caught():
    log = [{"symbol": "MRVL", "status": "closed_reconciled",
            "exit_timestamp": (NOW - timedelta(days=3)).isoformat()}]
    assert symbols_on_reentry_cooldown(log, cooldown_days=10, now=NOW) == {"MRVL"}
