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
from shared.portfolio_risk import would_breach_cluster_cap  # noqa: E402


def _f(x):
    """Tolerant float — malformed state never crashes validation."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0

def load_config():
    """Load risk limits, profile-aware. RISK_PROFILE=live selects the tighter
    risk_limits.live.json for the fractional live ramp (R4); anything else (the
    default) uses the paper limits. Falls back to paper if the live file is
    missing, so a misconfiguration can never silently widen limits."""
    profile = os.environ.get("RISK_PROFILE", "paper").strip().lower()
    candidate = "risk_limits.live.json" if profile == "live" else "risk_limits.json"
    path = os.path.join(CONFIG_DIR, candidate)
    if not os.path.exists(path):
        path = os.path.join(CONFIG_DIR, "risk_limits.json")
    with open(path) as f:
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

# Minimum crypto order notional (USD). Crypto sizes fractionally, so the
# "qty < 1 share" reject used for equities does not apply — gate on notional
# instead. Alpaca's real per-asset minimums are far below realistic P1 sizing;
# this is a dust guard, not a binding constraint.
MIN_CRYPTO_NOTIONAL_USD = 1.0


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
    suggested_pct = rm.get("suggested_position_pct")
    stop_loss = rm.get("stop_loss")
    take_profit = rm.get("take_profit")

    # A missing/degenerate size means the analyst could not produce a
    # volatility-based size (e.g. ATR unavailable). shared.sizing returns 0.0
    # (and analyst_v2 emits None) to mean "no trade"; honor that contract
    # FAIL-CLOSED and LOUD. The previous `... or 1.0` silently sized such a
    # signal at a flat 1% on no volatility info — the exact silent-failure class
    # this hardening targets (None and 0.0 are both falsy, so `or 1.0` hid them).
    if suggested_pct is None or suggested_pct <= 0:
        return {"approved": False, "symbol": symbol, "signal": sig,
                "rejections": [
                    f"No valid position size for {symbol} "
                    f"(suggested_position_pct={suggested_pct}); analyst could not "
                    f"size — missing ATR? (fail-closed, not defaulted to 1%)"
                ]}

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

    dollar_amount = round(equity * suggested_pct / 100, 2)
    # Crypto trades in FRACTIONAL units (a 5% BTC position is ~0.05 BTC); equities
    # trade in whole shares. Using int() for crypto silently zeroed every crypto
    # order, so P1's 10% crypto bucket never filled (2026-06-01 audit). Size
    # crypto fractionally and gate on a minimum notional rather than int(qty)>=1.
    if instrument_type == "crypto":
        qty = round(dollar_amount / price, 6) if price > 0 else 0
    else:
        qty = int(dollar_amount / price) if price > 0 else 0

    # An order that cleared every guardrail but sizes to nothing is a silent-
    # failure trap (the 2026-06-01 incident): the executor skips qty<=0 while the
    # order still looks "approved", so a run reports success while placing nothing.
    # Reject it LOUDLY with a precise reason — never approve a no-op order.
    if instrument_type == "crypto":
        if dollar_amount < MIN_CRYPTO_NOTIONAL_USD or qty <= 0:
            rejections.append(
                f"crypto notional ${dollar_amount:,.2f} (size {suggested_pct}% x "
                f"${equity:,.0f}) below ${MIN_CRYPTO_NOTIONAL_USD:.0f} minimum"
            )
    elif qty <= 0:
        rejections.append(
            f"computed_qty=0 (size {suggested_pct}% x ${equity:,.0f} / ${price} "
            f"< 1 share) — position size too small or price too high"
        )

    # --- De-correlation gates (committee rec #2): advisory caps layered INSIDE
    # the hardcoded limits. They only ever REJECT a new long add — never relax a
    # hard limit. Applied to BUY entries only; shorts/exits reduce correlated
    # long exposure, and crypto is handled by its own exposure cap above. ---
    if sig == "BUY" and instrument_type != "crypto":
        positions = portfolio.get("positions", {}) or {}
        held = positions.get(symbol)

        # (a) No new add to a name already at/above its single-stock cap. The
        # size-cap above only trims THIS order; it does not stop stacking onto a
        # position price-appreciation already pushed to the cap (NVDA at 8.1%).
        if held:
            cur_pct = (abs(_f(held.get("qty"))) * price / equity * 100) if equity else 0.0
            if cur_pct >= max_pct - 1e-9:
                rejections.append(
                    f"{symbol} already at single-stock cap "
                    f"({cur_pct:.1f}% >= {max_pct:.1f}%) — no new add")

        # (b) Correlated-cluster cap: a basket of names that move together is one
        # bet. Block adds that push the cluster over max_cluster_exposure_pct.
        clusters = limits.get("correlation_clusters") or {}
        max_cluster = limits.get("max_cluster_exposure_pct")
        if clusters and max_cluster:
            pos_list = [{"symbol": s, "market_value": abs(_f(p.get("qty")) * _f(p.get("avg_price")))}
                        for s, p in positions.items()]
            breach, cname, proj, cap = would_breach_cluster_cap(
                symbol, pos_list, equity, clusters, max_cluster,
                add_market_value=dollar_amount)
            if breach:
                rejections.append(
                    f"{symbol} in correlated cluster '{cname}': adding would push "
                    f"cluster exposure to {proj:.1f}% > {cap:.1f}% cap (de-correlation gate)")

    approved = len(rejections) == 0

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
