"""Tests for shared.sizing — the canonical, unit-safe position-sizing module.

These lock the 2026-06-01 incident: an inline risk-parity formula in analyst_v2
carried a stray `* 100`, making every suggested size 100x too small (0.11%
instead of 11%). The risk officer then computed qty=0 and the executor silently
skipped every order — a run "succeeded" while placing nothing. The fix
centralizes the math in shared/sizing.py; these tests are what keep it correct
forever.
"""
import pytest

from shared.sizing import (
    MAX_WEIGHT_PCT,
    meets_min_notional,
    position_add_room_qty,
    realized_risk_pct,
    shares_for_dollar_risk,
    volatility_position_pct,
)


# --- The exact regression: sizing must never be 100x too small --------------

def test_regression_never_100x_too_small():
    """NVDA-like ($220, ATR $8, 2.5x stop, 1% target) -> ~11%, NOT ~0.11%."""
    pct = volatility_position_pct(8.0, 220.0, 1.0, 2.5)
    assert pct == pytest.approx(11.0, abs=0.5)   # correct risk-parity weight
    assert pct > 1.0                             # the bug produced 0.11 — guard the decade


# --- Golden values (hand-computed: weight = target * price / (atr * stop)) --

@pytest.mark.parametrize("atr, price, target, stop, expected", [
    (8.0, 220.0, 1.0, 2.5, 11.0),    # 220 / 20
    (5.0, 50.0, 1.0, 3.0, 3.33),     # 50 / 15
    (4.0, 120.0, 1.0, 2.5, 12.0),    # 120 / 10 — exactly at the cap boundary
    (2.0, 100.0, 1.0, 2.0, 12.0),    # 100 / 4 = 25 -> capped to 12
    (10.0, 200.0, 2.0, 2.0, 12.0),   # 400 / 20 = 20 -> capped to 12
])
def test_golden_weights(atr, price, target, stop, expected):
    assert volatility_position_pct(atr, price, target, stop) == pytest.approx(expected, abs=0.01)


def test_hard_cap_default_is_12():
    # Very low volatility wants a huge weight; the hard cap binds at 12%.
    assert volatility_position_pct(0.5, 100.0, 1.0, 2.0) == MAX_WEIGHT_PCT


def test_size_multiplier_scales_then_caps():
    base = volatility_position_pct(8.0, 220.0, 1.0, 2.5)            # 11.0
    assert volatility_position_pct(8.0, 220.0, 1.0, 2.5, size_mult=0.5) == pytest.approx(base * 0.5, abs=0.05)
    # 11 * 1.5 = 16.5 -> capped to 12
    assert volatility_position_pct(8.0, 220.0, 1.0, 2.5, size_mult=1.5) == MAX_WEIGHT_PCT


def test_explicit_hard_cap_override():
    assert volatility_position_pct(8.0, 220.0, 1.0, 2.5, hard_cap_pct=8.0) == 8.0


# --- Degenerate inputs return 0.0 ("no trade"), never a bogus size ----------

@pytest.mark.parametrize("kwargs", [
    dict(atr=0.0, price=100.0, atr_risk_target_pct=1.0, stop_atr_mult=2.0),
    dict(atr=8.0, price=0.0, atr_risk_target_pct=1.0, stop_atr_mult=2.0),
    dict(atr=8.0, price=100.0, atr_risk_target_pct=0.0, stop_atr_mult=2.0),
    dict(atr=8.0, price=100.0, atr_risk_target_pct=1.0, stop_atr_mult=0.0),
    dict(atr=8.0, price=100.0, atr_risk_target_pct=1.0, stop_atr_mult=2.0, size_mult=0.0),
    dict(atr=None, price=100.0, atr_risk_target_pct=1.0, stop_atr_mult=2.0),
    dict(atr="x", price=100.0, atr_risk_target_pct=1.0, stop_atr_mult=2.0),
    dict(atr=-8.0, price=100.0, atr_risk_target_pct=1.0, stop_atr_mult=2.0),
])
def test_degenerate_inputs_return_zero(kwargs):
    assert volatility_position_pct(**kwargs) == 0.0


# --- The true invariant: realized dollar-risk == target (off cap), and never
# exceeds it (on cap). "Risk parity" *means* this; the *100 bug violated it. ---

def test_realized_risk_equals_target_off_cap_and_underrisks_on_cap():
    for target in (0.5, 1.0, 2.0):
        for atr in (1.0, 4.0, 8.0, 15.0):
            for price in (20.0, 100.0, 220.0, 600.0):
                for stop in (1.5, 2.0, 2.5, 3.0):
                    pct = volatility_position_pct(atr, price, target, stop)
                    if pct == 0.0:
                        continue
                    realized = realized_risk_pct(pct, atr, price, stop)
                    # Branch on the math (uncapped weight), not the rounded pct,
                    # to avoid boundary flakiness near the 12% cap.
                    uncapped = target * price / (atr * stop)
                    if uncapped <= MAX_WEIGHT_PCT - 0.05:        # safely off cap
                        assert realized == pytest.approx(target, abs=0.05)
                    elif uncapped >= MAX_WEIGHT_PCT + 0.05:      # safely capped
                        assert pct == MAX_WEIGHT_PCT
                        assert realized <= target + 1e-6         # under-risk, never over
                    # Universal guarantee: risk parity never over-risks the budget.
                    assert realized <= target + 0.05


