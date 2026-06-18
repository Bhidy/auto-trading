#!/usr/bin/env python3
"""Robust POINT-IN-TIME fundamentals from SEC EDGAR for the breakout universe
(OFFLINE research lane) -> data/fundamentals_pit.json.

WHY a second fetcher (vs scripts/research/fetch_fundamentals.py):
  The original picked the FIRST matching revenue concept per company. Several
  names (NVDA, BA, XOM, ...) switched XBRL revenue tags over time, so the chosen
  series TRUNCATED years before the 2021-2026 backtest window — freezing their
  quality stale. It also let quarterly rows (fp='FY' but ~90-day duration) leak
  into the "annual" series, producing nonsense YoY growth.

FIXES (all preserve no-look-ahead):
  * MERGE all revenue concepts into one fiscal_end -> value map (so a company can
    span a tag switch) and keep ONLY annual durations (350-385 days).
  * FREE-CASH-FLOW = OperatingCashFlow - CapEx (annual), and TOTAL-LIABILITIES /
    EQUITY leverage — the gate dimensions requested.
  * effective = EARLIEST `filed` date for each fiscal_end (first public
    disclosure). A metric is only usable on bar date t if effective <= t.

Emits a static artifact the backtest READS; the trading path never imports it.
"""
import argparse
import json
import os
import time
from datetime import date, datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "fundamentals_pit.json")
UA = {"User-Agent": "AutoTrading Research bheedey@gmail.com"}

REVENUE_CONCEPTS = ["Revenues",
                    "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "RevenueFromContractWithCustomerIncludingAssessedTax",
                    "SalesRevenueNet"]
