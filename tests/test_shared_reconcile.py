"""Tests for the shared reconciliation helpers used by all 3 portfolios."""
from shared.reconcile import compute_drift, working_orders_report


def test_in_sync():
    r = compute_drift(["AAPL", "MSFT"], ["AAPL", "MSFT"])
    assert r["in_sync"] is True
    assert r["orphan_open_trades"] == []
    assert r["unlogged_positions"] == []
    assert r["positions_held"] == 2 and r["open_trades_logged"] == 2


def test_orphan_open_trade():
    r = compute_drift(["AAPL"], ["AAPL", "NVDA"])
    assert r["in_sync"] is False
    assert r["orphan_open_trades"] == ["NVDA"]
    assert r["unlogged_positions"] == []


def test_unlogged_position():
    r = compute_drift(["AAPL", "TSLA"], ["AAPL"])
    assert r["in_sync"] is False
    assert r["unlogged_positions"] == ["TSLA"]


def test_ignores_empty_symbols():
    r = compute_drift(["AAPL", None, ""], ["AAPL", None])
    assert r["positions_held"] == 1 and r["open_trades_logged"] == 1
    assert r["in_sync"] is True


def test_working_orders_report_filters_terminal():
    orders = [
        {"symbol": "T", "side": "buy", "status": "new", "qty": "60"},
        {"symbol": "HD", "side": "buy", "status": "filled", "qty": "3"},
        {"symbol": "PH", "side": "buy", "status": "partially_filled", "qty": "1"},
        {"symbol": "X", "side": "buy", "status": "canceled", "qty": "5"},
    ]
    rep = working_orders_report(orders)
    syms = {o["symbol"] for o in rep["working_orders"]}
    assert syms == {"T", "PH"}  # filled/canceled excluded
    assert rep["working_count"] == 2


def test_working_orders_report_empty():
    assert working_orders_report([])["working_count"] == 0
    assert working_orders_report(None)["working_count"] == 0
