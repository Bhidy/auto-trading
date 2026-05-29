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