NI_CONCEPTS = ["NetIncomeLoss"]
EQ_CONCEPTS = ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
OCF_CONCEPTS = ["NetCashProvidedByUsedInOperatingActivities",
                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CAPEX_CONCEPTS = ["PaymentsToAcquirePropertyPlantAndEquipment",
                  "PaymentsToAcquireProductiveAssets"]
LIAB_CONCEPTS = ["Liabilities"]


def _annual_duration_ok(start, end):
    if not start or not end:
        return False
    try:
        d = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return False
    return 350 <= d <= 386


def _merge_annual(gaap, concepts, want_duration=True):
    """{fiscal_end: (value, earliest_filed)} merged across concepts.

    Annual filings only (10-K). Duration-gated for flow concepts (revenue, NI,
    cash flows). For stock concepts (equity, liabilities) duration is not
    applicable (instant), so want_duration=False keeps point-in-time balances at
    fiscal year-end.  earliest_filed = first public disclosure (no look-ahead).
    """
    out = {}
    for c in concepts:
        u = gaap.get(c, {}).get("units", {}).get("USD", [])
        for x in u:
            if x.get("form") != "10-K":
                continue
            end = x.get("end")
            if not end:
                continue
            if want_duration and not _annual_duration_ok(x.get("start"), end):
                continue
            if not want_duration:
                # balance-sheet item: take the value tagged at a fiscal year-end
                # that also appears as a flow end (filter later by intersection)
                pass
            filed = x.get("filed", end)
            val = x.get("val")
            if val is None:
                continue
            if end not in out or filed < out[end][1]:
                out[end] = (val, filed)
    return out


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def quality_score(rev_growth, net_margin, roe):
    s_margin = _clip(net_margin / 0.20, 0.0, 2.0) - 1.0
    s_growth = _clip(rev_growth / 0.20, -1.0, 1.0)
    s_roe = _clip(roe / 0.25, 0.0, 2.0) - 1.0
    return round(0.4 * s_margin + 0.3 * s_growth + 0.3 * s_roe, 4)


def fundamentals_for(cik):
    cf = requests.get(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
        headers=UA, timeout=30).json()
    gaap = cf.get("facts", {}).get("us-gaap", {})
    rev = _merge_annual(gaap, REVENUE_CONCEPTS)
    ni = _merge_annual(gaap, NI_CONCEPTS)
    ocf = _merge_annual(gaap, OCF_CONCEPTS)
    capex = _merge_annual(gaap, CAPEX_CONCEPTS)
    eq = _merge_annual(gaap, EQ_CONCEPTS, want_duration=False)
    liab = _merge_annual(gaap, LIAB_CONCEPTS, want_duration=False)

    ends = sorted(rev)
    series = []
    for i, end in enumerate(ends):
        if i == 0:
            continue
        prev = ends[i - 1]
        # require consecutive fiscal years (~1yr apart) for a clean YoY
        try:
            gap = (date.fromisoformat(end) - date.fromisoformat(prev)).days
        except ValueError:
            continue
        if not (330 <= gap <= 400):
            continue
        r_now, r_prev = rev[end][0], rev[prev][0]
        if not r_prev or not r_now:
            continue
        growth = (r_now - r_prev) / abs(r_prev)
        margin = (ni[end][0] / r_now) if end in ni and r_now else 0.0
        roe = (ni[end][0] / eq[end][0]) if end in ni and end in eq and eq[end][0] else 0.0
        fcf = None
        if end in ocf and end in capex:
            fcf = ocf[end][0] - capex[end][0]
        elif end in ocf:
            fcf = ocf[end][0]
        debt_to_equity = None
        if end in liab and end in eq and eq[end][0]:
            debt_to_equity = round(liab[end][0] / eq[end][0], 4)
        # effective = the latest of the inputs' earliest-filed dates (all must be
        # public before the metric is usable). Dominated by the 10-K filing.
        eff_candidates = [rev[end][1]]
        for src, k in ((ni, end), (ocf, end), (capex, end)):
            if k in src:
                eff_candidates.append(src[k][1])
        effective = max(eff_candidates)
        series.append({
            "effective": effective[:10],
            "fiscal_end": end,
            "revenue_growth": round(growth, 4),
            "net_margin": round(margin, 4),
            "roe": round(roe, 4),
            "fcf": fcf,
            "fcf_positive": bool(fcf is not None and fcf > 0),
            "debt_to_equity": debt_to_equity,
            "quality_score": quality_score(growth, margin, roe),
        })
    # dedupe by fiscal_end keeping last, then sort by effective
    series.sort(key=lambda r: (r["effective"], r["fiscal_end"]))
    return series


def universe_from_bars():
    import glob
    syms = {}
    for fp in glob.glob(os.path.join(ROOT, "data", "deep_wide5", "*.json")):
        sec = os.path.splitext(os.path.basename(fp))[0]
        if sec in ("core", "defensive"):
            continue
        d = json.load(open(fp))
        for s in d.get("bars", {}):
            syms[s] = sec
    return sorted(syms)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)

    tk = requests.get("https://www.sec.gov/files/company_tickers.json",
                      headers=UA, timeout=30).json()
    by_tic = {v["ticker"]: str(v["cik_str"]).zfill(10) for v in tk.values()}

    symbols = universe_from_bars()
    out = {}
    for s in symbols:
        cik = by_tic.get(s)
        if not cik:
            print(f"  {s}: no CIK — skipped")
            continue
        try:
            series = fundamentals_for(cik)
            if series:
                out[s] = series
                last = series[-1]
                print(f"  {s}: {len(series)} FY rows; last eff={last['effective']} "
                      f"growth={last['revenue_growth']} fcf+={last['fcf_positive']} "
                      f"q={last['quality_score']}")
            else:
                print(f"  {s}: no usable annual series")
            time.sleep(0.12)
        except Exception as e:  # noqa: BLE001
            print(f"  {s}: ERROR {e}")

    artifact = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "SEC EDGAR companyfacts (10-K annual, merged concepts, "
                  "point-in-time by earliest filed date)",
        "scoring": "quality_score=0.4*margin+0.3*growth+0.3*roe; "
                   "fcf=OCF-CapEx; debt_to_equity=Liabilities/Equity",
        "universe": len(symbols),
        "fundamentals": out,
    }
    with open(args.out, "w") as f:
        json.dump(artifact, f, indent=2)
        f.write("\n")
    print(f"\nWrote {args.out}: {len(out)}/{len(symbols)} symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
