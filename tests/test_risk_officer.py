"""Risk Officer validation tests.

These directly cover the bug class that silently broke P1 trading on
2026-05-29: validate_trade() indexing signal["indicators"]["price"] before
guarding signal type, crashing the entire session on an INSUFFICIENT_DATA
signal that carries no "indicators" key.
"""
import pytest

import risk_officer as ro


def _buy(symbol="SPY", price=500.0, itype="etf", pct=5.0):
    return {
        "symbol": symbol,
        "signal": "BUY",
        "instrument_type": itype,
        "indicators": {"price": price, "avg_volume_20d": 50_000_000},
        "risk_management": {"suggested_position_pct": pct, "stop_loss": price * 0.95,
                            "take_profit": price * 1.1},
    }


# --- The regression that broke production -----------------------------------

def test_insufficient_data_signal_does_not_crash(limits, portfolio):
    """The exact analyst output (analyst_v2.py:219) — no 'indicators' key."""
    sig = {"symbol": "NEWX", "signal": "INSUFFICIENT_DATA", "reason": "Only 12 bars"}
    result = ro.validate_trade(sig, portfolio, limits)
    assert result["approved"] is False
    assert "INSUFFICIENT_DATA" in result["rejections"][0]


def test_hold_signal_rejected_cleanly(limits, portfolio):
    sig = {"symbol": "AAPL", "signal": "HOLD"}
    result = ro.validate_trade(sig, portfolio, limits)
    assert result["approved"] is False


def test_buy_with_missing_indicators_rejected_not_crash(limits, portfolio):
    sig = {"symbol": "FOO", "signal": "BUY"}  # actionable but no price
    result = ro.validate_trade(sig, portfolio, limits)
    assert result["approved"] is False
    assert "price" in result["rejections"][0].lower()


def test_buy_with_zero_price_rejected(limits, portfolio):
    sig = _buy(price=0.0)
    result = ro.validate_trade(sig, portfolio, limits)
    assert result["approved"] is False


# --- Core approval logic ----------------------------------------------------

def test_valid_buy_is_approved(limits, portfolio):
    result = ro.validate_trade(_buy(), portfolio, limits)
    assert result["approved"] is True
    assert result["approved_qty"] > 0
    assert result["price"] == 500.0


# --- H2: cross-portfolio single-name veto ------------------------------------

def test_cross_portfolio_single_name_veto_blocks_overlap(limits, portfolio):
    # SPY is fine standalone, but combined P1+P3 SPY already exceeds the 10%
    # cross-portfolio single-name cap -> the add must be vetoed.
    limits = {**limits, "cross_portfolio": {"single_name_cap_pct": 10.0}}
    cross_books = [
        {"portfolio_id": "portfolio_1", "equity": 100000,
         "positions": [{"symbol": "SPY", "market_value": 20000}]},
        {"portfolio_id": "portfolio_3", "equity": 100000,
         "positions": [{"symbol": "SPY", "market_value": 12000}]},
        {"portfolio_id": "portfolio_2", "equity": 100000, "positions": []},
    ]
    res = ro.validate_trade(_buy(symbol="SPY"), portfolio, limits, cross_books=cross_books)
    assert res["approved"] is False
    assert any("cross-portfolio" in r for r in res["rejections"])


def test_cross_portfolio_veto_silent_within_cap(limits, portfolio):
    limits = {**limits, "cross_portfolio": {"single_name_cap_pct": 10.0}}
    cross_books = [
        {"portfolio_id": "portfolio_1", "equity": 100000,
         "positions": [{"symbol": "SPY", "market_value": 1000}]},
        {"portfolio_id": "portfolio_3", "equity": 100000, "positions": []},
        {"portfolio_id": "portfolio_2", "equity": 100000, "positions": []},
    ]
    res = ro.validate_trade(_buy(symbol="SPY"), portfolio, limits, cross_books=cross_books)
    assert res["approved"] is True  # within cap -> behaves exactly as before


def test_cross_portfolio_veto_skipped_without_books(limits, portfolio):
    # Backward-compatible: no cross_books -> no cross-portfolio rejection.
    res = ro.validate_trade(_buy(symbol="SPY"), portfolio, limits)
    assert res["approved"] is True


