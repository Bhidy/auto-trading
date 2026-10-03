#!/usr/bin/env python3
"""SIMULATION engine for the frozen 2026-07-04 P1 momentum spec. OFFLINE research only.

Signal logic is imported from the repo (scripts/momentum_selector.py) so we test the
exact deployed selector + vol-target code. Signals use SPLIT-ONLY adjusted closes (as the
live AlpacaClient.get_stock_bars does: feed=sip, adjustment=split); P&L uses
TOTAL-RETURN (adjustment=all) opens/closes so dividends are credited. Execution at the
OPEN of the rebalance day; signal from the PRIOR close. Cash earns BIL total return.
"""
import json
import math
import os
import sys

REPO = "."
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)
from momentum_selector import select_top_momentum, vol_target_scalar  # noqa: E402
from scripts.backtest import metrics as M  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def universe():
    u = json.load(open(os.path.join(REPO, "config/universe_wide.json")))
    syms, sector = [], {}
    for bucket, b in u["buckets"].items():
        if b.get("instrument_type") == "stock":
            for s in b["symbols"]:
                syms.append(s)
                sector[s] = bucket
    return sorted(set(syms)), sector


def load_dir(d):
    out = {}
    for fn in os.listdir(d):
        if fn.endswith(".json"):
            bars = json.load(open(os.path.join(d, fn)))
            if bars:
                out[fn[:-5]] = {b["t"][:10]: (b["o"], b["h"], b["l"], b["c"]) for b in bars}
    return out


# Corporate-action artifacts found in Alpaca data (verified by gap scan):
#  GE 2021-08-02 1:8 reverse split NOT adjusted in either 'all' or 'split' feeds (x8.07 gap)
#  GE 2023-01-04 GEHC spin-off, GE 2024-04-02 GEV spin-off, RTX 2020-04-03 UTC/Carrier/Otis
#  -> not adjusted in 'all' (total-return) data: neutralise the overnight gap to SPY's gap.
SPLIT_FIX = [("GE", "2021-08-02", 8.0)]
SPIN_FIX_PNL = [("GE", "2023-01-04"), ("GE", "2024-04-02"), ("RTX", "2020-04-03")]


def _scale_before(m, date, f):
    for d in list(m):
        if d < date:
            o, h, l, c = m[d]
            m[d] = (o * f, h * f, l * f, c * f)


def apply_fixes(px, sg, fix_signal_spins=False):
    for s, d, f in SPLIT_FIX:
        for m in (px, sg):
            if s in m:
                _scale_before(m[s], d, f)
    spy = px["SPY"]
    ds = sorted(spy)
    for s, d in SPIN_FIX_PNL:
        targets = [px] + ([sg] if fix_signal_spins else [])
        for mm in targets:
            if s not in mm or d not in mm[s]:
                continue
            m = mm[s]
            sd = sorted(m)
            prev = sd[sd.index(d) - 1]
            gap = m[d][0] / m[prev][3]
            pi = ds.index(d)
            spy_gap = spy[d][0] / spy[ds[pi - 1]][3]
            _scale_before(m, d, gap / spy_gap)


class Data:
    def __init__(self, pnl_dir, sig_dir, fix=True):
        self.px = load_dir(os.path.join(HERE, pnl_dir))      # total-return adjusted
        self.sg = load_dir(os.path.join(HERE, sig_dir))      # split-only (signal)
        if fix:
            apply_fixes(self.px, self.sg, fix_signal_spins=(pnl_dir == sig_dir))
        self.dates = sorted(self.px["SPY"].keys())
        self.di = {d: i for i, d in enumerate(self.dates)}
        self.syms, self.sector = universe()
        # per-symbol signal close history (own bars, like live)
        self.sig_dates, self.sig_closes = {}, {}
        for s, m in self.sg.items():
            ds = sorted(m)
            self.sig_dates[s] = ds
            self.sig_closes[s] = [m[d][3] for d in ds]
        self.sig_pos = {s: {d: i for i, d in enumerate(ds)} for s, ds in self.sig_dates.items()}

    def closes_upto(self, sym, date, n=300, window_start=None):
        """Signal closes of sym on/before `date`. If window_start is given, only bars
        dated >= window_start (mimics live: start = run_date - 420 calendar days)."""
        import bisect
        ds = self.sig_dates.get(sym)
        if not ds:
            return None
        pos = bisect.bisect_right(ds, date) - 1
        if pos < 0:
            return None
        lo = max(0, pos - n + 1)
        if window_start:
            lo = max(lo, bisect.bisect_left(ds, window_start))
        return self.sig_closes[sym][lo:pos + 1]

    def first_days_of_month(self, start, end):
        out = []
        for i, d in enumerate(self.dates):
            if d < start or d > end:
                continue
            if i == 0 or self.dates[i - 1][:7] != d[:7]:
                out.append(i)
        return out


