#!/usr/bin/env python3
"""P3 allocator sleeve — crisis_core_v1, scaled to P3's caps, PAPER FORWARD TEST.

FORWARD TEST of a strategy that FAILED its backtest promotion gate (max DD
14.8% > 12%, DSR 0.90 < 0.95; docs/research/STRATEGY_LAB_RESULTS_2026-10.md).
Paper only — this is a measurement of live tracking vs the scaled backtest, not
a promotion. Pre-registration: docs/specs/crisis_core_v1_forward.json.

What it does (once per ET session, inside p3-trading, before the quarantined
legacy path):
  * enabled ONLY by the human-owned ``portfolio_3.allocator`` block in
    config/strategy_controls.json (shared.strategy_controls.allocator_control);
    missing / malformed => disabled, no orders (fail closed). Independent of
    ``new_entries_enabled`` — the legacy event-driven entries stay quarantined.
  * targets = the REAL ``scripts/backtest/allocators.crisis_core_target_weights``
    (11.4% per risky ETF, T-bill basket remainder) multiplied by an explicit
    ``scale`` = live_cap / spec_cap, where live_cap = P3 hard per-symbol cap (8%)
    minus drift headroom (0.4pp) = 7.6%. Every weight, the band (2% x scale ~
    1.33% of equity, absolute) and the drift guard (12% x scale = 8%) scale the
    same way. Residual = cash.
  * monthly: targets are frozen per calendar month from the latest completed
    close (= prior month-end close on the first session of the month; the latest
    close on a catch-up run). The month is done only when every order placed
    for it filled completely, nothing was deferred by the trade budget and no
    buy was clipped by a P3 limit; until then each new session retries the
    diff against the SAME frozen targets.
  * the universe is the only thing it trades. Legacy P3 lots are never sold:
    allocator-owned qty is the sum of open trade-log lots tagged
    ``tranche == allocator_forward_test`` (or ``order_class`` of that name,
    stamped by the EOD reconcile from the ``p3alloc`` client_order_id prefix).
  * exits/trims first (fresh account read afterwards), then buys by |delta w|
    descending, capped by P3's shared ``max_trades_per_day``; buys are scaled
    down pro rata to fit min(cash room, gross-exposure room). Never sells legacy.
  * marketable DAY limits off the live quote (ask x (1+slip) / bid x (1-slip)),
    whole shares, deterministic ``p3alloc`` client_order_id, real fills booked
    via confirm_fill; a non-terminal order is held as pending and booked only
    once it is terminal (at the next run or the EOD journal). A 422 is a
    duplicate only if the broker holds that client_order_id.
  * P3 halt / daily-loss kill switch / failed preflight => no buys (trims and
    drift trims still run; a failed preflight blocks everything).

Pure-stdlib + requests (cloud-path purity).
"""
import json
import logging
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.append(_SCRIPTS)  # appended: never shadows P3's own modules

import shared.preflight as preflight_mod  # noqa: E402
from backtest.allocators import (  # noqa: E402
    CRISIS_DEFAULTS,
    TBILL_BASKET,
    crisis_core_target_weights,
)
from shared.accounting import realized_pnl  # noqa: E402
from shared.alpaca_http import confirm_fill, make_client_order_id  # noqa: E402
from shared.order_state import TERMINAL  # noqa: E402
from shared.reconcile import is_open_trade  # noqa: E402
from shared.strategy_controls import allocator_control  # noqa: E402

log = logging.getLogger("p3_allocator")

PORTFOLIO_ID = "portfolio_3"
CONTROL_STRATEGY = "crisis_core_v1"
STRATEGY_TAG = "crisis_core_v1_scaled"
TRANCHE = "allocator_forward_test"
COID_PREFIX = "p3alloc"
STATE_FILE = "allocator_state.json"
UNIVERSE = (tuple(CRISIS_DEFAULTS["equity"]) + tuple(CRISIS_DEFAULTS["managed_futures"])
            + tuple(CRISIS_DEFAULTS["ballast"]) + tuple(TBILL_BASKET))
FORWARD_TEST_NOTE = ("FORWARD TEST of a strategy that FAILED its backtest promotion gate "
                     "(DD 14.8% > 12%, DSR 0.90 < 0.95) — paper only, not a promotion")

