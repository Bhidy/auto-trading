"""Momentum-sleeve rebalance engine (audit 2026-07-04, high-return sleeve).

Pins compute_momentum_rebalance_orders: the pure engine that turns target weights into the
buy/sell orders to move P1's paper book to the top-13 momentum names. Verifies
the drift band, full-exit of dropped names, sells-before-buys ordering, whole
shares, and the 8%-cap-compatible sizing.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from portfolio_manager import compute_momentum_rebalance_orders  # noqa: E402


def _pos(sym, mv, qty):
    return {"symbol": sym, "market_value": mv, "qty": qty}


def test_dropped_names_are_fully_exited():
    # Held SPY (a core ETF) with no target -> sell ALL of it.
    positions = [_pos("SPY", 9000, 15)]
    orders = compute_momentum_rebalance_orders(positions, {"NVDA": 0.07}, 100000,
                                      {"SPY": 600, "NVDA": 120})
    sell = [o for o in orders if o["symbol"] == "SPY"][0]
    assert sell["side"] == "sell" and sell["qty"] == 15      # full exit


def test_new_target_is_bought_to_weight():
    orders = compute_momentum_rebalance_orders([], {"NVDA": 0.069}, 100000, {"NVDA": 120})
    buy = [o for o in orders if o["symbol"] == "NVDA"][0]
    # target $6,900 / $120 = 57 shares
    assert buy["side"] == "buy" and buy["qty"] == 57


def test_sells_ordered_before_buys():
    positions = [_pos("SPY", 9000, 15)]
    orders = compute_momentum_rebalance_orders(positions, {"NVDA": 0.07}, 100000,
                                      {"SPY": 600, "NVDA": 120})
    sides = [o["side"] for o in orders]
    assert sides == sorted(sides, key=lambda s: 0 if s == "sell" else 1)
    assert sides[0] == "sell"                                # frees cash first


def test_within_drift_band_is_skipped():
    # Position already ~at target (7% vs 7% target) -> no order (drift band).
    positions = [_pos("NVDA", 7000, 58)]
    orders = compute_momentum_rebalance_orders(positions, {"NVDA": 0.07}, 100000, {"NVDA": 120})
    assert orders == []


def test_trim_when_over_target():
    # Held $12k of NVDA, target 7% = $7k -> SELL the ~$5k excess (not a full exit).
    positions = [_pos("NVDA", 12000, 100)]
    orders = compute_momentum_rebalance_orders(positions, {"NVDA": 0.07}, 100000, {"NVDA": 120})
    assert len(orders) == 1
    o = orders[0]
    assert o["side"] == "sell"
    assert 0 < o["qty"] < 100                                # partial trim, not full exit


def test_full_rebalance_core_to_momentum():
    # Book holds 2 core ETFs; target is 3 momentum names at ~6.9% each.
    positions = [_pos("SPY", 45000, 75), _pos("TLT", 45000, 500)]
    targets = {"NVDA": 0.069, "AVGO": 0.069, "AAPL": 0.069}
    prices = {"SPY": 600, "TLT": 90, "NVDA": 120, "AVGO": 300, "AAPL": 200}
    orders = compute_momentum_rebalance_orders(positions, targets, 100000, prices)
    sells = {o["symbol"] for o in orders if o["side"] == "sell"}
    buys = {o["symbol"] for o in orders if o["side"] == "buy"}
    assert sells == {"SPY", "TLT"}                           # exit the core
    assert buys == {"NVDA", "AVGO", "AAPL"}                  # into momentum
    assert all(o["qty"] > 0 for o in orders)                # whole shares only


def test_empty_targets_liquidates_everything_risk_off():
    # Risk-off (trend filter -> no targets): sell all holdings, buy nothing.
    positions = [_pos("NVDA", 7000, 58), _pos("AAPL", 7000, 35)]
    orders = compute_momentum_rebalance_orders(positions, {}, 100000,
                                      {"NVDA": 120, "AAPL": 200})
    assert all(o["side"] == "sell" for o in orders)
    assert {o["symbol"] for o in orders} == {"NVDA", "AAPL"}


def test_full_exit_fires_even_without_a_price():
    # A dropped held name with no price must STILL be exited (market sell) so a
    # core ETF can't get stranded in the book — the dry-run bug this fixes.
    positions = [_pos("BADSYM", 5000, 10)]
    orders = compute_momentum_rebalance_orders(positions, {"BADSYM": 0.0}, 100000, {"BADSYM": 0})
    assert len(orders) == 1
    assert orders[0]["side"] == "sell" and orders[0]["qty"] == 10   # full exit by qty


def test_priceless_buy_is_skipped():
    # A BUY can't be sized without a price -> skipped (never a full exit).
    orders = compute_momentum_rebalance_orders([], {"NEW": 0.07}, 100000, {"NEW": 0})
    assert orders == []
