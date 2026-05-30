"""Tests for the ETB short gate + halt/tradable gate (C1/C3).

The single most material real-money safety gap the audit verification surfaced:
P1 actively places SHORT (sell-to-open) orders with no borrow check. These tests
prove the gate is FAIL-CLOSED for shorts and blocks new entries into
untradable/halted assets, while never affecting longs unnecessarily.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.alpaca_http import evaluate_asset_gate  # noqa: E402
import risk_officer as ro  # noqa: E402


ETB_ASSET = {"tradable": True, "shortable": True, "easy_to_borrow": True,
             "status": "active"}
HTB_ASSET = {"tradable": True, "shortable": True, "easy_to_borrow": False,
             "status": "active"}
NOT_SHORTABLE = {"tradable": True, "shortable": False, "easy_to_borrow": False,
                 "status": "active"}
INACTIVE = {"tradable": False, "shortable": False, "easy_to_borrow": False,
            "status": "inactive"}


# --- Pure gate: shorts ------------------------------------------------------

def test_short_allowed_only_when_etb():
    ok, reasons, info = evaluate_asset_gate(ETB_ASSET, "SHORT")
    assert ok is True
    assert reasons == []
    assert info["easy_to_borrow"] is True


def test_short_blocked_when_htb():
    ok, reasons, _ = evaluate_asset_gate(HTB_ASSET, "SHORT")
    assert ok is False
    assert any("easy-to-borrow" in r.lower() or "htb" in r.lower() for r in reasons)


def test_short_blocked_when_not_shortable():
    ok, reasons, _ = evaluate_asset_gate(NOT_SHORTABLE, "SHORT")
    assert ok is False
    assert any("shortable" in r.lower() for r in reasons)


def test_short_fail_closed_when_no_asset():
    """No broker confirmation => a short must be rejected, never assumed safe."""
    ok, reasons, info = evaluate_asset_gate(None, "SHORT")
    assert ok is False
    assert info["borrow_verified"] is False
    assert any("unverified" in r.lower() for r in reasons)


# --- Pure gate: longs -------------------------------------------------------

def test_long_allowed_on_etb_asset():
    ok, reasons, _ = evaluate_asset_gate(ETB_ASSET, "BUY")
    assert ok is True
    assert reasons == []


def test_long_allowed_when_no_asset_metadata():
    """A missing asset lookup should not block longs (broker rejects untradable)."""
    ok, reasons, _ = evaluate_asset_gate(None, "BUY")
    assert ok is True


def test_long_blocked_on_inactive_asset():
    ok, reasons, _ = evaluate_asset_gate(INACTIVE, "BUY")
    assert ok is False
    assert any("tradable" in r.lower() or "active" in r.lower() for r in reasons)


# --- Halt proxy -------------------------------------------------------------

def test_stale_quote_blocks_new_entry():
    ok, reasons, _ = evaluate_asset_gate(ETB_ASSET, "BUY", quote_fresh=False)
    assert ok is False
    assert any("halt" in r.lower() or "stale" in r.lower() for r in reasons)


def test_stale_quote_blocks_long_even_without_asset():
    ok, reasons, _ = evaluate_asset_gate(None, "BUY", quote_fresh=False)
    assert ok is False


# --- risk_officer integration ----------------------------------------------

def _short(symbol="XYZ", price=50.0, itype="stock", pct=3.0):
    return {
        "symbol": symbol,
        "signal": "SHORT",
        "instrument_type": itype,
        "indicators": {"price": price, "avg_volume_20d": 50_000_000},
        "risk_management": {"suggested_position_pct": pct, "stop_loss": price * 1.05,
                            "take_profit": price * 0.9},
    }


def _buy(symbol="SPY", price=500.0, itype="etf", pct=5.0):
    return {
        "symbol": symbol,
        "signal": "BUY",
        "instrument_type": itype,
        "indicators": {"price": price, "avg_volume_20d": 50_000_000},
        "risk_management": {"suggested_position_pct": pct, "stop_loss": price * 0.95,
                            "take_profit": price * 1.1},
    }


def test_validate_short_rejected_without_asset_info(limits, portfolio):
    """No asset_info => fail-closed short (the production-critical default)."""
    result = ro.validate_trade(_short(), portfolio, limits)
    assert result["approved"] is False
    assert any("short" in r.lower() for r in result["rejections"])


def test_validate_short_rejected_when_htb(limits, portfolio):
    result = ro.validate_trade(_short(), portfolio, limits, asset_info=dict(HTB_ASSET))
    assert result["approved"] is False


def test_validate_short_approved_when_etb(limits, portfolio):
    result = ro.validate_trade(_short(), portfolio, limits, asset_info=dict(ETB_ASSET))
    assert result["approved"] is True
    assert result["approved_qty"] > 0


def test_validate_buy_unaffected_by_missing_asset_info(limits, portfolio):
    """Longs keep working exactly as before when no asset_info is supplied."""
    result = ro.validate_trade(_buy(), portfolio, limits)
    assert result["approved"] is True


def test_validate_buy_blocked_on_inactive_asset(limits, portfolio):
    result = ro.validate_trade(_buy(symbol="DEAD", itype="stock"), portfolio, limits,
                               asset_info=dict(INACTIVE))
    assert result["approved"] is False


def test_validate_entry_blocked_on_stale_quote(limits, portfolio):
    info = dict(ETB_ASSET)
    info["quote_fresh"] = False
    result = ro.validate_trade(_buy(symbol="HALTD", itype="stock"), portfolio, limits,
                               asset_info=info)
    assert result["approved"] is False


def test_validate_crypto_short_exempt_from_etb(limits, portfolio):
    """Crypto is not subject to equity ETB rules; a crypto short is not
    auto-rejected by the borrow gate."""
    sig = _short(symbol="BTCUSD", itype="crypto", price=60000.0)
    result = ro.validate_trade(sig, portfolio, limits)
    # Not rejected for borrow reasons (may pass or be limited by other rules).
    assert not any("borrow" in r.lower() or "easy-to-borrow" in r.lower()
                   for r in result["rejections"])
