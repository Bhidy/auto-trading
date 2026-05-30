"""
Shared position/trade-log reconciliation — used by all three portfolios so the
integrity audit is identical everywhere.

Pure, dependency-free. Each bot builds its inputs from its own schema and writes
its own report file; the drift logic lives here once.
"""
from datetime import datetime, timezone


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
