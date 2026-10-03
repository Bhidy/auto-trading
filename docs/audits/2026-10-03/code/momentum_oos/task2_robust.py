#!/usr/bin/env python3
"""TASK 2 + 3 — ROBUSTNESS SIMULATION on the longest SIP history (2017-03 -> 2026-10)."""
import datetime as dt
import itertools
import json
import math
import sys

from engine import Data, simulate, bh_curve, stats, skew_kurt, M
from momentum_selector import select_top_momentum, vol_target_scalar

PNL = sys.argv[1] if len(sys.argv) > 1 else "bars_sip_all"
SIG = sys.argv[2] if len(sys.argv) > 2 else "bars_sip_split_full"
START = sys.argv[3] if len(sys.argv) > 3 else "2017-03-01"
END = "2026-10-02"
D = Data(PNL, SIG)
di = D.di
rebals = D.first_days_of_month(START, END)
s_idx, e_idx = rebals[0], di[END]
print(f"window {D.dates[s_idx]}..{END}  rebalances={len(rebals)}", file=sys.stderr)

# ---- precompute live-equivalent closes_by_sym per rebalance (420-cal-day window, >=274 bars)
CBS, SPYC = {}, {}
for r in rebals:
    sig = D.dates[r - 1]
    ws = (dt.date.fromisoformat(D.dates[r]) - dt.timedelta(days=420)).isoformat()
    cbs = {}
    for s in D.syms:
        c = D.closes_upto(s, sig, n=500, window_start=ws)
        if c and len(c) >= 274:
            cbs[s] = c
    CBS[r] = cbs

LB = {"6-1": 126, "9-1": 189, "12-1": 252}


def sched_for(k, lb, mps, vt, sleeve=0.90, exclude=None, rebal_list=None):
    out, vs_log = {}, []
    for r in (rebal_list or rebals):
        cbs = CBS[r]
        if exclude:
            cbs = {s: c for s, c in cbs.items() if s not in exclude}
        raw = select_top_momentum(cbs, k=k, max_weight=max(0.08, 1.0 / k), lookback=LB[lb],
                                  skip=21, use_trend=False, sector_map=D.sector,
                                  max_per_sector=mps)
        vs = 1.0
        if raw and vt:
            vs, _ = vol_target_scalar(cbs, raw, target_vol=vt, lookback=63, min_scale=0.30)
        vs_log.append(vs)
        out[r] = {s: w * sleeve * vs for s, w in raw.items()}
    return out, vs_log


spy = bh_curve(D, "SPY", s_idx, e_idx)
spyc = spy["curve"]
spy_r = M.returns_from_equity(spyc)
R = {"window": [D.dates[s_idx], END], "n_rebalances": len(rebals), "pnl": PNL, "sig": SIG}

# ================= (a) parameter surface =================
surface = []
curves = {}
for k, lb, mps, vt in itertools.product((8, 10, 13, 16, 20), ("6-1", "9-1", "12-1"),
                                        (3, 4, 5, None), (None, 0.20, 0.25)):
    sc, vsl = sched_for(k, lb, mps, vt)
    sim = simulate(D, sc, s_idx, e_idx, cost_bps=5)
    st = stats(sim["curve"], spyc)
    key = f"k{k}|{lb}|mps{mps}|vt{vt}"
    st.update({"k": k, "lb": lb, "mps": mps, "vt": vt, "key": key,
               "avg_vol_scale": round(sum(vsl) / len(vsl), 3),
               "turnover_pa": round(sim["turnover"] / (len(spyc) / 252), 2)})
    surface.append(st)
    curves[key] = sim["curve"]
DEP = "k13|12-1|mps4|vt0.25"
R["surface"] = surface
dep = next(x for x in surface if x["key"] == DEP)


def pct_rank(field):
    vals = sorted(x[field] for x in surface)
    return round(sum(v <= dep[field] for v in vals) / len(vals) * 100, 0)


cagrs = sorted(x["cagr%"] for x in surface)
xs = sorted(x["xs_cagr%"] for x in surface)
shs = sorted(x["sharpe"] for x in surface)


def q(v, p):
    return v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]


