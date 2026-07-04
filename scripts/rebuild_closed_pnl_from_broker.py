#!/usr/bin/env python3
"""Rebuild closed-trade P&L in a bot's trade log from broker FIFO truth.

Audit 2026-07-04, defects D2/D4: P3's committed log showed -$6,182.81 realized
while broker truth was ≈ -$187 (18/30 closes carried pnl=null after orphan
reconciliation), and P2's reconciler had closed bare ``side: "sell"`` exit rows
as SHORT lots, sign-flipping winners (TER +$662 logged as a loss) and
double-counting the same exit.

This script repairs the COMMITTED history once, honestly:
  * fetches every filled order from Alpaca (ground truth, read-only),
  * replays them long-FIFO per symbol into round-trip closures,
  * P2 first: voids the fabricated P&L on sell-side rows (they become
    ``exit_marker`` audit rows; the old value is preserved in
    ``voided_pnl_sign_bug``),
  * fills exit_price / pnl / pnl_pct / exit_reason on closed BUY lots whose
    pnl is null, allocating broker closures in entry order,
  * NEVER touches open lots, never invents a price that isn't a broker fill,
    and reports (without modifying) non-null entries that drift from broker.

Dry-run by default; ``--apply`` writes the log. Cloud-path pure: stdlib only.
Usage:  python3 scripts/rebuild_closed_pnl_from_broker.py --portfolio p3 [--apply]
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from shared.accounting import realized_pnl  # noqa: E402

PORTFOLIOS = {
    "p2": {"config_key": "portfolio_2",
           "log": REPO_ROOT / "political-copy-bot" / "data" / "trade_log.json"},
    "p3": {"config_key": "portfolio_3",
           "log": REPO_ROOT / "event-driven-bot" / "data" / "trade_log.json"},
}
BACKFILL_TAG = "broker_fifo_backfill_2026-07-04"


def classify_exit(order_type):
    t = str(order_type or "").lower()
    if "stop" in t:
        return "stop_loss"
    if t == "limit":
        return "take_profit"
    return "market_exit"


def fetch_filled_orders(base_url, key, secret):
    """All filled orders, oldest first (paginated, read-only)."""
    orders, until = [], None
    while True:
        params = {"status": "closed", "limit": "500", "direction": "desc"}
        if until:
            params["until"] = until
        url = f"{base_url}/v2/orders?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={
            "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
        with urllib.request.urlopen(req, timeout=30) as resp:
            batch = json.loads(resp.read())
        orders.extend(batch)
        if len(batch) < 500:
            break
        until = batch[-1]["submitted_at"]
    fills = []
    for o in orders:
        try:
            qty = float(o.get("filled_qty") or 0)
            px = float(o.get("filled_avg_price") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0 or px <= 0:
            continue
        fills.append({
            "symbol": o.get("symbol"),
            "side": str(o.get("side", "")).lower(),
            "qty": qty,
            "price": px,
            "time": o.get("filled_at") or o.get("updated_at") or "",
            "type": o.get("type") or o.get("order_type") or "",
        })
    fills.sort(key=lambda f: f["time"])
    return fills


def fifo_closures(fills):
    """Replay fills long-FIFO per symbol -> {symbol: [closure, ...]}.

    A closure is one (buy-lot portion, sell fill) match:
    {qty, entry_price, entry_time, exit_price, exit_time, exit_reason}.
    Sells with no open lot (shouldn't happen on a long-only book) are skipped
    and counted in the returned ``unmatched`` dict. The third return value is
    the leftover ``open_lots`` — shares the broker bought and still holds —
    used to REOPEN phantom closes (a row marked closed that the broker never
    actually sold, e.g. the duplicated MEDP lot).
    """
    lots, closures, unmatched = {}, {}, {}
    for f in fills:
        sym = f["symbol"]
        if f["side"] == "buy":
            lots.setdefault(sym, []).append(
                {"qty": f["qty"], "price": f["price"], "time": f["time"]})
            continue
        remaining = f["qty"]
        queue = lots.get(sym, [])
        while remaining > 1e-9 and queue:
            lot = queue[0]
            take = min(lot["qty"], remaining)
            closures.setdefault(sym, []).append({
                "qty": take,
                "entry_price": lot["price"],
                "entry_time": lot["time"],
                "exit_price": f["price"],
                "exit_time": f["time"],
                "exit_reason": classify_exit(f["type"]),
            })
            lot["qty"] -= take
            remaining -= take
            if lot["qty"] <= 1e-9:
                queue.pop(0)
        if remaining > 1e-9:
            unmatched[sym] = unmatched.get(sym, 0.0) + remaining
    open_lots = {s: q for s, q in
                 ((s, sum(lot["qty"] for lot in queue)) for s, queue in lots.items())
                 if q > 1e-9}
    return closures, unmatched, open_lots


def _is_sell_row(t):
    return str(t.get("side", "")).lower() == "sell"


def _is_closed_buy(t):
    return (not _is_sell_row(t)
            and str(t.get("status", "")) in ("closed", "closed_reconciled"))


def void_sell_rows(log):
    """P2 sign-bug repair: sell rows are exit markers, never lots (D4)."""
    voided = 0
    for t in log:
        if not _is_sell_row(t):
            continue
        if t.get("status") == "exit_marker" and t.get("pnl") is None:
            continue
        if t.get("pnl") is not None:
            t["voided_pnl_sign_bug"] = t.get("pnl")
            voided += 1
        t["pnl"] = None
        t["realized_pnl"] = None
        t["pnl_pct"] = None
        t["status"] = "exit_marker"
        reason = str(t.get("reason", "")).lower()
        if not t.get("exit_reason"):
            if "trailing stop" in reason:
                t["exit_reason"] = "trailing_stop"
            elif "take profit" in reason:
                t["exit_reason"] = "take_profit"
            elif "max hold" in reason:
                t["exit_reason"] = "max_hold"
            elif "sell" in reason:
                t["exit_reason"] = "copy_sell"
    return voided


def backfill_closed_buys(log, closures, open_lots=None):
    """Allocate broker closures to closed buy lots in entry order.

    Non-null entries consume their allocation (to keep FIFO alignment) and are
    only REPORTED when they drift from broker; null entries get the broker
    numbers written. A closed row with NO broker closure whose qty the broker
    still HOLDS is a phantom close — it is REOPENED (its P&L was never
    realized). Returns (filled, drift_reports, starved, reopened).
    """
    filled, drift, starved, reopened = 0, [], [], 0
    open_lots = dict(open_lots or {})
    queues = {s: list(cl) for s, cl in closures.items()}
    by_symbol = {}
    for t in log:
        if _is_closed_buy(t) and t.get("symbol"):
            by_symbol.setdefault(t["symbol"], []).append(t)
    for sym, entries in by_symbol.items():
        entries.sort(key=lambda t: str(t.get("timestamp", "")))
        queue = queues.get(sym, [])
        for t in entries:
            try:
                want = float(t.get("qty") or 0)
            except (TypeError, ValueError):
                want = 0.0
            if want <= 0:
                continue
            alloc, got = [], 0.0
            while got < want - 1e-9 and queue:
                c = queue[0]
                take = min(c["qty"], want - got)
                alloc.append({**c, "qty": take})
                c["qty"] -= take
                got += take
                if c["qty"] <= 1e-9:
                    queue.pop(0)
            if not alloc:
                if open_lots.get(sym, 0.0) >= want - 1e-9:
                    open_lots[sym] -= want
                    t["status"] = "open"
                    t["exit_price"] = None
                    t["exit_timestamp"] = None
                    t["pnl"] = None
                    t["realized_pnl"] = None
                    t["pnl_pct"] = None
                    t.pop("exit_reason", None)
                    t["pnl_backfill"] = BACKFILL_TAG + "_reopened_broker_holds"
                    reopened += 1
                else:
                    starved.append({"symbol": sym, "qty": want,
                                    "timestamp": t.get("timestamp")})
                continue
            entry_px = sum(a["entry_price"] * a["qty"] for a in alloc) / got
            exit_px = sum(a["exit_price"] * a["qty"] for a in alloc) / got
            pnl = sum(realized_pnl("buy", a["qty"], a["entry_price"],
                                   a["exit_price"])["net_pnl"] for a in alloc)
            reason = alloc[-1]["exit_reason"]
            if t.get("pnl") is None:
                if not t.get("entry_price"):
                    t["entry_price"] = round(entry_px, 4)
                t["exit_price"] = round(exit_px, 4)
                t["pnl"] = round(pnl, 2)
                t["realized_pnl"] = round(pnl, 2)
                notional = abs(float(t["entry_price"]) * got) or 1.0
                t["pnl_pct"] = round(pnl / notional * 100, 2)
                t["exit_timestamp"] = t.get("exit_timestamp") or alloc[-1]["exit_time"]
                if not t.get("exit_reason"):
                    t["exit_reason"] = reason
                t["status"] = "closed"
                t["pnl_backfill"] = BACKFILL_TAG
                filled += 1
            else:
                if not t.get("exit_reason"):
                    t["exit_reason"] = reason
                    t["pnl_backfill"] = BACKFILL_TAG + "_reason_only"
                old = float(t.get("pnl") or 0)
                if abs(old - pnl) > max(1.0, abs(pnl) * 0.05):
                    drift.append({"symbol": sym, "logged_pnl": round(old, 2),
                                  "broker_pnl": round(pnl, 2),
                                  "timestamp": t.get("timestamp")})
    return filled, drift, starved, reopened


def realized_total(log):
    return round(sum(float(t.get("pnl") or 0) for t in log
                     if str(t.get("status", "")) in ("closed", "closed_reconciled")), 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--portfolio", choices=["p2", "p3"], required=True)
    ap.add_argument("--apply", action="store_true",
                    help="write the repaired log (default: dry-run report)")
    args = ap.parse_args()

    spec = PORTFOLIOS[args.portfolio]
    cfg = json.loads((REPO_ROOT / "config" / "portfolios.json").read_text())[spec["config_key"]]
    log = json.loads(spec["log"].read_text())

    fills = fetch_filled_orders(cfg["base_url"], cfg["api_key"], cfg["api_secret"])
    closures, unmatched, open_lots = fifo_closures(fills)
    broker_total = round(sum(
        realized_pnl("buy", c["qty"], c["entry_price"], c["exit_price"])["net_pnl"]
        for cl in closures.values() for c in cl), 2)

    before = realized_total(log)
    voided = void_sell_rows(log) if args.portfolio == "p2" else 0
    filled, drift, starved, reopened = backfill_closed_buys(log, closures, open_lots)
    after = realized_total(log)

    print(f"[{args.portfolio}] fills={len(fills)}  broker FIFO realized={broker_total:+,.2f}")
    print(f"  log realized: before={before:+,.2f}  after={after:+,.2f}")
    print(f"  sell rows voided (sign bug): {voided}")
    print(f"  null-pnl closes backfilled: {filled}")
    print(f"  phantom closes reopened (broker still holds): {reopened}")
    for d in drift:
        print(f"  DRIFT (not modified): {d}")
    for s in starved:
        print(f"  NO BROKER CLOSURE FOUND (not modified): {s}")
    for sym, q in unmatched.items():
        print(f"  unmatched sell qty at broker (pre-log history?): {sym} x {q}")

    if args.apply:
        spec["log"].write_text(json.dumps(log, indent=2, default=str))
        print(f"  APPLIED -> {spec['log']}")
    else:
        print("  DRY RUN (use --apply to write)")


if __name__ == "__main__":
    main()
