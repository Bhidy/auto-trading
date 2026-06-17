"""
Shared position/trade-log reconciliation — used by all three portfolios so the
integrity audit is identical everywhere.

Pure, dependency-free. Each bot builds its inputs from its own schema and writes
its own report file; the drift logic lives here once.
"""
import copy
from datetime import datetime, timezone


def is_open_trade(t):
    """Open-trade predicate shared by all bots.

    A missing ``status`` means open (P3 legacy entries carry no status field),
    while any explicit closed* status (``closed`` or ``closed_reconciled``) is
    not-open. Use this everywhere the open set is built so the three bots agree.
    """
    return t.get("status", "open") == "open"


def _num(x):
    try:
        return abs(float(x))
    except (TypeError, ValueError):
        return None


def _qty_weighted_avg(trades):
    """Quantity-weighted average entry price across a symbol's open trades."""
    num = 0.0
    den = 0.0
    for t in trades:
        q = _num(t.get("qty"))
        p = _num(t.get("entry_price") if t.get("entry_price") is not None
                 else t.get("avg_price"))
        if q and p:
            num += q * p
            den += q
    return (num / den) if den else None


def compute_drift(position_symbols, open_trade_symbols, positions=None,
                  open_trades=None, qty_tol=1e-6, price_tol_pct=1.0):
    """Compare broker positions against the trade log's open positions.

    Symbol-level drift (always computed):
      * orphan_open_trades  — logged 'open' but no live position (exit not logged)
      * unlogged_positions  — live position with no open trade (entry not logged,
                              e.g. a limit that filled after the confirm window)

    Quantity / cost-basis drift (computed only when the detailed `positions` and
    `open_trades` record lists are supplied — C6). A wrong share count or wrong
    average price (a partial fill or a missed corporate action) is invisible to a
    pure symbol-set check yet silently corrupts risk and P&L, so for any symbol
    held in BOTH the broker and the log we compare:
      * qty_drift          — |broker_qty - summed_logged_qty| > qty_tol
      * cost_basis_drift   — |broker_avg - logged_qty_weighted_avg| exceeds
                             price_tol_pct of the logged average

    `positions`:  Alpaca position records (symbol, qty, avg_entry_price).
    `open_trades`: trade-log open records (symbol, qty, entry_price).
    Backward compatible: with only the two symbol lists, the qty/cost-basis lists
    are empty and `in_sync` keeps its original meaning.
    """
    pos = {s for s in position_symbols if s}
    opn = {s for s in open_trade_symbols if s}
    orphan = sorted(opn - pos)
    unlogged = sorted(pos - opn)

    qty_drift = []
    cost_basis_drift = []
    if positions is not None and open_trades is not None:
        pos_by_sym = {p.get("symbol"): p for p in positions if p.get("symbol")}
        log_by_sym = {}
        for t in open_trades:
            s = t.get("symbol")
            if s and t.get("status", "open") == "open":
                log_by_sym.setdefault(s, []).append(t)

        for sym in sorted(set(pos_by_sym) & set(log_by_sym)):
            p = pos_by_sym[sym]
            trades = log_by_sym[sym]
            broker_qty = _num(p.get("qty"))
            logged_qty = sum(_num(t.get("qty")) or 0.0 for t in trades)
            if broker_qty is not None and abs(broker_qty - logged_qty) > qty_tol:
                qty_drift.append({
                    "symbol": sym,
                    "broker_qty": broker_qty,
                    "logged_qty": logged_qty,
                })

            broker_avg = _num(p.get("avg_entry_price") or p.get("avg_price"))
            logged_avg = _qty_weighted_avg(trades)
            if (broker_avg and logged_avg
                    and abs(broker_avg - logged_avg) / logged_avg * 100 > price_tol_pct):
                cost_basis_drift.append({
                    "symbol": sym,
                    "broker_avg_price": round(broker_avg, 4),
                    "logged_avg_price": round(logged_avg, 4),
                    "drift_pct": round(abs(broker_avg - logged_avg) / logged_avg * 100, 3),
                })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "positions_held": len(pos),
        "open_trades_logged": len(opn),
        "orphan_open_trades": orphan,
        "unlogged_positions": unlogged,
        "qty_drift": qty_drift,
        "cost_basis_drift": cost_basis_drift,
        "in_sync": not orphan and not unlogged and not qty_drift and not cost_basis_drift,
    }


