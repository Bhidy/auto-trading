"""Tests for shared.reconcile.fill_reconciliation_report (Phase 1).

Read-only expected-vs-actual FILL reconciliation: joins logged orders to broker
FILL activities on order_id and surfaces slippage outliers + unmatched orders.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.reconcile import fill_reconciliation_report  # noqa: E402


def test_clean_match_within_p90_is_clean():
    log = [{"symbol": "AAPL", "side": "buy", "order_id": "o1",
            "intended_price": 100.0, "entry_price": 100.10}]
    fills = [{"symbol": "AAPL", "side": "buy", "order_id": "o1",
              "qty": 10, "price": 100.10}]  # 10 bps adverse
    rep = fill_reconciliation_report(log, fills, slippage_p90_bps=25.0)
    assert rep["clean"] is True
    assert rep["slippage_outliers"] == []
    assert rep["logged_orders"] == 1 and rep["broker_fill_orders"] == 1


def test_adverse_buy_slippage_beyond_p90_is_flagged():
    log = [{"symbol": "TSLA", "side": "buy", "order_id": "o2",
            "intended_price": 200.0}]
    fills = [{"symbol": "TSLA", "side": "buy", "order_id": "o2",
              "qty": 5, "price": 202.0}]  # 100 bps adverse
    rep = fill_reconciliation_report(log, fills, slippage_p90_bps=25.0)
    assert rep["clean"] is False
    assert len(rep["slippage_outliers"]) == 1
    out = rep["slippage_outliers"][0]
    assert out["order_id"] == "o2"
    assert round(out["slippage_bps"]) == 100


def test_favorable_fill_is_not_flagged():
    # Sell filled ABOVE intended = favorable -> negative adverse bps -> no flag.
    log = [{"symbol": "MSFT", "side": "sell", "order_id": "o3", "intended_price": 300.0}]
    fills = [{"symbol": "MSFT", "side": "sell", "order_id": "o3", "qty": 3, "price": 303.0}]
    rep = fill_reconciliation_report(log, fills, slippage_p90_bps=25.0)
    assert rep["slippage_outliers"] == []


def test_unmatched_logged_order_surfaced():
    log = [{"symbol": "NVDA", "side": "buy", "order_id": "o4",
            "intended_price": 50.0, "status": "open"}]
    rep = fill_reconciliation_report(log, [], slippage_p90_bps=25.0)
    assert rep["clean"] is False
    assert [u["order_id"] for u in rep["unmatched_logged"]] == ["o4"]
    assert rep["unmatched_broker"] == []


def test_unmatched_broker_fill_surfaced():
    fills = [{"symbol": "AMZN", "side": "buy", "order_id": "o5", "qty": 2, "price": 130.0}]
    rep = fill_reconciliation_report([], fills, slippage_p90_bps=25.0)
    assert rep["clean"] is False
    assert [u["order_id"] for u in rep["unmatched_broker"]] == ["o5"]


def test_legacy_entry_without_join_id_is_skipped_not_flagged():
    log = [{"symbol": "OLD", "side": "buy", "entry_price": 10.0}]  # no order_id
    rep = fill_reconciliation_report(log, [], slippage_p90_bps=25.0)
    assert rep["logged_orders"] == 0
    assert rep["unmatched_logged"] == []
    assert rep["clean"] is True


def test_client_order_id_fallback_join():
    log = [{"symbol": "AAPL", "side": "buy", "client_order_id": "c1", "intended_price": 100.0}]
    fills = [{"symbol": "AAPL", "side": "buy", "client_order_id": "c1", "qty": 1, "price": 100.0}]
    rep = fill_reconciliation_report(log, fills, slippage_p90_bps=25.0)
    assert rep["clean"] is True


def test_no_p90_means_no_slippage_gate_only_unmatched():
    # Without a calibrated p90, do not flag slippage (avoid false alarms); still
    # surface unmatched orders.
    log = [{"symbol": "AAPL", "side": "buy", "order_id": "o6", "intended_price": 100.0}]
    fills = [{"symbol": "AAPL", "side": "buy", "order_id": "o6", "qty": 1, "price": 130.0}]
    rep = fill_reconciliation_report(log, fills, slippage_p90_bps=None)
    assert rep["slippage_outliers"] == []
    assert rep["clean"] is True
