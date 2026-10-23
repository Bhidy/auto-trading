#!/usr/bin/env python3
"""Total-return (dividend-adjusted) daily bar fetcher — OFFLINE research lane.

Market-data GET only (``/v2/stocks/bars`` with ``adjustment=all``) plus the
read-only ``GET /v2/calendar`` (NYSE session list, used for gap/coverage checks);
never touches account or order endpoints. Credentials come from the environment
(``APCA_API_KEY_ID`` / ``APCA_API_SECRET_KEY``) and are never printed or written.

Two output layouts, both into a GITIGNORED cache:

* ``bucket`` (default, ``data/research_cache/adj_bars/``): one file in the shape
  ``{"bars": {symbol: [bar, ...]}}`` that ``passive_core_eval._bars_in_dir`` reads.
* ``per_symbol`` (``--universe-file``): ``{SYMBOL}.json`` = ``[{t,o,h,l,c,v}, ...]``
  plus ``MANIFEST.json`` (coverage, >5-session gaps, provenance) and ``QUALITY.md``
  (missing sessions vs the NYSE calendar, non-positive prices, >40% daily moves,
  split-artifact candidates, OHLC inconsistencies). Data is flagged, never altered.

Raw bars are never committed. Stdlib + ``requests`` only.
"""
import argparse
import bisect
import json
import os
import random
import time
from datetime import date, datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "data", "research_cache", "adj_bars")

RETRY_STATUSES = {429, 500, 502, 503, 504}
EXTREME_MOVE = 0.40
GAP_SESSIONS = 5
STRAY_GAP_SESSIONS = 20  # bars before a gap this long are stray prints, not usable history
SPLIT_RATIOS = (1.5, 2.0, 3.0, 4.0, 5.0, 8.0, 10.0, 20.0)
SPLIT_TOL = 0.03
SPLIT_MIN_MOVE = 0.25


# ---------------------------------------------------------------------------
# HTTP (GET only, retry 429/5xx with exponential backoff + jitter)
# ---------------------------------------------------------------------------

def _get(url, params, hdr, retries=6, pause=0.35):
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=hdr, timeout=60)
        except requests.RequestException as exc:
            if attempt == retries:
                raise RuntimeError(f"network error after {retries} retries: {type(exc).__name__}") from None
            time.sleep(min(60, 2 ** attempt) + random.random())
            continue
        if r.status_code == 200:
            time.sleep(pause)  # stay well under the free-tier 200 req/min
            return r.json()
        if r.status_code in RETRY_STATUSES and attempt < retries:
            retry_after = r.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else min(60, 2 ** attempt)
            time.sleep(wait + random.random())
            continue
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
    raise RuntimeError("unreachable")


def _headers(key, secret):
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def fetch(symbols, start, key, secret, data_url="https://data.alpaca.markets", feed="iex", max_pages=500,
          end=None, chunk=25):
    """Fully paginated adjusted daily bars for ``symbols`` (requested in chunks)."""
    hdr = _headers(key, secret)
    out = {s: [] for s in symbols}
    for i in range(0, len(symbols), chunk):
        batch = symbols[i:i + chunk]
        token = None
        for _ in range(max_pages):
            params = {"symbols": ",".join(batch), "timeframe": "1Day", "adjustment": "all", "feed": feed,
                      "start": start, "limit": 10000, "sort": "asc"}
            if end:
                params["end"] = end
            if token:
                params["page_token"] = token
            d = _get(f"{data_url}/v2/stocks/bars", params, hdr)
            for sym, bars in (d.get("bars") or {}).items():
                out.setdefault(sym, []).extend(bars or [])
            token = d.get("next_page_token")
            if not token:
                break
        else:
            raise RuntimeError("page cap reached before pagination finished")
    return out


def fetch_calendar(start, end, key, secret, trading_url="https://paper-api.alpaca.markets"):
    """NYSE session dates (``YYYY-MM-DD``) via the read-only calendar GET."""
    rows = _get(f"{trading_url}/v2/calendar", {"start": start, "end": end}, _headers(key, secret))
    return sorted(r["date"] for r in rows)


