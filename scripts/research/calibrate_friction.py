#!/usr/bin/env python3
"""Friction calibration (OFFLINE research lane) -> data/fee_source.json.

Replaces the FICTIONAL flat 5 bps cost/slippage assumption used by the
backtest stack with friction MEASURED from realized broker fills (the trade
logs already carry ``intended_price`` + ``entry_price`` + ``side`` after the
Phase-1 fill-fidelity work). Emits a STATIC artifact the pure-Python path reads
via ``scripts/backtest/friction.py`` — invariant A: this runs offline and the
trading path never imports it.

Pure-stdlib (no numpy/pandas) so it is trivially auditable and runs anywhere.

Honesty / model-risk policy (per the red-team):
  * The applied slippage is ``max(p90_adverse_measured, default)`` — calibration
    can only RAISE friction above the 5 bps floor, never lower it. This matters
    because Alpaca PAPER fills are frequently FAVORABLE (negative adverse
    slippage); we must never let optimistic paper data cheapen a backtest.
  * ``p90`` (not the median) is used — conservative tail, not the typical case.
  * Below ``--min-sample-n`` realized fills, a portfolio is marked
    ``below_floor`` and the loader falls back to the default (refuse-on-small-N).
  * The artifact is tagged ``basis: paper`` and carries a disclosure; recalibrate
    against LIVE fills before any go-live.

Usage:
    python3 scripts/research/calibrate_friction.py [--min-sample-n 25] [--out data/fee_source.json]
"""
import argparse
import json
import os
from datetime import datetime, timezone

DEFAULT_COST_BPS = 5.0
DEFAULT_SLIPPAGE_BPS = 5.0

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Each portfolio's committed trade log.
LOGS = {
    "portfolio_1": os.path.join(ROOT, "data", "trade_log.json"),
    "portfolio_2": os.path.join(ROOT, "political-copy-bot", "data", "trade_log.json"),
    "portfolio_3": os.path.join(ROOT, "event-driven-bot", "data", "trade_log.json"),
}


def _adverse_bps(side, intended, fill):
    """Signed ADVERSE slippage in bps: positive = worse than intended for either
    side (buy filled above intended, or sell filled below intended)."""
    try:
        intended = float(intended)
        fill = float(fill)
    except (TypeError, ValueError):
        return None
    if not intended or not fill:
        return None
    if str(side).lower().startswith("s"):  # sell
        return (intended - fill) / intended * 10_000.0
    return (fill - intended) / intended * 10_000.0  # buy (default)


def _percentile(sorted_vals, q):
    """Linear-interpolated percentile (q in [0,1]); pure-stdlib."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = q * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _median(sorted_vals):
    return _percentile(sorted_vals, 0.5)


def calibrate_portfolio(log_path, min_sample_n,
                        default_cost_bps=DEFAULT_COST_BPS,
                        default_slippage_bps=DEFAULT_SLIPPAGE_BPS):
    try:
        with open(log_path) as f:
            log = json.load(f)
    except (OSError, ValueError):
        log = []
    if not isinstance(log, list):
        log = []

    adverse = []
    for t in log:
        if not isinstance(t, dict):
            continue
        intended = t.get("intended_price")
        if intended is None:
            intended = t.get("limit_price")
        bps = _adverse_bps(t.get("side", "buy"), intended, t.get("entry_price"))
        if bps is not None:
            adverse.append(bps)

    n = len(adverse)
    below_floor = n < min_sample_n
    adverse.sort()
    median_bps = round(_median(adverse), 3) if adverse else None
    p90_bps = round(_percentile(adverse, 0.90), 3) if adverse else None

    # Conservative: only RAISE friction above the default; never lower it.
    if below_floor or p90_bps is None:
        applied_slip = default_slippage_bps
    else:
        applied_slip = round(max(p90_bps, default_slippage_bps), 3)

    return {
        "sample_n": n,
        "min_sample_n": min_sample_n,
        "below_floor": below_floor,
        "median_adverse_slippage_bps": median_bps,
        "p90_adverse_slippage_bps": p90_bps,
        "applied_slippage_bps": applied_slip,
        "applied_cost_bps": default_cost_bps,  # commissions ~0; keep conservative floor
        "note": ("below sample floor -> default used (refuse-on-small-N)" if below_floor
                 else ("favorable paper fills -> floored at default" if p90_bps is not None
                       and p90_bps <= default_slippage_bps
                       else "calibrated p90 above default -> applied")),
    }


def build_artifact(min_sample_n):
    portfolios = {pid: calibrate_portfolio(path, min_sample_n)
                  for pid, path in LOGS.items()}
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "trade_log realized fills (Alpaca PAPER)",
        "basis": "paper",
        "default_cost_bps": DEFAULT_COST_BPS,
        "default_slippage_bps": DEFAULT_SLIPPAGE_BPS,
        "policy": ("applied_slippage_bps = max(p90_adverse_measured, default); "
                   "never lowers friction on favorable paper fills; "
                   "refuse-on-small-N below min_sample_n; p90 (not median) used"),
        "portfolios": portfolios,
        "disclosure": ("Hypothetical/paper friction for research only — not investment "
                       "advice. Paper fills may differ materially from live fills "
                       "(market impact, liquidity, latency). Recalibrate against LIVE "
                       "fills before any go-live."),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Calibrate backtest friction from realized fills.")
    ap.add_argument("--min-sample-n", type=int, default=25,
                    help="minimum realized fills before a portfolio's calibration is trusted")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "fee_source.json"))
    args = ap.parse_args(argv)

    artifact = build_artifact(args.min_sample_n)
    with open(args.out, "w") as f:
        json.dump(artifact, f, indent=2)
        f.write("\n")

    print(f"Wrote {args.out}")
    for pid, pf in artifact["portfolios"].items():
        print(f"  {pid}: n={pf['sample_n']} p90={pf['p90_adverse_slippage_bps']} "
              f"-> applied_slippage={pf['applied_slippage_bps']}bps "
              f"({'below_floor' if pf['below_floor'] else pf['note']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