# Spec constants (docs/specs/crisis_core_v1.json; a test pins them to the file)
# and the live-execution knobs. The scale is DERIVED, never a hidden constant.
DEFAULTS = {
    "spec_cap": CRISIS_DEFAULTS["cap"],  # 0.114 per ETF in the tested spec
    "spec_band": 0.02,                   # spec no-trade band
    "spec_drift_trigger": 0.12,          # spec drift guard (weight > 12% => trim)
    "drift_headroom": 0.004,             # live_cap = hard cap - 0.4pp
    "slip": 0.0025,                      # marketable-limit offset off the quote
    "max_spread_pct": 1.0,               # wider/crossed quote => use last trade
    "cash_buffer_pct": 0.005,            # cash never spent below 0.5% of equity
    "min_order_notional": 250.0,         # no dust top-ups / trims
}
MAX_ORDER_RECORDS = 500
MAX_SESSION_RECORDS = 400
# Statuses whose filled_qty is FINAL for the order. ``done_for_day`` is not
# final (a DAY order still expires after it), so it stays pending.
FINAL = frozenset(TERMINAL) - {"done_for_day"}
# Run outcomes that must fail the workflow step (exit non-zero).
FAILURE_STATUSES = {"limits_invalid", "preflight_failed", "snapshot_failed",
                    "snapshot_incomplete", "refused_not_paper", "broker_orders_unavailable"}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def session_date_et(now=None):
    from zoneinfo import ZoneInfo
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def build_params(limits, **overrides):
    """Live parameters from P3's risk limits (read-only) + explicit scaling.

    scale = live_cap / spec_cap with live_cap = hard_cap - drift_headroom.
    Raises ValueError/KeyError on a missing/invalid cap (caller fails closed)."""
    p = dict(DEFAULTS)
    p.update(overrides)
    hard = float(limits["max_position_pct_per_symbol"]) / 100.0
    live_cap = hard - float(p["drift_headroom"])
    if not (0.0 < live_cap <= hard) or float(p["spec_cap"]) <= 0:
        raise ValueError(f"invalid cap geometry: hard={hard} live_cap={live_cap}")
    scale = live_cap / float(p["spec_cap"])
    p.update({
        "hard_cap": hard,
        "live_cap": live_cap,
        "scale": scale,
        "band": float(p["spec_band"]) * scale,
        "drift_trigger": min(float(p["spec_drift_trigger"]) * scale, hard),
        "max_gross": float(limits.get("max_gross_exposure_pct", 80.0)) / 100.0,
        "max_trades_per_day": int(limits["max_trades_per_day"]),
        "min_new_position_notional": float(limits.get("min_position_notional_usd", 0) or 0),
        "kill_switch_daily_loss_pct": float(limits.get("kill_switch_daily_loss_pct", 5.0)),
    })
    return p


def spec_target_weights(available):
    """The tested spec's weights via the REAL allocator; ``available`` = symbols
    with a close at the snapshot."""
    closes = {s: ([1.0] if s in available else [None]) for s in UNIVERSE}
    return crisis_core_target_weights(closes, 0)


def scale_targets(raw, params):
    """Every spec weight x scale. Each result is <= live_cap (asserted)."""
    out = {}
    for s, w in raw.items():
        sw = round(float(w) * params["scale"], 10)
        if sw > params["live_cap"] + 1e-9:
            raise ValueError(f"scaled weight {s}={sw} exceeds live cap {params['live_cap']}")
        if sw > 0:
            out[s] = sw
    return out


def is_allocator_lot(t):
    return isinstance(t, dict) and (t.get("tranche") == TRANCHE or t.get("order_class") == TRANCHE)


def _open_allocator_rows(trade_log, symbol=None):
    """Open allocator lots, counting each broker order_id ONCE (a row duplicated
    by a concurrent run + the trade-log list merge must never double holdings)."""
    seen, out = set(), []
    for t in trade_log or []:
        if not (is_allocator_lot(t) and is_open_trade(t) and t.get("symbol")):
            continue
        if symbol is not None and t.get("symbol") != symbol:
            continue
        oid = t.get("order_id")
        if oid:
            if oid in seen:
                continue
            seen.add(oid)
        out.append(t)
    return out


def void_duplicate_allocator_rows(trade_log):
    """Mark an open allocator row whose broker order_id already has an EARLIER
    open allocator row as ``void_duplicate`` (not open, no P&L). Returns count."""
    keep = {id(t) for t in _open_allocator_rows(trade_log)}
    n = 0
    for t in trade_log or []:
        if (is_allocator_lot(t) and is_open_trade(t) and t.get("order_id")
                and id(t) not in keep):
            t.update(status="void_duplicate", pnl=None, realized_pnl=None,
                     void_reason="duplicate booking of an order_id already booked")
            n += 1
    return n


def allocator_holdings(trade_log):
    """{symbol: qty} of OPEN allocator lots (the only qty the allocator may sell)."""
    out = {}
    for t in _open_allocator_rows(trade_log):
        try:
            q = abs(float(t.get("qty") or 0))
        except (TypeError, ValueError):
            continue
        out[t["symbol"]] = out.get(t["symbol"], 0.0) + q
    return out


