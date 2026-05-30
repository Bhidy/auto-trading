"""Tests for life-cycle accounting: regulatory fees + corporate actions (C5)."""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.accounting import (  # noqa: E402
    apply_cash_dividend,
    apply_corporate_actions,
    apply_split,
    estimate_regulatory_fees,
    net_proceeds,
    realized_pnl,
    split_realized_unrealized,
)


# --- Regulatory fees --------------------------------------------------------

def test_buy_has_no_sec_or_taf_only_cat():
    f = estimate_regulatory_fees("buy", 100, 50.0)
    assert f["sec_fee"] == 0.0
    assert f["taf"] == 0.0
    assert f["cat_fee"] > 0.0


def test_sell_incurs_sec_and_taf():
    f = estimate_regulatory_fees("sell", 100, 50.0)
    assert f["sec_fee"] > 0.0
    assert f["taf"] > 0.0
    assert f["total"] >= f["sec_fee"] + f["taf"]


def test_taf_is_capped():
    huge = estimate_regulatory_fees("sell", 10_000_000, 50.0)
    assert huge["taf"] == 8.30  # cap enforced


def test_short_side_treated_as_sell_for_fees():
    f = estimate_regulatory_fees("short", 100, 50.0)
    assert f["sec_fee"] > 0.0


# --- Net proceeds -----------------------------------------------------------

def test_buy_cash_out_includes_fees():
    # 1000 shares so the sub-cent CAT fee rounds to a visible amount.
    cash, fees = net_proceeds("buy", 1000, 100.0)
    assert cash < 0  # cash leaves the account
    assert abs(cash) > 100_000.0  # notional 100k + fees
    assert fees > 0


def test_sell_cash_in_net_of_fees():
    cash, fees = net_proceeds("sell", 1000, 100.0)
    assert cash > 0
    assert cash < 100_000.0  # less than notional after fees
    assert fees > 0


# --- Realized P&L net of fees ----------------------------------------------

def test_realized_pnl_long_net_less_than_gross():
    r = realized_pnl("buy", 100, 100.0, 110.0)
    assert r["gross_pnl"] == 1000.0
    assert r["fees"] > 0
    assert r["net_pnl"] < r["gross_pnl"]


def test_realized_pnl_short_direction():
    # Short entry at 110, cover at 100 => +10/share gross.
    r = realized_pnl("short", 100, 110.0, 100.0)
    assert r["gross_pnl"] == 1000.0
    assert r["net_pnl"] < 1000.0


def test_realized_pnl_can_exclude_fees():
    r = realized_pnl("buy", 100, 100.0, 110.0, include_fees=False)
    assert r["fees"] == 0.0
    assert r["net_pnl"] == r["gross_pnl"]


# --- Corporate actions ------------------------------------------------------

def test_forward_split_preserves_cost_basis():
    new_qty, new_avg = apply_split(10, 200.0, 2, 1)  # 2:1 forward
    assert new_qty == 20
    assert new_avg == 100.0
    assert new_qty * new_avg == 10 * 200.0  # basis preserved


def test_reverse_split_preserves_cost_basis():
    new_qty, new_avg = apply_split(100, 5.0, 1, 10)  # 1:10 reverse
    assert new_qty == 10
    assert new_avg == 50.0
    assert new_qty * new_avg == 100 * 5.0


def test_invalid_split_raises():
    import pytest
    with pytest.raises(ValueError):
        apply_split(10, 100.0, 0, 1)


def test_cash_dividend():
    assert apply_cash_dividend(100, 0.25) == 25.0


def test_apply_corporate_actions_sequence():
    pos = {"qty": 10, "avg_price": 200.0}
    actions = [
        {"type": "split", "numerator": 2, "denominator": 1},
        {"type": "dividend", "amount_per_share": 0.50},
    ]
    out = apply_corporate_actions(pos, actions)
    assert out["qty"] == 20
    assert out["avg_price"] == 100.0
    assert out["cash"] == 10.0  # 20 shares * $0.50 after split
    assert len(out["applied"]) == 2


# --- Realized vs unrealized -------------------------------------------------

def test_split_realized_unrealized():
    closed = [
        {"side": "buy", "qty": 100, "entry_price": 100.0, "exit_price": 110.0},
        {"side": "buy", "qty": 50, "entry_price": 200.0, "exit_price": 190.0},
    ]
    openp = [
        {"symbol": "AAPL", "qty": 25, "avg_price": 300.0, "current_price": 310.0,
         "side": "long"},
    ]
    out = split_realized_unrealized(closed, openp)
    # realized gross: +1000 -500 = +500 (minus fees)
    assert out["realized_pnl"] < 500.0
    assert out["realized_pnl"] > 400.0
    # unrealized: 25 * (310-300) = 250
    assert out["unrealized_pnl"] == 250.0
    assert out["total_pnl"] == round(out["realized_pnl"] + out["unrealized_pnl"], 2)


def test_unrealized_short_direction():
    openp = [{"symbol": "X", "qty": 10, "avg_price": 100.0, "current_price": 90.0,
              "side": "short"}]
    out = split_realized_unrealized([], openp)
    # short profits when price falls: (100-90)*10 = +100
    assert out["unrealized_pnl"] == 100.0
