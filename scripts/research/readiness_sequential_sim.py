"""Readiness Engine v2.1 — validation simulation of the always-valid edge test.

RESEARCH LANE (offline; not imported by the cloud path). Re-runs the ENGINE's
own ``shared.readiness.edge_test`` on synthetic books (beta 0.5 to a SPY-like
market, 10% residual vol) at every look, to measure:
  null  : false-GO rate over 5 years of DAILY looks at zero true alpha
          (iid normal at K=1, AR(1) 0.15 and Student-t(4) residuals at 0.05/6;
          the iid 0.05/6 case was run with 1,000 paths)
  power : median sessions to GO for annual IR 0.5 / 0.8 / 1.2 (monthly looks,
          20-year horizon)
  old   : the v2.0 fixed-z rule (N=1) under looks every 5 sessions, for contrast
Usage: python3 scripts/research/readiness_sequential_sim.py {null|power|old} <paths>
Results are recorded in docs/LIVE_READINESS.md §2.
"""
import math
import os
import random
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from shared import readiness as R  # noqa: E402

RF = 0.04/252
def gen(seed, n, alpha_ann=0.0, beta=0.5, resid_ann=0.10, spy_ann=0.16, ar=0.0, t_df=None):
    rng = random.Random(seed)
    xs, ys, rf = [], [], []
    e_prev = 0.0
    for _ in range(n):
        m = rng.gauss(0.0004, spy_ann/math.sqrt(252))
        if t_df:
            z = rng.gauss(0,1)/math.sqrt(rng.gammavariate(t_df/2, 2/t_df)); z *= math.sqrt((t_df-2)/t_df)
        else:
            z = rng.gauss(0,1)
        e = ar*e_prev + math.sqrt(1-ar*ar)*z*resid_ann/math.sqrt(252); e_prev = e
        xs.append(m + RF); ys.append(RF + alpha_ann/252 + beta*m + e); rf.append(RF)
    return ys, xs, rf

def first_pass(args):
    seed, nmax, step, lvl, kw = args
    y, x, rf = gen(seed, nmax, **kw)
    for n in range(60, nmax+1, step):
        if R.edge_test(y[:n], x[:n], rf[:n], 1, alpha_level=lvl)["status"] == "pass":
            return n
    return None

def old_rule(args):
    seed, nmax, step, N, kw = args
    y, x, rf = gen(seed, nmax, **kw)
    for n in range(90, nmax+1, step):
        e = R.edge_test(y[:n], x[:n], rf[:n], N)
        if e["alpha_daily"] > 0 and e["dsr"] >= 0.95 and (e["t_hac"] or 0) >= e["z_required"]:
            return n
    return None

if __name__ == "__main__":
    mode = sys.argv[1]
    S = int(sys.argv[2])
    lvl = R.family_alpha_level(6)
    with Pool(8) as p:
        t = time.time()
        if mode == "null":
            for kw, lab, L, ln in [({}, "iid normal", 0.05, "alpha=0.05 (K=1)"),
                                   ({"ar": 0.15}, "AR1 0.15", lvl, "alpha/6"),
                                   ({"t_df": 4}, "t4 fat tails", lvl, "alpha/6")]:
                if True:
                    res = p.map(first_pass, [(s, 1260, 1, L, kw) for s in range(S)])
                    print(f"NULL {lab:12} {ln:17} 5y daily looks: false-GO {sum(r is not None for r in res)}/{S} = {sum(r is not None for r in res)/S:.2%}", flush=True)
        if mode == "old":
            res = p.map(old_rule, [(s, 1260, 5, 1, {}) for s in range(S)])
            print(f"OLD v2.0 rule N=1 5y daily looks: false-GO {sum(r is not None for r in res)/S:.2%}", flush=True)
        if mode == "power":
            for ir in (0.5, 0.8, 1.2):
                kw = {"alpha_ann": ir*0.10}
                res = p.map(first_pass, [(s, 5040, 21, lvl, kw) for s in range(S)])
                hit = sorted(r for r in res if r is not None)
                med = hit[len(res)//2] if len(hit) > len(res)//2 else None
                within = {y: sum(1 for r in hit if r <= 252*y)/S for y in (2, 5, 10, 20)}
                print(f"POWER IR {ir}: median sessions to GO = {med} ({'>20y' if med is None else f'{med/252:.1f}y'}); P(GO by 2/5/10/20y) = " + ", ".join(f"{v:.0%}" for v in within.values()), flush=True)
        print("elapsed", round(time.time()-t), "s")