def test_position_size_capped_to_instrument_max(limits, portfolio):
    # Request 50% on a stock; stock cap is 8%.
    result = ro.validate_trade(_buy(symbol="NVDA", itype="stock", pct=50.0), portfolio, limits)
    assert result["approved"] is True
    assert result["approved_position_pct"] <= 8.0


# --- Hard guardrails --------------------------------------------------------

def test_halted_portfolio_blocks_everything(limits, portfolio):
    portfolio["halted"] = True
    portfolio["halt_reason"] = "Daily loss limit"
    result = ro.validate_trade(_buy(), portfolio, limits)
    assert result["approved"] is False
    assert "HALTED" in result["rejections"][0]


def test_daily_loss_limit_halts_trading(limits, portfolio):
    portfolio["equity"] = 95_000.0  # -5% vs day_start 100k, limit is 4%
    result = ro.validate_trade(_buy(), portfolio, limits)
    assert result["approved"] is False
    assert "DAILY LOSS" in result["rejections"][0]


def test_kill_switch_drawdown_blocks(limits, portfolio):
    # Isolate the kill switch: equity down 20% vs *starting*, but flat on the
    # day/week (so the daily/weekly guards, which are checked first, don't fire).
    portfolio["equity"] = 80_000.0
    portfolio["day_start_equity"] = 80_000.0
    portfolio["week_start_equity"] = 80_000.0
    result = ro.validate_trade(_buy(), portfolio, limits)
    assert result["approved"] is False
    assert "KILL SWITCH" in result["rejections"][0]


def test_max_trades_per_day_enforced(limits, portfolio):
    portfolio["trades_today"] = 12
    result = ro.validate_trade(_buy(), portfolio, limits)
    assert result["approved"] is False


def test_penny_stock_outside_price_band_rejected(limits, portfolio):
    # price 0.40 -> below penny min 1.0; instrument 'stock' under $5 triggers penny rules
    sig = _buy(symbol="PENNY", price=0.40, itype="stock", pct=1.0)
    result = ro.validate_trade(sig, portfolio, limits)
    assert result["approved"] is False


# --- Silent-failure guards (2026-06-01 incident) ----------------------------

def test_approved_order_never_has_zero_qty(limits, portfolio):
    """A BUY that clears every guardrail but sizes to <1 share must be REJECTED,
    not approved with qty=0 (the executor silently skips qty<=0). This is the
    exact symptom that hid the *100 sizing bug."""
    sig = _buy(symbol="BRKA", price=600_000.0, itype="stock", pct=5.0)
    result = ro.validate_trade(sig, portfolio, limits)
    assert result["approved"] is False
    assert any("computed_qty" in r for r in result["rejections"])


def test_missing_position_size_fails_closed_not_defaulted(limits, portfolio):
    """A signal with no suggested_position_pct (analyst could not size) must be
    rejected fail-closed — never silently defaulted to a flat 1% position. The
    old `... or 1.0` masked this."""
    sig = _buy()
    del sig["risk_management"]["suggested_position_pct"]
    result = ro.validate_trade(sig, portfolio, limits)
    assert result["approved"] is False
    assert "position size" in result["rejections"][0].lower()


def test_zero_position_size_rejected(limits, portfolio):
    """sizing returns 0.0 to mean 'no trade'; the risk officer must honor that
    (0.0 is falsy — the old `or 1.0` turned it into a live 1% position)."""
    result = ro.validate_trade(_buy(pct=0.0), portfolio, limits)
    assert result["approved"] is False
    assert "position size" in result["rejections"][0].lower()


def test_all_approved_orders_have_positive_qty_invariant(limits, portfolio):
    """Cross-cutting invariant: scan a basket; ANY approved order must carry a
    strictly positive qty. Guards the contradiction 'approved but qty<=0'."""
    basket = [
        _buy(symbol="SPY", price=500.0, itype="etf", pct=5.0),
        _buy(symbol="NVDA", price=220.0, itype="stock", pct=8.0),
        _buy(symbol="BRKA", price=600_000.0, itype="stock", pct=5.0),  # -> qty 0 -> rejected
    ]
    for sig in basket:
        result = ro.validate_trade(sig, portfolio, limits)
        if result["approved"]:
            assert result["approved_qty"] > 0


# --- Crypto fractional sizing (F1 — P1's 10% crypto bucket never filled) -----

