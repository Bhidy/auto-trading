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

def _pnum(params, key, default):
    v = (params or {}).get(key, default)
    try:
        return float(v) if v is not None else float(default)
    except (TypeError, ValueError):
        return float(default)


def compute_stop_levels(positions, signals_data, open_trades=None, params=None):
    """Stop/take-profit levels per position.

    open_trades (optional): the trade log's currently-OPEN entries. A held
    position that is absent from TODAY's signals would otherwise get stop=None
    and be left UNPROTECTED (this is how a 1%-risk-sized trade ran to -10.8%).
    We fall back to the position's PERSISTED entry stop/take-profit so protection
    survives even when the symbol drops out of the daily signal payload. This is
    risk-REDUCING only — trailing/breakeven below can tighten it, never loosen it.
    """
    signals = {s["symbol"]: s for s in signals_data.get("signals", [])}
    entry_stops = {}
    for t in (open_trades or []):
        if isinstance(t, dict) and t.get("status") == "open" and t.get("symbol"):
            entry_stops[t["symbol"]] = t  # most-recent open lot wins
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

        # Persisted-stop fallback: never leave a held position unprotected.
        fb = entry_stops.get(sym, {})
        if stop is None and fb.get("stop_loss") not in (None, 0):
            stop = fb.get("stop_loss")
        if take_profit is None and fb.get("take_profit") not in (None, 0):
            take_profit = fb.get("take_profit")

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

        # Breakeven stop: once up the trigger %, lock in a small gain. The trigger
        # is parameterized (breakeven_trigger_pct) — the validated optimization
        # raised it 0.03 -> 0.08 so a normal pullback stops killing winners (the
        # documented disposition error). Defaults reproduce the old +3%/+0.5%.
        be_trigger = _pnum(params, "breakeven_trigger_pct", 0.03)
        be_lock = _pnum(params, "breakeven_lock_pct", 0.005)
        if side == "long" and current > entry * (1 + be_trigger):
            breakeven_stop = round(entry * (1 + be_lock), 2)
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

_BUCKET_ASSET = {
    "core_equity": "etf", "sector_momentum": "etf", "defensive": "etf",
    "defensive_cash": "etf", "aggressive_growth": "stock", "crypto": "crypto",
    "penny_lab": "penny", "penny": "penny",
}


def core_regime(signals):
    """Market regime for the passive core, read from the SAME key analyst_v2 writes
    (``market_regime``). The old ``regime`` key always missed -> the core sized at
    full BULL weight even in bears (audit fix); this pins the correct contract."""
    return (signals or {}).get("market_regime", "BULL")


def compute_core_orders(positions, equity, cash, params, regime, prices, limits):
    """Passive index-core allocation (regime-aware), BUYS ONLY.

    Evidence (core_satellite study): a passive broad-ETF core dominates the active
    multifactor strategy out-of-sample by ~+2.16 Sharpe. Allocate ``core_weight`` x
    equity across a diversified broad-market ETF basket (SPY/QQQ/IWM/DIA), scaled
    DOWN in bear regimes by the existing regime equity multiplier.

    HARD SAFETY: each ETF is capped strictly UNDER ``max_single_position_pct.etf``
    (the 12% hardcoded limit is never breached) — so a high core_weight simply
    spreads across the basket rather than over-concentrating. Gradual: spends only
    available cash each session (active positions free cash as they close).
    ``core_weight=0`` -> no-op. Returns [{symbol, qty, target_value, reason}].
    """
    core_weight = float(params.get("core_weight", 0.0) or 0.0)
    if core_weight <= 0 or equity <= 0 or cash <= 0:
        return []
    from analyst_v2 import regime_allocation_modifier
    basket = params.get("core_basket") or ["SPY", "QQQ", "IWM", "DIA"]
    etf_cap = float((limits.get("max_single_position_pct") or {}).get("etf", 12.0)) / 100.0
    per_cap = etf_cap * 0.95 * equity                      # strict buffer under the hard cap
    eq_mult = float(regime_allocation_modifier(regime).get("equity_mult", 1.0))
    target_each = min(core_weight * eq_mult * equity / len(basket), per_cap)
    min_notional = float(limits.get("min_position_notional_usd", 500))

    held = {p.get("symbol"): float(p.get("market_value", 0) or 0) for p in positions}
    orders, avail = [], float(cash)
    for s in basket:
        price = float((prices or {}).get(s, 0) or 0)
        if price <= 0:
            continue
        gap = target_each - held.get(s, 0.0)
        if gap <= target_each * 0.05:                      # within 5% drift band -> skip
            continue
        spend = min(gap, avail)
        qty = int(spend / price)
        if qty <= 0 or qty * price < min_notional:
            continue
        avail -= qty * price
        orders.append({"symbol": s, "qty": qty, "target_value": round(target_each, 2),
                       "reason": f"passive_core_w{core_weight:g}_regime_{regime}"})
    return orders


