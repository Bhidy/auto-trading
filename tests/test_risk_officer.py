"""Risk Officer validation tests.

These directly cover the bug class that silently broke P1 trading on
2026-05-29: validate_trade() indexing signal["indicators"]["price"] before
guarding signal type, crashing the entire session on an INSUFFICIENT_DATA
signal that carries no "indicators" key.
"""
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
