"""Tests for P2 signal-hierarchy discipline (T9):

Congressional disclosures are delayed (STOCK Act 30-45d) and must be treated as
research-grade context, not fresh alpha. These tests prove the bot (1) rejects
stale disclosures and (2) refuses to copy without technical confirmation.
"""
import os
import sys
from datetime import datetime, timedelta

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P2_SCRIPTS = os.path.join(REPO_ROOT, "political-copy-bot", "scripts")
for _p in (REPO_ROOT, P2_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from politician_bot import (  # noqa: E402
    _DISCLOSURE_DATE_FORMATS,
    PoliticianBot,
    _parse_date,
    confirm_with_technicals,
    disclosure_age_days,
    is_fresh_enough,
)


def _trade(days_ago, fmt="%Y-%m-%d"):
    d = (datetime.now() - timedelta(days=days_ago)).strftime(fmt)
    return {"dates": {"trade": d}, "issuer": {"ticker": "AAPL"},
            "transaction": {"type": "BUY"}}


# --- Disclosure age ---------------------------------------------------------

def test_disclosure_age_recent():
    assert disclosure_age_days(_trade(10)) in (9, 10, 11)


def test_disclosure_age_unparseable_is_none():
    assert disclosure_age_days({"dates": {"trade": "not-a-date"}}) is None
    assert disclosure_age_days({}) is None


# --- REGRESSION (2026-06-02): the Capitol Trades feed emits the transaction date
# as "8 May2026", NOT ISO. The T9 freshness gate parsed only ISO, so EVERY
# disclosure failed closed as "stale" and P2 idled ~$90K for days. These tests
# lock every format the live feed has been observed to emit. -------------------

def test_parse_real_capitol_trades_format_8may2026():
    # The exact literal strings seen in processed_trades.json on 2026-06-02.
    assert _parse_date("8 May2026") == datetime(2026, 5, 8)
    assert _parse_date("11 May2026") == datetime(2026, 5, 11)
    assert _parse_date("15 May2026") == datetime(2026, 5, 15)


@pytest.mark.parametrize("fmt", _DISCLOSURE_DATE_FORMATS + ("%Y-%m-%d",))
def test_disclosure_age_parses_every_supported_format(fmt):
    # A 10-day-old disclosure in EVERY supported format must yield a real age,
    # never None (which would silently fail the freshness gate closed).
    age = disclosure_age_days(_trade(10, fmt))
    assert age is not None, f"format {fmt!r} regressed to unparseable"
    assert age in (9, 10, 11)


@pytest.mark.parametrize("fmt", _DISCLOSURE_DATE_FORMATS)
def test_fresh_within_window_non_iso_formats(fmt):
    assert is_fresh_enough(_trade(10, fmt), max_age_days=45) is True


def test_iso_with_time_component_still_parses():
    assert _parse_date("2026-05-15T09:30:00Z") == datetime(2026, 5, 15)


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


# --- Blinded-feed detection: an UNPARSEABLE date must be counted separately from
# a genuinely STALE one, so a feed format drift screams instead of hiding. ------

class _StubBot:
    """Minimal object to exercise PoliticianBot._is_copyable_trade in isolation
    (no broker/config/network), to assert the unparseable-vs-stale bookkeeping."""
    def __init__(self):
        self.watchlist_cfg = {"copy_filters": {"transaction_types": ["BUY"]}}
        self._freshness_evaluated = 0
        self._unparseable_dates = 0

    def _max_disclosure_age(self):
        return 45


def test_unparseable_date_counted_not_treated_as_stale():
    stub = _StubBot()
    bad = {"dates": {"trade": "totally-not-a-date"}, "issuer": {"ticker": "AAPL"},
           "transaction": {"type": "BUY"}}
    assert PoliticianBot._is_copyable_trade(stub, bad) is False
    assert stub._freshness_evaluated == 1
    assert stub._unparseable_dates == 1  # the LOUD path, not a silent stale-skip


def test_genuinely_stale_date_not_counted_as_unparseable():
    stub = _StubBot()
    old = _trade(120)  # parseable, but far beyond the 45d window
    assert PoliticianBot._is_copyable_trade(stub, old) is False
    assert stub._freshness_evaluated == 1
    assert stub._unparseable_dates == 0  # parseable -> stale, NOT a feed problem


def test_fresh_real_format_disclosure_is_copyable():
    stub = _StubBot()
    fresh = _trade(10, "%d %b%Y")  # the real Capitol Trades format, recent
    assert PoliticianBot._is_copyable_trade(stub, fresh) is True
    assert stub._unparseable_dates == 0