def build_targets(D, sig_idx, k=13, lookback=252, skip=21, max_per_sector=4,
                  vol_target=0.25, sleeve=0.90, exclude=None, min_bars=274,
                  return_meta=False):
    import datetime as _dt
    sig_date = D.dates[sig_idx]
    run_date = D.dates[min(sig_idx + 1, len(D.dates) - 1)]
    ws = (_dt.date.fromisoformat(run_date) - _dt.timedelta(days=420)).isoformat()
    cbs = {}
    for s in D.syms:
        if exclude and s in exclude:
            continue
        c = D.closes_upto(s, sig_date, n=500, window_start=ws)
        if c and len(c) >= min_bars:
            cbs[s] = c
    max_w = max(0.08, 1.0 / k)                   # k<13 only reachable by relaxing cap
    raw = select_top_momentum(cbs, k=k, max_weight=max_w, lookback=lookback, skip=skip,
                              market_closes=D.closes_upto("SPY", sig_date, 500, ws),
                              use_trend=False, sector_map=D.sector,
                              max_per_sector=max_per_sector)
    vs, bv = 1.0, None
    if raw and vol_target:
        vs, bv = vol_target_scalar(cbs, raw, target_vol=vol_target, lookback=63,
                                   min_scale=0.30)
    tgt = {s: w * sleeve * vs for s, w in raw.items()}
    if return_meta:
        return tgt, {"raw": raw, "vol_scale": vs, "book_vol": bv, "n_univ": len(cbs)}
    return tgt


def simulate(D, sched, start_idx, end_idx, cost_bps=5.0, delay=0, e0=1.0,
             cash_sym="BIL"):
    """sched: {rebal_idx: {sym: weight}} (weights of total equity; rest = cash).
    Trades at OPEN of rebal_idx+delay. Returns dict(curve=[e0, close_start..close_end],
    dates, contrib{sym:$pnl}, turnover)."""
    fr = cost_bps / 1e4
    px = D.px
    exec_sched = {}
    for ri, w in sched.items():
        ei = ri + delay
        if ei <= end_idx:
            exec_sched[ei] = w
    sh, last = {}, {}
    cash = e0
    curve, cdates = [e0], [D.dates[start_idx] + "@open"]
    contrib, turnover, costs = {}, 0.0, 0.0
    bil = px[cash_sym]
    for i in range(start_idx, end_idx + 1):
        d = D.dates[i]
        dprev = D.dates[i - 1]
        # mark-to-open
        if i in exec_sched:
            vals = {}
            for s, q in sh.items():
                o = px[s].get(d, (None,))[0] or last.get(s)
                vals[s] = q * o
                if s in last:
                    contrib[s] = contrib.get(s, 0.0) + q * (o - last[s])
                last[s] = o
            eq = cash + sum(vals.values())
            tgt = exec_sched[i]
            trade = 0.0
            new_sh = {}
            for s in set(tgt) | set(sh):
                o = px[s].get(d, (None,))[0] or last.get(s)
                if o is None:
                    continue
                tv = eq * tgt.get(s, 0.0)
                cv = vals.get(s, 0.0)
                trade += abs(tv - cv)
                if tv > 0:
                    new_sh[s] = tv / o
                    last[s] = o
            c = fr * trade
            costs += c
            turnover += trade / eq if eq else 0
            cash = eq - sum(new_sh[s] * last[s] for s in new_sh) - c
            sh = new_sh
            # held from open to close
        else:
            # overnight + intraday: last is previous close
            pass
        # cash accrual (BIL close-to-close)
        b0, b1 = bil.get(dprev), bil.get(d)
        if b0 and b1:
            cash *= b1[3] / b0[3]
        val = cash
        for s, q in sh.items():
            c_ = px[s].get(d, (None, None, None, None))[3] or last.get(s)
            if s in last and last[s]:
                contrib[s] = contrib.get(s, 0.0) + q * (c_ - last[s])
            last[s] = c_
            val += q * c_
        curve.append(val)
        cdates.append(d)
    return {"curve": curve, "dates": cdates, "contrib": contrib, "turnover": turnover,
            "costs": costs}


def bh_curve(D, sym, start_idx, end_idx, e0=1.0, cost_bps=5.0):
    """Buy at OPEN of start_idx, hold to close end_idx."""
    return simulate(D, {start_idx: {sym: 1.0}}, start_idx, end_idx, cost_bps, e0=e0)


def stats(curve, bench=None, ppy=252):
    r = M.returns_from_equity(curve)
    out = {
        "tot%": round((curve[-1] / curve[0] - 1) * 100, 2),
        "cagr%": round(M.cagr(curve, ppy) * 100, 2),
        "vol%": round(M.annualized_volatility(r, ppy) * 100, 1),
        "sharpe": round(M.sharpe_ratio(r, 0.0, ppy), 2),
        "maxdd%": round(-M.max_drawdown(curve) * 100, 1),
    }
    if bench is not None:
        rb = M.returns_from_equity(bench)
        out["xs_cagr%"] = round(out["cagr%"] - M.cagr(bench, ppy) * 100, 2)
        act = [a - b for a, b in zip(r, rb)]
        te = M._std(act) * math.sqrt(ppy)
        out["IR"] = round((M._mean(act) * ppy) / te, 2) if te else None
    return out


def skew_kurt(xs):
    n = len(xs)
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / n
    if v <= 0:
        return 0.0, 3.0
    sk = sum((x - m) ** 3 for x in xs) / n / v ** 1.5
    ku = sum((x - m) ** 4 for x in xs) / n / v ** 2
    return sk, ku