R["surface_summary"] = {
    "n_configs": len(surface),
    "deployed": dep,
    "deployed_pct_rank": {"cagr": pct_rank("cagr%"), "sharpe": pct_rank("sharpe"),
                          "xs": pct_rank("xs_cagr%")},
    "cagr_q10_q50_q90": [q(cagrs, .1), q(cagrs, .5), q(cagrs, .9)],
    "xs_q10_q50_q90": [q(xs, .1), q(xs, .5), q(xs, .9)],
    "sharpe_q10_q50_q90": [q(shs, .1), q(shs, .5), q(shs, .9)],
    "frac_beat_spy_cagr": round(sum(v > 0 for v in xs) / len(xs), 3),
    "best_by_sharpe": max(surface, key=lambda x: x["sharpe"]),
    "worst_by_sharpe": min(surface, key=lambda x: x["sharpe"]),
}
# marginal means per factor (plateau diagnostics)
marg = {}
for f in ("k", "lb", "mps", "vt"):
    g = {}
    for x in surface:
        g.setdefault(str(x[f]), []).append(x)
    marg[f] = {v: {"cagr%": round(sum(y["cagr%"] for y in L) / len(L), 2),
                   "sharpe": round(sum(y["sharpe"] for y in L) / len(L), 3),
                   "xs%": round(sum(y["xs_cagr%"] for y in L) / len(L), 2),
                   "maxdd%": round(sum(y["maxdd%"] for y in L) / len(L), 1)}
               for v, L in g.items()}
R["marginals"] = marg
# immediate neighbours of the deployed point (one factor changed)
nb = []
for x in surface:
    diff = sum([x["k"] != 13, x["lb"] != "12-1", x["mps"] != 4, x["vt"] != 0.25])
    if diff == 1:
        nb.append({k_: x[k_] for k_ in ("key", "cagr%", "sharpe", "maxdd%", "xs_cagr%")})
R["neighbours"] = nb

# ================= (b) cost shock, (c) delay =================
dep_sched, dep_vs = sched_for(13, "12-1", 4, 0.25)
base = simulate(D, dep_sched, s_idx, e_idx, cost_bps=5)
R["deployed_avg_vol_scale"] = round(sum(dep_vs) / len(dep_vs), 3)
R["cost_delay"] = {
    "5bps (base)": stats(base["curve"], spyc),
    "10bps (2x)": stats(simulate(D, dep_sched, s_idx, e_idx, cost_bps=10)["curve"], spyc),
    "20bps (4x)": stats(simulate(D, dep_sched, s_idx, e_idx, cost_bps=20)["curve"], spyc),
    "1-day delay @5bps": stats(simulate(D, dep_sched, s_idx, e_idx, cost_bps=5,
                                        delay=1)["curve"], spyc),
}
R["turnover_pa"] = round(base["turnover"] / (len(spyc) / 252), 2)

# ================= (d) remove best months / names =================
bc = base["curve"]
mrets, srets, labels = [], [], []
pts = rebals + [e_idx + 1]
for a, b in zip(pts, pts[1:]):
    ia, ib = a - s_idx, b - s_idx
    mrets.append(bc[ib] / bc[ia] - 1)
    srets.append(spyc[ib] / spyc[ia] - 1)
    labels.append(D.dates[a][:7])
yrs = len(spy_r) / 252


def cagr_from(rs):
    e = 1.0
    for x in rs:
        e *= 1 + x
    return (e ** (1 / yrs) - 1) * 100


best5 = sorted(range(len(mrets)), key=lambda i: -mrets[i])[:5]
act = [m - s for m, s in zip(mrets, srets)]
best5a = sorted(range(len(act)), key=lambda i: -act[i])[:5]
m_noBest = [0.0 if i in best5 else x for i, x in enumerate(mrets)]
m_noBestA = [srets[i] if i in best5a else x for i, x in enumerate(mrets)]
R["remove_best_months"] = {
    "base_cagr%": round(cagr_from(mrets), 2), "spy_cagr%": round(cagr_from(srets), 2),
    "best5_months": [(labels[i], round(mrets[i] * 100, 1)) for i in best5],
    "cagr_best5_set_to_cash%": round(cagr_from(m_noBest), 2),
    "best5_active_months": [(labels[i], round(act[i] * 100, 1)) for i in best5a],
    "cagr_best5_active_months_replaced_by_SPY%": round(cagr_from(m_noBestA), 2),
    "hit_rate_months_beat_spy": round(sum(a > 0 for a in act) / len(act), 3),
    "n_months": len(act),
}
top_names = sorted(base["contrib"].items(), key=lambda x: -x[1])
best_names = [s for s, _ in top_names[:5]]
ex_sched, _ = sched_for(13, "12-1", 4, 0.25, exclude=set(best_names))
ex = simulate(D, ex_sched, s_idx, e_idx, cost_bps=5)
R["remove_best_names"] = {
    "best5_names_by_$contrib": [(s, round(v, 3)) for s, v in top_names[:5]],
    "share_of_total_pnl": round(sum(v for _, v in top_names[:5]) / (bc[-1] - bc[0]), 3),
    "rerun_without_them": stats(ex["curve"], spyc),
}

