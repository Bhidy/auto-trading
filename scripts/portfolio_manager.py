#!/usr/bin/env python3
"""
Smart Portfolio Manager — Auto-Rebalancing, Stop Management, Dynamic Allocation
"""
import json
import os
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

def load_json(path, default=None):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default if default is not None else {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# ---------------------------------------------------------------------------
# STOP-LOSS MANAGEMENT
# ---------------------------------------------------------------------------

def compute_stop_levels(positions, signals_data):
    signals = {s["symbol"]: s for s in signals_data.get("signals", [])}
    stops = {}
    for pos in positions:
        sym = pos["symbol"]
        signal = signals.get(sym, {})
        rm = signal.get("risk_management", {})

        entry = float(pos.get("avg_entry_price", 0))
        current = float(pos.get("current_price", 0))
        side = pos.get("side", "long")

        stop = rm.get("stop_loss")
        trailing_pct = rm.get("trailing_stop_pct")
        take_profit = rm.get("take_profit")

        # For longs: trailing stop rises with price
        if side == "long" and trailing_pct and current > entry:
            profit_pct = (current - entry) / entry * 100
            # Tighten stop as profit grows
            if profit_pct > 10:
                effective_trail = trailing_pct * 0.7
            elif profit_pct > 5:
                effective_trail = trailing_pct * 0.85
            else:
                effective_trail = trailing_pct
            trailing_stop = round(current * (1 - effective_trail / 100), 2)
            if stop is None or trailing_stop > stop:
                stop = trailing_stop

        # Breakeven stop: once up 3%+, don't let it become a loss
        if side == "long" and current > entry * 1.03:
            breakeven_stop = round(entry * 1.005, 2)
            if stop is None or breakeven_stop > stop:
                stop = breakeven_stop

        stops[sym] = {
            "side": side,
            "entry": entry,
            "current": current,
            "stop_loss": stop,
            "take_profit": take_profit,
            "trailing_pct": trailing_pct,
            "unrealized_pnl_pct": round((current - entry) / entry * 100, 2) if entry > 0 else 0,
        }

    return stops

def check_stop_triggers(positions, signals_data):
    stops = compute_stop_levels(positions, signals_data)
    triggers = []

    for sym, stop_info in stops.items():
        current = stop_info["current"]
        side = stop_info["side"]

        if stop_info["stop_loss"] and side == "long" and current <= stop_info["stop_loss"]:
            triggers.append({
                "symbol": sym,
                "action": "STOP_LOSS_SELL",
                "current_price": current,
                "stop_price": stop_info["stop_loss"],
                "pnl_pct": stop_info["unrealized_pnl_pct"],
            })

        if stop_info["take_profit"] and side == "long" and current >= stop_info["take_profit"]:
            triggers.append({
                "symbol": sym,
                "action": "TAKE_PROFIT_SELL",
                "current_price": current,
                "take_profit": stop_info["take_profit"],
                "pnl_pct": stop_info["unrealized_pnl_pct"],
            })

    return triggers

# ---------------------------------------------------------------------------
# REBALANCING ENGINE
# ---------------------------------------------------------------------------

def compute_current_allocation(positions, equity):
    allocation = {"core_equity": 0, "aggressive_growth": 0, "sector_momentum": 0,
                  "crypto": 0, "defensive": 0, "cash": 0}
    bucket_map = load_json(os.path.join(DATA_DIR, "portfolio_state.json"), {}).get("positions", {})

    for pos in positions:
        sym = pos["symbol"]
        mv = float(pos.get("market_value", 0))
        bucket = bucket_map.get(sym, {}).get("bucket", "unknown")
        if bucket in allocation:
            allocation[bucket] += mv

    invested = sum(allocation.values())
    allocation["cash"] = max(equity - invested, 0)

    pcts = {}
    for k, v in allocation.items():
        pcts[k] = round(v / equity * 100, 2) if equity > 0 else 0

    return allocation, pcts

def compute_rebalance_orders(positions, equity, regime):
    from analyst_v2 import regime_allocation_modifier
    limits = load_json(os.path.join(CONFIG_DIR, "risk_limits.json"))
    targets = limits.get("allocation_targets", {})
    regime_mod = regime_allocation_modifier(regime)

    adjusted_targets = {}
    for bucket, target in targets.items():
        if bucket in ("core_equity", "aggressive_growth", "sector_momentum"):
            adjusted_targets[bucket] = target * regime_mod["equity_mult"]
        elif bucket == "defensive_cash":
            adjusted_targets[bucket] = target * regime_mod["defensive_mult"]
        else:
            adjusted_targets[bucket] = target

    total = sum(adjusted_targets.values())
    if total > 0:
        for k in adjusted_targets:
            adjusted_targets[k] /= total

    current_alloc, current_pcts = compute_current_allocation(positions, equity)
    rebalance_actions = []

    for bucket, target_pct in adjusted_targets.items():
        current_pct = current_pcts.get(bucket, 0) / 100
        diff = target_pct - current_pct
        threshold = 0.03  # 3% drift threshold

        if abs(diff) > threshold:
            dollar_amount = abs(diff) * equity
            rebalance_actions.append({
                "bucket": bucket,
                "action": "INCREASE" if diff > 0 else "DECREASE",
                "current_pct": round(current_pct * 100, 1),
                "target_pct": round(target_pct * 100, 1),
                "drift_pct": round(diff * 100, 1),
                "dollar_amount": round(dollar_amount, 2),
            })

    return {
        "current_allocation": current_pcts,
        "adjusted_targets": {k: round(v*100, 1) for k, v in adjusted_targets.items()},
        "regime": regime,
        "rebalance_actions": rebalance_actions,
        # ADVISORY HRP tilts — OFF by default (see hrp_advisory_tilts); a disabled
        # stub here changes nothing, it only exposes the integration point.
        "hrp_advisory": hrp_advisory_tilts(),
    }

# ---------------------------------------------------------------------------
# HRP ADVISORY TILTS (T2 artifact consumer — OFF by default, never auto-trades)
# ---------------------------------------------------------------------------

def load_hrp_weights(path=None):
    """Load the T2 HRP artifact (data/hrp_weights.json) or None if absent."""
    path = path or os.path.join(DATA_DIR, "hrp_weights.json")
    art = load_json(path, None)
    return art if isinstance(art, dict) else None


def hrp_advisory_tilts(*, enabled=None, hrp_path=None, limits=None):
    """ADVISORY HRP target weights, clamped inside the hardcoded single-name caps.

    Gated by HRP_TILTS_ENABLED (default OFF). When off (or the artifact is
    missing) it returns a disabled stub with weights=None and has ZERO effect on
    allocation. When on, each weight is clamped to the single-name cap and the
    uninvested remainder is routed to cash (NOT renormalized — renormalizing would
    re-inflate a name back over its cap). Never relaxes a cap; never places an
    order. Wiring these into live orders is a separate, explicitly-approved step.
    """
    if enabled is None:
        enabled = os.environ.get("HRP_TILTS_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return {"enabled": False, "weights": None,
                "note": "HRP tilts OFF (set HRP_TILTS_ENABLED=1) — no effect on allocation."}
    art = load_hrp_weights(hrp_path)
    if not art or not isinstance(art.get("weights"), dict) or not art["weights"]:
        return {"enabled": True, "weights": None,
                "note": "HRP enabled but artifact missing/empty — no effect on allocation."}
    if limits is None:
        limits = load_json(os.path.join(CONFIG_DIR, "risk_limits.json"))
    caps = (limits or {}).get("max_single_position_pct", {}) or {}
    cap = float(caps.get("stock", 8)) / 100.0          # conservative single-name cap
    clamped = {s: min(float(w), cap) for s, w in art["weights"].items()
               if isinstance(w, (int, float))}
    invested = sum(clamped.values())
    return {
        "enabled": True,
        "source_generated_at": art.get("generated_at"),
        "shrinkage_delta": art.get("shrinkage_delta"),
        "single_name_cap_pct": round(cap * 100, 2),
        "weights": {s: round(w, 6) for s, w in clamped.items()},
        "cash_residual": round(max(0.0, 1.0 - invested), 6),
        "note": "ADVISORY only — clamped to the single-name cap; NOT applied to live orders.",
    }

# ---------------------------------------------------------------------------
# PORTFOLIO HEALTH CHECK
# ---------------------------------------------------------------------------

def portfolio_health_check(account_info, positions):
    equity = float(account_info.get("equity", 100000))
    starting = float(account_info.get("last_equity", equity))
    portfolio_state = load_json(os.path.join(DATA_DIR, "portfolio_state.json"))
    limits = load_json(os.path.join(CONFIG_DIR, "risk_limits.json"))

    long_mv = sum(float(p.get("market_value", 0)) for p in positions if p.get("side") == "long")
    short_mv = sum(abs(float(p.get("market_value", 0))) for p in positions if p.get("side") == "short")

    daily_pnl_pct = (equity - starting) / starting * 100 if starting > 0 else 0
    week_start = portfolio_state.get("week_start_equity", starting)
    weekly_pnl_pct = (equity - week_start) / week_start * 100 if week_start > 0 else 0
    max_dd = (portfolio_state.get("starting_equity", 100000) - equity) / portfolio_state.get("starting_equity", 100000) * 100

    health = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "equity": equity,
        "daily_pnl_pct": round(daily_pnl_pct, 3),
        "weekly_pnl_pct": round(weekly_pnl_pct, 3),
        "max_drawdown_pct": round(max(max_dd, 0), 3),
        "gross_exposure_pct": round((long_mv + short_mv) / equity * 100, 1),
        "long_exposure_pct": round(long_mv / equity * 100, 1),
        "short_exposure_pct": round(short_mv / equity * 100, 1),
        "position_count": len(positions),
        "alerts": [],
    }

    # Check limits
    if daily_pnl_pct <= -limits["max_daily_loss_pct"]:
        health["alerts"].append({"level": "CRITICAL", "msg": f"DAILY LOSS LIMIT BREACHED: {daily_pnl_pct:.2f}%"})
    elif daily_pnl_pct <= -limits["max_daily_loss_pct"] * 0.75:
        health["alerts"].append({"level": "WARNING", "msg": f"Approaching daily loss limit: {daily_pnl_pct:.2f}%"})

    if weekly_pnl_pct <= -limits["max_weekly_loss_pct"]:
        health["alerts"].append({"level": "CRITICAL", "msg": f"WEEKLY LOSS LIMIT BREACHED: {weekly_pnl_pct:.2f}%"})

    if max_dd >= limits["kill_switch_drawdown_pct"]:
        health["alerts"].append({"level": "EMERGENCY", "msg": f"KILL SWITCH: Drawdown {max_dd:.2f}% — LIQUIDATE ALL"})
    elif max_dd >= limits["kill_switch_drawdown_pct"] * 0.7:
        health["alerts"].append({"level": "WARNING", "msg": f"Drawdown warning: {max_dd:.2f}%"})

    for pos in positions:
        pnl_pct = float(pos.get("unrealized_plpc", 0)) * 100
        sym = pos["symbol"]
        if pnl_pct < -5:
            health["alerts"].append({"level": "WARNING", "msg": f"{sym} down {pnl_pct:.1f}% — review stop"})
        if pnl_pct > 15:
            health["alerts"].append({"level": "INFO", "msg": f"{sym} up {pnl_pct:.1f}% — consider taking partial profits"})

    if not health["alerts"]:
        health["alerts"].append({"level": "OK", "msg": "All systems nominal"})

    return health

if __name__ == "__main__":
    print("Portfolio Manager loaded. Use functions from scheduled tasks.")
