#!/usr/bin/env python3
"""
Risk Officer Engine — Validates trade signals against hardcoded limits.
Enforces institutional guardrails that cannot be overridden.
"""
import json
import os
import sys
from datetime import datetime, timezone

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
JOURNAL_DIR = os.path.join(os.path.dirname(__file__), "..", "journal")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from shared.alpaca_http import evaluate_asset_gate  # noqa: E402

def load_config():
    with open(os.path.join(CONFIG_DIR, "risk_limits.json")) as f:
        return json.load(f)

def load_signals():
    signal_file = os.path.join(DATA_DIR, "signals.json")
    if not os.path.exists(signal_file):
        return {"signals": []}
    with open(signal_file) as f:
        return json.load(f)

def load_portfolio_state():
    state_file = os.path.join(DATA_DIR, "portfolio_state.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            return json.load(f)
    return {
        "equity": 100000,
        "starting_equity": 100000,
        "day_start_equity": 100000,
        "week_start_equity": 100000,
        "positions": {},
        "trades_today": 0,
        "total_exposure": 0,
        "short_exposure": 0,
        "crypto_exposure": 0,
        "halted": False,
        "halt_reason": None,
        "halt_until": None,
    }

def save_portfolio_state(state):
    with open(os.path.join(DATA_DIR, "portfolio_state.json"), "w") as f:
        json.dump(state, f, indent=2)

def validate_trade(signal, portfolio, limits, asset_info=None):
    """Validate a single signal against hardcoded limits.

    `asset_info`: optional dict from a fresh Alpaca asset lookup (tradable,
    shortable, easy_to_borrow, status) plus an optional `quote_fresh` flag. When
    present it enforces the ETB short gate and the halt/not-tradable gate. A
    SHORT with no borrow confirmation is FAIL-CLOSED (rejected) — you cannot
    short what you cannot confirm is borrowable.
    """
    rejections = []
    symbol = signal.get("symbol", "UNKNOWN")
    sig = signal.get("signal", "INSUFFICIENT_DATA")
    instrument_type = signal.get("instrument_type", "stock")

    # Guardrail checks that do NOT require price/indicators come first, so a
    # malformed or INSUFFICIENT_DATA signal can never crash the session.
    if portfolio.get("halted"):
        return {"approved": False, "symbol": symbol, "signal": sig,
                "rejections": [f"SYSTEM HALTED: {portfolio.get('halt_reason', 'Unknown')}"]}

    if sig in ("HOLD", "INSUFFICIENT_DATA"):
        return {"approved": False, "symbol": symbol, "signal": sig,
                "rejections": [f"Signal is {sig}, no action needed"]}

    # Only actionable BUY/SHORT signals reach here — extract price defensively.
    indicators = signal.get("indicators") or {}
    price = indicators.get("price")
    if price is None or price <= 0:
        return {"approved": False, "symbol": symbol, "signal": sig,
                "rejections": [f"No valid price for {symbol} (price={price})"]}

    # --- Asset tradability + easy-to-borrow gate (C1/C3) ---
    # Crypto is exempt from equity ETB/halt rules. For everything else: a SHORT
    # is fail-closed unless a fresh asset lookup confirms shortable + ETB; a new
    # entry into a non-tradable / inactive / stale (halted) asset is rejected.
    # Exits never pass through validate_trade, so closes are unaffected.
    if instrument_type != "crypto":
        a = dict(asset_info) if isinstance(asset_info, dict) else None
        quote_fresh = a.pop("quote_fresh", True) if a is not None else True
        ok_gate, gate_reasons, _gate_info = evaluate_asset_gate(
            a, sig, quote_fresh=quote_fresh)
        if not ok_gate:
            rejections.extend(gate_reasons)

    rm = signal.get("risk_management", {})
    suggested_pct = rm.get("suggested_position_pct") or signal.get("suggested_position_size_pct") or 1.0
    stop_loss = rm.get("stop_loss")
    take_profit = rm.get("take_profit")

    equity = portfolio["equity"]

    # Check daily loss
    daily_pnl_pct = ((equity - portfolio["day_start_equity"]) / portfolio["day_start_equity"]) * 100
    if daily_pnl_pct <= -limits["max_daily_loss_pct"]:
        return {"approved": False, "rejections": ["DAILY LOSS LIMIT BREACHED — trading halted for 24h"]}

    # Check weekly loss
    weekly_pnl_pct = ((equity - portfolio["week_start_equity"]) / portfolio["week_start_equity"]) * 100
    if weekly_pnl_pct <= -limits["max_weekly_loss_pct"]:
        return {"approved": False, "rejections": ["WEEKLY LOSS LIMIT BREACHED — trading halted for 7 days"]}

    # Kill switch
    drawdown_pct = ((portfolio["starting_equity"] - equity) / portfolio["starting_equity"]) * 100
    if drawdown_pct >= limits["kill_switch_drawdown_pct"]:
        return {"approved": False, "rejections": ["KILL SWITCH — max drawdown breached, full liquidation required"]}

    # Max trades per day
    if portfolio["trades_today"] >= limits["max_trades_per_day"]:
        rejections.append(f"Max trades per day ({limits['max_trades_per_day']}) reached")

    # Position size limits — cap to institutional max but approve at capped size
    max_pct = limits["max_single_position_pct"].get(instrument_type, limits["max_single_position_pct"]["stock"])
    if suggested_pct > max_pct:
        suggested_pct = max_pct

    # Crypto exposure
    if instrument_type == "crypto":
        proposed_crypto = portfolio.get("crypto_exposure", 0) + (suggested_pct / 100 * equity)
        if (proposed_crypto / equity * 100) > limits["max_crypto_exposure_pct"]:
            rejections.append(f"Crypto exposure would exceed {limits['max_crypto_exposure_pct']}%")

    # Gross exposure
    proposed_exposure = portfolio.get("total_exposure", 0) + (suggested_pct / 100 * equity)
    if (proposed_exposure / equity * 100) > limits["max_gross_exposure_pct"]:
        rejections.append(f"Gross exposure would exceed {limits['max_gross_exposure_pct']}%")

    # Short exposure
    if sig == "SHORT":
        proposed_short = portfolio.get("short_exposure", 0) + (suggested_pct / 100 * equity)
        if (proposed_short / equity * 100) > limits["max_short_exposure_pct"]:
            rejections.append(f"Short exposure would exceed {limits['max_short_exposure_pct']}%")

    # Penny stock rules
    if instrument_type == "stock" and price < 5.0:
        penny = limits["penny_stock_rules"]
        if price < penny["min_price"] or price > penny["max_price"]:
            rejections.append(f"Penny price ${price} outside ${penny['min_price']}-${penny['max_price']} range")
        vol = indicators.get("avg_volume_20d", 0)
        if vol < penny["min_volume"]:
            rejections.append(f"Volume {vol:,.0f} below minimum {penny['min_volume']:,}")
        max_pct = limits["max_single_position_pct"]["penny"]
        if suggested_pct > max_pct:
            suggested_pct = max_pct

    approved = len(rejections) == 0
    dollar_amount = round(equity * suggested_pct / 100, 2)
    qty = int(dollar_amount / price) if price > 0 else 0

    result = {
        "approved": approved,
        "symbol": symbol,
        "signal": sig,
        "rejections": rejections,
        "approved_position_pct": round(suggested_pct, 2),
        "approved_dollar_amount": dollar_amount,
        "approved_qty": qty,
        "price": price,
    }
    if stop_loss is not None:
        result["stop_loss"] = stop_loss
    if take_profit is not None:
        result["take_profit"] = take_profit
    return result

def run_validation(asset_lookup=None):
    """Validate all pending signals.

    `asset_lookup`: optional callable `symbol -> asset_info dict` (a fresh Alpaca
    asset record, optionally carrying `quote_fresh`). When supplied it enforces
    the ETB short gate and halt/not-tradable gate on the live money path. Lookup
    failures fail-closed: a SHORT with no confirmable borrow is rejected.
    """
    limits = load_config()
    signals = load_signals()
    portfolio = load_portfolio_state()

    approved_orders = []
    rejected_orders = []

    for signal in signals.get("signals", []):
        asset_info = None
        if asset_lookup is not None:
            try:
                asset_info = asset_lookup(signal.get("symbol"))
            except Exception:
                asset_info = None  # fail-closed (shorts get rejected downstream)
        result = validate_trade(signal, portfolio, limits, asset_info=asset_info)
        result["confidence"] = signal.get("score", signal.get("confidence", 0))
        result["reasons"] = signal.get("reasons", [])
        if result["approved"]:
            approved_orders.append(result)
        else:
            rejected_orders.append(result)

    # Sort by confidence descending
    approved_orders.sort(key=lambda x: x.get("confidence", 0), reverse=True)

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "portfolio_equity": portfolio["equity"],
        "trades_today": portfolio["trades_today"],
        "approved_orders": approved_orders,
        "rejected_orders": rejected_orders,
        "summary": {
            "total_signals": len(signals.get("signals", [])),
            "approved": len(approved_orders),
            "rejected": len(rejected_orders),
        }
    }

    output_path = os.path.join(DATA_DIR, "validated_orders.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    return output

if __name__ == "__main__":
    result = run_validation()
    print(json.dumps(result, indent=2))
