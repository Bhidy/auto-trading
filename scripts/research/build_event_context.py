#!/usr/bin/env python3
"""Build the advisory event-context artifact (OFFLINE research lane).

Pre-computes decision-support context for P2/P3 — upcoming corporate actions
(ex-div/splits), fresh news, and liquidity rank — into ``data/event_context.json``.
The trading path may READ this as ADVISORY input (fail-open via
``shared.event_context``); it is NEVER a live dependency and is NOT imported by
any Actions trading workflow (invariants A/B).

The TRANSFORMS below are pure + unit-tested. ``main()`` is a thin fetch wrapper
(Alpaca Market Data REST, research lane) — run manually with data credentials; it
fails safe and writes nothing it cannot source. Pure-stdlib transforms.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DISCLOSURE = ("Advisory decision-support only — not investment advice. Built offline "
              "from Alpaca data; consumed fail-open by the trading path.")


def _parse_date(s):
    if not s:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(str(s)[:10], "%Y-%m-%d")
        except ValueError:
            return None
    # Always tz-aware (assume UTC if naive) so date math never mixes naive/aware.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def corporate_action_flags(actions, now, within_days=5):
    """Map symbol -> nearest upcoming ex-date corporate action within the window."""
    out = {}
    for a in actions or []:
        sym = a.get("symbol")
        ex = _parse_date(a.get("ex_date") or a.get("ex_dividend_date") or a.get("process_date"))
        if not sym or ex is None:
            continue
        days = (ex - now).days
        if 0 <= days <= within_days:
            prev = out.get(sym)
            if prev is None or days < prev["days_until"]:
                out[sym] = {"type": a.get("type") or a.get("ca_type") or "corporate_action",
                            "ex_date": ex.date().isoformat(), "days_until": days}
    return out


def liquidity_rank(movers):
    """Map symbol -> {volume, rank_pct} ranked by traded volume (0=thinnest, 1=most)."""
    rows = [(m.get("symbol"), float(m.get("volume") or m.get("dollar_volume") or 0))
            for m in movers or [] if m.get("symbol")]
    rows = [(s, v) for s, v in rows if s]
    if not rows:
        return {}
    rows.sort(key=lambda x: x[1])
    n = len(rows)
    return {s: {"volume": v, "rank_pct": round((i / (n - 1)) if n > 1 else 1.0, 4)}
            for i, (s, v) in enumerate(rows)}


def news_recency(news, now, within_hours=48):
    """Map symbol -> list of recent headlines within the window."""
    out = {}
    for item in news or []:
        ts = _parse_date(item.get("created_at") or item.get("updated_at") or item.get("timestamp"))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if (now - ts).total_seconds() / 3600.0 > within_hours:
            continue
        for sym in item.get("symbols", []) or []:
            out.setdefault(sym, []).append({
                "headline": item.get("headline") or item.get("title"),
                "at": ts.isoformat(),
            })
    return out


def build_context(corporate_actions, movers, news, now):
    """Assemble the advisory artifact from already-fetched inputs (pure)."""
    return {
        "as_of": now.isoformat(),
        "corporate_actions": corporate_action_flags(corporate_actions, now),
        "liquidity": liquidity_rank(movers),
        "news": news_recency(news, now),
        "disclosure": DISCLOSURE,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build advisory event-context artifact.")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "event_context.json"))
    args = ap.parse_args(argv)

    # Live fetch is research-lane only; do it via the shared resilient client when
    # credentials are present. Without creds, fail safe and explain (write nothing).
    key, secret = os.environ.get("ALPACA_DATA_KEY"), os.environ.get("ALPACA_DATA_SECRET")
    if not (key and secret):
        print("No ALPACA_DATA_KEY/SECRET in env — research-lane fetch skipped "
              "(run interactively with data credentials). No artifact written.")
        return 0

    sys.path.insert(0, ROOT)
    # NOTE: the actual REST fetch (corporate actions / news / movers) is intentionally
    # left to the interactive research session, where the Alpaca MCP/CLI provide the
    # data with OAuth and the human confirms scope. build_context() consumes whatever
    # those return. This keeps the committed script free of credentialed network code.
    print("Credentials present, but live fetch is performed interactively via the "
          "Alpaca MCP/CLI in the research session; pass fetched inputs to build_context().")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
