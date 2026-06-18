"""Live passive-core allocation (compute_core_orders): the evidence-mandated
+2.16-Sharpe move. Regime-aware, BUYS ONLY, and HARD-capped strictly under the
12% ETF limit so the hardcoded risk limit is never breached."""
from portfolio_manager import compute_core_orders, core_regime


def test_core_regime_reads_the_correct_signals_key():
    # Audit regression: the live core read "regime" (always None -> BULL), so bear
    # de-risking never fired. It must read "market_regime" (what analyst_v2 writes).
    assert core_regime({"market_regime": "STRONG_BEAR"}) == "STRONG_BEAR"
    assert core_regime({"regime": "STRONG_BEAR"}) == "BULL"   # old buggy key ignored
    assert core_regime({}) == "BULL"
    assert core_regime(None) == "BULL"

LIMITS = {"max_single_position_pct": {"etf": 12.0}, "min_position_notional_usd": 500}
PRICES = {"SPY": 600.0, "QQQ": 500.0, "IWM": 220.0, "DIA": 430.0}
EQ = 100_000.0


def test_off_by_default():
    assert compute_core_orders([], EQ, 50_000, {"core_weight": 0}, "BULL", PRICES, LIMITS) == []
    assert compute_core_orders([], EQ, 50_000, {}, "BULL", PRICES, LIMITS) == []


def test_buys_the_basket_within_the_12pct_cap():
    orders = compute_core_orders([], EQ, EQ, {"core_weight": 0.5}, "BULL", PRICES, LIMITS)
    assert {o["symbol"] for o in orders} == {"SPY", "QQQ", "IWM", "DIA"}
    for o in orders:                                   # never breach the hard 12% ETF cap
        assert o["qty"] * PRICES[o["symbol"]] <= 0.12 * EQ


def test_high_core_weight_still_respects_cap():
    # core_weight 0.9 would imply 22.5%/ETF — must be capped to <12%, not over-concentrate.
    orders = compute_core_orders([], EQ, EQ, {"core_weight": 0.9}, "BULL", PRICES, LIMITS)
    for o in orders:
        assert o["qty"] * PRICES[o["symbol"]] <= 0.12 * EQ


def test_regime_scales_the_core_down_in_bears():
    p = {"core_weight": 0.3}   # below the cap so the regime multiplier is the binding effect
    bull = compute_core_orders([], EQ, EQ, p, "BULL", PRICES, LIMITS)
    bear = compute_core_orders([], EQ, EQ, p, "STRONG_BEAR", PRICES, LIMITS)
    bull_v = sum(o["qty"] * PRICES[o["symbol"]] for o in bull)
    bear_v = sum(o["qty"] * PRICES[o["symbol"]] for o in bear)
    assert bear_v < bull_v                              # less equity core in a bear regime


def test_buys_only_skips_positions_near_target():
    positions = [{"symbol": "SPY", "market_value": 11_200.0}]  # ~ at the ~11.4% target
    orders = compute_core_orders(positions, EQ, EQ, {"core_weight": 0.5}, "BULL", PRICES, LIMITS)
    assert not any(o["symbol"] == "SPY" for o in orders)       # within drift band -> no buy, never sells


def test_gradual_only_spends_available_cash():
    orders = compute_core_orders([], EQ, 5_000.0, {"core_weight": 0.5}, "BULL", PRICES, LIMITS)
    assert sum(o["qty"] * PRICES[o["symbol"]] for o in orders) <= 5_000.0
