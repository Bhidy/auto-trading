#!/usr/bin/env python3
"""
Automated market-history collector — mirrors Alpaca free-tier (IEX) daily bars
into Supabase so the dashboard charts have a durable, self-updating store that
never depends on a live API call.

Design for "never fail, no manual action":
  * Per-symbol isolation — one symbol failing never aborts the run.
  * Idempotent upserts (merge-duplicates on symbol+date) — safe to re-run.
  * Backfill OR incremental via --days (workflow passes 12 daily; a dispatch can
    pass 730 for a one-time multi-year backfill).
  * Skips cleanly when Supabase creds absent (exit 0).

Universe = config/watchlist.json symbols (stocks/ETFs) ∪ a curated chart core.
Crypto (BTC/USD etc.) is skipped here (different endpoint).

Usage:
    python3 scripts/collect_market_history.py --api-key K --api-secret S [--days 730] [--symbols A,B]
Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
"""
import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SSL_CTX = ssl.create_default_context()
DATA_URL = "https://data.alpaca.markets"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

CHART_CORE = [
    "SPY", "QQQ", "DIA", "IWM",
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "NFLX", "INTC",
    "XLK", "XLE", "XLF", "XLV", "XLY", "XLI", "XLU", "XLP", "XLB", "XLRE", "XLC",
    "TLT", "GLD", "SHY", "BIL",
]


def load_universe(extra_csv=None):
    syms = set(CHART_CORE)
    wl_path = os.path.join(os.path.dirname(__file__), "..", "config", "watchlist.json")
    try:
        with open(wl_path) as f:
            wl = json.load(f)
        for bucket in wl.values():
            if isinstance(bucket, dict):
                for s in bucket.get("symbols", []):
                    if s and "/" not in s:   # skip crypto pairs
                        syms.add(s.upper())
    except Exception:
        pass
    if extra_csv:
        for s in extra_csv.split(","):
            s = s.strip().upper()
            if s and "/" not in s:
                syms.add(s)
    return sorted(syms)


def alpaca_daily_bars(symbol, api_key, api_secret, start, limit=1000):
    url = (f"{DATA_URL}/v2/stocks/{symbol}/bars"
           f"?timeframe=1Day&limit={limit}&feed=iex&sort=asc&start={start}")
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret})
    with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as r:
        return json.loads(r.read()).get("bars", []) or []


def supabase_upsert(rows):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("  SUPABASE creds not set — skipping upsert")
        return False
    if not rows:
        return True
    url = f"{SUPABASE_URL}/rest/v1/market_daily_history"
    body = json.dumps(rows).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates",
    })
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as r:
            return r.status in (200, 201, 204)
    except urllib.error.HTTPError as e:
        print(f"  Supabase error: {e.code} {e.read().decode()[:200]}")
        return False


def collect(symbol, api_key, api_secret, start):
    bars = alpaca_daily_bars(symbol, api_key, api_secret, start)
    rows = []
    for b in bars:
        if not b.get("c"):
            continue
        rows.append({
            "symbol": symbol,
            "date": b["t"][:10],
            "close_price": round(float(b["c"]), 4),
            "open_price": round(float(b.get("o", b["c"])), 4),
            "high_price": round(float(b.get("h", b["c"])), 4),
            "low_price": round(float(b.get("l", b["c"])), 4),
            "volume": int(b.get("v", 0)),
        })
    if rows:
        supabase_upsert(rows)
    return len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--api-secret", required=True)
    ap.add_argument("--days", type=int, default=12)
    ap.add_argument("--symbols", default=None, help="extra comma-separated symbols")
    args = ap.parse_args(argv)

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — nothing to do.")
        return 0

    start = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")
    universe = load_universe(args.symbols)
    print(f"Collecting {args.days}d daily history for {len(universe)} symbols from {start}")

    total_rows, ok, failed = 0, 0, 0
    for sym in universe:
        try:
            n = collect(sym, args.api_key, args.api_secret, start)
            total_rows += n
            ok += 1
            print(f"  {sym}: {n} rows")
            time.sleep(0.25)   # gentle on the rate limit
        except Exception as e:
            failed += 1
            print(f"  {sym}: FAILED ({e}) — continuing")
    print(f"Done. {ok} ok, {failed} failed, {total_rows} rows upserted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
