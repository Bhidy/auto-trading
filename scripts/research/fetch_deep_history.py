#!/usr/bin/env python3
"""Deep-history fetcher (OFFLINE research lane) -> data/deep/{bucket}.json.

THE data-depth unlock. The backtest/walk-forward stack validated on a SELF-IMPOSED
~220-bar (~0.9y) cache, so only ~3 OOS windows existed and PBO (which needs >=4
slices) could never fire — every "validated" improvement was flagged thin-sample.
Alpaca's FREE IEX feed returns ~3 YEARS of daily bars when a start date is set
(proven: SPY = 755 bars). This fetches that depth for the full equity universe so
the validation stack finally has enough out-of-sample data to trust.

Writes deep bucket files in the SAME shape the existing loader reads
(backtest.walk_forward.load_aligned_bars), so nothing downstream changes except
the data directory. Pure-stdlib + requests; offline; never on the trading path.
"""
import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WATCHLIST = os.path.join(ROOT, "config", "watchlist.json")
CONFIG = os.path.join(ROOT, "config", "alpaca_config.json")
OUT_DIR = os.path.join(ROOT, "data", "deep")


def _creds():
    key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY")
    sec = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET")
    data_url = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets")
    if not key and os.path.exists(CONFIG):
        cfg = json.load(open(CONFIG))
        key, sec = cfg["api_key"], cfg["api_secret"]
        data_url = cfg.get("data_url", data_url)
    return key, sec, data_url


def fetch_symbol(symbol, key, sec, data_url, start, feed="iex"):
    """All daily bars from `start` (handles pagination)."""
    hdr = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    bars, token = [], None
    for _ in range(20):  # page cap
        params = {"timeframe": "1Day", "start": start, "limit": 10000, "feed": feed,
                  "adjustment": "split", "sort": "asc"}
        if token:
            params["page_token"] = token
        r = requests.get(f"{data_url}/v2/stocks/{symbol}/bars", params=params, headers=hdr, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"{symbol}: HTTP {r.status_code} {r.text[:120]}")
        d = r.json()
        bars.extend(d.get("bars") or [])
        token = d.get("next_page_token")
        if not token:
            break
    return bars


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch deep (multi-year) daily history per bucket.")
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--feed", default="iex")
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--watchlist", default=WATCHLIST,
                    help="universe config (e.g. config/universe_wide.json for the breadth expansion)")
    args = ap.parse_args(argv)

    key, sec, data_url = _creds()
    if not key or not sec:
        print("No Alpaca credentials (config/alpaca_config.json or APCA_* env). Cannot fetch.")
        return 1

    w = json.load(open(args.watchlist))
    buckets = w.get("buckets", w)
    start = (date.today() - timedelta(days=int(args.years * 366))).isoformat()
    os.makedirs(args.out_dir, exist_ok=True)

    summary = {}
    for bucket, spec in buckets.items():
        syms = spec.get("symbols", spec) if isinstance(spec, dict) else spec
        syms = [s for s in (syms or []) if "/" not in s]  # equities/ETFs only (skip crypto pairs)
        if not syms:
            continue
        out = {}
        for s in syms:
            try:
                b = fetch_symbol(s, key, sec, data_url, start, feed=args.feed)
                if len(b) >= 100:
                    out[s] = b
                summary[s] = len(b)
            except Exception as e:
                print(f"  {s}: {e}")
                summary[s] = 0
        if out:
            path = os.path.join(args.out_dir, f"{bucket}.json")
            with open(path, "w") as f:
                json.dump({"as_of": datetime.now(timezone.utc).isoformat(),
                           "years": args.years, "source": "alpaca_iex_free",
                           "bars": out}, f)
            print(f"  wrote {bucket}.json: {len(out)} symbols x ~{max(len(v) for v in out.values())} bars")

    n = max(summary.values()) if summary else 0
    print(f"Done. Deepest series ~{n} bars (~{n // 252}y). Symbols fetched: "
          f"{sum(1 for v in summary.values() if v >= 100)}/{len(summary)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
