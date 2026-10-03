"""Fetch daily IEX bars (read-only market-data GETs) for every symbol in the snapshots."""
import json
import time
import urllib.parse
import urllib.request

REPO = "."
OUT = "/tmp/audit_2026_10_03/agentE"

cfg = json.load(open(f"{REPO}/config/portfolios.json"))["portfolio_1"]
HDR = {"APCA-API-KEY-ID": cfg["api_key"], "APCA-API-SECRET-KEY": cfg["api_secret"]}

syms = {"SPY"}
p1 = json.load(open(f"{OUT}/snap_p1.json"))
for s in p1.values():
    for x in s["data"]["signals"]:
        if "/" not in x["symbol"]:
            syms.add(x["symbol"])
p3 = json.load(open(f"{OUT}/snap_p3.json"))
for s in p3.values():
    for x in s["data"]["signals"]:
        syms.add(x["symbol"])
    for x in (s.get("watchlist") or {}).get("universe", []):
        syms.add(x["symbol"])
pn = json.load(open(f"{OUT}/snap_p3news.json"))
for s in pn.values():
    for x in s["data"]["signals"]:
        syms.add(x["symbol"])

bars = {}
fails = []
for sym in sorted(syms):
    out, tok = [], None
    for _ in range(20):
        q = {"timeframe": "1Day", "adjustment": "all", "feed": "iex", "start": "2026-05-01",
             "end": "2026-10-03", "limit": "10000"}
        if tok:
            q["page_token"] = tok
        url = f"https://data.alpaca.markets/v2/stocks/{urllib.parse.quote(sym)}/bars?" + urllib.parse.urlencode(q)
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers=HDR)
                with urllib.request.urlopen(req, timeout=30) as r:
                    d = json.loads(r.read())
                break
            except Exception as e:  # noqa: BLE001
                err = e
                time.sleep(1.5 * (attempt + 1))
        else:
            fails.append((sym, str(err)))
            d = {}
        out += d.get("bars") or []
        tok = d.get("next_page_token")
        if not tok:
            break
    bars[sym] = [{"d": b["t"][:10], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]} for b in out]
    time.sleep(0.1)

json.dump(bars, open(f"{OUT}/bars.json", "w"))
print("symbols", len(syms), "fails", fails)
print({k: len(v) for k, v in bars.items() if len(v) < 100})
print("SPY", len(bars["SPY"]), bars["SPY"][0]["d"], bars["SPY"][-1]["d"])
