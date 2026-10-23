#!/usr/bin/env python3
"""Total-return (dividend-adjusted) daily bar fetcher — OFFLINE research lane.

Market-data GET only (``/v2/stocks/bars`` with ``adjustment=all``); never touches
account or trading endpoints. Credentials come from the environment
(``APCA_API_KEY_ID`` / ``APCA_API_SECRET_KEY``) and are never printed or written.
Output goes to a GITIGNORED cache (default ``data/research_cache/adj_bars/``) in the
bucket-file shape ``{"bars": {symbol: [bar, ...]}}`` that
``passive_core_eval._bars_in_dir`` reads. Raw bars are never committed.
"""
import argparse
import json
import os
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "data", "research_cache", "adj_bars")


def fetch(symbols, start, key, secret, data_url="https://data.alpaca.markets", feed="iex", max_pages=50):
    hdr = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    out = {s: [] for s in symbols}
    token = None
    for _ in range(max_pages):
        params = {"symbols": ",".join(symbols), "timeframe": "1Day", "adjustment": "all", "feed": feed,
                  "start": start, "limit": 10000, "sort": "asc"}
        if token:
            params["page_token"] = token
        r = requests.get(f"{data_url}/v2/stocks/bars", params=params, headers=hdr, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
        d = r.json()
        for sym, bars in (d.get("bars") or {}).items():
            out.setdefault(sym, []).extend(bars or [])
        token = d.get("next_page_token")
        if not token:
            break
    else:
        raise RuntimeError("page cap reached before pagination finished")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch dividend-adjusted daily bars (research cache).")
    ap.add_argument("--symbols", default="SPY,QQQ,IWM,DIA,TLT,GLD,SHY,BIL")
    ap.add_argument("--start", default="2021-06-01")
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args(argv)
    key, secret = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("APCA_API_KEY_ID / APCA_API_SECRET_KEY not set")
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    bars = fetch(symbols, args.start, key, secret, os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets"))
    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, "etf8_adjusted.json")
    with open(path, "w") as f:
        json.dump({"as_of": datetime.now(timezone.utc).isoformat(), "adjustment": "all", "feed": "iex",
                   "start": args.start, "bars": bars}, f)
    for s in symbols:
        b = bars.get(s) or []
        print(f"  {s}: {len(b)} bars {b[0]['t'][:10] if b else '-'} -> {b[-1]['t'][:10] if b else '-'}")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
