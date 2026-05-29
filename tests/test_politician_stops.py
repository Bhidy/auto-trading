"""Tests for P2 (politician bot) position-age logic backing the max_hold_days
exit. This exit was previously dead config (max_hold_days read but never used);
these lock in the implemented behavior."""
import os
import sys
import types
from datetime import datetime, timedelta

import pytest

P2_SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "political-copy-bot", "scripts",
)
if P2_SCRIPTS not in sys.path:
    sys.path.insert(0, P2_SCRIPTS)

politician_bot = pytest.importorskip("politician_bot")


def _bot(trade_log):
    bot = politician_bot.PoliticianBot.__new__(politician_bot.PoliticianBot)
    bot.risk = types.SimpleNamespace(trade_log=trade_log)
    return bot


def _iso_days_ago(days):
    return (datetime.now() - timedelta(days=days)).isoformat()


def test_age_uses_oldest_buy():
    bot = _bot([
        {"symbol": "AAPL", "side": "buy", "timestamp": _iso_days_ago(200)},
        {"symbol": "AAPL", "side": "buy", "timestamp": _iso_days_ago(5)},
    ])
    assert bot._position_age_days("AAPL") == 200


def test_age_none_when_no_buy_record():
    bot = _bot([{"symbol": "MSFT", "side": "buy", "timestamp": _iso_days_ago(3)}])
    assert bot._position_age_days("TSLA") is None


def test_age_ignores_sell_records():
    bot = _bot([
        {"symbol": "NVDA", "side": "sell", "timestamp": _iso_days_ago(300)},
        {"symbol": "NVDA", "side": "buy", "timestamp": _iso_days_ago(10)},
    ])
    assert bot._position_age_days("NVDA") == 10


def test_age_handles_malformed_timestamp():
    bot = _bot([
        {"symbol": "GOOG", "side": "buy", "timestamp": "not-a-date"},
        {"symbol": "GOOG", "side": "buy", "timestamp": _iso_days_ago(7)},
    ])
    assert bot._position_age_days("GOOG") == 7


def test_max_hold_threshold_logic():
    # 200d-old position exceeds default 180d max hold; 5d-old does not.
    bot = _bot([
        {"symbol": "OLD", "side": "buy", "timestamp": _iso_days_ago(200)},
        {"symbol": "NEW", "side": "buy", "timestamp": _iso_days_ago(5)},
    ])
    max_hold = 180
    assert bot._position_age_days("OLD") >= max_hold
    assert bot._position_age_days("NEW") < max_hold
