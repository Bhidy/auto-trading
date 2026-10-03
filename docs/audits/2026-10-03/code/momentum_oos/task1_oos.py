#!/usr/bin/env python3
"""TASK 1 — TRUE OOS SIMULATION of the frozen spec, 2026-07-06 open -> 2026-10-02 close."""
import json
import sys

from engine import Data, build_targets, simulate, bh_curve, stats, M

PNL = sys.argv[1] if len(sys.argv) > 1 else "bars_sip_all"
SIG = sys.argv[2] if len(sys.argv) > 2 else "bars_sip_split_full"
D = Data(PNL, SIG)
di = D.di
start, end = di["2026-07-06"], di["2026-10-02"]
rebals = [di[d] for d in ("2026-07-06", "2026-08-03", "2026-09-01", "2026-10-01")]
out = {"pnl_data": PNL, "sig_data": SIG}

sched, meta = {}, {}
for r in rebals:
    t, m = build_targets(D, r - 1, return_meta=True)
    sched[r] = t
    meta[D.dates[r]] = {"signal_date": D.dates[r - 1], "picks": sorted(m["raw"]),
                        "vol_scale": round(m["vol_scale"], 4),
                        "book_vol": round(m["book_vol"], 4) if m["book_vol"] else None,
                        "deployed%": round(sum(t.values()) * 100, 1), "n_univ": m["n_univ"]}
out["rebalances"] = meta

spy = bh_curve(D, "SPY", start, end)["curve"]
res = {}
for bps in (5, 10, 20):
    s = simulate(D, sched, start, end, cost_bps=bps)
    res[f"MOM deployed spec @{bps}bps"] = stats(s["curve"], spy)
    if bps == 5:
        base = s
for b in ("SPY", "RSP", "QQQ"):
    res[f"{b} buy&hold"] = stats(bh_curve(D, b, start, end)["curve"], spy)
# 60/40 SPY/AGG rebalanced at the same monthly dates
s6040 = simulate(D, {r: {"SPY": 0.6, "AGG": 0.4} for r in rebals}, start, end)
res["60/40 SPY/AGG"] = stats(s6040["curve"], spy)
# Undiluted (no vol-target, 90% sleeve) and 100% raw book, for attribution
s_nv = simulate(D, {r: build_targets(D, r - 1, vol_target=None) for r in rebals}, start, end)
res["MOM no-vol-target (90%)"] = stats(s_nv["curve"], spy)
s_eq = simulate(D, {r: build_targets(D, r - 1, vol_target=None, sleeve=1.0) for r in rebals},
                start, end)
res["MOM raw book 100% invested"] = stats(s_eq["curve"], spy)
# July book held, never rebalanced (what live intended before the defects froze it)
s_hold = simulate(D, {rebals[0]: sched[rebals[0]]}, start, end)
res["MOM July book, no later rebal"] = stats(s_hold["curve"], spy)
# Concentration check: rerun with the two biggest OOS winners excluded from the universe
ex = {r: build_targets(D, r - 1, exclude={"MPC", "PSX"}) for r in rebals}
res["MOM excl. MPC+PSX (re-picked)"] = stats(simulate(D, ex, start, end)["curve"], spy)
# Significance of OOS active return (PSR vs 0, per-period)
import math  # noqa: E402
from engine import skew_kurt  # noqa: E402
ra = M.returns_from_equity(base["curve"]); rs = M.returns_from_equity(spy)
act = [a - b for a, b in zip(ra, rs)]
sd = M._std(act); sk, ku = skew_kurt(act)
out["oos_active"] = {"n_days": len(act), "ann_IR": round(M._mean(act) / sd * math.sqrt(252), 2),
                     "PSR_active_gt_0": round(M.probabilistic_sharpe_ratio(M._mean(act) / sd, 0.0, len(act), sk, ku), 3),
                     "ann_TE%": round(sd * math.sqrt(252) * 100, 1)}
out["results"] = res
out["contrib_top"] = sorted(((k, round(v * 100, 2)) for k, v in base["contrib"].items()),
                            key=lambda x: -x[1])
# monthly path
out["monthly"] = {}
for a, b in zip(rebals, rebals[1:] + [end + 1]):
    ia, ib = a - start, b - start          # curve index: 0 = open(start), j+1 = close(start+j)
    out["monthly"][D.dates[a][:7]] = {
        "mom%": round((base["curve"][ib] / base["curve"][ia] - 1) * 100, 2),
        "spy%": round((spy[ib] / spy[ia] - 1) * 100, 2)}

# P1 actual (broker): 2026-07-02 close (ts 2026-07-03T00Z) -> 2026-10-02 close
p1 = json.load(open("../broker/portfolio_1.json"))["history"]
import datetime as dt  # noqa: E402
eq = {}
for t, e in zip(p1["timestamp"], p1["equity"]):
    eq[dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")] = e
e_start, e_end = eq["2026-07-03"], eq["2026-10-03"]
# daily P1 curve between those points for DD/vol
keys = sorted(k for k in eq if "2026-07-03" <= k <= "2026-10-03")
p1c = [eq[k] for k in keys]
out["P1_actual"] = {"start_equity_0702close": e_start, "end_equity_1002close": e_end,
                    **stats(p1c)}
# Same-window benchmark from 07-02 close (apples to apples with P1)
c0 = di["2026-07-02"]
spyc = [D.px["SPY"][D.dates[i]][3] for i in range(c0, end + 1)]
out["SPY_0702close_to_1002close%"] = round((spyc[-1] / spyc[0] - 1) * 100, 2)
mom_pct = res["MOM deployed spec @5bps"]["tot%"]
out["defect_cost_estimate_usd"] = round(e_start * (mom_pct / 100) - (e_end - e_start), 0)
print(json.dumps(out, indent=1))
json.dump(out, open(f"task1_{PNL}.json", "w"), indent=1)
