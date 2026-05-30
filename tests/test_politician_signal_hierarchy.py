"""Tests for P2 signal-hierarchy discipline (T9):

Congressional disclosures are delayed (STOCK Act 30-45d) and must be treated as
research-grade context, not fresh alpha. These tests prove the bot (1) rejects
stale disclosures and (2) refuses to copy without technical confirmation.
"""
import os
import sys
from datetime import datetime, timedelta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P2_SCRIPTS = os.path.join(REPO_ROOT, "political-copy-bot", "scripts")
for _p in (REPO_ROOT, P2_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from politician_bot import (  # noqa: E402
    confirm_with_technicals,
    disclosure_age_days,
    is_fresh_enough,
)


def _trade(days_ago):
    d = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return {"dates": {"trade": d}, "issuer": {"ticker": "AAPL"},
            "transaction": {"type": "BUY"}}


# --- Disclosure age ---------------------------------------------------------

def test_disclosure_age_recent():
    assert disclosure_age_days(_trade(10)) in (9, 10, 11)


def test_disclosure_age_unparseable_is_none():
    assert disclosure_age_days({"dates": {"trade": "not-a-date"}}) is None
    assert disclosure_age_days({}) is None


def test_fresh_within_window():
    assert is_fresh_enough(_trade(10), max_age_days=45) is True


def test_stale_beyond_window_rejected():
    assert is_fresh_enough(_trade(75), max_age_days=45) is False


def test_unknown_age_fails_closed():
    assert is_fresh_enough({"dates": {}}, max_age_days=45) is False


def test_future_dated_rejected():
    assert is_fresh_enough(_trade(-5), max_age_days=45) is False


# --- Technical confirmation overlay ----------------------------------------

def test_confirmation_true_on_uptrend():
    closes = [100 + i for i in range(40)]  # steady uptrend, price > MA, +momentum
    assert confirm_with_technicals(closes) is True


def test_confirmation_false_on_downtrend():
    closes = [140 - i for i in range(40)]  # downtrend, price < MA
    assert confirm_with_technicals(closes) is False


def test_confirmation_fails_closed_on_insufficient_data():
    assert confirm_with_technicals([100, 101, 102]) is False
    assert confirm_with_technicals([]) is False


def test_confirmation_false_when_below_ma_despite_recent_bounce():
    # Long decline then a tiny one-bar bounce: still below the 20-day average.
    closes = [200 - i * 2 for i in range(39)] + [130]
    assert confirm_with_technicals(closes) is False
