#!/usr/bin/env python3
"""P2 "Capitol Shadow" — SIGNAL-CONVERGENCE experiment (no look-ahead).

Question
--------
The prior committed backtest (scripts/research/p2_congress_copy_backtest.py)
found congress disclosure-copy has NO durable alpha: the deployed 8% / 180d
rule is t_alpha=0.41, and the only headline (hold_63d, t_alpha=3.76) is
2020-COVID + 2022-bear concentrated BETA, flat-to-negative in 2021/24/25/26.
Common cause across P2/P3: each fires on ONE signal.

This experiment tests whether requiring a SECOND, INDEPENDENT confirmation —
a price/technical gate ON THE FILL DATE — turns disclosure-copy's no-alpha
into real, OOS-stable alpha.

It EXTENDS the committed script by importing its no-look-ahead machinery
(PTR parse cache, ticker mapping, friction, t+1 fill, matched-pair SPY alpha)
and adds a technical-confirmation variant. The committed money-path / live-bot
files are NOT touched — this is an offline (T2) research script only.

No-look-ahead discipline (identical to the base study, plus the gate):
  * signal known at CLOSE of the public filing date t; fill at OPEN of t+1;
  * point-in-time: only the DISCLOSURE (filing) date is used, never the
    private transaction date;
  * friction >= 5 bps EACH side (reuses friction.load_friction, floored 5/5);
  * the TECHNICAL GATE at fill bar ei uses ONLY data dated strictly before the
    fill open: 50-day SMA from the 50 closes ending at ei-1, and a 3-month
    (63-trading-day) trailing return from ei-1 back to ei-64. The fill OPEN
    (which IS observable at the fill instant) is compared to that SMA.

Matched comparison (the honest part)
------------------------------------
Both variants are evaluated on the SAME eligible set: a copy event qualifies
only if (a) it fills t+1 within the stale-fill guard AND (b) it has >= 64 bars
of prior history (needed to compute the gate). Disclosure-ALONE = every
eligible event. Disclosure+TECH = the subset that ALSO passes the gate. So the
gate's effect is a clean within-sample partition, not a different universe.

Headline horizon = hold_63d (the base study's strongest disclosure window).
Also reports hold_21d / hold_126d and the deployed p2_rules exit for context.
Reports n, mean alpha % vs SPY (matched-pair), t_stat_alpha, and by-year OOS
for each variant. Real numbers only — run it; small N is flagged, not smoothed.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# Reuse the committed base study's verified, no-look-ahead building blocks.
import scripts.research.p2_congress_copy_backtest as base  # noqa: E402
from scripts.backtest.friction import load_friction  # noqa: E402

# Gate parameters (the convergence hypothesis under test).
SMA_WINDOW = 50          # fill price must be above its 50-day SMA (uptrend filter)
MOM_LOOKBACK = 63        # ~3 trading months for the trailing-return filter
MIN_HISTORY = MOM_LOOKBACK + 1  # bars required BEFORE the fill bar to compute the gate
HORIZONS = [21, 63, 126]


def technical_gate(series, ei, entry_open):
    """Decide the gate at fill bar ``ei`` using ONLY pre-fill data.

    Returns (passes: bool, info: dict|None). info is None when there is
    insufficient history to even evaluate the gate (the event is then
    INELIGIBLE for BOTH variants, so the comparison stays matched).

    No look-ahead: closes used are series[ei-1] .. series[ei-50]/[ei-64], all
    strictly before the fill bar's OPEN. The fill OPEN itself is observable at
    the moment of the fill, so comparing it to the (already-known) SMA is fair.
    """
    if ei < MIN_HISTORY:
        return None, None  # ineligible: cannot compute gate
    # 50-day SMA of closes ending at the bar BEFORE the fill (indices ei-50..ei-1)
    window = series[ei - SMA_WINDOW: ei]
    sma = sum(b[2] for b in window) / SMA_WINDOW
    # 3-month trailing return: close[ei-1] / close[ei-1-63] - 1  (all pre-fill)
    prior_close = series[ei - 1][2]
    past_close = series[ei - 1 - MOM_LOOKBACK][2]
    mom_3m = (prior_close / past_close - 1.0) if past_close > 0 else None
    if mom_3m is None:
        return None, None
    above_sma = entry_open > sma
    positive_mom = mom_3m > 0.0
    passes = above_sma and positive_mom
    return passes, {
        "above_sma": above_sma,
        "positive_mom": positive_mom,
        "sma": sma,
        "mom_3m": mom_3m,
    }


def run_variants(buys, bars, spy, cost_bps, slip_bps):
    """Build matched (stock_ret, spy_ret) pairs for two variants per horizon,
    on the SAME eligible set. Returns nested dict + diagnostics."""
    fr = (cost_bps + slip_bps) / 10000.0  # per side, fraction

    def blank():
        return {"pairs": [], "by_year": {}}

    variants = {
        "disclosure_alone": {f"hold_{h}d": blank() for h in HORIZONS},
        "disclosure_plus_tech": {f"hold_{h}d": blank() for h in HORIZONS},
    }
    # deployed-exit context (8%/25%/180d) on each variant too
    for v in variants:
        variants[v]["p2_rules"] = blank()

    diag = {"eligible": 0, "gate_pass": 0, "gate_fail": 0,
            "ineligible_no_history": 0, "no_price": 0, "no_future_bar": 0,
            "stale_skipped": 0, "bad_open": 0,
            "gate_fail_reason": {"below_sma": 0, "neg_mom": 0, "both": 0}}

    for bz in buys:
        tk = bz["ticker"]
        series = bars.get(tk)
        if not series:
            diag["no_price"] += 1
            continue
        fdate = bz["filing_date"]
        ei = base.next_open_index(series, fdate)
        if ei is None:
            diag["no_future_bar"] += 1
            continue
        # identical stale-fill guard as the base study
        if base._iso_gap_days(fdate, series[ei][0]) > base.MAX_FILL_GAP_DAYS:
            diag["stale_skipped"] += 1
            continue
        entry_open = series[ei][1]
        if entry_open <= 0:
            diag["bad_open"] += 1
            continue

        passes, info = technical_gate(series, ei, entry_open)
        if info is None:
            diag["ineligible_no_history"] += 1
            continue  # ineligible for BOTH -> stays matched

        diag["eligible"] += 1
        entry_px = entry_open * (1 + fr)
        yr = str(bz["filing_year"])
        spy_ei = base.next_open_index(spy, fdate) if spy else None

        if passes:
            diag["gate_pass"] += 1
        else:
            diag["gate_fail"] += 1
            if not info["above_sma"] and not info["positive_mom"]:
                diag["gate_fail_reason"]["both"] += 1
            elif not info["above_sma"]:
                diag["gate_fail_reason"]["below_sma"] += 1
            else:
                diag["gate_fail_reason"]["neg_mom"] += 1

        # Build the per-trade pairs once; assign to alone always, to tech if it passes.
        targets = ["disclosure_alone"] + (["disclosure_plus_tech"] if passes else [])

        for h in HORIZONS:
            xi = ei + h
            if xi >= len(series):
                continue
            exit_px = series[xi][2] * (1 - fr)
            ret = exit_px / entry_px - 1.0
            sret = base.spy_ret(spy, spy_ei, h, fr)
            for v in targets:
                d = variants[v][f"hold_{h}d"]
                d["pairs"].append((ret, sret))
                d["by_year"].setdefault(yr, []).append((ret, sret))

        # deployed exit (8% trailing / 25% TP / 180d)
        rret, hold_used = base.p2_exit(series, ei, entry_px, fr, stop=0.08, tp=0.25, maxhold=180)
        rsret = base.spy_ret(spy, spy_ei, hold_used, fr)
        for v in targets:
            d = variants[v]["p2_rules"]
            d["pairs"].append((rret, rsret))
            d["by_year"].setdefault(yr, []).append((rret, rsret))

    return variants, diag


def main():
    print("=" * 74)
    print("P2 CAPITOL SHADOW — TECHNICAL-CONFIRMATION convergence test (no look-ahead)")
    print("=" * 74)

    # ----- reuse the base pipeline through final_buys (parse cache + mapping) -----
    filings = json.loads(base.INDEX.read_text())
    cache = base.stage2_parse(filings)  # cached -> no network

    txns = []
    for f in filings:
        rec = cache.get(f["doc_id"], {})
        for row in rec.get("rows", []):
            txns.append({**row, "member": f["member"], "filing_date": f["filing_date"],
                         "filing_year": f["year"]})

    equity_buys = [t for t in txns
                   if t["code"] == "P"
                   and not base.looks_like_bond_or_private(t["asset_name"], t["asset_code"])]

    bars = base.load_universe_bars()
    priceable = set(bars.keys())
    # extend with cached extra bars (parenthetical tickers not in deep_wide5)
    import re
    extra_candidates = sorted({b["ticker_paren"] for b in equity_buys
                               if b.get("ticker_paren") and b["ticker_paren"] not in priceable
                               and re.fullmatch(r"[A-Z]{1,5}", b["ticker_paren"])})
    extra = base.fetch_extra_bars(extra_candidates)  # cached -> no network
    for tk, rows in extra.items():
        if len(rows) >= 100:
            bars[tk] = sorted((b["t"][:10], float(b["o"]), float(b["c"])) for b in rows)
            priceable.add(tk)

    mapped = []
    for b in equity_buys:
        tk = base.map_to_ticker(b, priceable)
        if tk:
            b2 = dict(b)
            b2["ticker"] = tk
            mapped.append(b2)

    final_buys = []
    for b in mapped:
        try:
            fd = base.parse_mdy(b["filing_date"])
            td = base.parse_mdy(b["txn_date"])
            lag = (fd - td).days
            if lag < 0 or lag > 400:
                lag = None
            b["filing_date"] = fd.isoformat()
            b["disclosure_lag_days"] = lag
            final_buys.append(b)
        except Exception:  # noqa: BLE001
            continue
    seen, dedup = set(), []
    for b in final_buys:
        k = (b["member"], b["ticker"], b["txn_date"], b["filing_date"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(b)
    final_buys = dedup
    print("Final distinct equity-BUY copy events: %d (unique tickers: %d)"
          % (len(final_buys), len({b["ticker"] for b in final_buys})))

    cost_bps, slip_bps = load_friction("portfolio_2")
    print("Friction: cost=%.1fbps slip=%.1fbps each side" % (cost_bps, slip_bps))
    print("Gate: fill_open > %dd-SMA  AND  %dd trailing return > 0  (both pre-fill)"
          % (SMA_WINDOW, MOM_LOOKBACK))

    spy = bars.get("SPY")
    variants, diag = run_variants(final_buys, bars, spy, cost_bps, slip_bps)

    print("\nELIGIBILITY / GATE DIAGNOSTICS:")
    print("  eligible (fills + >=64d history): %d" % diag["eligible"])
    print("  gate PASS: %d  |  gate FAIL: %d  (fail reasons: %s)"
          % (diag["gate_pass"], diag["gate_fail"], diag["gate_fail_reason"]))
    print("  ineligible(no history): %d  stale: %d  no_price: %d"
          % (diag["ineligible_no_history"], diag["stale_skipped"], diag["no_price"]))

    report = {
        "as_of": datetime.utcnow().isoformat(),
        "experiment": "P2 disclosure-copy + technical-confirmation convergence",
        "n_copy_events": len(final_buys),
        "gate": {"sma_window": SMA_WINDOW, "mom_lookback_days": MOM_LOOKBACK,
                 "rule": "fill_open > %dd_SMA AND %dd_trailing_return > 0"
                         % (SMA_WINDOW, MOM_LOOKBACK)},
        "friction_bps_each_side": {"cost": cost_bps, "slippage": slip_bps},
        "diagnostics": diag,
        "variants": {},
    }

    for vname, vdata in variants.items():
        report["variants"][vname] = {}
        print("\n" + "#" * 70)
        print("VARIANT: %s" % vname)
        print("#" * 70)
        for sname, d in vdata.items():
            block = base.stats_block(d["pairs"])
            if not block:
                continue
            by_year = {y: base.stats_block(rs) for y, rs in sorted(d["by_year"].items())}
            report["variants"][vname][sname] = {"overall": block, "by_year": by_year}
            print("\n  [%s]  n=%d  mean=%.2f%%  win=%.0f%%  PF=%s"
                  % (sname, block["n"], block["mean_ret_pct"],
                     block["win_rate_pct"], block["profit_factor"]))
            print("    alpha_vs_SPY=%s%%  (alpha_win=%s%%, t_alpha=%.2f, matched_n=%d)"
                  % (block["mean_alpha_vs_spy_pct"], block["alpha_win_rate_pct"],
                     block["t_stat_alpha"], block["matched_n"]))
            if sname == "hold_63d":
                for y, yb in by_year.items():
                    if yb:
                        flag = " (small N)" if yb["n"] < 30 else ""
                        print("      %s: n=%-4d alpha=%7.2f%% t_alpha=%5.2f%s"
                              % (y, yb["n"], yb["mean_alpha_vs_spy_pct"] or 0.0,
                                 yb["t_stat_alpha"], flag))

    # ------- headline side-by-side on the decision horizon (hold_63d) -------
    a = report["variants"]["disclosure_alone"]["hold_63d"]["overall"]
    g = report["variants"]["disclosure_plus_tech"]["hold_63d"]["overall"]
    print("\n" + "=" * 74)
    print("HEADLINE — hold_63d matched-pair alpha vs SPY")
    print("=" * 74)
    print("  disclosure ALONE      : n=%-4d alpha=%6.3f%%  t_alpha=%.2f"
          % (a["n"], a["mean_alpha_vs_spy_pct"], a["t_stat_alpha"]))
    print("  disclosure + TECH gate: n=%-4d alpha=%6.3f%%  t_alpha=%.2f"
          % (g["n"], g["mean_alpha_vs_spy_pct"], g["t_stat_alpha"]))

    # OOS stability check: count years (n>=30) with positive alpha, post-COVID
    def oos_years(vname):
        by = report["variants"][vname]["hold_63d"]["by_year"]
        rows = []
        for y, b in by.items():
            if b and int(y) >= 2021 and b["n"] >= 30:
                rows.append((y, b["mean_alpha_vs_spy_pct"], b["t_stat_alpha"], b["n"]))
        return rows

    print("\n  POST-2020 OOS by-year alpha (n>=30 only; excludes COVID 2020):")
    for vname in ("disclosure_alone", "disclosure_plus_tech"):
        rows = oos_years(vname)
        pos = sum(1 for _, al, _, _ in rows if al > 0)
        print("    %-22s positive-alpha years: %d/%d  -> %s"
              % (vname, pos, len(rows),
                 ", ".join("%s:%+.1f%%" % (y, al) for y, al, _, _ in rows)))

    out_path = REPO / "data" / "p2_congress_technical_confirmation_backtest.json"
    out_path.write_text(json.dumps(report, indent=2))
    print("\nReport -> %s" % out_path)
    return report


if __name__ == "__main__":
    main()