def working_orders_report(open_orders):
    """Summarize still-working (unfilled/partial) orders — the unfilled-limit
    surface, relevant to portfolios that use limit entries (P2). Read-only.
    """
    working = []
    for o in open_orders or []:
        status = o.get("status", "")
        if status in ("new", "accepted", "partially_filled", "pending_new", "held"):
            working.append({
                "symbol": o.get("symbol"),
                "side": o.get("side"),
                "qty": o.get("qty"),
                "filled_qty": o.get("filled_qty"),
                "limit_price": o.get("limit_price"),
                "status": status,
                "submitted_at": o.get("submitted_at") or o.get("created_at"),
            })
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "working_orders": working,
        "working_count": len(working),
    }


def _slip_bps(side, intended, fill):
    """Signed ADVERSE slippage in bps: positive = worse than intended for either
    side (buy filled above intended, or sell filled below intended)."""
    if not intended or not fill:
        return None
    if str(side).lower().startswith("s"):  # sell
        return (intended - fill) / intended * 10_000.0
    return (fill - intended) / intended * 10_000.0  # buy (default)


def fill_reconciliation_report(trade_log, fill_activities, *, slippage_p90_bps=None):
    """Expected-vs-actual FILL reconciliation (READ-ONLY; places NO orders).

    ``compute_drift`` checks symbol/qty/cost-basis vs live *positions*; this is the
    complementary check against the broker's authoritative *FILL activities*
    (Alpaca account activities, ``activity_type == 'FILL'``). It joins each logged
    order to its broker fills on ``order_id`` (preferred) or ``client_order_id`` and
    surfaces three classes of execution problem:

      * slippage_outliers — realized adverse slippage (vs the logged
        ``intended_price``, falling back to ``limit_price``) exceeds
        ``slippage_p90_bps`` (the calibrated p90 from ``data/fee_source.json``).
        Catches a systematically bad route / worse-than-intended execution.
      * unmatched_logged  — a logged order with no matching broker FILL (logged as
        filled but the broker shows none, or a still-working limit order).
      * unmatched_broker  — a broker FILL with no matching logged order (filled but
        never written to the trade log).

    Inputs are plain dicts so each bot builds them from its own schema. Slippage is
    only computed where the bot logged an intended price; legacy entries with no
    joinable id are skipped (not flagged) so this stays backward compatible.
    """
    fills_by_order = {}
    for a in fill_activities or []:
        oid = a.get("order_id") or a.get("client_order_id")
        if oid:
            fills_by_order.setdefault(str(oid), []).append(a)

    logged_order_ids = set()
    slippage_outliers = []
    unmatched_logged = []

    for t in trade_log or []:
        oid = t.get("order_id") or t.get("client_order_id")
        if not oid:
            continue  # legacy entry with nothing to join on — skip, not an error
        oid = str(oid)
        logged_order_ids.add(oid)
        broker_fills = fills_by_order.get(oid)
        if not broker_fills:
            unmatched_logged.append({
                "symbol": t.get("symbol"),
                "order_id": oid,
                "side": t.get("side"),
                "status": t.get("status", t.get("order_status")),
            })
            continue

        intended = t.get("intended_price")
        if intended is None:
            intended = t.get("limit_price")
        num = den = 0.0
        for f in broker_fills:
            q = _num(f.get("qty"))
            p = _num(f.get("price") if f.get("price") is not None
                     else f.get("filled_avg_price"))
            if q and p:
                num += q * p
                den += q
        fill_price = (num / den) if den else None

        slip = _slip_bps(t.get("side", "buy"), _num(intended), fill_price)
        if (slip is not None and slippage_p90_bps is not None
                and slip > slippage_p90_bps):
            slippage_outliers.append({
                "symbol": t.get("symbol"),
                "order_id": oid,
                "side": t.get("side"),
                "intended_price": intended,
                "fill_price": round(fill_price, 4) if fill_price else None,
                "slippage_bps": round(slip, 2),
                "p90_bps": slippage_p90_bps,
            })

    unmatched_broker = []
    for oid, fills in fills_by_order.items():
        if oid not in logged_order_ids:
            f0 = fills[0]
            unmatched_broker.append({
                "symbol": f0.get("symbol"),
                "order_id": oid,
                "side": f0.get("side"),
                "fills": len(fills),
            })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "logged_orders": len(logged_order_ids),
        "broker_fill_orders": len(fills_by_order),
        "slippage_p90_bps": slippage_p90_bps,
        "slippage_outliers": slippage_outliers,
        "unmatched_logged": sorted(unmatched_logged, key=lambda x: x["order_id"]),
        "unmatched_broker": sorted(unmatched_broker, key=lambda x: x["order_id"]),
        "clean": not slippage_outliers and not unmatched_logged and not unmatched_broker,
    }


