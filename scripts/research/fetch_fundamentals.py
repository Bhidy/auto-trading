#!/usr/bin/env python3
"""Point-in-time fundamentals from SEC EDGAR (OFFLINE research lane) ->
data/fundamentals.json.

The genuine orthogonal-alpha lever: P1's score is pure price/momentum on the most-
arbitraged names, which is WHY its entry is anti-predictive. This adds a
quality/value/growth tilt from PRIMARY-SOURCE financials (the committee rates SEC
filings as highest-quality evidence). Free, key-free, pure-requests.

NO LOOK-AHEAD: every metric is stamped with the 10-K FILED date, so the backtest
can use only fundamentals that were public AT each historical bar. Annual
(10-K/FY) figures only — slow-moving, restatement-robust.

Emits a static artifact the cloud path could later READ (invariant A); the
trading path never imports this. The fundamental FACTOR is param-gated and OFF by
default until validated on the 3-year deep data.
"""
import argparse
import json
import os
import time
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WATCHLIST = os.path.join(ROOT, "config", "watchlist.json")
OUT = os.path.join(ROOT, "data", "fundamentals.json")
UA = {"User-Agent": "AutoTrading Research bheedey@gmail.com"}

REVENUE_CONCEPTS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                    "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"]
NI_CONCEPTS = ["NetIncomeLoss"]
EQ_CONCEPTS = ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def quality_score(rev_growth, net_margin, roe):
    """Absolute quality/growth tilt in [-1, 1] (margin-weighted, growth + ROE)."""
    s_margin = _clip(net_margin / 0.20, 0.0, 2.0) - 1.0      # 20% margin -> 0, 40%+ -> +1
    s_growth = _clip(rev_growth / 0.20, -1.0, 1.0)            # +/-20% YoY -> +/-1
    s_roe = _clip(roe / 0.25, 0.0, 2.0) - 1.0                # 25% ROE -> 0, 50%+ -> +1
    return round(0.4 * s_margin + 0.3 * s_growth + 0.3 * s_roe, 4)


def _annual(gaap, concepts):
    """{end_date: (val, filed_date)} for the first matching concept (10-K/FY)."""
    for c in concepts:
        u = gaap.get(c, {}).get("units", {}).get("USD", [])
        rows = [x for x in u if x.get("form") == "10-K" and x.get("fp") == "FY" and x.get("end")]
        if rows:
            out = {}
            for x in sorted(rows, key=lambda r: r.get("filed", "")):  # last filed wins (restatements)
                out[x["end"]] = (x["val"], x.get("filed", x["end"]))
            return out
    return {}


def fundamentals_for(cik):
    cf = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                      headers=UA, timeout=30).json()
    gaap = cf.get("facts", {}).get("us-gaap", {})
    rev, ni, eq = _annual(gaap, REVENUE_CONCEPTS), _annual(gaap, NI_CONCEPTS), _annual(gaap, EQ_CONCEPTS)
    ends = sorted(rev)
    series = []
    for i, end in enumerate(ends):
        if i == 0 or ends[i - 1] not in rev:
            continue
        r_now, r_prev = rev[end][0], rev[ends[i - 1]][0]
        if not r_prev or not r_now:
            continue
        growth = (r_now - r_prev) / abs(r_prev)
        margin = ni[end][0] / r_now if end in ni and r_now else 0.0
        roe = (ni[end][0] / eq[end][0]) if end in ni and end in eq and eq[end][0] else 0.0
        # effective date = when this 10-K became public (the revenue filing date)
        effective = rev[end][1]
        series.append({"effective": effective[:10], "fiscal_end": end,
                       "revenue_growth": round(growth, 4), "net_margin": round(margin, 4),
                       "roe": round(roe, 4),
                       "quality_score": quality_score(growth, margin, roe)})
    return series


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch point-in-time fundamentals from SEC EDGAR.")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)

    tk = requests.get("https://www.sec.gov/files/company_tickers.json", headers=UA, timeout=30).json()
    by_tic = {v["ticker"]: str(v["cik_str"]).zfill(10) for v in tk.values()}

    w = json.load(open(WATCHLIST))
    buckets = w.get("buckets", w)
    symbols = []
    for spec in buckets.values():
        syms = spec.get("symbols", spec) if isinstance(spec, dict) else spec
        symbols += [s for s in (syms or []) if "/" not in s]

    out = {}
    for s in symbols:
        cik = by_tic.get(s)
        if not cik:
            print(f"  {s}: no CIK (ETF/non-filer) — skipped")
            continue
        try:
            series = fundamentals_for(cik)
            if series:
                out[s] = series
                print(f"  {s}: {len(series)} fiscal years, latest quality={series[-1]['quality_score']}")
            time.sleep(0.12)  # SEC fair-access (~10 req/s cap)
        except Exception as e:
            print(f"  {s}: {e}")

    artifact = {"as_of": datetime.now(timezone.utc).isoformat(),
                "source": "SEC EDGAR companyfacts (10-K/FY, point-in-time by filed date)",
                "scoring": "quality_score = 0.4*margin + 0.3*growth + 0.3*roe, each in [-1,1]",
                "fundamentals": out}
    with open(args.out, "w") as f:
        json.dump(artifact, f, indent=2)
        f.write("\n")
    print(f"Wrote {args.out}: {len(out)}/{len(symbols)} symbols with fundamentals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