# ---------------------------------------------------------------------------
# Per-symbol layout: manifest + quality
# ---------------------------------------------------------------------------

def _slim(bars):
    seen, out = set(), []
    for b in sorted(bars, key=lambda x: x["t"]):
        if b["t"] in seen:
            continue
        seen.add(b["t"])
        out.append({"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]})
    return out


def _near_split(ratio):
    for r in SPLIT_RATIOS:
        for target in (r, 1.0 / r):
            if abs(ratio / target - 1.0) <= SPLIT_TOL:
                return target
    return None


def analyze(symbol, bars, sessions):
    """Coverage + quality facts for one symbol (pure; never mutates bars)."""
    days = [b["t"][:10] for b in bars]
    res = {"symbol": symbol, "n_bars": len(bars), "first_date": days[0] if days else None,
           "last_date": days[-1] if days else None, "gaps": [], "missing_sessions": 0,
           "off_calendar_bars": [], "nonpositive": [], "extreme_moves": [], "split_suspects": [],
           "ohlc_inconsistent": [], "zero_volume_days": 0, "effective_first_date": None,
           "stray_leading_bars": 0}
    if not bars:
        return res
    session_set = set(sessions)
    res["off_calendar_bars"] = [d for d in days if d not in session_set]
    eff_idx = 0
    for k, (a, b) in enumerate(zip(days, days[1:])):
        skipped = bisect.bisect_left(sessions, b) - bisect.bisect_right(sessions, a)
        if skipped > GAP_SESSIONS:
            res["gaps"].append({"from": a, "to": b, "missing_sessions": skipped})
        if skipped > STRAY_GAP_SESSIONS:
            eff_idx = k + 1
    res["effective_first_date"] = days[eff_idx]
    res["stray_leading_bars"] = eff_idx
    # Missing sessions are counted over the usable (post-stray) span only.
    i0 = bisect.bisect_left(sessions, days[eff_idx])
    i1 = bisect.bisect_right(sessions, days[-1])
    have = set(days)
    res["missing_sessions"] = sum(1 for s in sessions[i0:i1] if s not in have)
    prev = None
    for b in bars:
        d = b["t"][:10]
        if min(b["o"], b["h"], b["l"], b["c"]) <= 0:
            res["nonpositive"].append(d)
        if b["h"] < max(b["o"], b["c"]) - 1e-9 or b["l"] > min(b["o"], b["c"]) + 1e-9:
            res["ohlc_inconsistent"].append(d)
        if not b["v"]:
            res["zero_volume_days"] += 1
        if prev and prev["c"] > 0 and b["c"] > 0 and d > res["effective_first_date"]:
            move = b["c"] / prev["c"] - 1.0
            if abs(move) > EXTREME_MOVE:
                res["extreme_moves"].append({"date": d, "move": round(move, 4)})
            gap_ratio = b["o"] / prev["c"] if b["o"] > 0 else None
            split = _near_split(b["c"] / prev["c"]) or (_near_split(gap_ratio) if gap_ratio else None)
            if split and abs(move) >= SPLIT_MIN_MOVE:
                res["split_suspects"].append({"date": d, "close_ratio": round(b["c"] / prev["c"], 4),
                                              "near_factor": round(split, 4)})
        prev = b
    return res


def write_quality_md(path, facts, meta, core, core_start):
    L = [f"# Research dataset quality — {meta['dataset']}", "",
         f"Generated {meta['fetched_at']} · adjustment=`{meta['adjustment']}` · feed=`{meta['feed']}` · "
         f"timeframe=1Day · requested start {meta['start']} → {meta['end']}.",
         f"Calendar: Alpaca `GET /v2/calendar` ({meta['n_sessions']} NYSE sessions in range). "
         "Data is flagged only — nothing was altered.", "",
         "## Caveats", "",
         ("- **IEX feed**: volume is IEX-venue volume only (a small fraction of consolidated volume); "
          "OHLC are IEX prints, so thinly-traded names can show sparse/odd bars. Free-plan IEX history "
          "starts ~2020-07-27 (no 2018 Q4 / COVID-crash coverage)." if meta["feed"] == "iex" else
          "- **SIP feed**: consolidated tape (all venues); end date kept before today (free-plan 15-min rule)."),
         "- **Survivorship bias (Universe B)**: S&P 100 membership is the CURRENT list "
         f"(as of {meta.get('sp100_as_of')}), applied retroactively. Delisted/removed names are absent, "
         "so any backtest over B is upward-biased. The deep_wide5 list is also a present-day selection.",
         "- `adjustment=all` back-adjusts splits AND dividends, so early prices are below historical prints.", ""]
    L += ["## Universe A core common start", "",
          f"Core: {', '.join(core)} → earliest common start **{core_start}**.", ""]
    rows = [f for f in facts if f["n_bars"] == 0]
    L += ["## No data returned", ""] + ([f"- {f['symbol']}" for f in rows] or ["- none"]) + [""]
    L += ["## Coverage per symbol", "",
          "First = first bar returned; Effective = first bar after the last >20-session gap (earlier bars are "
          "stray IEX prints, kept in the file but excluded from missing-session and move checks).", "",
          "| Symbol | Universe | First | Effective | Last | Bars | Missing sessions | Gaps >5 | >40% moves | Split suspects | Non-pos | OHLC bad |",
          "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for f in sorted(facts, key=lambda x: (x["universe"][0], x["symbol"])):
        L.append(f"| {f['symbol']} | {'+'.join(f['universe'])} | {f['first_date'] or '-'} | "
                 f"{f['effective_first_date'] or '-'} | {f['last_date'] or '-'} | "
                 f"{f['n_bars']} | {f['missing_sessions']} | {len(f['gaps'])} | {len(f['extreme_moves'])} | "
                 f"{len(f['split_suspects'])} | {len(f['nonpositive'])} | {len(f['ohlc_inconsistent'])} |")
    L += ["", "## Flag detail", ""]
    any_flag = False
    for f in sorted(facts, key=lambda x: x["symbol"]):
        parts = []
        if f["gaps"]:
            parts.append("gaps " + "; ".join(f"{g['from']}→{g['to']} ({g['missing_sessions']})" for g in f["gaps"]))
        if f["extreme_moves"]:
            parts.append(">40% " + "; ".join(f"{m['date']} {m['move']:+.1%}" for m in f["extreme_moves"]))
        if f["split_suspects"]:
            parts.append("split? " + "; ".join(f"{s['date']} x{s['close_ratio']}" for s in f["split_suspects"]))
        if f["nonpositive"]:
            parts.append("non-positive " + ", ".join(f["nonpositive"][:10]))
        if f["ohlc_inconsistent"]:
            parts.append(f"OHLC-inconsistent {len(f['ohlc_inconsistent'])}d (first {f['ohlc_inconsistent'][0]})")
        if f["off_calendar_bars"]:
            parts.append("off-calendar " + ", ".join(f["off_calendar_bars"][:5]))
        if parts:
            any_flag = True
            L.append(f"- **{f['symbol']}**: " + " · ".join(parts))
    if not any_flag:
        L.append("- none")
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")


def run_per_symbol(spec, start, end, out_dir, key, secret, data_url, trading_url, feed="iex"):
    membership = {}
    for uname, syms in spec["universes"].items():
        for s in syms:
            membership.setdefault(s.upper(), []).append(uname)
    symbols = sorted(membership)
    bars = fetch(symbols, start, key, secret, data_url, feed=feed, end=end)
    sessions = fetch_calendar(start, end, key, secret, trading_url)
    os.makedirs(out_dir, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat()
    facts, manifest_rows = [], []
    for s in symbols:
        slim = _slim(bars.get(s) or [])
        if slim:
            with open(os.path.join(out_dir, f"{s}.json"), "w") as fh:
                json.dump(slim, fh, separators=(",", ":"))
        f = analyze(s, slim, sessions)
        f["universe"] = membership[s]
        facts.append(f)
        manifest_rows.append({"symbol": s, "first_date": f["first_date"],
                              "effective_first_date": f["effective_first_date"],
                              "stray_leading_bars": f["stray_leading_bars"], "last_date": f["last_date"],
                              "n_bars": f["n_bars"], "missing_sessions": f["missing_sessions"],
                              "gaps_gt5_sessions": f["gaps"], "adjustment": "all", "feed": feed,
                              "timeframe": "1Day", "fetched_at": fetched_at, "source_universe": membership[s]})
    core = [c for c in spec.get("core", []) if c in membership]
    firsts = [f["effective_first_date"] for f in facts if f["symbol"] in core and f["effective_first_date"]]
    core_start = max(firsts) if len(firsts) == len(core) else None
    meta = {"dataset": os.path.basename(out_dir.rstrip("/")), "fetched_at": fetched_at, "adjustment": "all",
            "feed": feed, "start": start, "end": end, "n_sessions": len(sessions),
            "sp100_as_of": spec.get("sp100_as_of")}
    manifest = {**meta, "source": "alpaca data v2 /v2/stocks/bars (GET)", "universe_spec": spec,
                "core_common_start": core_start, "total_bars": sum(f["n_bars"] for f in facts),
                "symbols": manifest_rows}
    with open(os.path.join(out_dir, "MANIFEST.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    write_quality_md(os.path.join(out_dir, "QUALITY.md"), facts, meta, core, core_start)
    return manifest, facts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch dividend-adjusted daily bars (research cache).")
    ap.add_argument("--symbols", default="SPY,QQQ,IWM,DIA,TLT,GLD,SHY,BIL")
    ap.add_argument("--start", default="2021-06-01")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD (per_symbol default: today)")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--feed", default="iex", choices=("iex", "sip"),
                    help="sip = consolidated history (free plan allows SIP older than 15 min; use an end date "
                         "before today); iex history on the free plan starts ~2020-07-27")
    ap.add_argument("--universe-file", default=None,
                    help='JSON {"universes": {name: [syms]}, "core": [...], "sp100_as_of": ...}; '
                         "switches to the per-symbol layout with MANIFEST.json + QUALITY.md")
    args = ap.parse_args(argv)
    key, secret = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("APCA_API_KEY_ID / APCA_API_SECRET_KEY not set")
    data_url = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets")
    trading_url = os.environ.get("ALPACA_TRADING_URL", "https://paper-api.alpaca.markets")

    if args.universe_file:
        with open(args.universe_file) as fh:
            spec = json.load(fh)
        out_dir = args.out_dir or os.path.join(ROOT, "data", "research_cache", "adj10y")
        end = args.end or date.today().isoformat()
        manifest, facts = run_per_symbol(spec, args.start, end, out_dir, key, secret, data_url, trading_url,
                                         feed=args.feed)
        for f in sorted(facts, key=lambda x: x["symbol"]):
            print(f"  {f['symbol']:6s} {f['n_bars']:5d} bars {f['first_date'] or '-'} -> {f['last_date'] or '-'}")
        print(f"Total bars {manifest['total_bars']} · core common start {manifest['core_common_start']}")
        print(f"Wrote {out_dir}/MANIFEST.json and QUALITY.md")
        return 0

    out_dir = args.out_dir or OUT_DIR
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    bars = fetch(symbols, args.start, key, secret, data_url, feed=args.feed, end=args.end)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "etf8_adjusted.json")
    with open(path, "w") as f:
        json.dump({"as_of": datetime.now(timezone.utc).isoformat(), "adjustment": "all", "feed": args.feed,
                   "start": args.start, "bars": bars}, f)
    for s in symbols:
        b = bars.get(s) or []
        print(f"  {s}: {len(b)} bars {b[0]['t'][:10] if b else '-'} -> {b[-1]['t'][:10] if b else '-'}")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
