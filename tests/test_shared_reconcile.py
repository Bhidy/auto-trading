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


# --- C6: quantity + cost-basis drift ---------------------------------------

def test_detailed_in_sync_qty_and_cost_basis():
    positions = [{"symbol": "AAPL", "qty": "25", "avg_entry_price": "310.58"}]
    open_trades = [{"symbol": "AAPL", "qty": 25, "entry_price": 310.58,
                    "status": "open"}]
    r = compute_drift(["AAPL"], ["AAPL"], positions=positions, open_trades=open_trades)
    assert r["in_sync"] is True
    assert r["qty_drift"] == []
    assert r["cost_basis_drift"] == []


def test_quantity_drift_detected():
    """Broker holds 25 but the log only recorded 20 (a partial fill not logged)."""
    positions = [{"symbol": "AAPL", "qty": "25", "avg_entry_price": "310.58"}]
    open_trades = [{"symbol": "AAPL", "qty": 20, "entry_price": 310.58,
                    "status": "open"}]
    r = compute_drift(["AAPL"], ["AAPL"], positions=positions, open_trades=open_trades)
    assert r["in_sync"] is False
    assert len(r["qty_drift"]) == 1
    assert r["qty_drift"][0]["symbol"] == "AAPL"
    assert r["qty_drift"][0]["broker_qty"] == 25.0
    assert r["qty_drift"][0]["logged_qty"] == 20.0


def test_cost_basis_drift_detected():
    """Broker avg 330 vs logged 310 — e.g. a missed split or wrong fill price."""
    positions = [{"symbol": "AAPL", "qty": "25", "avg_entry_price": "330.00"}]
    open_trades = [{"symbol": "AAPL", "qty": 25, "entry_price": 310.00,
                    "status": "open"}]
    r = compute_drift(["AAPL"], ["AAPL"], positions=positions, open_trades=open_trades)
    assert r["in_sync"] is False
    assert len(r["cost_basis_drift"]) == 1
    assert r["cost_basis_drift"][0]["symbol"] == "AAPL"
    assert r["cost_basis_drift"][0]["drift_pct"] > 1.0


def test_cost_basis_small_diff_within_tolerance():
    positions = [{"symbol": "AAPL", "qty": "25", "avg_entry_price": "310.80"}]
    open_trades = [{"symbol": "AAPL", "qty": 25, "entry_price": 310.58,
                    "status": "open"}]
    r = compute_drift(["AAPL"], ["AAPL"], positions=positions, open_trades=open_trades)
    assert r["cost_basis_drift"] == []  # < 1% drift ignored
    assert r["in_sync"] is True


def test_qty_weighted_avg_across_multiple_open_trades():
    """Two entries averaged; broker avg matches the qty-weighted blend."""
    positions = [{"symbol": "NVDA", "qty": "30", "avg_entry_price": "210.00"}]
    open_trades = [
        {"symbol": "NVDA", "qty": 10, "entry_price": 200.00, "status": "open"},
        {"symbol": "NVDA", "qty": 20, "entry_price": 215.00, "status": "open"},
    ]
    # weighted avg = (10*200 + 20*215)/30 = 210.0
    r = compute_drift(["NVDA"], ["NVDA"], positions=positions, open_trades=open_trades)
    assert r["qty_drift"] == []
    assert r["cost_basis_drift"] == []
    assert r["in_sync"] is True


def test_legacy_symbol_only_call_unchanged():
    """Existing 2-arg callers keep working and get empty drift lists."""
    r = compute_drift(["AAPL"], ["AAPL"])
    assert r["in_sync"] is True
    assert r["qty_drift"] == []
    assert r["cost_basis_drift"] == []