# --- realized_risk_pct + shares_for_dollar_risk -----------------------------

def test_realized_risk_zero_on_degenerate():
    assert realized_risk_pct(11.0, 0.0, 220.0, 2.5) == 0.0
    assert realized_risk_pct(11.0, 8.0, 0.0, 2.5) == 0.0


def test_shares_for_dollar_risk_golden():
    # (100k equity, 1% budget, ATR 8, 2.5x stop): $1000 risk / $20 per-share = 50.
    assert shares_for_dollar_risk(100_000, 1.0, 8.0, 2.5) == 50
    assert shares_for_dollar_risk(100_000, 1.0, 2.0, 2.0) == 250


@pytest.mark.parametrize("args", [
    (0.0, 1.0, 8.0, 2.5),
    (100_000, 0.0, 8.0, 2.5),
    (100_000, 1.0, 0.0, 2.5),
    (100_000, 1.0, 8.0, 0.0),
])
def test_shares_for_dollar_risk_zero_on_degenerate(args):
    assert shares_for_dollar_risk(*args) == 0


def test_percent_and_dollar_models_agree_off_cap():
    """The %-of-equity model and the $-risk model must yield the same dollars
    when the cap doesn't bind — they are two views of one risk-parity rule."""
    equity, target, atr, price, stop = 100_000.0, 1.0, 8.0, 220.0, 2.5
    pct = volatility_position_pct(atr, price, target, stop)     # 11.0 (off cap)
    dollars_from_pct = equity * pct / 100.0
    shares = shares_for_dollar_risk(equity, target, atr, stop)
    dollars_from_shares = shares * price
    assert dollars_from_pct == pytest.approx(dollars_from_shares, rel=0.02)


# --- position_add_room_qty: enforce single-position cap on PROPOSED total ----
# Locks the 2026-06-02 finding: the executor capped the NEW order to max_pct but
# didn't subtract the existing holding, so an add could land at ~2x the cap.

def test_add_room_caps_to_remaining_headroom():
    # Hold $6,000 (6%) of a $100/sh name on $100k equity, 8% cap -> $2,000 room
    # = 20 shares. An "8% order" (80 sh) must be capped to 20.
    assert position_add_room_qty(6_000, 100.0, 100_000, 8.0) == 20


def test_add_room_zero_when_already_at_cap():
    assert position_add_room_qty(8_000, 100.0, 100_000, 8.0) == 0
    assert position_add_room_qty(9_500, 100.0, 100_000, 8.0) == 0  # over cap -> 0


def test_add_room_full_cap_when_nothing_held():
    # No existing position -> full 8% = $8,000 = 80 shares.
    assert position_add_room_qty(0, 100.0, 100_000, 8.0) == 80


def test_add_room_fractional_for_crypto():
    # Crypto sizes fractionally: $5,000 held, 10% cap on $100k -> $5,000 room.
    qty = position_add_room_qty(5_000, 40_000.0, 100_000, 10.0, fractional=True)
    assert qty == pytest.approx(5_000 / 40_000.0, rel=1e-6)  # 0.125 BTC, not int(0)=0


@pytest.mark.parametrize("args", [
    (6_000, 0.0, 100_000, 8.0),      # price <= 0
    (6_000, 100.0, 0.0, 8.0),        # equity <= 0
    (6_000, 100.0, 100_000, 0.0),    # cap <= 0
    (None, 100.0, 100_000, 8.0),     # non-numeric
])
def test_add_room_zero_on_degenerate(args):
    assert position_add_room_qty(*args) == 0


# --- meets_min_notional: stop capital-starved stub orders --------------------
# Locks the 2026-06-02 stub: P1 had $80 cash, placed 3 shares of XLE ($184) and
# called it a position. The floor turns that into a clean skip.

def test_min_notional_passes_above_floor():
    assert meets_min_notional(10, 100.0, floor_usd=500) is True   # $1,000 >= $500


def test_min_notional_blocks_the_xle_stub():
    # 3 shares * $61.29 = ~$184 — the actual stub that shipped. Must be rejected.
    assert meets_min_notional(3, 61.29, floor_usd=500) is False


def test_min_notional_scales_with_equity():
    # floor = max($500, 0.5% of equity). On a $1M book that is $5,000.
    assert meets_min_notional(20, 100.0, floor_usd=500, equity=1_000_000, floor_pct=0.5) is False  # $2k < $5k
    assert meets_min_notional(60, 100.0, floor_usd=500, equity=1_000_000, floor_pct=0.5) is True   # $6k >= $5k


def test_min_notional_no_floor_allows_anything_positive():
    assert meets_min_notional(1, 1.0) is True


@pytest.mark.parametrize("qty, price", [(0, 100.0), (-1, 100.0), (5, 0.0), (None, 100.0), (5, "x")])
def test_min_notional_false_on_degenerate(qty, price):
    assert meets_min_notional(qty, price, floor_usd=500) is False
