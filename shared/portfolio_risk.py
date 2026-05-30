"""Cross-portfolio aggregate risk + portfolio heat (R1).

Each book (P1/P2/P3) enforces its own limits in isolation, but nothing caps the
COMBINED exposure to a single name or sector across the three $100K accounts —
exactly the concentration the audit's Example 4 warns about. These pure helpers
aggregate the books so a cross-portfolio reporter can flag (and a soft cap can
veto) correlated stacking. Read-only; places no orders.
"""
from datetime import datetime, timezone


def _abs_float(x):
    try:
        return abs(float(x))
    except (TypeError, ValueError):
        return 0.0


def aggregate_exposure(books, single_name_cap_pct=10.0, sector_cap_pct=30.0):
    """Combine positions across books into single-name and sector exposure as a
    percentage of TOTAL equity, and flag soft-cap breaches.

    `books`: list of {"portfolio_id", "equity", "positions": [{"symbol",
    "market_value", "sector"}]}. Returns a report with per-symbol / per-sector
    aggregates, breach lists, and an overall `ok` flag.
    """
    total_equity = sum(_abs_float(b.get("equity")) for b in books) or 0.0
    by_symbol = {}
    by_sector = {}
    for b in books:
        pid = b.get("portfolio_id", "?")
        for p in b.get("positions", []):
            sym = p.get("symbol")
            if not sym:
                continue
            mv = _abs_float(p.get("market_value"))
            entry = by_symbol.setdefault(sym, {"market_value": 0.0, "books": set()})
            entry["market_value"] += mv
            entry["books"].add(pid)
            sec = p.get("sector") or "Unknown"
            by_sector[sec] = by_sector.get(sec, 0.0) + mv

    def pct(v):
        return round(v / total_equity * 100, 3) if total_equity else 0.0

    sym_report = {
        s: {"market_value": round(d["market_value"], 2),
            "pct_of_total": pct(d["market_value"]),
            "books": sorted(d["books"])}
        for s, d in by_symbol.items()
    }
    sector_report = {s: {"market_value": round(v, 2), "pct_of_total": pct(v)}
                     for s, v in by_sector.items()}

    single_name_breaches = sorted(
        [s for s, d in sym_report.items() if d["pct_of_total"] > single_name_cap_pct])
    sector_breaches = sorted(
        [s for s, d in sector_report.items() if d["pct_of_total"] > sector_cap_pct])

    gross = sum(d["market_value"] for d in by_symbol.values())
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_equity": round(total_equity, 2),
        "gross_exposure_pct": pct(gross),
        "by_symbol": sym_report,
        "by_sector": sector_report,
        "single_name_cap_pct": single_name_cap_pct,
        "sector_cap_pct": sector_cap_pct,
        "single_name_breaches": single_name_breaches,
        "sector_breaches": sector_breaches,
        "ok": not single_name_breaches and not sector_breaches,
    }


def exceeds_aggregate_cap(books, symbol, add_market_value, single_name_cap_pct=10.0):
    """Would adding `add_market_value` of `symbol` push its COMBINED exposure
    across all books above the single-name cap? A soft pre-trade check the bots
    can call before stacking a name they may already hold elsewhere."""
    total_equity = sum(_abs_float(b.get("equity")) for b in books) or 0.0
    if not total_equity:
        return False
    current = 0.0
    for b in books:
        for p in b.get("positions", []):
            if p.get("symbol") == symbol:
                current += _abs_float(p.get("market_value"))
    projected_pct = (current + _abs_float(add_market_value)) / total_equity * 100
    return projected_pct > single_name_cap_pct


def portfolio_heat(positions, equity):
    """Portfolio 'heat' = total open risk to predefined stops, as a % of equity.

    For each position, open risk = qty × max(0, entry/current − stop) for a long
    (mirror for a short). High heat means a cluster of stops could be hit at once.
    `positions`: [{"qty","stop_loss","entry_price"|"avg_price"|"current_price","side"}].
    """
    equity = _abs_float(equity)
    if not equity:
        return {"open_risk": 0.0, "heat_pct": 0.0, "positions_at_risk": 0}
    open_risk = 0.0
    at_risk = 0
    for p in positions or []:
        qty = _abs_float(p.get("qty"))
        stop = p.get("stop_loss")
        ref = (p.get("current_price") if p.get("current_price") is not None
               else p.get("entry_price", p.get("avg_price")))
        if not qty or stop is None or ref is None:
            continue
        ref = float(ref)
        stop = float(stop)
        is_long = str(p.get("side", "long")).lower() in ("long", "buy")
        per_share = max(0.0, (ref - stop) if is_long else (stop - ref))
        risk = per_share * qty
        if risk > 0:
            open_risk += risk
            at_risk += 1
    return {
        "open_risk": round(open_risk, 2),
        "heat_pct": round(open_risk / equity * 100, 3),
        "positions_at_risk": at_risk,
    }
