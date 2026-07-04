"""Trade-log P&L integrity (audit 2026-07-04, defects D2/D4/D5).

Three data-truth bugs poisoned self-evaluation:
  * D4 — P2 logged its stop/TP/copy sells as bare ``side: "sell"`` rows; the
    reconciler treated them as open SHORT lots and booked (entry - exit) x qty,
    sign-flipping every winner (TER's ~+$662 exit logged as a loss) and
    double-counting the same exit.
  * D2 — P3's orphan-reconciled closes carried pnl=None (log said -$6,183
    realized vs broker truth ≈ -$195) and exit_reason=None on 30/30 closes.
  * D5 — P1's close_trade() had no reason parameter, so exit attribution was
    lost on 59/61 closes.

These tests pin the fixes: the sell-marker predicate, exit-reason plumbing
through reconciliation, broker-order exit classification, P2's FIFO lot
closing, and the backfill script's FIFO engine (broker-vs-log regression).
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P2_SCRIPTS = os.path.join(REPO_ROOT, "political-copy-bot", "scripts")
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts"), P2_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.accounting import realized_pnl  # noqa: E402
from shared.reconcile import (exit_reasons_from_orders, guarded_pnl_fn,  # noqa: E402
                              is_open_trade, reconcile_log_to_broker)
from rebuild_closed_pnl_from_broker import fifo_closures  # noqa: E402


# --------------------------------------------------------------------------
# D4: bare sell rows are exit markers, never open (short) lots
# --------------------------------------------------------------------------

def test_bare_sell_row_is_not_an_open_lot():
    assert is_open_trade({"symbol": "TER", "side": "sell", "qty": 2}) is False


def test_statusless_buy_row_is_still_open_p3_legacy():
    assert is_open_trade({"symbol": "JPM", "side": "buy", "qty": 5}) is True
    assert is_open_trade({"symbol": "JPM", "qty": 5}) is True  # no side field


def test_explicit_open_short_is_still_open():
    # Genuine short entries always carry an explicit status (P1 convention).
    assert is_open_trade({"symbol": "X", "side": "sell", "status": "open"}) is True


def test_exit_marker_rows_are_never_open():
    assert is_open_trade({"symbol": "X", "side": "sell", "status": "exit_marker"}) is False


def test_reconciler_no_longer_books_short_math_on_sell_markers():
    """The exact TER shape: a winning long whose exit-sell was logged as a bare
    sell row. Before the fix the sell row was closed as a short at a LOSS."""
    log = [
        {"symbol": "TER", "side": "buy", "qty": 7, "entry_price": 368.88,
         "status": "open"},
        {"symbol": "TER", "side": "sell", "qty": 7,
         "reason": "Take profit at 25.0%"},        # bare marker, no status
    ]
    repaired, actions = reconcile_log_to_broker(
        log, [],                                    # broker no longer holds TER
        exit_prices={"TER": 466.74},
        pnl_fn=guarded_pnl_fn(realized_pnl),
        exit_reasons={"TER": "take_profit"},
    )
    closes = [t for t in repaired if t.get("status") == "closed"]
    assert len(closes) == 1                        # ONLY the buy lot closed
    buy = closes[0]
    assert buy["side"] == "buy"
    assert buy["pnl"] > 600                        # long math: real winner
    assert buy["exit_reason"] == "take_profit"
    # the marker row was not turned into a closed short
    marker = [t for t in repaired if t.get("side") == "sell"][0]
    assert marker.get("status") != "closed"
    assert marker.get("pnl") is None


# --------------------------------------------------------------------------
# D2: exit-reason attribution from broker order types
# --------------------------------------------------------------------------

def test_exit_reasons_from_orders_classifies_bracket_legs():
    orders = [
        {"symbol": "MRVL", "side": "sell", "status": "filled", "type": "stop",
         "filled_qty": "10", "filled_at": "2026-06-17T15:00:00Z"},
        {"symbol": "MPC", "side": "sell", "status": "filled", "type": "limit",
         "filled_qty": "20", "filled_at": "2026-07-02T15:00:00Z"},
        {"symbol": "OXY", "side": "sell", "status": "filled", "type": "market",
         "filled_qty": "30", "filled_at": "2026-06-20T15:00:00Z"},
        {"symbol": "ZZZ", "side": "sell", "status": "canceled", "type": "limit",
         "filled_qty": "0", "filled_at": ""},              # never filled: ignored
        {"symbol": "MRVL", "side": "buy", "status": "filled", "type": "market",
         "filled_qty": "10", "filled_at": "2026-06-16T15:00:00Z"},  # buys ignored
    ]
    reasons = exit_reasons_from_orders(orders)
    assert reasons == {"MRVL": "stop_loss", "MPC": "take_profit",
                       "OXY": "market_exit"}


def test_exit_reasons_most_recent_sell_wins():
    orders = [
        {"symbol": "MU", "side": "sell", "status": "filled", "type": "stop",
         "filled_qty": "5", "filled_at": "2026-06-05T15:00:00Z"},
        {"symbol": "MU", "side": "sell", "status": "filled", "type": "limit",
         "filled_qty": "5", "filled_at": "2026-06-15T15:00:00Z"},
    ]
    assert exit_reasons_from_orders(orders) == {"MU": "take_profit"}


def test_reconciled_close_without_real_exit_stays_unattributed():
    log = [{"symbol": "GONE", "side": "buy", "qty": 3, "entry_price": 100.0,
            "status": "open"}]
    repaired, _ = reconcile_log_to_broker(
        log, [], exit_reasons={"GONE": "take_profit"})  # reason but NO price
    t = repaired[0]
    assert t["status"] == "closed_reconciled"
    assert t["pnl"] is None
    assert "exit_reason" not in t   # never attribute without a real exit


# --------------------------------------------------------------------------
# D4: P2 RiskManager.apply_exit — FIFO long closes at the real fill
# --------------------------------------------------------------------------

def _risk_manager(tmp_path, rows):
    import json
    from politician_bot import RiskManager
    limits = tmp_path / "limits.json"
    limits.write_text(json.dumps({"max_daily_trades": 10}))
    tl = tmp_path / "trade_log.json"
    tl.write_text(json.dumps(rows))
    return RiskManager(limits, tl)


def test_apply_exit_closes_buy_lot_with_long_math(tmp_path):
    rm = _risk_manager(tmp_path, [
        {"symbol": "TER", "side": "buy", "qty": 7, "entry_price": 368.88,
         "status": "open"},
    ])
    closed = rm.apply_exit("TER", 7, 466.74, reason="take_profit")
    assert closed == 7
    lot = rm.trade_log[0]
    assert lot["status"] == "closed"
    assert lot["exit_reason"] == "take_profit"
    assert lot["pnl"] > 600     # (466.74 - 368.88) * 7 minus fees


def test_apply_exit_partial_splits_lot(tmp_path):
    rm = _risk_manager(tmp_path, [
        {"symbol": "MEDP", "side": "buy", "qty": 3, "entry_price": 448.17,
         "status": "open"},
    ])
    closed = rm.apply_exit("MEDP", 2, 561.00, reason="take_profit")
    assert closed == 2
    open_lots = [t for t in rm.trade_log if t.get("status") == "open"]
    closed_lots = [t for t in rm.trade_log if t.get("status") == "closed"]
    assert len(open_lots) == 1 and float(open_lots[0]["qty"]) == 1
    assert len(closed_lots) == 1 and float(closed_lots[0]["qty"]) == 2
    assert closed_lots[0]["pnl"] > 200


def test_apply_exit_never_touches_sell_markers_or_fabricates(tmp_path):
    rm = _risk_manager(tmp_path, [
        {"symbol": "PG", "side": "sell", "qty": 5},                  # marker
        {"symbol": "PG", "side": "buy", "qty": 5, "status": "open"},  # no basis
    ])
    closed = rm.apply_exit("PG", 5, 160.0, reason="copy_sell")
    assert closed == 5
    marker, lot = rm.trade_log[0], rm.trade_log[1]
    assert "status" not in marker or marker.get("status") != "closed"
    assert lot["status"] == "closed"
    assert lot["pnl"] is None    # no cost basis -> honest None, never invented


# --------------------------------------------------------------------------
# D2: backfill FIFO engine — broker fills -> round-trip closures
# --------------------------------------------------------------------------

def test_fifo_closures_long_roundtrip_sign_and_reason():
    fills = [
        {"symbol": "MU", "side": "buy", "qty": 10, "price": 100.0,
         "time": "2026-06-01T14:00:00Z", "type": "market"},
        {"symbol": "MU", "side": "sell", "qty": 10, "price": 110.0,
         "time": "2026-06-10T14:00:00Z", "type": "limit"},
    ]
    closures, unmatched, open_lots = fifo_closures(fills)
    assert not unmatched and not open_lots
    c = closures["MU"][0]
    assert c["qty"] == 10 and c["exit_reason"] == "take_profit"
    assert realized_pnl("buy", c["qty"], c["entry_price"],
                        c["exit_price"])["net_pnl"] > 90   # a WIN stays a win


def test_fifo_closures_partial_sell_leaves_open_lot():
    fills = [
        {"symbol": "MEDP", "side": "buy", "qty": 3, "price": 448.17,
         "time": "2026-05-29T14:00:00Z", "type": "limit"},
        {"symbol": "MEDP", "side": "sell", "qty": 2, "price": 561.0,
         "time": "2026-07-02T14:00:00Z", "type": "limit"},
    ]
    closures, unmatched, open_lots = fifo_closures(fills)
    assert sum(c["qty"] for c in closures["MEDP"]) == 2
    assert open_lots == {"MEDP": 1}   # broker still holds 1 -> phantom-close guard
