"""Tests for the shared reconciliation helpers used by all 3 portfolios."""
from shared.reconcile import (compute_drift, working_orders_report,
                              reconcile_log_to_broker, is_open_trade)


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


# --- Audit-trail repair: reconcile_log_to_broker ----------------------------

def _is_in_sync(log, positions):
    """Re-audit a repaired log the way the bots do (default-open predicate)."""
    open_trades = [t for t in log if is_open_trade(t) and t.get("symbol")]
    return compute_drift(
        [p["symbol"] for p in positions],
        [t["symbol"] for t in open_trades],
        positions=positions, open_trades=open_trades,
    )["in_sync"]


def test_is_open_trade_predicate():
    assert is_open_trade({}) is True                      # P3 legacy: no status
    assert is_open_trade({"status": "open"}) is True
    assert is_open_trade({"status": "closed"}) is False
    assert is_open_trade({"status": "closed_reconciled"}) is False


def test_repair_closes_orphan_without_exit_no_fabricated_pnl():
    log = [{"id": 1, "symbol": "OXY", "side": "buy", "qty": 10,
            "entry_price": 50.0, "status": "open"}]
    new, actions = reconcile_log_to_broker(log, [])  # broker holds nothing
    assert [a["action"] for a in actions] == ["close_orphan"]
    t = new[0]
    assert t["status"] == "closed_reconciled"   # distinct -> excluded from metrics
    assert t["pnl"] is None and t["exit_price"] is None
    assert t["reconciled"] is True
    assert _is_in_sync(new, [])


def test_repair_closes_orphan_with_real_exit_recovers_pnl():
    log = [{"id": 1, "symbol": "OXY", "side": "buy", "qty": 10,
            "entry_price": 50.0, "status": "open"}]
    new, _ = reconcile_log_to_broker(
        log, [], exit_prices={"OXY": 55.0},
        pnl_fn=lambda side, qty, entry, ex: (ex - entry) * qty)
    t = new[0]
    assert t["status"] == "closed"          # genuine close, counts in stats
    assert t["exit_price"] == 55.0
    assert t["pnl"] == 50.0                  # (55-50)*10
    assert t["pnl_pct"] == 10.0


def test_repair_trims_double_logged_lots_to_broker_qty():
    # Broker holds 2 QQQ; log double-logged 6 across two lots (the P1 qty_drift).
    log = [
        {"id": 1, "symbol": "QQQ", "side": "buy", "qty": 2, "entry_price": 700.0,
         "status": "open"},
        {"id": 2, "symbol": "QQQ", "side": "buy", "qty": 4, "entry_price": 710.0,
         "status": "open"},
    ]
    positions = [{"symbol": "QQQ", "qty": "2", "avg_entry_price": "700.0"}]
    new, actions = reconcile_log_to_broker(log, positions)
    assert any(a["action"] == "trim_qty" and a["symbol"] == "QQQ" for a in actions)
    open_qty = sum(t["qty"] for t in new if is_open_trade(t) and t["symbol"] == "QQQ")
    assert abs(open_qty - 2.0) < 1e-6
    assert _is_in_sync(new, positions)       # qty AND cost-basis reconciled


def test_repair_adds_unlogged_position():
    log = []
    positions = [{"symbol": "XLK", "qty": "30", "avg_entry_price": "250.0"}]
    new, actions = reconcile_log_to_broker(log, positions)
    assert [a["action"] for a in actions] == ["add_unlogged"]
    lot = new[-1]
    assert lot["symbol"] == "XLK" and lot["qty"] == 30.0
    assert lot["entry_price"] == 250.0 and lot["status"] == "open"
    assert lot["reconciled"] is True
    assert _is_in_sync(new, positions)


def test_repair_adds_missing_qty_when_broker_holds_more():
    log = [{"id": 1, "symbol": "AAPL", "side": "buy", "qty": 10,
            "entry_price": 300.0, "status": "open"}]
    positions = [{"symbol": "AAPL", "qty": "25", "avg_entry_price": "300.0"}]
    new, actions = reconcile_log_to_broker(log, positions)
    assert any(a["action"] == "add_qty" for a in actions)
    open_qty = sum(t["qty"] for t in new if is_open_trade(t) and t["symbol"] == "AAPL")
    assert abs(open_qty - 25.0) < 1e-6
    assert _is_in_sync(new, positions)


def test_repair_is_idempotent():
    log = [
        {"id": 1, "symbol": "OXY", "side": "buy", "qty": 10, "entry_price": 50.0,
         "status": "open"},
        {"id": 2, "symbol": "QQQ", "side": "buy", "qty": 6, "entry_price": 700.0,
         "status": "open"},
    ]
    positions = [{"symbol": "QQQ", "qty": "2", "avg_entry_price": "700.0"}]
    new, actions1 = reconcile_log_to_broker(log, positions)
    assert actions1 and _is_in_sync(new, positions)
    new2, actions2 = reconcile_log_to_broker(new, positions)
    assert actions2 == []                    # second pass finds nothing to do
    assert _is_in_sync(new2, positions)


def test_repair_p3_style_log_no_status_no_id():
    # P3 entries carry no 'status' and no 'id'; closed brackets lingered as orphans.
    log = [
        {"symbol": "CSCO", "side": "buy", "qty": 26, "entry_price": 126.0,
         "order_status": "filled"},   # broker no longer holds -> orphan
        {"symbol": "VLO", "side": "buy", "qty": 10, "entry_price": 260.0,
         "order_status": "filled"},   # still held
    ]
    positions = [{"symbol": "VLO", "qty": "10", "avg_entry_price": "260.0"}]
    new, actions = reconcile_log_to_broker(log, positions)
    csco = next(t for t in new if t["symbol"] == "CSCO")
    assert csco["status"] == "closed_reconciled"   # P3's first-ever close path
    assert "id" not in csco                         # no id convention introduced
    assert _is_in_sync(new, positions)


def test_repair_p1_style_assigns_ids_to_appended_lots():
    log = [{"id": 1, "symbol": "AAPL", "side": "buy", "qty": 10,
            "entry_price": 300.0, "status": "open"}]
    positions = [
        {"symbol": "AAPL", "qty": "10", "avg_entry_price": "300.0"},
        {"symbol": "XLK", "qty": "5", "avg_entry_price": "250.0"},  # unlogged
    ]
    new, _ = reconcile_log_to_broker(log, positions)
    xlk = next(t for t in new if t["symbol"] == "XLK")
    assert isinstance(xlk["id"], int) and xlk["id"] == 2   # next id after 1


def test_repair_noop_when_already_in_sync():
    log = [{"id": 1, "symbol": "AAPL", "side": "buy", "qty": 25,
            "entry_price": 310.0, "status": "open"}]
    positions = [{"symbol": "AAPL", "qty": "25", "avg_entry_price": "310.0"}]
    new, actions = reconcile_log_to_broker(log, positions)
    assert actions == []
    assert new == log