# ================= (e) subperiods: year, regime, pre/in/post spec window =================
dates = [D.dates[s_idx]] + D.dates[s_idx:e_idx + 1]
br = M.returns_from_equity(bc)
byyear = {}
for i, d in enumerate(dates[1:]):
    y = d[:4]
    byyear.setdefault(y, [1.0, 1.0])
    byyear[y][0] *= 1 + br[i]
    byyear[y][1] *= 1 + spy_r[i]
R["by_year"] = {y: {"mom%": round((a - 1) * 100, 1), "spy%": round((b - 1) * 100, 1),
                    "xs%": round((a - b) * 100, 1)} for y, (a, b) in byyear.items()}
# regime: SPY total-return close vs its 200-day SMA at the PRIOR close
spx = [D.px["SPY"][d][3] for d in D.dates]
reg = {"above200": [[], []], "below200": [[], []]}
for i in range(len(br)):
    day_idx = s_idx + i
    p = day_idx - 1
    sma = sum(spx[p - 199:p + 1]) / 200
    key = "above200" if spx[p] > sma else "below200"
    reg[key][0].append(br[i])
    reg[key][1].append(spy_r[i])
R["by_regime"] = {}
for kk, (a, b) in reg.items():
    n = len(a)
    R["by_regime"][kk] = {"days": n,
                          "mom_ann%": round(M._mean(a) * 252 * 100, 1),
                          "spy_ann%": round(M._mean(b) * 252 * 100, 1),
                          "mom_vol%": round(M._std(a) * math.sqrt(252) * 100, 1),
                          "spy_vol%": round(M._std(b) * math.sqrt(252) * 100, 1)}


def window_stats(d0, d1):
    i0 = max(di[d0] if d0 in di else s_idx, s_idx) - s_idx
    i1 = di[d1] - s_idx + 1
    a = bc[i0:i1 + 1]
    b = spyc[i0:i1 + 1]
    return {"mom": stats(a, b), "spy": stats(b)}


R["spec_windows"] = {
    "pre-sample 2017-03..2021-06-11 (never seen by spec search)": window_stats("2017-03-01", "2021-06-11"),
    "in-sample 2021-06-14..2026-06-17 (spec search window)": window_stats("2021-06-14", "2026-06-17"),
    "post-freeze 2026-07-06..2026-10-02": window_stats("2026-07-06", "2026-10-02"),
}

# ================= (f) DSR + PBO =================
n_obs = len(spy_r)
pp = []
pp_act = []
for x in surface:
    r = M.returns_from_equity(curves[x["key"]])
    sd = M._std(r)
    pp.append(M._mean(r) / sd if sd else 0.0)
    a = [ri - si for ri, si in zip(r, spy_r)]
    sda = M._std(a)
    pp_act.append(M._mean(a) / sda if sda else 0.0)
dep_i = [x["key"] for x in surface].index(DEP)
dep_r = M.returns_from_equity(curves[DEP])
sk, ku = skew_kurt(dep_r)
dep_a = [ri - si for ri, si in zip(dep_r, spy_r)]
ska, kua = skew_kurt(dep_a)


def sr0(trials, n_total):
    m = sum(trials) / len(trials)
    v = sum((s - m) ** 2 for s in trials) / (len(trials) - 1)
    z1 = M.inverse_normal_cdf(1 - 1 / n_total)
    z2 = M.inverse_normal_cdf(1 - 1 / (n_total * math.e))
    return math.sqrt(v) * ((1 - 0.5772156649015329) * z1 + 0.5772156649015329 * z2)


LEDGER_N = len(json.load(open("./data/trial_ledger.json")))
PRIOR_MOM_N = 22   # momentum-family variants in scripts/research/high_return_backtest.py (+0.25 recal)
N_ALL = len(surface) + LEDGER_N + PRIOR_MOM_N
dsr = {
    "n_obs_daily": n_obs,
    "N_surface": len(surface), "N_ledger": LEDGER_N, "N_prior_momentum_search": PRIOR_MOM_N,
    "N_total": N_ALL,
    "deployed_daily_SR": round(pp[dep_i], 4), "deployed_ann_SR": round(pp[dep_i] * math.sqrt(252), 3),
    "deployed_skew": round(sk, 2), "deployed_kurt": round(ku, 2),
    "DSR_best_of_surface_repo_fn_N180_normal": round(M.deflated_sharpe_ratio(pp, n_obs), 4),
    "DSR_best_of_surface_repo_fn_N180_nonnormal": round(M.deflated_sharpe_ratio(pp, n_obs, sk, ku), 4),
}
for N in (len(surface), N_ALL):
    b = sr0(pp, N)
    dsr[f"PSR_deployed_vs_SR0_N{N}"] = round(M.probabilistic_sharpe_ratio(pp[dep_i], b, n_obs, sk, ku), 4)
    dsr[f"SR0_ann_N{N}"] = round(b * math.sqrt(252), 3)
    ba = sr0(pp_act, N)
    dsr[f"ACTIVE_vs_SPY_PSR_deployed_vs_SR0_N{N}"] = round(
        M.probabilistic_sharpe_ratio(pp_act[dep_i], ba, n_obs, ska, kua), 4)
    dsr[f"ACTIVE_SR0_ann_N{N}"] = round(ba * math.sqrt(252), 3)