# ---------------------------------------------------------------------------
# AUDIT-TRAIL REPAIR (broker is ground truth) — places NO orders.
# compute_drift() *detects* drift; this *repairs* the trade log so the audit
# trail reaches in_sync. It never touches the broker and never fabricates P&L.
# ---------------------------------------------------------------------------

def exit_prices_from_fills(fill_activities):
    """Map ``{symbol: most-recent SELL fill price}`` from Alpaca FILL activities.

    Sources REAL exit prices so ``reconcile_log_to_broker`` can close orphan lots
    as genuine realized-P&L ``closed`` trades instead of ``pnl=None``
    ``closed_reconciled`` — the fix that makes P2/P3 edge measurable. Never
    fabricates: only an actual broker sell fill yields an exit price.
    """
    by_sym = {}
    for f in fill_activities or []:
        if not isinstance(f, dict):
            continue
        if not str(f.get("side", "")).lower().startswith("s"):  # sells only
            continue
        sym, px = f.get("symbol"), f.get("price")
        if not sym or px in (None, ""):
            continue
        try:
            px = float(px)
        except (TypeError, ValueError):
            continue
        ttime = f.get("transaction_time") or f.get("date") or ""
        if sym not in by_sym or ttime >= by_sym[sym][0]:
            by_sym[sym] = (ttime, px)
    return {s: v[1] for s, v in by_sym.items()}


def guarded_pnl_fn(realized_pnl):
    """Wrap ``shared.accounting.realized_pnl`` so it NEVER computes P&L on a
    missing/zero entry price or qty — closing an entry-less legacy lot off a 0
    cost basis would fabricate a huge fake result. Returns None instead, so the
    lot closes honestly with pnl=None. Used by P2/P3 reconcile."""
    def _fn(side, qty, entry, exit_price):
        try:
            if not qty or not entry or float(entry) <= 0:
                return None
            return realized_pnl(side, qty, entry, exit_price)["net_pnl"]
        except (TypeError, ValueError, KeyError):
            return None
    return _fn


def _close_record(trade, now_iso, exit_price=None, pnl_fn=None, reason="reconciled"):
    """Turn an open lot into a reconciled close (mutates `trade`).

    A real broker exit price -> a genuine ``closed`` trade with realized P&L
    (recovers true history into the readiness sample). An unknown exit ->
    ``closed_reconciled`` with ``pnl=None`` — we remove it from open risk
    without inventing a realized result the system never observed.
    """
    trade["reconciled"] = True
    trade["reconcile_reason"] = reason
    trade["exit_timestamp"] = now_iso
    if exit_price is not None:
        trade["exit_price"] = exit_price
        trade["status"] = "closed"
        if pnl_fn is not None:
            try:
                qty = float(trade.get("qty") or 0)
                entry = float(trade.get("entry_price") or 0)
                pnl = pnl_fn(trade.get("side", "buy"), qty, entry, float(exit_price))
                trade["pnl"] = pnl
                trade["realized_pnl"] = pnl
                notional = abs(entry * qty) or 1.0
                trade["pnl_pct"] = round(pnl / notional * 100, 2)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
    else:
        trade["exit_price"] = None
        trade["pnl"] = None
        trade["realized_pnl"] = None
        trade["status"] = "closed_reconciled"
    return trade


def _unlogged_lot(symbol, qty, entry_price, now_iso, reason):
    """A fresh open lot reconstructed from a live broker position (real cost basis)."""
    return {
        "symbol": symbol,
        "side": "buy",
        "qty": round(float(qty), 6),
        "entry_price": entry_price,
        "timestamp": now_iso,
        "status": "open",
        "reconciled": True,
        "reconcile_reason": reason,
        "reasons": ["reconciled from broker position"],
        "exit_price": None,
        "pnl": None,
        "pnl_pct": None,
    }


