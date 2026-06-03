"""Cross-portfolio aggregate exposure (committee rec #3).

Each book (P1/P2/P3) enforces its own caps in isolation, but nothing measures the
COMBINED bet across the three $100K accounts — the correlation-convergence risk
the committee flagged (P1 mega-cap/AI cluster + P2 ETF sleeve + P3 tilts are
increasingly the same long-US-beta bet). This module combines the books'
committed state into one view: aggregate single-name, sector, and correlated-
cluster exposure as a % of TOTAL equity, with breach flags.

ADVISORY and read-only: it reads state files, computes a report, places NO orders
and relaxes NO limit. Written by P1 EOD (committed so the dashboard can read it)
and surfaced by the heartbeat watchdog — mirroring how reconciliation flows.
"""
import json
from datetime import datetime, timezone

from shared.portfolio_risk import aggregate_exposure, cluster_exposure_pct
from shared.reconcile import is_open_trade


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _read_json(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return default


def load_books(root):
    """Build the normalized books list from each portfolio's committed state.

    Returns [{"portfolio_id", "equity", "positions": [{symbol, market_value,
    sector}]}]. Best-effort: a missing/unreadable book is skipped so the monitor
    never crashes the EOD or the watchdog. P1/P2 carry no GICS sector in state
    (sector aggregation is driven by P3, which does); single-name and cluster
    aggregation work across all three regardless.
    """
    import os
    books = []

    # P1 — data/portfolio_state.json: equity + positions dict {sym: {qty, avg_price}}
    p1 = _read_json(os.path.join(root, "data", "portfolio_state.json"))
    if isinstance(p1, dict):
        positions = []
        for sym, p in (p1.get("positions") or {}).items():
            mv = abs(_f(p.get("qty")) * _f(p.get("avg_price")))
            if mv:
                positions.append({"symbol": sym, "market_value": mv, "sector": None})
        books.append({"portfolio_id": "portfolio_1",
                      "equity": _f(p1.get("equity")), "positions": positions})

    # P2 — political-copy-bot/data/portfolio_state.json: account.equity + positions list
    p2 = _read_json(os.path.join(root, "political-copy-bot", "data", "portfolio_state.json"))
    if isinstance(p2, dict):
        acct = p2.get("account") or {}
        equity = _f(acct.get("equity") or acct.get("portfolio_value"))
        positions = []
        for p in p2.get("positions") or []:
            mv = abs(_f(p.get("market_value")) or _f(p.get("qty")) * _f(p.get("avg_entry")))
            if p.get("symbol") and mv:
                positions.append({"symbol": p["symbol"], "market_value": mv,
                                  "sector": p.get("sector")})
        books.append({"portfolio_id": "portfolio_2", "equity": equity, "positions": positions})

    # P3 — bot_state.json (equity) + trade_log.json open trades (sector-tagged)
    p3_state = _read_json(os.path.join(root, "event-driven-bot", "data", "bot_state.json"), {})
    p3_log = _read_json(os.path.join(root, "event-driven-bot", "data", "trade_log.json"), [])
    if isinstance(p3_state, dict) or isinstance(p3_log, list):
        positions = []
        for t in p3_log or []:
            if not is_open_trade(t) or not t.get("symbol"):
                continue
            mv = abs(_f(t.get("qty")) * _f(t.get("entry_price")))
            if mv:
                positions.append({"symbol": t["symbol"], "market_value": mv,
                                  "sector": t.get("sector")})
        books.append({"portfolio_id": "portfolio_3",
                      "equity": _f((p3_state or {}).get("equity")), "positions": positions})

    return books


def cross_portfolio_report(books, *, single_name_cap_pct=10.0, sector_cap_pct=30.0,
                           clusters=None, max_cluster_pct=None):
    """Aggregate single-name / sector / correlated-cluster exposure across books
    as a % of TOTAL equity, with breach flags. Pure (no IO). Advisory only.

    Builds on aggregate_exposure() (single-name + sector) and adds the
    correlated-cluster view so a basket that moves together is one bet, not many.
    `ok` is True only when no single-name, sector, OR cluster cap is breached.
    """
    agg = aggregate_exposure(books, single_name_cap_pct=single_name_cap_pct,
                             sector_cap_pct=sector_cap_pct)
    combined = [p for b in (books or []) for p in b.get("positions", [])]
    clusters = clusters or {}
    cl = (cluster_exposure_pct(combined, clusters, agg["total_equity"])
          if clusters and agg["total_equity"] else {})
    cluster_breaches = sorted(
        c for c, pct in cl.items() if max_cluster_pct and pct > max_cluster_pct)
    # P1/P2 state carries no GICS sector, so their value pools into "Unknown".
    # That bucket is a metadata gap, not a real sector concentration — exclude it
    # from sector breaches so it can't raise a false aggregate-cap alert. (Real
    # sector aggregation is driven by P3, which tags sectors.)
    sector_breaches = [s for s in agg["sector_breaches"] if s != "Unknown"]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_equity": agg["total_equity"],
        "gross_exposure_pct": agg["gross_exposure_pct"],
        "by_symbol": agg["by_symbol"],
        "by_sector": agg["by_sector"],
        "single_name_cap_pct": single_name_cap_pct,
        "sector_cap_pct": sector_cap_pct,
        "single_name_breaches": agg["single_name_breaches"],
        "sector_breaches": sector_breaches,
        "cluster_exposure_pct": cl,
        "max_cluster_exposure_pct": max_cluster_pct,
        "cluster_breaches": cluster_breaches,
        "ok": not agg["single_name_breaches"] and not sector_breaches and not cluster_breaches,
    }
