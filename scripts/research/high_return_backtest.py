#!/usr/bin/env python3
"""High-return / higher-risk strategy search — no-look-ahead, net of friction.

Client objective: MAXIMIZE absolute return, accepting larger drawdowns, for a
long-only $100k US-equity account on DAILY bars, WITHIN the hardcoded caps
(no leverage/margin/derivatives; single-name concentration is the only "more
risk" lever). Universe: data/deep_wide5 (124 symbols x 1259 daily bars, 5y).

Discipline: monthly rebalance on month-end signals, executed at the NEXT day's
open-equivalent (we hold from the next session). Momentum uses 12-1 (skip the
most recent month) by default. Friction charged on turnover each rebalance.
Metrics reuse scripts/backtest/metrics.py (Sharpe/Sortino/CAGR/maxDD).

This is OFFLINE research (T2). Places NO orders. Reports absolute AND
risk-adjusted numbers so the trade-off is explicit.
"""
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from scripts.backtest import metrics as M  # noqa: E402

DATA_GLOB = os.path.join(REPO, "data", "deep_wide5", "*.json")
FRICTION_BPS = 10.0          # each side (cost+slippage), matches the P3 backtest floor
ETFS = {"SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "SHY", "BIL"}


def load():
    close, sector = {}, {}
    for fp in glob.glob(DATA_GLOB):
        sec = os.path.splitext(os.path.basename(fp))[0]
        d = json.load(open(fp))
        for sym, bars in d.get("bars", {}).items():
            close[sym] = {b["t"][:10]: b["c"] for b in bars}
            sector[sym] = sec
    dates = sorted({dt for s in close.values() for dt in s})
    return close, sector, dates


def sma(series, dates, i, n):
    if i < n:
        return None
    vals = [series.get(dates[j]) for j in range(i - n + 1, i + 1)]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if len(vals) >= n * 0.8 else None


def month_end_idx(dates):
    """Indices of the last trading day of each month."""
    idx = []
    for i in range(len(dates) - 1):
        if dates[i][:7] != dates[i + 1][:7]:
            idx.append(i)
    idx.append(len(dates) - 1)
    return idx


def ret(close, sym, dates, i, lookback, skip=0):
    """Return of sym from date[i-lookback-skip] to date[i-skip]. None if data missing."""
    a, b = i - lookback - skip, i - skip
    if a < 0:
        return None
    ca, cb = close[sym].get(dates[a]), close[sym].get(dates[b])
    if not ca or not cb:
        return None
    return cb / ca - 1.0


def simulate(close, dates, weights_at_rebal, rebal_idx):
    """Daily equity curve from a dict {rebal_i: {sym: weight}}. Weights drift with
    price between rebalances; friction charged on turnover at each rebalance."""
    fr = FRICTION_BPS / 10000.0
    equity = 1.0
    curve = [1.0]
    w = {}
    prev_w = {}
    rebal_set = dict(weights_at_rebal)
    for i in range(1, len(dates)):
        # rebalance happens at the OPEN after a month-end signal -> apply target
        # weights computed at i-1 (a rebal index) starting from day i.
        if (i - 1) in rebal_set:
            target = rebal_set[i - 1]
            turnover = sum(abs(target.get(s, 0) - prev_w.get(s, 0))
                           for s in set(target) | set(prev_w))
            equity *= (1.0 - fr * turnover)
            w = dict(target)
            prev_w = dict(target)
        # daily portfolio return from held names
        d0, d1 = dates[i - 1], dates[i]
        port_r, new_w, tot = 0.0, {}, 0.0
        for s, wi in w.items():
            c0, c1 = close[s].get(d0), close[s].get(d1)
            r = (c1 / c0 - 1.0) if (c0 and c1) else 0.0
            port_r += wi * r
            new_w[s] = wi * (1.0 + r)
            tot += new_w[s]
        if tot > 0:
            w = {s: v / tot for s, v in new_w.items()}
            prev_w = dict(w)
        equity *= (1.0 + port_r)
        curve.append(equity)
    return curve


def stats(curve):
    rets = M.returns_from_equity(curve)
    return {
        "CAGR%": round(M.cagr(curve, periods_per_year=252) * 100, 1),
        "Sharpe": round(M.sharpe_ratio(rets), 2),
        "Sortino": round(M.sortino_ratio(rets), 2),
        "MaxDD%": round(M.max_drawdown(curve) * 100, 1),
        "TotRet%": round((curve[-1] / curve[0] - 1) * 100, 0),
    }


def build_momentum(close, sector, dates, rebal_idx, *, topk, lookback=252, skip=21,
                   trend_filter=False, risk_off="BIL", stocks_only=True,
                   max_per_sector=None):
    """{rebal_i: {sym: weight}} for concentrated cross-sectional momentum.
    ``max_per_sector`` optionally caps how many names one sector can contribute
    (diversification guard against a single-industry concentration bomb)."""
    weights = {}
    for i in rebal_idx:
        if trend_filter:
            spy_c = close["SPY"].get(dates[i])
            spy_sma = sma(close["SPY"], dates, i, 200)
            if spy_c is None or spy_sma is None or spy_c < spy_sma:
                weights[i] = {risk_off: 1.0}
                continue
        cands = []
        for sym in close:
            if stocks_only and sym in ETFS:
                continue
            m = ret(close, sym, dates, i, lookback, skip)
            if m is not None:
                cands.append((m, sym))
        if not cands:
            continue
        cands.sort(reverse=True)
        picks, sec_count = [], {}
        for _, s in cands:
            if len(picks) >= topk:
                break
            sec = sector.get(s, "?")
            if max_per_sector and sec_count.get(sec, 0) >= max_per_sector:
                continue
            picks.append(s)
            sec_count[sec] = sec_count.get(sec, 0) + 1
        weights[i] = {s: 1.0 / len(picks) for s in picks}
    return weights


def build_dual_momentum(close, dates, rebal_idx, *, risk_assets=("QQQ", "SPY"),
                        safe="TLT", lookback=252):
    """GEM-style: if the best risk asset's 12m return > 0 (absolute momentum),
    hold it; else go to the safe asset (bonds)."""
    weights = {}
    for i in rebal_idx:
        best, best_r = None, -1e9
        for a in risk_assets:
            r = ret(close, a, dates, i, lookback)
            if r is not None and r > best_r:
                best, best_r = a, r
        weights[i] = {best: 1.0} if (best and best_r > 0) else {safe: 1.0}
    return weights


def build_trend(close, dates, rebal_idx, *, asset="QQQ", safe="BIL", n=200):
    """Hold `asset` when above its n-day SMA, else `safe`."""
    weights = {}
    for i in rebal_idx:
        c = close[asset].get(dates[i]); s = sma(close[asset], dates, i, n)
        weights[i] = {asset: 1.0} if (c and s and c > s) else {safe: 1.0}
    return weights


def buy_hold(sym):
    return sym


def main():
    close, sector, dates = load()
    rebal = month_end_idx(dates)
    print(f"universe {len(close)} symbols, {len(dates)} days "
          f"{dates[0]}..{dates[-1]}, {len(rebal)} monthly rebalances, "
          f"friction {FRICTION_BPS}bps/side\n")

    results = {}

    # Benchmarks
    for bh in ("SPY", "QQQ"):
        w = {rebal[0]: {bh: 1.0}}
        results[f"BUY&HOLD {bh}"] = stats(simulate(close, dates, w, rebal))

    # Concentrated momentum (the high-return lever): top-K, 12-1
    for k in (5, 10, 20):
        w = build_momentum(close, sector, dates, rebal, topk=k)
        results[f"MOMENTUM top{k} (12-1)"] = stats(simulate(close, dates, w, rebal))

    # Momentum + market trend filter (crash protection) -> cash or bonds when risk-off
    for k in (5, 10):
        for off in ("BIL", "TLT"):
            w = build_momentum(close, sector, dates, rebal, topk=k,
                               trend_filter=True, risk_off=off)
            results[f"MOM top{k} + trend->{off}"] = stats(simulate(close, dates, w, rebal))

    # Shorter-lookback (6-month) concentrated momentum
    for k in (5, 10):
        w = build_momentum(close, sector, dates, rebal, topk=k, lookback=126, skip=21)
        results[f"MOMENTUM top{k} (6-1)"] = stats(simulate(close, dates, w, rebal))
    w = build_momentum(close, sector, dates, rebal, topk=10, lookback=126, skip=21,
                       trend_filter=True, risk_off="TLT")
    results["MOM top10 (6-1) + trend->TLT"] = stats(simulate(close, dates, w, rebal))

    # Dual momentum (GEM-style)
    w = build_dual_momentum(close, dates, rebal, risk_assets=("QQQ", "SPY"), safe="TLT")
    results["DUAL-MOM QQQ/SPY vs TLT"] = stats(simulate(close, dates, w, rebal))

    # Trend-following on QQQ
    w = build_trend(close, dates, rebal, asset="QQQ", safe="BIL")
    results["TREND QQQ>200SMA else BIL"] = stats(simulate(close, dates, w, rebal))
    w = build_trend(close, dates, rebal, asset="QQQ", safe="TLT")
    results["TREND QQQ>200SMA else TLT"] = stats(simulate(close, dates, w, rebal))

    # CAP-COMPLIANT versions: our hardcoded stock cap is 8%/name, so equal-weight
    # topK needs K>=13 (1/13=7.7%). These are the ACTUALLY implementable variants.
    curves = {}
    for k in (13, 15):
        w = build_momentum(close, sector, dates, rebal, topk=k)
        c = simulate(close, dates, w, rebal); curves[f"MOM top{k} (12-1) [cap-ok]"] = c
        results[f"MOM top{k} (12-1) [cap-ok]"] = stats(c)
    w = build_momentum(close, sector, dates, rebal, topk=15, trend_filter=True, risk_off="BIL")
    c = simulate(close, dates, w, rebal); curves["MOM top15 + trend->BIL [cap-ok]"] = c
    results["MOM top15 + trend->BIL [cap-ok]"] = stats(c)
    # EXACT deployed config: top-13 + trend->BIL (the live sleeve's use_trend=true).
    w = build_momentum(close, sector, dates, rebal, topk=13, trend_filter=True, risk_off="BIL")
    c = simulate(close, dates, w, rebal); curves["MOM top13 + trend->BIL [DEPLOYED]"] = c
    results["MOM top13 + trend->BIL [DEPLOYED]"] = stats(c)
    # CORRECTION candidates: no-trend (the validated high-return variant) WITH a
    # per-sector cap so it can't go ~55% into one industry (the semis-bubble risk).
    for mps in (3, 4):
        w = build_momentum(close, sector, dates, rebal, topk=13, max_per_sector=mps)
        c = simulate(close, dates, w, rebal)
        curves[f"MOM top13 no-trend, max{mps}/sector [FIX]"] = c
        results[f"MOM top13 no-trend, max{mps}/sector [FIX]"] = stats(c)

    # ---- report, sorted by CAGR (the client's objective) ----
    hdr = f"{'STRATEGY':<34}{'CAGR%':>7}{'MaxDD%':>8}{'Sharpe':>8}{'Sortino':>9}{'TotRet%':>9}"
    print(hdr); print("-" * len(hdr))
    for name, s in sorted(results.items(), key=lambda kv: -kv[1]["CAGR%"]):
        print(f"{name:<34}{s['CAGR%']:>7}{s['MaxDD%']:>8}{s['Sharpe']:>8}"
              f"{s['Sortino']:>9}{s['TotRet%']:>9}")

    # ---- ROBUSTNESS: by-calendar-year return of the cap-compliant leader ----
    lead = "MOM top15 (12-1) [cap-ok]"
    w = build_momentum(close, sector, dates, rebal, topk=15)
    curve = simulate(close, dates, w, rebal)
    print(f"\nBy-year total return — {lead} (out-of-sample robustness):")
    yrs = {}
    for i in range(1, len(dates)):
        y = dates[i][:4]
        yrs.setdefault(y, []).append(curve[i] / curve[i - 1] - 1)
    spy_w = {rebal[0]: {"SPY": 1.0}}; spy_c = simulate(close, dates, spy_w, rebal)
    spy_yrs = {}
    for i in range(1, len(dates)):
        spy_yrs.setdefault(dates[i][:4], []).append(spy_c[i] / spy_c[i - 1] - 1)

    def compound(rs):
        e = 1.0
        for r in rs:
            e *= (1 + r)
        return (e - 1) * 100
    for y in sorted(yrs):
        print(f"  {y}: strategy {compound(yrs[y]):+6.1f}%   vs SPY {compound(spy_yrs[y]):+6.1f}%")

    # ---- multiple-testing penalty: deflated Sharpe across ALL variants tried ----
    all_curves = dict(curves)
    all_curves[lead] = curve
    pps = []
    for c in all_curves.values():
        r = M.returns_from_equity(c); sd = M._std(r)
        pps.append((M._mean(r) / sd) if sd else 0.0)
    n_obs = len(M.returns_from_equity(curve))
    n_trials = len(results)
    dsr = M.deflated_sharpe_ratio(pps, n_obs)
    print(f"\nDeflated Sharpe (best of ~{n_trials} variants, n_obs={n_obs}): {dsr:.3f} "
          f"(>0.95 = significant after multiple-testing)")
    print("CAVEAT: universe is 124 CURRENT large-caps — SURVIVORSHIP BIAS inflates "
          "momentum returns (dead/delisted names excluded). Treat live expectations LOWER.")

    print("\n###JSON###")
    print(json.dumps({"as_of": None, "window": [dates[0], dates[-1]],
                      "friction_bps_each_side": FRICTION_BPS,
                      "universe": len(close), "results": results}, indent=2))


if __name__ == "__main__":
    main()