def reconcile_log_to_broker(trade_log, positions, *, now_iso=None,
                            exit_prices=None, pnl_fn=None):
    """Repair the OPEN trades in ``trade_log`` to match broker ``positions``
    (ground truth). Returns ``(new_log, actions)``. Places NO orders.

    Corrections (broker always wins):
      * orphan      — open lot(s) for a symbol the broker does not hold -> close
                      (real exit if in ``exit_prices`` else ``closed_reconciled``)
      * qty over    — summed open qty > broker qty -> trim oldest lots/portions
                      (handles double-logged duplicate lots)
      * qty under / unlogged — broker holds more than logged -> append a
                      reconciled open lot at the broker's average price

    Honest by construction: never fabricates P&L (reconciled-without-exit closes
    carry ``pnl=None`` and a distinct ``closed_reconciled`` status, so they stay
    out of win-rate/Sharpe stats). Idempotent: an in-sync log yields no actions.

    ``exit_prices``: optional {symbol: real_exit_price}.
    ``pnl_fn(side, qty, entry, exit) -> net_pnl``: optional, used only when a real
    exit price is known (pass shared.accounting.realized_pnl for net-of-fee P&L).
    """
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    exit_prices = exit_prices or {}
    log = copy.deepcopy(trade_log)
    actions = []

    broker = {}
    for p in positions or []:
        s = p.get("symbol")
        if not s:
            continue
        q = _num(p.get("qty"))
        broker[s] = {
            "qty": q,  # None when the caller passes symbol-only positions
            "avg": _num(p.get("avg_entry_price") or p.get("avg_price")),
        }

    open_by_sym = {}
    for idx, t in enumerate(log):
        if is_open_trade(t) and t.get("symbol"):
            open_by_sym.setdefault(t["symbol"], []).append(idx)

    touched = set()

    # 1) symbols present in the log's open set
    for sym, idxs in open_by_sym.items():
        b = broker.get(sym)
        logged_qty = sum(_num(log[i].get("qty")) or 0.0 for i in idxs)
        # held = present at broker with a positive (or unknown) qty
        held = b is not None and (b["qty"] is None or b["qty"] > 0)

        if not held:
            for i in idxs:
                _close_record(log[i], now_iso, exit_prices.get(sym), pnl_fn,
                              reason="orphan_no_live_position")
            actions.append({"action": "close_orphan", "symbol": sym,
                            "lots": len(idxs), "qty": round(logged_qty, 6)})
            continue

        broker_qty = b["qty"]
        if broker_qty is None or logged_qty <= 1e-9:
            continue  # held but qty not comparable -> symbol-level audit only

        diff = logged_qty - broker_qty
        if diff > 1e-6:
            touched.add(sym)
            to_remove = diff
            for i in idxs:
                if to_remove <= 1e-6:
                    break
                lot_qty = _num(log[i].get("qty")) or 0.0
                if lot_qty <= to_remove + 1e-9:
                    _close_record(log[i], now_iso, exit_prices.get(sym), pnl_fn,
                                  reason="qty_drift_excess_lot")
                    to_remove -= lot_qty
                else:
                    removed = to_remove
                    log[i]["qty"] = round(lot_qty - removed, 6)
                    split = copy.deepcopy(log[i])
                    split["qty"] = round(removed, 6)
                    split.pop("id", None)
                    _close_record(split, now_iso, exit_prices.get(sym), pnl_fn,
                                  reason="qty_drift_excess_partial")
                    log.append(split)
                    to_remove = 0.0
            actions.append({"action": "trim_qty", "symbol": sym,
                            "removed_qty": round(diff, 6), "broker_qty": broker_qty})
        elif diff < -1e-6:
            touched.add(sym)
            log.append(_unlogged_lot(sym, -diff, b["avg"], now_iso,
                                     reason="qty_drift_short"))
            actions.append({"action": "add_qty", "symbol": sym,
                            "added_qty": round(-diff, 6), "broker_qty": broker_qty})

    # 2) broker symbols with no open log trade -> unlogged position
    for sym, b in broker.items():
        if sym not in open_by_sym and (b["qty"] or 0) > 0:
            log.append(_unlogged_lot(sym, b["qty"], b["avg"], now_iso,
                                     reason="unlogged_position"))
            actions.append({"action": "add_unlogged", "symbol": sym,
                            "qty": round(b["qty"], 6)})

    # 3) cost-basis snap: for any symbol whose lots we changed, set the surviving
    # open lots' entry to the broker's average (ground truth) so the repair also
    # clears cost_basis_drift and the symbol reaches full in_sync.
    for sym in touched:
        b = broker.get(sym)
        if not b or not b.get("avg") or (b["qty"] or 0) <= 0:
            continue
        for t in log:
            if t.get("symbol") == sym and is_open_trade(t):
                t["entry_price"] = b["avg"]
                t["reconciled"] = True
                t.setdefault("reconcile_reason", "cost_basis_synced")

    # preserve the integer-id convention where the log uses one (P1); P3 has none
    if any(isinstance(t.get("id"), int) for t in trade_log):
        next_id = max([t.get("id", 0) for t in log
                       if isinstance(t.get("id"), int)] or [0]) + 1
        for t in log:
            if t.get("id") is None:
                t["id"] = next_id
                next_id += 1

    return log, actions
