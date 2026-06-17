"""Tests for the advisory event-context consumer + offline builder (Phase 4)."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.event_context import adverse_entry_flags, load_event_context  # noqa: E402
from research.build_event_context import (  # noqa: E402
    build_context, corporate_action_flags, liquidity_rank, news_recency,
)

NOW = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)


# --- consumer (fail-open) -------------------------------------------------

def test_missing_artifact_is_empty(tmp_path):
    assert load_event_context(str(tmp_path)) == {}


def test_malformed_artifact_is_empty(tmp_path):
    (tmp_path / "event_context.json").write_text("{nope")
    assert load_event_context(str(tmp_path)) == {}


def test_fresh_artifact_loads(tmp_path):
    (tmp_path / "event_context.json").write_text(json.dumps({"as_of": NOW.isoformat(), "liquidity": {}}))
    assert load_event_context(str(tmp_path), now=NOW) != {}


def test_stale_artifact_fails_open(tmp_path):
    old = (NOW - timedelta(hours=72)).isoformat()
    (tmp_path / "event_context.json").write_text(json.dumps({"as_of": old, "liquidity": {"X": {}}}))
    assert load_event_context(str(tmp_path), max_age_hours=36, now=NOW) == {}


def test_adverse_entry_flags():
    ctx = {
        "corporate_actions": {"AAA": {"type": "dividend", "days_until": 2}},
        "liquidity": {"BBB": {"rank_pct": 0.1}, "CCC": {"rank_pct": 0.9}},
    }
    assert adverse_entry_flags("AAA", ctx)            # ex-div proximity
    assert adverse_entry_flags("BBB", ctx)            # thin liquidity
    assert adverse_entry_flags("CCC", ctx) == []      # deep liquidity, no flag
    assert adverse_entry_flags("ZZZ", ctx) == []      # unknown symbol


# --- builder transforms (pure) --------------------------------------------

def test_corporate_action_flags_within_window():
    actions = [
        {"symbol": "AAA", "type": "dividend", "ex_date": (NOW + timedelta(days=2)).date().isoformat()},
        {"symbol": "BBB", "type": "split", "ex_date": (NOW + timedelta(days=30)).date().isoformat()},
    ]
    flags = corporate_action_flags(actions, NOW, within_days=5)
    assert "AAA" in flags and 1 <= flags["AAA"]["days_until"] <= 2  # ~2d (day-floored)
    assert "BBB" not in flags  # outside window


def test_liquidity_rank_orders_thin_to_deep():
    rank = liquidity_rank([
        {"symbol": "THIN", "volume": 1000},
        {"symbol": "MID", "volume": 50000},
        {"symbol": "DEEP", "volume": 999999},
    ])
    assert rank["THIN"]["rank_pct"] == 0.0
    assert rank["DEEP"]["rank_pct"] == 1.0
    assert rank["THIN"]["rank_pct"] < rank["MID"]["rank_pct"] < rank["DEEP"]["rank_pct"]


def test_news_recency_filters_old():
    news = [
        {"symbols": ["AAA"], "headline": "fresh", "created_at": (NOW - timedelta(hours=2)).isoformat()},
        {"symbols": ["BBB"], "headline": "old", "created_at": (NOW - timedelta(hours=200)).isoformat()},
    ]
    out = news_recency(news, NOW, within_hours=48)
    assert "AAA" in out and "BBB" not in out


def test_build_context_shape():
    ctx = build_context([], [], [], NOW)
    assert ctx["as_of"] == NOW.isoformat()
    assert set(ctx) >= {"as_of", "corporate_actions", "liquidity", "news", "disclosure"}