def legacy_holdings(positions, alloc_qty):
    """Broker qty NOT owned by the allocator, per symbol (never traded here)."""
    out = {}
    for p in positions or []:
        s = p.get("symbol")
        try:
            q = float(p.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        if not s or q <= 0:
            continue
        out[s] = max(0.0, q - alloc_qty.get(s, 0.0))
    return out


def marketable_limits(quote, last, params):
    """(buy_limit, sell_limit, quote_ok) off a quote dict {bp, ap}; a missing,
    crossed or too-wide quote falls back to the last trade price."""
    try:
        bid, ask = float(quote.get("bp") or 0), float(quote.get("ap") or 0)
    except (TypeError, ValueError, AttributeError):
        bid = ask = 0.0
    sane = (bid > 0 and ask > 0 and ask >= bid
            and (ask - bid) / ((ask + bid) / 2) * 100 <= params["max_spread_pct"])
    buy_ref = ask if sane else last
    sell_ref = bid if sane else last
    if not buy_ref or not sell_ref or buy_ref <= 0 or sell_ref <= 0:
        return None, None, False
    return (round(buy_ref * (1 + params["slip"]), 2),
            round(sell_ref * (1 - params["slip"]), 2), sane)


def plan_rebalance(targets, equity, alloc_qty, legacy_qty, prices, params, *,
                   drift_only=False):
    """Desired orders before the trade budget and buy-room fit. Pure.

    Returns (sells, buys, skips). Sells sorted before buys, each by |delta w|
    descending then symbol (deterministic). Sells never exceed allocator-owned
    qty. Buys are floored to whole shares and bounded so the symbol's TOTAL
    position (allocator + any legacy lot) stays <= live_cap at max(last, limit)."""
    sells, buys, skips = [], [], []
    if equity <= 0:
        return sells, buys, [{"symbol": "*", "reason": "equity <= 0"}]
    syms = sorted(set(targets) | {s for s, q in alloc_qty.items() if q > 0})
    for sym in syms:
        aq = float(alloc_qty.get(sym, 0.0))
        lq = float(legacy_qty.get(sym, 0.0))
        tgt = float(targets.get(sym, 0.0))
        px = prices.get(sym) or {}
        last = float(px.get("last") or 0)
        if last <= 0:
            skips.append({"symbol": sym, "reason": "no live price", "blocking": True})
            continue
        cur_w = aq * last / equity
        tot_w = (aq + lq) * last / equity
        delta = tgt - cur_w
        over_live = aq > 0 and tot_w > params["live_cap"] + 1e-9
        if drift_only:
            if not (aq > 0 and tot_w > params["drift_trigger"] + 1e-9):
                continue
        elif not (abs(delta) >= params["band"] - 1e-12 or (tgt <= 0 < aq) or over_live):
            continue
        base = {"symbol": sym, "last": last, "cur_w": round(cur_w, 6), "tgt_w": round(tgt, 6),
                "delta_w": round(delta, 6), "tot_w": round(tot_w, 6)}
        if delta < 0 or over_live or drift_only:
            if aq <= 0:
                continue
            limit = px.get("sell_limit")
            if not limit or limit <= 0:
                skips.append({"symbol": sym, "reason": "no sell quote", "blocking": True})
                continue
            if tgt <= 0:
                qty = aq
            else:
                need_w = max(cur_w - tgt, tot_w - params["live_cap"], 0.0)
                qty = min(aq, float(math.ceil(need_w * equity / last - 1e-9)))
            if qty <= 0:
                continue
            if qty * last < params["min_order_notional"] and tgt > 0 and not over_live:
                skips.append({"symbol": sym, "reason": "trim below min order notional"})
                continue
            reason = ("drift_trim" if drift_only else "cap_trim" if over_live
                      else "exit" if tgt <= 0 else "rebalance_trim")
            sells.append(dict(base, side="sell", qty=qty, limit_price=limit, reason=reason))
        elif delta > 0:
            limit = px.get("buy_limit")
            if not limit or limit <= 0:
                skips.append({"symbol": sym, "reason": "no buy quote", "blocking": True})
                continue
            cap_px = max(last, float(limit))
            room_cap = params["live_cap"] * equity - (aq + lq) * cap_px
            want = min(delta * equity, room_cap)
            # Underweight forced by the per-symbol cap (a legacy lot in the name).
            cap_short_w = max(0.0, delta * equity - max(room_cap, 0.0)) / equity
            qty = float(math.floor(want / cap_px + 1e-9)) if want > 0 else 0.0
            if qty < 1:
                skips.append({"symbol": sym, "reason": "below 1 whole share",
                              "cap_short_w": round(cap_short_w, 8)})
                continue
            notional = qty * float(limit)
            if aq + lq <= 0 and notional < params["min_new_position_notional"]:
                skips.append({"symbol": sym, "reason": "new position below P3 min notional"})
                continue
            if notional < params["min_order_notional"]:
                skips.append({"symbol": sym, "reason": "buy below min order notional"})
                continue
            if (aq + lq + qty) * cap_px > params["hard_cap"] * equity + 1e-6:
                skips.append({"symbol": sym, "reason": "would breach hard cap", "blocking": True})
                continue
            buys.append(dict(base, side="buy", qty=qty, limit_price=float(limit),
                             cap_short_w=round(cap_short_w, 8),
                             reason="rebalance_buy" if aq > 0 else "initial_buy"))
    key = (lambda o: (-abs(o["delta_w"]), o["symbol"]))
    return sorted(sells, key=key), sorted(buys, key=key), skips


def select_by_budget(orders, slots):
    slots = max(0, int(slots))
    return list(orders[:slots]), list(orders[slots:])


def fit_buys_to_room(buys, room, params):
    """Scale buys pro rata so their limit notional fits ``room`` (cash/gross).
    Returns (fitted, factor, clipped)."""
    total = sum(b["qty"] * b["limit_price"] for b in buys)
    if total <= 0 or total <= room:
        return list(buys), 1.0, []
    f = max(0.0, room) / total
    fitted, clipped = [], []
    for b in buys:
        q = float(math.floor(b["qty"] * f + 1e-9))
        notional = q * b["limit_price"]
        new_pos = b["cur_w"] <= 0 and b["tot_w"] <= 0
        if (q < 1 or notional < params["min_order_notional"]
                or (new_pos and notional < params["min_new_position_notional"])):
            clipped.append(dict(b, qty=q, reason_skipped="room clipped below minimum"))
            continue
        fitted.append(dict(b, qty=q, scaled_by=round(f, 6)))
    return fitted, f, clipped


def constrained_targets(targets, equity, selected_buys, fitted, skips):
    """The CAP-CONSTRAINED target the engine actually pursued this session
    (forward-spec F1 benchmark) and the cap shortfall (pct of equity).

    Shortfall = underweight forced by P3 limits only: the per-symbol cap on a
    name with a legacy lot, and the pro-rata cash / gross-exposure clip. Band,
    budget deferral and halts are NOT cap shortfall."""
    short = {}
    fitted_qty = {b["symbol"]: b["qty"] for b in fitted}
    for b in selected_buys:
        s = b["symbol"]
        clip_w = (b["qty"] - fitted_qty.get(s, 0.0)) * b["last"] / equity if equity > 0 else 0.0
        short[s] = short.get(s, 0.0) + float(b.get("cap_short_w") or 0.0) + max(0.0, clip_w)
    for k in skips or []:
        if k.get("cap_short_w"):
            short[k["symbol"]] = short.get(k["symbol"], 0.0) + float(k["cap_short_w"])
    out = {s: round(max(0.0, w - min(short.get(s, 0.0), w)), 8) for s, w in targets.items()}
    shortfall = sum(min(short.get(s, 0.0), w) for s, w in targets.items())
    return out, round(shortfall * 100, 4)


def run_failed(result):
    """True when an allocator run must fail its workflow step: a fail-closed
    status, or any order that errored / was rejected."""
    if not isinstance(result, dict):
        return True
    if result.get("status") in FAILURE_STATUSES:
        return True
    return any(str(o.get("status")) in ("error", "rejected_422")
               for o in result.get("orders") or [])


def foreign_session_orders(alpaca, state, session_date):
    """p3alloc orders at the BROKER for this ET session that this run's state
    does not know — another (concurrent or committed-later) run traded today."""
    start = datetime.fromisoformat(session_date)
    from zoneinfo import ZoneInfo
    after = start.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc).isoformat()
    orders = alpaca.get_orders(status="all", after=after, limit=500) or []
    prefix = f"{COID_PREFIX}-{session_date.replace('-', '')}-"
    known = set(((state or {}).get("orders") or {}).keys())
    return sorted({o.get("client_order_id") for o in orders
                   if str(o.get("client_order_id") or "").startswith(prefix)
                   and o.get("client_order_id") not in known})