dsr["ACTIVE_deployed_ann_IR"] = round(pp_act[dep_i] * math.sqrt(252), 3)
dsr["ACTIVE_PSR_deployed_vs_0"] = round(M.probabilistic_sharpe_ratio(pp_act[dep_i], 0.0, n_obs, ska, kua), 4)
dsr["ACTIVE_DSR_best_of_surface_repo_fn"] = round(M.deflated_sharpe_ratio(pp_act, n_obs, ska, kua), 4)
R["dsr"] = dsr

# PBO (CSCV): 12 contiguous slices, cell = slice Sharpe (raw) and slice mean active return
S = 12
L = n_obs // S
pm_raw, pm_act = [], []
for x in surface:
    r = M.returns_from_equity(curves[x["key"]])
    rowr, rowa = [], []
    for j in range(S):
        seg = r[j * L:(j + 1) * L]
        sseg = spy_r[j * L:(j + 1) * L]
        sd = M._std(seg)
        rowr.append(M._mean(seg) / sd if sd else 0.0)
        rowa.append(M._mean([u - v for u, v in zip(seg, sseg)]))
    pm_raw.append(rowr)
    pm_act.append(rowa)
R["pbo"] = {"slices": S, "pbo_raw_sharpe": M.probability_of_backtest_overfitting(pm_raw),
            "pbo_active_return": M.probability_of_backtest_overfitting(pm_act)}

# ================= TASK 3 baselines + (g) survivorship =================
def ew_sched(weight=1.0):
    out = {}
    for r in rebals:
        names = list(CBS[r].keys())
        out[r] = {s: weight / len(names) for s in names}
    return out


base3 = {}
base3["SPY buy&hold"] = stats(spyc, spyc)
base3["RSP buy&hold"] = stats(bh_curve(D, "RSP", s_idx, e_idx)["curve"], spyc)
base3["QQQ buy&hold"] = stats(bh_curve(D, "QQQ", s_idx, e_idx)["curve"], spyc)
ew = simulate(D, ew_sched(), s_idx, e_idx, cost_bps=5)
base3["EW universe (monthly)"] = stats(ew["curve"], spyc)
tr = {}
for r in rebals:
    p = r - 1
    sma = sum(spx[p - 199:p + 1]) / 200
    tr[r] = {"SPY": 1.0} if spx[p] > sma else {"BIL": 1.0}
base3["SPY 200dma trend (else BIL)"] = stats(simulate(D, tr, s_idx, e_idx, 5)["curve"], spyc)
raw13, _ = sched_for(13, "12-1", 4, None, sleeve=1.0)
cs = {r: dict({"SPY": 0.8}, **{s: 0.2 * w for s, w in raw13[r].items()}) for r in rebals}
base3["Core-sat 80% SPY + 20% mom top13"] = stats(simulate(D, cs, s_idx, e_idx, 5)["curve"], spyc)
base3["60/40 SPY/AGG (monthly)"] = stats(
    simulate(D, {r: {"SPY": 0.6, "AGG": 0.4} for r in rebals}, s_idx, e_idx, 5)["curve"], spyc)
base3["MOM deployed spec"] = stats(bc, spyc)
base3["MOM raw top13 100% (no vt, no sleeve)"] = stats(simulate(D, raw13, s_idx, e_idx, 5)["curve"], spyc)
R["baselines"] = base3
rsp = bh_curve(D, "RSP", s_idx, e_idx)["curve"]
R["survivorship"] = {
    "EW_universe_cagr%": base3["EW universe (monthly)"]["cagr%"],
    "RSP_cagr%": base3["RSP buy&hold"]["cagr%"],
    "EWuniv_minus_RSP_pp": round(base3["EW universe (monthly)"]["cagr%"] - base3["RSP buy&hold"]["cagr%"], 2),
    "MOM_minus_EWuniv_pp": round(base3["MOM deployed spec"]["cagr%"] - base3["EW universe (monthly)"]["cagr%"], 2),
    "MOMraw_minus_EWuniv_pp": round(base3["MOM raw top13 100% (no vt, no sleeve)"]["cagr%"] - base3["EW universe (monthly)"]["cagr%"], 2),
}
json.dump(R, open(f"task2_{START}.json", "w"), indent=1)
R2 = {k: v for k, v in R.items() if k != "surface"}
print(json.dumps(R2, indent=1))
