"""Exit-order hygiene: no exit order may outlive the position it protects.

INCIDENT (P3, 2026-07-22 → 2026-10): ``_enforce_catalyst_decay`` cancelled DDOG's
bracket legs and submitted a market close; in the SAME monitor run
``_rearm_protective_stops`` still saw the position (the close had not settled)
with no protective order, and placed a GTC sell-stop. The close filled, the stop
was orphaned, and on 2026-08-06 DDOG gapped through it — opening a 14-share
SHORT in a long-only book that sat unnoticed for two months. V and LLY carried
the same orphan stops, live, at the time of the 2026-10-03 audit.

Two invariants, enforced every session:
  1. an open SELL exit order needs a long position behind it, and an open
     BUY stop needs a short behind it — otherwise it is cancelled;
  2. a long-only book holds no short — any short found is flattened and alerted.

``find_orphan_exit_orders`` / ``find_unintended_shorts`` are pure (CI-tested);
``enforce_exit_hygiene`` is the thin executor the bots call.
"""

# Orders that can still fire. Bracket/OCO legs waiting on an unfilled parent sit
# in "held" and are owned by that parent — never touched here.
_LIVE = {"new", "accepted", "pending_new", "partially_filled", "accepted_for_bidding"}


def _signed_qty(p):
    try:
        q = float(p.get("qty") or 0)
    except (TypeError, ValueError):
        return 0.0
    if p.get("side") == "short" and q > 0:
        q = -q
    return q


def find_orphan_exit_orders(open_orders, positions):
    """Open exit orders with no position behind them (they would OPEN exposure).

    * a live SELL order on a symbol with no long position (would open a short);
    * a live BUY stop / stop-limit on a symbol with no short (would open a long).
    Plain BUY limit/market orders are entries, not exits, and are never flagged.
    """
    held = {}
    for p in positions or []:
        if p.get("symbol"):
            held[p["symbol"]] = held.get(p["symbol"], 0.0) + _signed_qty(p)
    orphans = []
    for o in open_orders or []:
        if o.get("status") not in _LIVE or not o.get("symbol") or not o.get("id"):
            continue
        sym, side, typ = o["symbol"], o.get("side"), o.get("type")
        h = held.get(sym, 0.0)
        if side == "sell" and h <= 0:
            orphans.append({"id": o["id"], "symbol": sym, "side": side, "type": typ,
                            "qty": o.get("qty"), "client_order_id": o.get("client_order_id"),
                            "reason": "sell exit order with no long position"})
        elif side == "buy" and typ in ("stop", "stop_limit") and h >= 0:
            orphans.append({"id": o["id"], "symbol": sym, "side": side, "type": typ,
                            "qty": o.get("qty"), "client_order_id": o.get("client_order_id"),
                            "reason": "buy stop with no short position"})
    return orphans


def find_unintended_shorts(positions):
    """Short positions — for a LONG-ONLY book every one of these is a defect."""
    return [{"symbol": p["symbol"], "qty": _signed_qty(p),
             "market_value": p.get("market_value")}
            for p in positions or [] if p.get("symbol") and _signed_qty(p) < 0]


def enforce_exit_hygiene(client, log, *, long_only=True, label=""):
    """Cancel orphan exit orders, then (long-only books) flatten any short.

    Order matters: orphans are cancelled FIRST so one cannot fire after the
    flatten. Never raises — hygiene must not break a session. Returns a summary.
    """
    summary = {"orphans_cancelled": [], "shorts_flattened": [], "errors": []}
    try:
        positions = client.get_positions() or []
        open_orders = client.get_orders(status="open") or []
    except Exception as e:
        summary["errors"].append(f"read failed: {e}")
        log.warning(f"  {label} exit hygiene skipped (read failed): {e}")
        return summary

    for o in find_orphan_exit_orders(open_orders, positions):
        try:
            client.cancel_order(o["id"])
            summary["orphans_cancelled"].append(o)
            log.error(f"::error::{label} ORPHAN exit order cancelled: {o['symbol']} "
                      f"{o['side']} {o['type']} x{o['qty']} ({o['client_order_id']}) — "
                      f"{o['reason']}")
        except Exception as e:
            summary["errors"].append(f"cancel {o['symbol']}: {e}")
            log.error(f"::error::{label} could not cancel orphan {o['symbol']} {o['id']}: {e}")

    if long_only:
        for s in find_unintended_shorts(positions):
            try:
                client.close_position(s["symbol"])
                summary["shorts_flattened"].append(s)
                log.error(f"::error::{label} UNINTENDED SHORT in long-only book flattened: "
                          f"{s['symbol']} qty {s['qty']} (mv {s['market_value']})")
            except Exception as e:
                summary["errors"].append(f"flatten {s['symbol']}: {e}")
                log.error(f"::error::{label} could not flatten short {s['symbol']}: {e}")
    return summary
