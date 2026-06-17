"""Phase-0 fix C7: source real exit prices from broker sell fills so reconciled
closes carry realized P&L instead of pnl=None — the fix that makes P3 (and P2)
strategy edge measurable."""
from shared.accounting import realized_pnl
from shared.reconcile import exit_prices_from_fills, reconcile_log_to_broker


def test_exit_prices_sells_only_most_recent_wins():
    fills = [
        {"side": "buy", "symbol": "AAA", "price": "100", "transaction_time": "2026-06-18T14:00:00Z"},
        {"side": "sell", "symbol": "AAA", "price": "110", "transaction_time": "2026-06-18T15:00:00Z"},
        {"side": "sell", "symbol": "AAA", "price": "108", "transaction_time": "2026-06-18T15:30:00Z"},
        {"side": "sell", "symbol": "BBB", "price": "50", "transaction_time": "2026-06-18T15:00:00Z"},
    ]
    assert exit_prices_from_fills(fills) == {"AAA": 108.0, "BBB": 50.0}


def test_exit_prices_ignores_bad_or_buy_rows():
    bad = [{"side": "sell", "symbol": "X", "price": None},
           {"side": "sell", "price": "5"},          # no symbol
           {"side": "buy", "symbol": "Y", "price": "9"},  # buy
           {}, None, "junk"]
    assert exit_prices_from_fills(bad) == {}
    assert exit_prices_from_fills(None) == {}


def test_reconcile_with_exit_price_yields_genuine_realized_pnl():
    log = [{"symbol": "AAA", "side": "buy", "qty": 10, "entry_price": 100.0, "status": "open"}]
    new_log, actions = reconcile_log_to_broker(
        log, positions=[], exit_prices={"AAA": 110.0},
        pnl_fn=lambda s, q, e, x: realized_pnl(s, q, e, x)["net_pnl"])
    t = new_log[0]
    assert t["status"] == "closed"          # a REAL close, not closed_reconciled
    assert t["exit_price"] == 110.0
    assert t["realized_pnl"] is not None and t["realized_pnl"] > 0   # ~+$100 minus fees


def test_reconcile_without_exit_price_stays_honest_pnl_none():
    log = [{"symbol": "AAA", "side": "buy", "qty": 10, "entry_price": 100.0, "status": "open"}]
    new_log, _ = reconcile_log_to_broker(log, positions=[], exit_prices={})
    assert new_log[0]["status"] == "closed_reconciled"
    assert new_log[0]["realized_pnl"] is None   # never fabricates a result it didn't observe
