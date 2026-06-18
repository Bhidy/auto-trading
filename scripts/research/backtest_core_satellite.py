#!/usr/bin/env python3
"""Faithful backtest of the DEPLOYED core-satellite allocation (OFFLINE lane).

Audit gap closed: prior validation blended return streams abstractly. This
reproduces what is actually LIVE — compute_core_orders' cap-constrained,
regime-scaled passive core (SPY/QQQ/IWM/DIA, each strictly < 12%) + the active
multifactor satellite — and reports full risk metrics (OOS Sharpe, max drawdown,
win rate, worst window) walk-forward, versus active-only and core-only baselines.

Honest on "no loss trades": NO strategy avoids all losing days. This quantifies
the REAL loss profile so the trade-off is visible, not promised away.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from analyst_v2 import detect_regime, load_adaptive_params, regime_allocation_modifier  # noqa: E402
from backtest import metrics  # noqa: E402
from backtest.multifactor import backtest_multifactor  # noqa: E402
from backtest.walk_forward import auto_test_days, load_aligned_bars  # noqa: E402

CORE = ["SPY", "QQQ", "IWM", "DIA"]
ETF_CAP_FRAC = 0.12 * 0.95           # the live per-ETF cap buffer
MAX_CORE = len(CORE) * ETF_CAP_FRAC  # ~0.456 — the deployed cap-constrained ceiling


def _equity_from_returns(rets):
    eq, v = [1.0], 1.0
    for r in rets:
        v *= (1.0 + r)
        eq.append(v)
    return eq


def _stats(rets):
    if len(rets) < 5:
        return None
    eq = _equity_from_returns(rets)
    return {
        "sharpe": round(metrics.sharpe_ratio(rets), 4),
        "total_return": round(eq[-1] - 1.0, 4),
        "max_drawdown": round(metrics.max_drawdown(eq), 4),
        "win_rate_days": round(sum(1 for r in rets if r > 0) / len(rets), 4),
        "worst_day": round(min(rets), 4),
    }


def _window_returns(sb, spy, params, lo, hi, mp, core_weight, basket, max_core):
    """Return (active_rets, deployed_rets, core_rets) aligned over [lo, hi]."""
    sub_spy = spy[:hi + 1]
    sub = {s: b[:hi + 1] for s, b in sb.items()}
    res = backtest_multifactor(sub, sub_spy, params=params, max_positions=mp, warmup=lo)
    active = metrics.returns_from_equity(res["equity_curve"])

    spy_c = [b["c"] for b in spy]
    held = [s for s in basket if s in sb]
    core, eff_core = [], []
    for t in range(lo + 1, hi + 1):
        day = []
        for s in held:
            c0, c1 = sb[s][t - 1]["c"], sb[s][t]["c"]
            if c0:
                day.append(c1 / c0 - 1.0)
        core.append(sum(day) / len(day) if day else 0.0)
        eqm = float(regime_allocation_modifier(detect_regime(spy_c[:t + 1])).get("equity_mult", 1.0))
        eff_core.append(min(core_weight * eqm, max_core))   # exactly what compute_core_orders targets

    m = min(len(active), len(core))
    active, core, eff_core = active[-m:], core[-m:], eff_core[-m:]
    deployed = [w * c + (1 - w) * a for w, c, a in zip(eff_core, core, active)]
    return active, deployed, core


def run(data_dir, core_weight=0.50, max_positions=20, warmup=150, basket=None):
    sb, spy = load_aligned_bars(data_dir, min_coverage=0.80)
    if not sb or not spy:
        return {"verdict": "INSUFFICIENT_DATA"}
    basket = basket or CORE
    max_core = len(basket) * ETF_CAP_FRAC          # cap-constrained ceiling for this basket
    params = {**load_adaptive_params(), "confidence_buy_threshold": 0.50}
    n = len(spy)
    td = auto_test_days(n, warmup)
    acc = {"active": [], "deployed": [], "core": []}
    sharpes = {"active": [], "deployed": [], "core": []}
    start, nwin = warmup, 0
    while start + td < n:
        a, d, c = _window_returns(sb, spy, params, start, start + td, max_positions,
                                  core_weight, basket, max_core)
        if len(a) >= 5:
            acc["active"] += a
            acc["deployed"] += d
            acc["core"] += c
            for k, r in (("active", a), ("deployed", d), ("core", c)):
                sharpes[k].append(metrics.sharpe_ratio(r))
            nwin += 1
        start += td

    def agg(k):
        s = _stats(acc[k]) or {}
        s["mean_oos_sharpe"] = round(sum(sharpes[k]) / len(sharpes[k]), 4) if sharpes[k] else None
        s["losing_windows"] = sum(1 for x in sharpes[k] if x < 0)
        return s

    out = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": "deployed_core_satellite_backtest",
        "source": f"{data_dir} ({len(sb)} symbols x {n} bars), {nwin} OOS windows",
        "core_weight": core_weight, "basket": basket,
        "cap_constrained_core_ceiling": round(max_core, 3),
        "active_only": agg("active"), "core_only": agg("core"), "deployed": agg("deployed"),
        "disclosure": "Hypothetical/paper, net of modeled costs. No strategy avoids all losing days.",
    }
    dep, act = out["deployed"], out["active_only"]
    out["verdict"] = ("DEPLOYED_IMPROVES" if dep.get("mean_oos_sharpe", -9) > act.get("mean_oos_sharpe", -9)
                      and dep.get("max_drawdown", 9) <= act.get("max_drawdown", 9) else "REVIEW")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Backtest the deployed core-satellite allocation.")
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data", "deep_wide"))
    ap.add_argument("--core-weight", type=float, default=0.50)
    ap.add_argument("--max-positions", type=int, default=20)
    ap.add_argument("--basket", default=None, help="comma-separated ETF core basket (default SPY,QQQ,IWM,DIA)")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "core_satellite_backtest.json"))
    args = ap.parse_args(argv)
    basket = [s.strip() for s in args.basket.split(",")] if args.basket else None
    out = run(args.data_dir, args.core_weight, args.max_positions, basket=basket)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(f"Wrote {args.out}: verdict={out.get('verdict')}")
    for k in ("active_only", "core_only", "deployed"):
        s = out.get(k, {})
        print(f"  {k:12s} OOS Sharpe={s.get('mean_oos_sharpe')} maxDD={s.get('max_drawdown')} "
              f"win%={s.get('win_rate_days')} totRet={s.get('total_return')} losingWindows={s.get('losing_windows')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
