#!/usr/bin/env python3
"""Strategy optimizer (OFFLINE research lane) -> data/strategy_optimization.json.

The profit lever: P1 has a NEGATIVE edge driven by an exit disposition error
(breakeven kills winners, losers run) and a weak entry threshold. Now that the
backtester models exits (Phase 0) and the walk-forward gate is functional
(Phase 2), we can search the entry+exit configuration on REAL cached bars and
walk-forward validate a candidate that BEATS the current config out-of-sample.

Evaluates each candidate by its out-of-sample mean Sharpe (walk_forward) and its
full-period metrics, on the real data/ bucket bars. Supports --slice i/n so a
team of agents can search disjoint regions in parallel. The winner is only
trustworthy if it clears the SAME gate_param_change (DSR/PBO/walk-forward) the
live self-learning loop uses — fail-closed otherwise. Pure-Python; offline; the
trading path never imports it. NEVER auto-deploys: emits a CANDIDATE artifact for
committee + human-approved adoption (committee rule #14).
"""
import argparse
import itertools
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

from analyst_v2 import load_adaptive_params  # noqa: E402
from backtest.multifactor import backtest_multifactor  # noqa: E402
from backtest.walk_forward import gate_param_change, load_aligned_bars, walk_forward  # noqa: E402

DATA_DIR = os.path.join(ROOT, "data")

# Search the highest-impact knobs the audit flagged: the breakeven that kills
# winners, the trailing/TP/time-stop that let losers run, and the weak entry bar.
SEARCH = {
    "breakeven_trigger_pct": [0.03, 0.08],     # 0.03 = current (arms early, kills winners)
    "trailing_stop_atr_mult": [1.8, 2.5, 3.2],  # 2.5 = current
    "take_profit_atr_mult": [3.0, 5.0],         # 4.0 = current (between)
    "time_stop_days": [0, 7],                   # 0 = current (none)
    "confidence_buy_threshold": [0.50, 0.65],   # 0.50 = current (too low)
}


def grid():
    keys = list(SEARCH)
    return [dict(zip(keys, combo)) for combo in itertools.product(*SEARCH.values())]


def evaluate(symbol_bars, spy_bars, baseline, delta):
    params = {**baseline, **delta}
    try:
        wf = walk_forward(symbol_bars, spy_bars, params)
        oos = wf["aggregate"]["mean_sharpe"] if wf["aggregate"] else None
        n_windows = wf["aggregate"]["n_windows"] if wf["aggregate"] else 0
        bt = backtest_multifactor(symbol_bars, spy_bars, params=params)
        m = bt["metrics"]
        return {"delta": delta, "oos_sharpe": oos, "n_windows": n_windows,
                "full_sharpe": m.get("sharpe"), "full_return": m.get("total_return"),
                "max_drawdown": m.get("max_drawdown"), "n_trades": len(bt["trade_pnls"])}
    except Exception as e:
        return {"delta": delta, "oos_sharpe": None, "error": str(e)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Search entry+exit config on real bars (OOS-validated).")
    ap.add_argument("--slice", default=None, help="i/n — evaluate strided subset (for parallel agents)")
    ap.add_argument("--baseline-only", action="store_true")
    ap.add_argument("--validate", default=None,
                    help="JSON param-delta — run the REAL gate_param_change on it (for verifiers)")
    ap.add_argument("--out", default=os.path.join(DATA_DIR, "strategy_optimization.json"))
    args = ap.parse_args(argv)

    symbol_bars, spy_bars = load_aligned_bars(DATA_DIR, min_coverage=0.85)
    if not symbol_bars or not spy_bars:
        print(json.dumps({"verdict": "INSUFFICIENT_DATA", "reason": "no aligned cached bars"}))
        return 0
    baseline = load_adaptive_params()
    base_eval = evaluate(symbol_bars, spy_bars, baseline, {})
    base_oos = base_eval["oos_sharpe"]

    if args.baseline_only:
        print(json.dumps({"baseline_oos_sharpe": base_oos, "baseline": base_eval}, indent=2))
        return 0

    if args.validate:
        delta = json.loads(args.validate)
        cand_eval = evaluate(symbol_bars, spy_bars, baseline, delta)
        approved, detail = gate_param_change(baseline, {**baseline, **delta}, symbol_bars, spy_bars)
        print(json.dumps({"delta": delta, "baseline_oos_sharpe": base_oos,
                          "candidate_oos_sharpe": cand_eval.get("oos_sharpe"),
                          "gate_approved": approved, "gate_detail": detail}, indent=2))
        return 0

    candidates = grid()
    if args.slice:
        i, n = (int(x) for x in args.slice.split("/"))
        candidates = candidates[i::n]
    results = [evaluate(symbol_bars, spy_bars, baseline, d) for d in candidates]
    ranked = sorted([r for r in results if r.get("oos_sharpe") is not None],
                    key=lambda r: r["oos_sharpe"], reverse=True)

    # Slice mode: just report this region's ranked results for the synthesizer.
    if args.slice:
        print(json.dumps({"baseline_oos_sharpe": base_oos,
                          "n_evaluated": len(results), "top": ranked[:5]}, indent=2))
        return 0

    # Full run: validate the best through the REAL gate (fail-closed) and emit a candidate.
    best = ranked[0] if ranked else None
    artifact = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": "p1_strategy_optimization",
        "source": "data/ cached bucket bars (real OHLC), exit-aware backtester + walk-forward",
        "baseline_oos_sharpe": base_oos,
        "n_candidates": len(results),
        "disclosure": ("Hypothetical/paper research — not investment advice. A CANDIDATE only; "
                       "adoption is committee + human-approval gated (rule #14). Validated on "
                       "~220 bars / 21 symbols; small sample — treat as directional."),
    }
    if best is None or base_oos is None or best["oos_sharpe"] <= base_oos:
        artifact["verdict"] = "NO_IMPROVEMENT_FOUND"
        artifact["reason"] = "no candidate beat the current config out-of-sample (fail-closed)"
        artifact["best_candidate"] = best
    else:
        approved, detail = gate_param_change(baseline, {**baseline, **best["delta"]},
                                             symbol_bars, spy_bars)
        artifact["verdict"] = "VALIDATED_CANDIDATE" if approved else "BEATS_BASELINE_BUT_GATE_REJECTED"
        artifact["best_candidate"] = best
        artifact["oos_improvement"] = round(best["oos_sharpe"] - base_oos, 4)
        artifact["gate_approved"] = approved
        artifact["gate_detail"] = detail

    with open(args.out, "w") as f:
        json.dump(artifact, f, indent=2)
        f.write("\n")
    try:
        from shared.research_provenance import write_provenance
        write_provenance(args.out, [os.path.join(DATA_DIR, "core_equity.json")],
                         warnings=[artifact.get("reason", "")] if artifact.get("reason") else [],
                         source=artifact["source"])
    except Exception:
        pass
    print(f"Wrote {args.out}: verdict={artifact['verdict']} "
          f"baseline_oos={base_oos} best_oos={best['oos_sharpe'] if best else None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