def buy_room(account, positions, open_orders, params):
    """USD available for allocator buys: min(cash room, gross-exposure room)."""
    equity = float(account.get("equity") or 0)
    cash = float(account.get("cash") or 0)
    working = 0.0
    for o in open_orders or []:
        if o.get("side") != "buy":
            continue
        try:
            rem = float(o.get("qty") or 0) - float(o.get("filled_qty") or 0)
            px = float(o.get("limit_price") or 0)
        except (TypeError, ValueError):
            continue
        working += max(0.0, rem) * px
    gross = sum(abs(float(p.get("market_value") or 0)) for p in positions or [])
    cash_room = cash - working - params["cash_buffer_pct"] * equity
    gross_room = params["max_gross"] * equity - gross - working
    return max(0.0, min(cash_room, gross_room)), {
        "cash": round(cash, 2), "working_buy_notional": round(working, 2),
        "gross_mv": round(gross, 2), "cash_room": round(cash_room, 2),
        "gross_room": round(gross_room, 2)}


def trades_used_today(trade_log, state, session_date):
    """P3's shared daily trade count: legacy trade-log rows dated today plus
    every allocator order submitted this session."""
    legacy = sum(1 for t in trade_log or []
                 if str(t.get("date") or "").startswith(session_date) and not is_allocator_lot(t))
    return legacy + allocator_orders_on(session_date, state)


def allocator_orders_on(session_date, state=None, data_dir=None):
    """Allocator orders submitted on ``session_date`` (for the legacy path's
    shared max_trades_per_day count)."""
    if state is None:
        state = _load(Path(data_dir) / STATE_FILE, {})
    return sum(1 for o in ((state or {}).get("orders") or {}).values()
               if o.get("session") == session_date and o.get("order_id"))


def buys_block_reason(bot_state, account, params, session_date, now):
    """P3 halt or daily-loss kill-switch state => allocator BUYS blocked."""
    bs = bot_state or {}
    if bs.get("halted"):
        hu = bs.get("halt_until")
        expired = False
        if hu:
            try:
                expired = datetime.fromisoformat(str(hu)) <= now
            except ValueError:
                expired = False
        if not expired:
            return f"P3 halted ({bs.get('halt_reason') or 'no reason'})"
    try:
        equity = float(account.get("equity") or 0)
        if bs.get("day_start_date") == session_date and float(bs.get("day_start_equity") or 0) > 0:
            ds = float(bs["day_start_equity"])
        else:
            ds = float(account.get("last_equity") or 0)
    except (TypeError, ValueError):
        return "equity unreadable"
    if ds > 0 and (equity - ds) / ds * 100 <= -params["kill_switch_daily_loss_pct"]:
        return f"daily loss {(equity - ds) / ds * 100:.2f}% at/over kill switch"
    return None


# ---------------------------------------------------------------------------
# Booking (real fills only, idempotent by order)
# ---------------------------------------------------------------------------

def _already_booked(trade_log, order_id):
    return any(t.get("order_id") == order_id or t.get("exit_order_id") == order_id
               for t in trade_log if order_id)


