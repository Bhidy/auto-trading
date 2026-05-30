"""Tests for the order-state reconciler (C2).

Proves partial fills, late fills, cancels, rejections, and replaces all produce
explicit events so no order sits in an unknown state across a monitor cycle.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.order_state import (  # noqa: E402
    prune_terminal,
    reconcile_and_persist,
    reconcile_orders,
    stale_working_orders,
)


def _order(oid, status, filled_qty="0", qty="100", symbol="AAPL",
           filled_avg_price=None, updated_at=None):
    return {"id": oid, "client_order_id": f"c-{oid}", "symbol": symbol,
            "side": "buy", "qty": qty, "filled_qty": filled_qty,
            "status": status, "filled_avg_price": filled_avg_price,
            "updated_at": updated_at}


# --- New / fill / partial ---------------------------------------------------

def test_new_order_emits_new_event():
    state, events = reconcile_orders({}, [_order("o1", "new")])
    assert any(e["type"] == "new" and e["order_id"] == "o1" for e in events)
    assert state["o1"]["status"] == "new"


def test_partial_fill_emits_partial_event_with_delta():
    prior, _ = reconcile_orders({}, [_order("o1", "new")])
    state, events = reconcile_orders(prior, [
        _order("o1", "partially_filled", filled_qty="40")])
    pf = [e for e in events if e["type"] == "partial_fill"]
    assert len(pf) == 1
    assert pf[0]["delta_qty"] == 40.0
    assert state["o1"]["status"] == "partially_filled"


def test_progressive_partials_only_count_delta():
    s0, _ = reconcile_orders({}, [_order("o1", "partially_filled", filled_qty="40")])
    s1, events = reconcile_orders(s0, [
        _order("o1", "partially_filled", filled_qty="70")])
    pf = [e for e in events if e["type"] == "partial_fill"]
    assert pf[0]["delta_qty"] == 30.0  # 70 - 40, not 70


def test_full_fill_emits_fill_event():
    prior, _ = reconcile_orders({}, [_order("o1", "partially_filled", filled_qty="40")])
    _, events = reconcile_orders(prior, [
        _order("o1", "filled", filled_qty="100", filled_avg_price="150.25")])
    fills = [e for e in events if e["type"] == "fill"]
    assert len(fills) == 1
    assert fills[0]["delta_qty"] == 60.0
    assert fills[0]["filled_avg_price"] == "150.25"


def test_late_fill_without_qty_delta_still_emits_fill():
    """Status catches up to 'filled' even if filled_qty was already current."""
    prior = {"o1": {"id": "o1", "symbol": "AAPL", "side": "buy",
                    "status": "partially_filled", "filled_qty": "100"}}
    _, events = reconcile_orders(prior, [
        _order("o1", "filled", filled_qty="100", filled_avg_price="10")])
    assert any(e["type"] == "fill" for e in events)


# --- Terminal transitions ---------------------------------------------------

def test_cancel_emits_event():
    prior, _ = reconcile_orders({}, [_order("o1", "new")])
    _, events = reconcile_orders(prior, [_order("o1", "canceled")])
    assert any(e["type"] == "canceled" for e in events)


def test_reject_emits_event():
    prior, _ = reconcile_orders({}, [_order("o1", "new")])
    _, events = reconcile_orders(prior, [_order("o1", "rejected")])
    assert any(e["type"] == "rejected" for e in events)


def test_replaced_emits_event():
    prior, _ = reconcile_orders({}, [_order("o1", "new")])
    _, events = reconcile_orders(prior, [_order("o1", "replaced")])
    assert any(e["type"] == "replaced" for e in events)


def test_order_without_id_ignored():
    state, events = reconcile_orders({}, [{"status": "new"}])
    assert state == {} and events == []


# --- Stale working orders ---------------------------------------------------

def test_stale_working_orders_flagged():
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    state = {"o1": {"symbol": "AAPL", "status": "new", "updated_at": old}}
    stale = stale_working_orders(state, max_age_s=7200)
    assert len(stale) == 1 and stale[0]["order_id"] == "o1"


def test_recent_working_order_not_flagged():
    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    state = {"o1": {"symbol": "AAPL", "status": "new", "updated_at": recent}}
    assert stale_working_orders(state, max_age_s=7200) == []


def test_filled_order_not_considered_stale():
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    state = {"o1": {"symbol": "AAPL", "status": "filled", "updated_at": old}}
    assert stale_working_orders(state, max_age_s=7200) == []


# --- Prune + persist --------------------------------------------------------

def test_prune_drops_terminal_keeps_working():
    state = {
        "o1": {"status": "filled"},
        "o2": {"status": "new"},
        "o3": {"status": "partially_filled"},
    }
    pruned = prune_terminal(state)
    assert set(pruned) == {"o2", "o3"}


def test_reconcile_and_persist_roundtrip(tmp_path):
    path = os.path.join(str(tmp_path), "order_state.json")
    events = reconcile_and_persist(path, [_order("o1", "new")])
    assert any(e["type"] == "new" for e in events)
    # Second run: o1 fills -> fill event, terminal pruned from persisted state.
    events2 = reconcile_and_persist(path, [
        _order("o1", "filled", filled_qty="100", filled_avg_price="10")])
    assert any(e["type"] == "fill" for e in events2)
    import json
    with open(path) as f:
        persisted = json.load(f)
    assert "o1" not in persisted  # terminal pruned
