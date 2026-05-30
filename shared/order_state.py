"""Order-state reconciler (C2) — partial-fill / reject / replace aware.

The audit asks for an event-driven order-state machine on Alpaca's trade_updates
stream. Vercel serverless cannot hold a persistent WebSocket and the data path is
15-min delayed, so the equivalent, robust design is a PERSISTED RECONCILING
POLLER: each monitor run diffs the broker's current orders against the last
persisted snapshot and emits explicit transition events (new, fill, partial_fill,
canceled, rejected, replaced). No order can sit in an unknown state across a cycle.

The diff core is pure and dependency-free (fully CI-testable). Feed it ALL
relevant orders — get_orders(status="all") — so terminal transitions are visible.
"""
import json
import os
from datetime import datetime, timezone

TERMINAL = {"filled", "canceled", "rejected", "expired", "done_for_day", "replaced"}
WORKING = {"new", "accepted", "partially_filled", "pending_new", "held",
           "pending_replace", "pending_cancel"}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def order_view(o):
    """Normalize a broker order to the fields the reconciler tracks."""
    return {
        "id": o.get("id"),
        "client_order_id": o.get("client_order_id"),
        "symbol": o.get("symbol"),
        "side": o.get("side"),
        "qty": o.get("qty"),
        "filled_qty": o.get("filled_qty"),
        "filled_avg_price": o.get("filled_avg_price"),
        "status": o.get("status"),
        "updated_at": o.get("updated_at") or o.get("submitted_at") or o.get("created_at"),
    }


def reconcile_orders(prior_state, broker_orders):
    """Diff broker orders against the prior persisted snapshot.

    Returns (new_state, events). `prior_state` and `new_state` are
    {order_id: order_view}. Events make every transition explicit:
      * new          — first time we see this order
      * fill         — became fully filled (carries newly filled qty/price)
      * partial_fill — filled_qty increased but not yet complete
      * canceled / rejected / expired / replaced — terminal status change
    """
    prior_state = prior_state or {}
    new_state = dict(prior_state)
    events = []

    for o in broker_orders or []:
        v = order_view(o)
        oid = v["id"]
        if not oid:
            continue
        prev = prior_state.get(oid)

        if prev is None:
            events.append({"type": "new", "order_id": oid, "symbol": v["symbol"],
                           "side": v["side"], "status": v["status"]})
        else:
            prev_filled = _f(prev.get("filled_qty"))
            cur_filled = _f(v.get("filled_qty"))
            if cur_filled > prev_filled:
                delta = cur_filled - prev_filled
                etype = "fill" if v["status"] == "filled" else "partial_fill"
                events.append({
                    "type": etype, "order_id": oid, "symbol": v["symbol"],
                    "side": v["side"], "delta_qty": delta,
                    "filled_qty": cur_filled,
                    "filled_avg_price": v.get("filled_avg_price"),
                })
            if v["status"] != prev.get("status") and v["status"] in (
                    "canceled", "rejected", "expired", "replaced"):
                events.append({"type": v["status"], "order_id": oid,
                               "symbol": v["symbol"], "side": v["side"]})
            elif (v["status"] == "filled" and prev.get("status") != "filled"
                  and cur_filled <= prev_filled):
                # Became filled without an observed qty delta (status caught up).
                events.append({"type": "fill", "order_id": oid, "symbol": v["symbol"],
                               "side": v["side"], "delta_qty": cur_filled,
                               "filled_qty": cur_filled,
                               "filled_avg_price": v.get("filled_avg_price")})

        new_state[oid] = v

    return new_state, events


def stale_working_orders(state, max_age_s=7200, now=None):
    """Working (unfilled/partial) orders older than `max_age_s` — the surface for
    repricing or cancellation. `now` defaults to current UTC."""
    now = now or datetime.now(timezone.utc)
    out = []
    for oid, v in (state or {}).items():
        if v.get("status") not in WORKING:
            continue
        ts = v.get("updated_at")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        age = (now - t).total_seconds()
        if age >= max_age_s:
            out.append({"order_id": oid, "symbol": v.get("symbol"),
                        "status": v.get("status"), "age_seconds": round(age)})
    return out


def prune_terminal(state, keep_terminal=False):
    """Drop terminal orders from the persisted state once acknowledged, so the
    snapshot tracks only live working orders (bounded growth)."""
    if keep_terminal:
        return dict(state or {})
    return {oid: v for oid, v in (state or {}).items()
            if v.get("status") in WORKING}


# --- Thin persistence (live path) ------------------------------------------

def load_state(path):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(path, state):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def reconcile_and_persist(path, broker_orders, prune=True):
    """Load → reconcile → optionally prune terminal → persist. Returns the
    events list so the caller can act (log fills, reprice stale, etc.)."""
    prior = load_state(path)
    new_state, events = reconcile_orders(prior, broker_orders)
    save_state(path, prune_terminal(new_state) if prune else new_state)
    return events
