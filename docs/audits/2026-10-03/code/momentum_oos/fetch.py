#!/usr/bin/env python3
"""READ-ONLY market-data fetch (Alpaca data API, GET only). No orders.
Usage: fetch.py <feed> <adjustment> <start> <outdir>
"""
import json
import os
import sys
import time

import requests

REPO = "."
cfg = json.load(open(os.path.join(REPO, "config/portfolios.json")))["portfolio_1"]
H = {"APCA-API-KEY-ID": cfg["api_key"], "APCA-API-SECRET-KEY": cfg["api_secret"]}
DATA = "https://data.alpaca.markets"

feed, adj, start, outdir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
os.makedirs(outdir, exist_ok=True)
end = "2026-10-02T21:00:00Z"

u = json.load(open(os.path.join(REPO, "config/universe_wide.json")))
syms = []
for b in u["buckets"].values():
    syms += b["symbols"]
syms += ["RSP", "AGG", "BIL", "SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "SHY", "MTUM", "SPMO"]
syms = sorted(set(syms))
if len(sys.argv) > 5:
    syms = sys.argv[5].split(",")


def get(url, params):
    for attempt in range(6):
        r = requests.get(url, headers=H, params=params, timeout=30)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 * (attempt + 1))
            continue
        return r
    return r


summary = {}
for s in syms:
    fp = os.path.join(outdir, f"{s}.json")
    if os.path.exists(fp):
        continue
    bars, tok = [], None
    while True:
        p = {"timeframe": "1Day", "adjustment": adj, "feed": feed, "start": start,
             "end": end, "limit": 10000}
        if tok:
            p["page_token"] = tok
        r = get(f"{DATA}/v2/stocks/{s}/bars", p)
        if r.status_code != 200:
            print(s, "ERR", r.status_code, r.text[:200])
            break
        j = r.json()
        bars += j.get("bars") or []
        tok = j.get("next_page_token")
        if not tok:
            break
    json.dump(bars, open(fp, "w"))
    summary[s] = (len(bars), bars[0]["t"][:10] if bars else None, bars[-1]["t"][:10] if bars else None)
    print(s, summary[s], flush=True)
    time.sleep(0.35)
