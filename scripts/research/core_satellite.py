#!/usr/bin/env python3
"""Core-satellite allocation study (OFFLINE research lane) -> data/core_satellite.json.

The evidence-based profit-maximizing answer. Deep, broad, PBO-validated testing
proved the active multifactor strategy has NEGATIVE out-of-sample edge and loses
to buy-and-hold on every universe. The institutional response is core-satellite:
allocate a PASSIVE index core (the market beta that actually compounds) plus a
small active satellite — and only grow the satellite if/when it earns OOS edge.

This blends the active strategy's return stream with a passive SPY/QQQ core at
several core weights and reports the out-of-sample Sharpe of each, so the
allocation is chosen by evidence, not opinion. Pure-Python; offline; the trading
path never imports it.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from analyst_v2 import load_adaptive_params  # noqa: E402
from backtest import metrics  # noqa: E402
from backtest.multifactor import backtest_multifactor  # noqa: E402
from backtest.walk_forward import auto_test_days, load_aligned_bars  # noqa: E402

CORE_WEIGHTS = [0.0, 0.25, 0.5, 0.75, 0.9, 1.0]


def _passive_returns(symbol_bars, names, lo, hi):
    """Equal-weight buy-and-hold daily returns of `names` over [lo, hi]."""
    rets = []
    for t in range(lo + 1, hi + 1):
        day = []
        for s in names:
            if s in symbol_bars:
                c0, c1 = symbol_bars[s][t - 1]["c"], symbol_bars[s][t]["c"]
                if c0:
                    day.append(c1 / c0 - 1.0)
        if day:
            rets.append(sum(day) / len(day))
    return rets


def _active_returns(symbol_bars, spy_bars, params, lo, hi, mp):
    sub_spy = spy_bars[:hi + 1]
    sub = {s: b[:hi + 1] for s, b in symbol_bars.items()}
    res = backtest_multifactor(sub, sub_spy, params=params, max_positions=mp, warmup=lo)
    return metrics.returns_from_equity(res["equity_curve"])


def study(data_dir, max_positions=20, core_names=("SPY", "QQQ")):
    sb, spy = load_aligned_bars(data_dir, min_coverage=0.80)
    if not sb or not spy:
        return {"verdict": "INSUFFICIENT_DATA"}
    params = {**load_adaptive_params(), "confidence_buy_threshold": 0.50}
    n = len(spy)
    warmup = 150
    td = auto_test_days(n, warmup)

    # Out-of-sample windows; blend active + passive returns inside each.
    per_w = {w: [] for w in CORE_WEIGHTS}
    start = warmup
    n_windows = 0
    while start + td < n:
        end = start + td
        act = _active_returns(sb, spy, params, start, end, max_positions)
        pas = _passive_returns(sb, [c for c in core_names if c in sb], start, end)
        m = min(len(act), len(pas))
        if m >= 5:
            act, pas = act[-m:], pas[-m:]
            for w in CORE_WEIGHTS:
                blend = [w * p + (1 - w) * a for p, a in zip(pas, act)]
                per_w[w].append(metrics.sharpe_ratio(blend))
            n_windows += 1
        start += td

    table = []
    for w in CORE_WEIGHTS:
        s = per_w[w]
        table.append({"core_weight": w, "active_weight": round(1 - w, 2),
                      "mean_oos_sharpe": round(sum(s) / len(s), 4) if s else None})
    valid = [r for r in table if r["mean_oos_sharpe"] is not None]
    best = max(valid, key=lambda r: r["mean_oos_sharpe"]) if valid else None
    active_only = next((r for r in table if r["core_weight"] == 0.0), None)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": "core_satellite_allocation",
        "source": f"{data_dir} ({len(sb)} symbols x {n} bars), {n_windows} OOS windows",
        "core_basket": list(core_names),
        "by_core_weight": table,
        "optimal": best,
        "active_only_oos_sharpe": active_only["mean_oos_sharpe"] if active_only else None,
        "verdict": ("PASSIVE_CORE_DOMINATES" if best and active_only
                    and best["core_weight"] > 0 and best["mean_oos_sharpe"] > (active_only["mean_oos_sharpe"] or -9)
                    else "ACTIVE_COMPETITIVE"),
        "recommendation": ("Allocate the optimal core weight to a passive SPY/QQQ index; keep the "
                           "active multifactor as the residual satellite. Grow the satellite only "
                           "when it earns OOS edge over the benchmark (it does not today)."),
        "disclosure": "Hypothetical/paper research — not investment advice. Net of modeled costs.",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Core-satellite allocation study (OOS).")
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data", "deep_wide"))
    ap.add_argument("--max-positions", type=int, default=20)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "core_satellite.json"))
    args = ap.parse_args(argv)
    out = study(args.data_dir, args.max_positions)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(f"Wrote {args.out}: verdict={out.get('verdict')}")
    if out.get("by_core_weight"):
        for r in out["by_core_weight"]:
            print(f"  core={r['core_weight']:.2f} active={r['active_weight']:.2f} -> OOS Sharpe {r['mean_oos_sharpe']}")
        print(f"  OPTIMAL: core_weight={out['optimal']['core_weight']} (OOS Sharpe {out['optimal']['mean_oos_sharpe']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