def compute_cap_trims(positions, equity, limits, bucket_map, buffer_pct=0.5):
    """Trim-only plan (H1): any single position above its asset-class
    max_single_position_pct (ETF 12 / stock 8 / crypto 5 / penny 1) is trimmed
    back to the cap. The risk officer caps positions at ENTRY but nothing trims a
    position that DRIFTS past the cap as it appreciates (IWM/XLI breached 12%).

    Risk-REDUCING only: produces SELLs, never buys; skips sub-min-notional trims;
    whole shares (limit-order safe); unknown bucket -> the tighter 'stock' cap.
    Returns [{symbol, trim_qty, reason, weight_pct, cap_pct, trim_value}].
    """
    caps = limits.get("max_single_position_pct", {})
    min_notional = float(limits.get("min_position_notional_usd", 500))
    trims = []
    if equity <= 0:
        return trims
    for pos in positions:
        sym = pos.get("symbol")
        mv = float(pos.get("market_value", 0) or 0)
        price = float(pos.get("current_price", 0) or 0)
        qty = float(pos.get("qty", 0) or 0)
        if not sym or mv <= 0 or price <= 0 or qty <= 0:
            continue
        asset = _BUCKET_ASSET.get(bucket_map.get(sym, {}).get("bucket", ""), "stock")
        cap_pct = float(caps.get(asset, 8.0))
        weight_pct = mv / equity * 100
        if weight_pct <= cap_pct + buffer_pct:
            continue
        trim_value = mv - (cap_pct / 100.0) * equity
        trim_qty = min(int(trim_value / price), int(qty))
        if trim_qty <= 0 or trim_qty * price < min_notional:
            continue
        trims.append({
            "symbol": sym, "trim_qty": trim_qty,
            "reason": f"cap_maintenance_{asset}_{cap_pct:g}pct",
            "weight_pct": round(weight_pct, 2), "cap_pct": cap_pct,
            "trim_value": round(trim_qty * price, 2),
        })
    return trims


def check_stop_triggers(positions, signals_data, open_trades=None, params=None):
    stops = compute_stop_levels(positions, signals_data, open_trades, params)
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
# CAPITAL RECYCLING (rotation) — free cash for high-conviction starved BUYs
# ---------------------------------------------------------------------------

def compute_rotation_plan(positions, validated, cash, equity, *,
                          min_cash_pct=3.0, rotation_edge=0.25,
                          max_rotation_pct=15.0, max_rotations=3):
    """Free capital for high-conviction approved BUYs that are starved for cash by
    exiting the lowest-conviction CURRENT holdings the analyst no longer wants.

    WHY THIS EXISTS: without it P1 deploys ~100% on day one and freezes. Observed
    2026-06-02: P1 held 14 names at 86% gross / **$80 cash** and could not act on
    its own #1/#2-ranked adds (XLK conf 0.86, SPY 0.72) while still holding
    low-conviction HOLDs (TSLA score 0.08, XLI 0.01, XLY 0.05). Capital only ever
    freed up when a stop/TP happened to fire — so in a flat market it never traded.

    DESIGN (conservative & fail-safe):
      * Returns [] unless the book is genuinely STARVED (cash < min_cash_pct% of
        equity). Default behavior off the starved path is "do nothing".
      * Only proposes FULL exits (clean close_trade accounting, no qty drift) of
        names whose current signal is HOLD — NEVER a name still signalled BUY, and
        never a name that is itself an approved BUY this run.
      * Only rotates when the best starved BUY out-ranks the exit candidate by at
        least `rotation_edge` (prevents churn between similar-conviction names).
      * Caps total rotation at `max_rotation_pct`% of equity and `max_rotations`
        names per run.
      * Pure function — places NO orders. Returns a list of sell actions for the
        caller to execute and account for.

    `validated` is the risk-officer output (approved_orders + rejected_orders, each
    carrying `symbol`, `signal`, `confidence`). Each returned action is
    {symbol, qty, side='sell', est_value, score, reason}.
    """
    try:
        equity = float(equity); cash = float(cash)
    except (TypeError, ValueError):
        return []
    if equity <= 0 or cash >= equity * min_cash_pct / 100.0:
        return []

    approved = validated.get("approved_orders", []) or []
    rejected = validated.get("rejected_orders", []) or []
    signal_by, score_by = {}, {}
    for o in list(approved) + list(rejected):
        sym = o.get("symbol")
        if not sym:
            continue
        signal_by[sym] = o.get("signal")
        score_by[sym] = o.get("confidence", 0) or 0

    buys = sorted([o for o in approved if o.get("signal") == "BUY"],
                  key=lambda o: o.get("confidence", 0) or 0, reverse=True)
    if not buys:
        return []
    best_buy_conf = buys[0].get("confidence", 0) or 0
    approved_syms = {o.get("symbol") for o in approved}

    # How much extra cash the top starved BUYs need (beyond what's on hand).
    need = 0.0
    for b in buys[:max_rotations]:
        bn = b.get("approved_dollar_amount") or (
            (b.get("approved_qty", 0) or 0) * (b.get("price", 0) or 0))
        need += float(bn or 0)
    need = max(0.0, need - cash)
    if need <= 0:
        return []

    # Rotation candidates: held, currently HOLD, not an approved buy. Weakest first.
    candidates = []
    for p in positions:
        sym = p.get("symbol")
        if not sym or signal_by.get(sym) != "HOLD" or sym in approved_syms:
            continue
        mv = abs(float(p.get("market_value", 0) or 0))
        qty = int(float(p.get("qty", 0) or 0))
        if qty <= 0 or mv <= 0:
            continue
        candidates.append({"symbol": sym, "score": score_by.get(sym, 0) or 0,
                           "mv": mv, "qty": qty})
    candidates.sort(key=lambda c: c["score"])

    rotation_cap = equity * max_rotation_pct / 100.0
    plan, freed = [], 0.0
    for c in candidates:
        if len(plan) >= max_rotations or need <= 0:
            break
        if freed + c["mv"] > rotation_cap:
            continue  # would breach the daily rotation cap — skip this (larger) name
        if best_buy_conf - c["score"] < rotation_edge:
            continue  # not enough conviction edge to justify the swap
        plan.append({
            "symbol": c["symbol"], "qty": c["qty"], "side": "sell",
            "est_value": round(c["mv"], 2), "score": round(c["score"], 3),
            "reason": (f"rotate out of HOLD {c['symbol']} (conf {c['score']:.2f}) to fund "
                       f"higher-conviction BUY (top conf {best_buy_conf:.2f})"),
        })
        freed += c["mv"]
        need -= c["mv"]
    return plan


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
