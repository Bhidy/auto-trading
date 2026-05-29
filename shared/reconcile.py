"""
Shared position/trade-log reconciliation — used by all three portfolios so the
integrity audit is identical everywhere.

Pure, dependency-free. Each bot builds its inputs from its own schema and writes
its own report file; the drift logic lives here once.
"""
from datetime import datetime, timezone


def compute_drift(position_symbols, open_trade_symbols):
    """Compare broker positions against the trade log's open positions.

    Returns a report dict with two drift classes:
      * orphan_open_trades  — logged 'open' but no live position (exit not logged)
      * unlogged_positions  — live position with no open trade (entry not logged,
                              e.g. a limit that filled after the confirm window)
    """
    pos = {s for s in position_symbols if s}
    opn = {s for s in open_trade_symbols if s}
    orphan = sorted(opn - pos)
    unlogged = sorted(pos - opn)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "positions_held": len(pos),
        "open_trades_logged": len(opn),
        "orphan_open_trades": orphan,
        "unlogged_positions": unlogged,
        "in_sync": not orphan and not unlogged,
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