def book_fill(trade_log, rec, filled_qty, fill_px, now_iso):
    """Book a TERMINAL order's real fill into the trade log. Returns booked qty."""
    oid = rec.get("order_id")
    if rec.get("booked") or _already_booked(trade_log, oid):
        rec["booked"] = True
        return 0.0
    rec["booked"] = True
    if not filled_qty or filled_qty <= 0 or not fill_px:
        return 0.0
    sym = rec["symbol"]
    if rec["side"] == "buy":
        ref = rec.get("ref_price") or rec.get("limit_price")
        trade_log.append({
            "timestamp": now_iso,
            "date": rec.get("session"),
            "symbol": sym,
            "side": "buy",
            "qty": filled_qty,
            "entry_price": round(fill_px, 4),
            "intended_price": ref,
            "limit_price": rec.get("limit_price"),
            "slippage_pct": round((fill_px - ref) / ref * 100, 4) if ref else None,
            "client_order_id": rec.get("client_order_id"),
            "order_id": oid,
            "order_status": rec.get("status"),
            "filled_qty": filled_qty,
            "trade_value": round(filled_qty * fill_px, 2),
            "sector": "ETF",
            "tranche": TRANCHE,
            "strategy": STRATEGY_TAG,
            "signal_type": "ALLOCATOR_REBALANCE",
            "signal_score": None,
            "reasons": [rec.get("reason_text") or rec.get("reason") or "allocator", FORWARD_TEST_NOTE],
            "status": "open",
        })
        return filled_qty
    # SELL: consume this sleeve's open lots FIFO at the real fill price.
    left = float(filled_qty)
    booked = 0.0
    lots = _open_allocator_rows(trade_log, symbol=sym)
    for t in lots:
        if left <= 1e-9:
            break
        lot_qty = float(t.get("qty") or 0)
        if lot_qty <= 0:
            continue
        take = min(lot_qty, left)
        if take < lot_qty - 1e-9:
            rest = dict(t)  # the unsold remainder stays open, in FIFO position
            rest["qty"] = round(lot_qty - take, 6)
            at = next(i for i, x in enumerate(trade_log) if x is t)
            trade_log.insert(at + 1, rest)
            t["qty"] = round(take, 6)
        entry = float(t.get("entry_price") or 0)
        pnl = realized_pnl("buy", take, entry, fill_px)["net_pnl"] if entry > 0 else None
        t.update({
            "status": "closed",
            "exit_price": round(fill_px, 4),
            "exit_timestamp": now_iso,
            "exit_reason": f"allocator_{rec.get('reason') or 'rebalance'}",
            "exit_order_id": oid,
            "exit_client_order_id": rec.get("client_order_id"),
            "pnl": pnl,
            "realized_pnl": pnl,
            "pnl_pct": round(pnl / (entry * take) * 100, 2) if pnl is not None and entry > 0 else None,
        })
        left -= take
        booked += take
    if left > 1e-6:
        rec["unbooked_qty"] = round(left, 6)
        log.warning(f"::warning::P3 allocator sell {sym} filled {filled_qty} but only "
                    f"{booked} allocator qty was open — remainder left to EOD reconcile")
    return booked


def settle_orders(alpaca, state, trade_log, now_iso, logger=None):
    """Book every not-yet-booked allocator order that has reached a terminal
    state at the broker. Non-terminal orders stay pending. Never raises."""
    lg = logger or log
    settled = 0
    for rec in (state.get("orders") or {}).values():
        if rec.get("booked") or not rec.get("order_id"):
            continue
        try:
            o = alpaca.get_order(rec["order_id"]) or {}
        except Exception as e:
            lg.warning(f"  allocator settle: could not read {rec['order_id']}: {e}")
            continue
        status = o.get("status", "unknown")
        rec["status"] = status
        if status not in FINAL:
            rec["pending"] = True
            continue
        fq = float(o.get("filled_qty") or 0)
        fap = o.get("filled_avg_price")
        fp = float(fap) if fap else None
        rec.update({"filled_qty": fq, "filled_avg_price": fp, "pending": False})
        book_fill(trade_log, rec, fq, fp, now_iso)
        settled += 1
    return settled


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def _load(path, default):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if data is not None else default
    except (OSError, ValueError):
        return default


def _save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _new_state():
    return {"strategy": CONTROL_STRATEGY, "strategy_tag": STRATEGY_TAG, "mode": "paper_forward_test",
            "note": FORWARD_TEST_NOTE, "last_rebalance_month": None, "targets_month": None,
            "targets_frozen_at": None, "targets": {}, "last_run_at": None,
            "last_trade_session": None, "orders": {}}


def _prune_orders(state):
    orders = state.get("orders") or {}
    if len(orders) <= MAX_ORDER_RECORDS:
        return
    keep = sorted(orders.items(), key=lambda kv: kv[1].get("submitted_at") or "")[-MAX_ORDER_RECORDS:]
    state["orders"] = dict(keep)


def settle_allocator_orders(alpaca, data_dir, logger=None, now=None):
    """EOD hook: settle pending allocator orders BEFORE the reconcile, so a fill
    is booked as an allocator lot (not as an untagged reconciled lot)."""
    data_dir = Path(data_dir)
    path = data_dir / STATE_FILE
    if not path.exists():
        return 0
    state = _load(path, None)
    if not isinstance(state, dict):
        return 0
    trade_log = _load(data_dir / "trade_log.json", [])
    now_iso = (now or datetime.now(timezone.utc)).isoformat()
    voided = void_duplicate_allocator_rows(trade_log)
    n = settle_orders(alpaca, state, trade_log, now_iso, logger)
    if n or voided:
        _save(data_dir / "trade_log.json", trade_log)
        state["last_updated"] = now_iso
        _save(path, state)
    return n


