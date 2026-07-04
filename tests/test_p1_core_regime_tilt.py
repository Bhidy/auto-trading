"""P1 passive-core regime tilt + bucket attribution (audit 2026-07-04, D8/D9).

D8 — the old allocator applied ONE equity_mult to every basket member, so a BULL
regime funded the 4 defensive ETFs (TLT/GLD/SHY/BIL) to the same target as the 4
equity ETFs and the book carried ~45% defensive against a ~20% target. The
class-tilted allocator sizes the equity vs defensive sleeves from a base 80/20
split scaled by the regime's equity_mult/defensive_mult, so BULL trims defensive
toward target while bear regimes raise it.

D9 — every passive-core buy was logged with bucket "core_equity", including the
defensive ETFs, which would poison future by-bucket learning; core orders now
carry asset_class so the runner logs the real bucket.
"""
from portfolio_manager import CORE_DEFENSIVE_SYMBOLS, compute_core_orders, core_class_targets

DEPLOYED_BASKET = ["SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "SHY", "BIL"]
PRICES = {"SPY": 600.0, "QQQ": 500.0, "IWM": 220.0, "DIA": 430.0,
          "TLT": 90.0, "GLD": 380.0, "SHY": 82.0, "BIL": 91.0}
LIMITS = {"max_single_position_pct": {"etf": 12.0}, "min_position_notional_usd": 500}
EQ = 100_000.0
PARAMS = {"core_weight": 1.0, "core_basket": DEPLOYED_BASKET}


def _class_split(targets):
    eq = sum(v for v, c in targets.values() if c == "equity")
    dfn = sum(v for v, c in targets.values() if c == "defensive")
    return eq, dfn, dfn / (eq + dfn)


def test_defensive_symbols_are_classified_as_defensive():
    targets = core_class_targets(DEPLOYED_BASKET, EQ, 1.0, "BULL", PARAMS)
    assert {s for s, (_, c) in targets.items() if c == "defensive"} == {
        "TLT", "GLD", "SHY", "BIL"}
    assert {s for s, (_, c) in targets.items() if c == "equity"} == {
        "SPY", "QQQ", "IWM", "DIA"}
    assert {"TLT", "GLD", "SHY", "BIL"} <= CORE_DEFENSIVE_SYMBOLS


def test_bull_holds_far_less_defensive_than_the_old_uniform_split():
    _, _, def_share = _class_split(
        core_class_targets(DEPLOYED_BASKET, EQ, 1.0, "BULL", PARAMS))
    # Old uniform allocator: 4 of 8 names defensive -> ~50%. Tilted BULL: ~17%.
    assert def_share < 0.25
    assert abs(def_share - 0.167) < 0.02


def test_bear_regime_raises_the_defensive_share():
    _, _, bull = _class_split(core_class_targets(DEPLOYED_BASKET, EQ, 1.0, "BULL", PARAMS))
    _, _, bear = _class_split(
        core_class_targets(DEPLOYED_BASKET, EQ, 1.0, "STRONG_BEAR", PARAMS))
    assert bear > bull
    assert bear > 0.45                         # strong bear tilts firmly defensive


def test_all_equity_basket_has_no_defensive_and_still_scales_by_regime():
    eq_only = ["SPY", "QQQ", "IWM", "DIA"]
    targets = core_class_targets(eq_only, EQ, 0.5, "BULL", PARAMS | {"core_basket": eq_only})
    assert all(c == "equity" for _, c in targets.values())


def test_compute_core_orders_tags_asset_class_and_respects_cap():
    orders = compute_core_orders([], EQ, EQ, PARAMS, "BULL", PRICES, LIMITS)
    by_sym = {o["symbol"]: o for o in orders}
    assert by_sym["TLT"]["asset_class"] == "defensive"
    assert by_sym["SPY"]["asset_class"] == "equity"
    # hard 12% ETF cap is never breached, whatever the tilt
    for o in orders:
        assert o["qty"] * PRICES[o["symbol"]] <= 0.12 * EQ
    # reason string carries the class for the audit trail
    assert "defensive" in by_sym["GLD"]["reason"]
    assert "equity" in by_sym["QQQ"]["reason"]


def test_bull_book_equity_dollars_exceed_defensive_dollars():
    orders = compute_core_orders([], EQ, EQ, PARAMS, "BULL", PRICES, LIMITS)
    eq_v = sum(o["qty"] * PRICES[o["symbol"]] for o in orders if o["asset_class"] == "equity")
    dfn_v = sum(o["qty"] * PRICES[o["symbol"]] for o in orders if o["asset_class"] == "defensive")
    assert eq_v > dfn_v * 2                     # equity clearly dominates in a bull tape