def _crypto_buy(symbol="BTC/USD", price=100_000.0, pct=5.0):
    return {
        "symbol": symbol, "signal": "BUY", "instrument_type": "crypto",
        "indicators": {"price": price},
        "risk_management": {"suggested_position_pct": pct, "stop_loss": price * 0.9,
                            "take_profit": price * 1.2},
    }


def test_crypto_sized_fractionally_and_approved(limits, portfolio):
    """A crypto BUY must size in FRACTIONAL units, not int() (which zeroed P1's
    10% crypto bucket forever). 5% of $100k at $100k/BTC = 0.05 BTC."""
    result = ro.validate_trade(_crypto_buy(pct=5.0), portfolio, limits)
    assert result["approved"] is True
    assert 0 < result["approved_qty"] < 1                       # fractional, not int-zeroed
    assert result["approved_qty"] == pytest.approx(0.05, abs=1e-6)


def test_crypto_dust_order_rejected_by_min_notional(limits, portfolio):
    """A sub-$1 crypto notional is rejected (dust guard), not approved at qty~0."""
    result = ro.validate_trade(_crypto_buy(pct=0.0005), portfolio, limits)  # ~$0.50
    assert result["approved"] is False
    assert any("notional" in r.lower() for r in result["rejections"])


# --- De-correlation gates (committee rec #2) --------------------------------

def _clustered(limits):
    """Limits + a correlated-cluster config, mirroring production risk_limits.json."""
    out = dict(limits)
    out["correlation_clusters"] = {"mega_cap_tech_ai": ["NVDA", "AAPL", "QQQ", "XLK", "AMZN"]}
    out["max_cluster_exposure_pct"] = 55.0
    return out


def test_no_add_to_name_already_at_single_stock_cap(limits, portfolio):
    """NVDA appreciated to 8.1% (>= 8% stock cap). A further BUY is rejected even
    though the per-order size cap alone would still 'fit' the increment."""
    portfolio["positions"] = {"NVDA": {"qty": 37, "avg_price": 219.0}}  # 37*220/100k=8.14%
    result = ro.validate_trade(
        _buy(symbol="NVDA", price=220.0, itype="stock", pct=2.0), portfolio, _clustered(limits))
    assert result["approved"] is False
    assert any("single-stock cap" in r for r in result["rejections"])


def test_cluster_cap_blocks_correlated_add(limits, portfolio):
    """Mega-cap cluster already ~51.8%; a new correlated NVDA add (->~59.8%) is
    rejected by the cluster cap (55%)."""
    portfolio["positions"] = {
        "AAPL": {"qty": 60, "avg_price": 300.0},   # 18.0%
        "QQQ": {"qty": 30, "avg_price": 700.0},    # 21.0%
        "AMZN": {"qty": 40, "avg_price": 320.0},   # 12.8% -> 51.8% total
    }
    result = ro.validate_trade(
        _buy(symbol="NVDA", price=220.0, itype="stock", pct=8.0), portfolio, _clustered(limits))
    assert result["approved"] is False
    assert any("correlated cluster" in r for r in result["rejections"])


def test_cluster_cap_allows_diversifying_add(limits, portfolio):
    """The same heavy mega-cap book does NOT block a de-correlating add — XLE
    (energy) is not in the cluster, so the gate steers capital toward diversity."""
    portfolio["positions"] = {
        "AAPL": {"qty": 60, "avg_price": 300.0},
        "QQQ": {"qty": 30, "avg_price": 700.0},
        "AMZN": {"qty": 40, "avg_price": 320.0},
    }
    result = ro.validate_trade(
        _buy(symbol="XLE", price=58.0, itype="etf", pct=5.0), portfolio, _clustered(limits))
    assert result["approved"] is True


def test_decorrelation_gates_off_when_unconfigured(limits, portfolio):
    """Backward compatible: with no cluster config the gates never fire."""
    portfolio["positions"] = {
        "AAPL": {"qty": 60, "avg_price": 300.0},
        "QQQ": {"qty": 30, "avg_price": 700.0},
        "AMZN": {"qty": 40, "avg_price": 320.0},
    }
    result = ro.validate_trade(
        _buy(symbol="NVDA", price=220.0, itype="stock", pct=8.0), portfolio, limits)
    assert result["approved"] is True