def _snapshot(alpaca, session_date, lookback_days=20):
    """{symbol: (date, close)} of the latest COMPLETED daily close before the
    session (end = session 00:00Z excludes today's bar). Raises on a gap."""
    start = (datetime.fromisoformat(session_date) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end = f"{session_date}T00:00:00Z"
    out = {}
    for s in UNIVERSE:
        bars = (alpaca.get_stock_bars(s, timeframe="1Day", start=start, limit=50, end=end) or {}).get("bars") or []
        bars = [b for b in bars if str(b.get("t", ""))[:10] < session_date and b.get("c")]
        if bars:
            out[s] = (str(bars[-1]["t"])[:10], float(bars[-1]["c"]))
    return out


def _live_prices(alpaca, symbols, params, positions_by_sym):
    out = {}
    for s in symbols:
        last = 0.0
        quote = {}
        try:
            last = float(((alpaca.get_latest_trade(s) or {}).get("trade") or {}).get("p") or 0)
        except Exception:
            last = 0.0
        try:
            quote = (alpaca.get_latest_quote(s) or {}).get("quote") or {}
        except Exception:
            quote = {}
        if last <= 0:
            try:
                last = float((positions_by_sym.get(s) or {}).get("current_price") or 0)
            except (TypeError, ValueError):
                last = 0.0
        if last <= 0:
            continue
        buy_l, sell_l, ok = marketable_limits(quote, last, params)
        out[s] = {"last": last, "bid": quote.get("bp"), "ask": quote.get("ap"),
                  "buy_limit": buy_l, "sell_limit": sell_l, "quote_ok": ok}
    return out


def _submit(alpaca, o, session_date, state, trade_log, now_iso, confirm, lg):
    """Place one marketable DAY limit. Returns the order record."""
    sym, side = o["symbol"], o["side"]
    coid = make_client_order_id(COID_PREFIX, sym, side, day=session_date.replace("-", ""))
    orders = state.setdefault("orders", {})
    rec = orders.get(coid) or {
        "client_order_id": coid, "symbol": sym, "side": side, "qty": o["qty"],
        "limit_price": o["limit_price"], "ref_price": o.get("last"), "session": session_date,
        "submitted_at": now_iso, "reason": o["reason"], "booked": False, "order_id": None,
        "reason_text": (f"crisis_core_v1 scaled target {o['tgt_w']:.2%} vs allocator "
                        f"{o['cur_w']:.2%} ({o['reason']})"),
    }
    orders[coid] = rec
    if rec.get("order_id"):
        lg.info(f"  {sym} {side}: order {rec['order_id']} already exists this session")
        return rec
    try:
        order = alpaca.place_order(symbol=sym, qty=o["qty"], side=side, order_type="limit",
                                   limit_price=o["limit_price"], time_in_force="day",
                                   client_order_id=coid)
    except requests.HTTPError as e:
        resp = getattr(e, "response", None)
        if resp is not None and resp.status_code == 422:
            prior = None
            try:
                prior = alpaca.get_order_by_client_id(coid) or {}
            except Exception as le:
                lg.error(f"::error::P3 allocator {sym} {side}: 422 and duplicate lookup failed ({le})")
            if prior and prior.get("id"):
                # Placed by ANOTHER run (we had no record of it). Never book it
                # here — that run may already have; settlement (next run / EOD,
                # on the merged trade log) books it once, by order_id.
                lg.warning(f"::warning::P3 allocator {sym} {side}: 422 resolved to existing "
                           f"order {prior['id']} — recorded as pending, not booked here")
                rec.update(order_id=prior.get("id"), duplicate=True, pending=True,
                           status=prior.get("status"))
                return rec
            else:
                rec.update(status="rejected_422", error=(resp.text or "")[:300])
                lg.error(f"::error::P3 allocator {sym} {side} rejected (422, no such "
                         f"client_order_id at broker): {(resp.text or '')[:200]}")
                return rec
        else:
            rec.update(status="error", error=str(e)[:300])
            lg.error(f"::error::P3 allocator order failed {sym} {side}: {e}")
            return rec
    except Exception as e:
        rec.update(status="error", error=str(e)[:300])
        lg.error(f"::error::P3 allocator order failed {sym} {side}: {e}")
        return rec
    rec["order_id"] = order.get("id")
    status, fq, fp = confirm(alpaca, rec["order_id"])
    rec.update(status=status, filled_qty=fq, filled_avg_price=fp)
    if status in FINAL:
        rec["pending"] = False
        book_fill(trade_log, rec, fq, fp, now_iso)
    else:
        rec["pending"] = True  # booked by settle_orders once terminal (next run / EOD)
    lg.info(f"  ALLOC {side.upper()} {o['qty']:g} {sym} @lmt {o['limit_price']:.2f} -> "
            f"{status} filled {fq:g}{f' @ {fp:.4f}' if fp else ''} ({o['reason']})")
    return rec


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def run_allocator(alpaca, *, data_dir, config_dir, controls=None, now=None,
                  confirm=None, logger=None):
    """One allocator session. Returns a summary dict (also stored as last_run)."""
    lg = logger or log
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    confirm = confirm or (lambda c, oid: confirm_fill(c, oid, logger=lg))
    data_dir, config_dir = Path(data_dir), Path(config_dir)
    state_path = data_dir / STATE_FILE
    tl_path = data_dir / "trade_log.json"
    summary = {"at": now_iso, "orders": [], "skips": [], "deferred": [], "clipped": []}

    state = _load(state_path, None)
    if not isinstance(state, dict):
        state = None
    trade_log = _load(tl_path, [])
    voided = void_duplicate_allocator_rows(trade_log)
    if voided:
        lg.warning(f"::warning::P3 allocator voided {voided} duplicate allocator row(s) "
                   f"(same broker order_id booked twice)")

    def _persist():
        if state is None:
            return
        _prune_orders(state)
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        _save(state_path, state)
        _save(tl_path, trade_log)

    problems = []
    control = allocator_control(PORTFOLIO_ID, controls=controls, problems=problems)
    enabled = control is not None and control.get("strategy") == CONTROL_STRATEGY
    session = session_date_et(now)
    if state is None and not enabled:
        lg.info(f"P3 allocator disabled: {'; '.join(problems) or 'not crisis_core_v1'}")
        return dict(summary, status="disabled", detail=problems)

    # Broker truth before ANY write: a p3alloc order for this session that our
    # state does not know means another run (a racing Guardian catch-up, or a
    # run whose commit we have not pulled) traded today. Our checkout is stale:
    # write nothing (its allocator_state would win the snapshot merge whole and
    # its trade log lacks those fills), trade nothing.
    try:
        foreign = foreign_session_orders(alpaca, state, session)
    except Exception as e:
        lg.error(f"::error::P3 allocator: broker order history unavailable ({e}) — "
                 f"no settlement, no orders (fail closed)")
        return dict(summary, status="broker_orders_unavailable")
    if foreign:
        lg.warning(f"::warning::P3 allocator: {len(foreign)} p3alloc order(s) for {session} "
                   f"exist at the broker but not in this checkout's state {foreign[:3]} — "
                   f"another run traded this session; stale checkout, doing nothing")
        return dict(summary, status="concurrent_run_detected", foreign=foreign)

    # Real fills of orders already placed are booked even when disabled.
    settled = 0
    if state is not None and any(not r.get("booked") and r.get("order_id")
                                 for r in (state.get("orders") or {}).values()):
        settled = settle_orders(alpaca, state, trade_log, now_iso, lg)
    if state is not None and (voided or settled):
        _persist()

    if not enabled:
        lg.info(f"P3 allocator disabled: {'; '.join(problems) or 'not crisis_core_v1'}")
        return dict(summary, status="disabled", detail=problems)
    if "paper-api" not in str(getattr(alpaca, "base_url", "")):
        lg.error("::error::P3 allocator refused: broker base_url is not the PAPER endpoint")
        return dict(summary, status="refused_not_paper")
    if not alpaca.is_market_open():
        lg.info("Market closed — P3 allocator skipped")
        return dict(summary, status="market_closed")

    if state is None:
        state = _new_state()
    month = session[:7]
    if state.get("last_trade_session") == session:
        lg.info(f"P3 allocator already traded session {session} — settle-only")
        return dict(summary, status="already_ran_today")

    def _finish(status, **extra):
        state["last_run_at"] = now_iso
        state["last_run"] = dict(summary, status=status, session=session, **extra)
        _persist()
        return state["last_run"]

    try:
        limits = _load(config_dir / "risk_limits.json", None)
        params = build_params(limits or {})
    except (KeyError, ValueError, TypeError) as e:
        lg.error(f"::error::P3 allocator: risk limits unusable ({e}) — no orders (fail closed)")
        return _finish("limits_invalid")

    account = alpaca.get_account()
    pf_ok, pf = preflight_mod.run_preflight(limits=limits, account=account, portfolio_id=PORTFOLIO_ID)
    if not pf_ok:
        for f in pf.get("hard_failures", []):
            lg.error(f"::error::P3 allocator PREFLIGHT FAILED: {f}")
        return _finish("preflight_failed", preflight=pf.get("hard_failures"))

    bot_state = _load(data_dir / "bot_state.json", {})
    block = buys_block_reason(bot_state, account, params, session, now)
    if block:
        lg.warning(f"::warning::P3 allocator BUYS blocked: {block} (trims still allowed)")

    # ---- targets: frozen per month ---------------------------------------
    done = state.get("last_rebalance_month") == month
    if not done and not (state.get("targets_month") == month and state.get("targets")):
        try:
            snap = _snapshot(alpaca, session)
        except Exception as e:
            lg.error(f"::error::P3 allocator snapshot failed ({e}) — no orders (fail closed)")
            return _finish("snapshot_failed")
        missing = [s for s in UNIVERSE if s not in snap]
        snap_date = max((d for d, _ in snap.values()), default=None)
        stale = [s for s, (d, _) in snap.items() if d != snap_date]
        if missing or stale:
            lg.error(f"::error::P3 allocator snapshot incomplete (missing={missing}, "
                     f"stale={stale}) — no orders; a data gap is never read as 'unlisted'")
            return _finish("snapshot_incomplete", missing=missing, stale=stale)
        raw = spec_target_weights(set(snap))
        state.update({
            "targets_month": month, "targets_frozen_at": snap_date,
            "spec_weights": raw, "targets": scale_targets(raw, params),
            "snapshot_closes": {s: c for s, (_, c) in snap.items()},
            "scale": round(params["scale"], 8), "band": round(params["band"], 8),
            "live_cap": params["live_cap"], "hard_cap": params["hard_cap"],
        })
        lg.info(f"P3 allocator: froze {month} targets from {snap_date} close "
                f"(scale {params['scale']:.4f}, band {params['band']:.4%})")
    targets = state.get("targets") or {}

    positions = alpaca.get_positions() or []
    pos_by_sym = {p.get("symbol"): p for p in positions}
    equity = float(account.get("equity") or 0)
    alloc_qty = allocator_holdings(trade_log)
    legacy_qty = legacy_holdings(positions, alloc_qty)
    prices = _live_prices(alpaca, sorted(set(targets) | set(alloc_qty)), params, pos_by_sym)
    slots = params["max_trades_per_day"] - trades_used_today(trade_log, state, session)

    # ---- phase 1: exits / trims (allowed even when buys are blocked) --------
    sells, buys, skips = plan_rebalance(targets, equity, alloc_qty, legacy_qty, prices, params,
                                        drift_only=done)
    summary["skips"] += skips
    planned_any = bool(sells or buys)
    sel_sells, deferred = select_by_budget(sells, slots)
    summary["deferred"] += [d["symbol"] + ":sell" for d in deferred]
    placed = []
    for o in sel_sells:
        placed.append(_submit(alpaca, o, session, state, trade_log, now_iso, confirm, lg))
        _persist()
    slots -= len(sel_sells)

    # ---- phase 2: buys on a FRESH read (sold notional is now real) ----------
    clipped_factor = 1.0
    sel_buys_rec, fitted_rec, skips_rec = [], [], []
    if buys and not done:
        if block:
            summary["skips"] += [{"symbol": b["symbol"], "reason": f"buy blocked: {block}"} for b in buys]
        else:
            account = alpaca.get_account()
            positions = alpaca.get_positions() or []
            alloc_qty = allocator_holdings(trade_log)
            legacy_qty = legacy_holdings(positions, alloc_qty)
            equity = float(account.get("equity") or 0)
            _s, buys, skips2 = plan_rebalance(targets, equity, alloc_qty, legacy_qty, prices, params)
            summary["skips"] += skips2
            sel_buys, deferred_b = select_by_budget(buys, slots)
            summary["deferred"] += [d["symbol"] + ":buy" for d in deferred_b]
            room, room_detail = buy_room(account, positions, alpaca.get_orders(status="open") or [], params)
            fitted, clipped_factor, clipped = fit_buys_to_room(sel_buys, room, params)
            sel_buys_rec, fitted_rec, skips_rec = sel_buys, fitted, skips2
            summary["clipped"] += [c["symbol"] for c in clipped]
            summary["room"] = dict(room_detail, room=round(room, 2), factor=round(clipped_factor, 6))
            if clipped_factor < 1:
                lg.warning(f"::warning::P3 allocator buys scaled x{clipped_factor:.3f} to fit "
                           f"P3 limits (room ${room:,.0f}; legacy positions are never sold)")
            for o in fitted:
                placed.append(_submit(alpaca, o, session, state, trade_log, now_iso, confirm, lg))
                _persist()

    summary["orders"] = [{k: r.get(k) for k in ("client_order_id", "symbol", "side", "qty",
                                                 "limit_price", "status", "filled_qty",
                                                 "filled_avg_price", "order_id")} for r in placed]
    all_filled = all(r.get("status") == "filled" and abs(float(r.get("filled_qty") or 0)
                                                         - float(r.get("qty") or 0)) < 1e-9
                     for r in placed)
    seen, uniq = set(), []
    for k in summary["skips"]:
        if (k.get("symbol"), k.get("reason")) not in seen:
            seen.add((k.get("symbol"), k.get("reason")))
            uniq.append(k)
    summary["skips"] = uniq
    blocking_skips = [k for k in uniq if k.get("blocking")]
    incomplete = (summary["deferred"] or summary["clipped"] or clipped_factor < 1
                  or not all_filled or (buys and block and not done) or blocking_skips)
    # Complete ONLY when nothing is incomplete: a run that planned nothing
    # because prices/quotes were missing (blocking skips) stays in progress.
    c_targets, shortfall = constrained_targets(targets, equity, sel_buys_rec, fitted_rec, skips_rec)
    sessions = state.setdefault("session_targets", {})
    sessions[session] = {"equity": round(equity, 2), "targets": targets,
                         "targets_constrained": c_targets, "cap_shortfall_pct": shortfall,
                         "room_factor": round(clipped_factor, 6), "buys_blocked": block,
                         "deferred": list(summary["deferred"])}
    for old in sorted(sessions)[:-MAX_SESSION_RECORDS]:
        sessions.pop(old)
    state["targets_constrained"] = c_targets
    state["cap_shortfall_pct"] = shortfall
    summary["cap_shortfall_pct"] = shortfall
    if not done and not incomplete:
        state["last_rebalance_month"] = month
        status = "month_complete"
    elif done:
        status = "drift_check" if planned_any else "month_already_complete"
    else:
        status = "month_in_progress"
    state["last_trade_session"] = session
    lg.info(f"P3 allocator {status}: {len(placed)} order(s), deferred={summary['deferred']}, "
            f"clipped={summary['clipped']}")
    return _finish(status, buys_blocked=block)
