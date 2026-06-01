#!/usr/bin/env python3
"""
T2 research runner — compute HRP target weights and write a STATIC ARTIFACT.

Loads morning-research's cached per-bucket daily bars (data/{bucket}.json),
aligns them on a common date axis, computes Ledoit-Wolf-shrunk HRP weights, and
writes data/hrp_weights.json with full provenance. The pure-Python trading path
may later READ this artifact as advisory allocation tilts (clamped inside the
hardcoded caps); this script never places orders and never touches live state.

Usage:
    python3 scripts/research/run_hrp.py
    python3 scripts/research/run_hrp.py --data-dir data --out data/hrp_weights.json
    python3 scripts/research/run_hrp.py --no-shrink --min-obs 60
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from hrp import hrp_weights  # noqa: E402

# State files in data/ that are NOT per-bucket bar caches.
_STATE_FILES = {
    "signals.json", "portfolio_state.json", "trade_log.json", "strategy_params.json",
    "validated_orders.json", "learning_report.json", "news_signals.json",
    "bot_state.json", "reconciliation_report.json", "execution_integrity.json",
    "preflight_report.json", "strategy_conformance.json", "order_state.json",
    "crypto.json", "hrp_weights.json", "fracdiff_params.json", "regime_state.json",
}


def _git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def load_aligned_returns(data_dir, min_obs=60, min_coverage=0.9):
    """Load cached bucket bars → (symbols, returns_matrix [n_obs, n_assets]).

    Aligns all symbols to their common set of dates and converts close prices to
    simple returns. Returns (None, None) if insufficient data.
    """
    by_symbol = {}
    for path in glob.glob(os.path.join(data_dir, "*.json")):
        if os.path.basename(path) in _STATE_FILES:
            continue
        try:
            with open(path) as fh:
                payload = json.load(fh)
        except Exception:
            continue
        bars = payload.get("bars") if isinstance(payload, dict) else None
        if not isinstance(bars, dict):
            continue
        for sym, series in bars.items():
            if isinstance(series, list) and len(series) >= min_obs:
                by_symbol[sym] = {b["t"][:10]: b["c"] for b in series
                                  if b.get("t") and b.get("c") is not None}

    if len(by_symbol) < 2:
        return None, None

    # Common date axis present across enough symbols.
    all_dates = sorted(set().union(*[set(d) for d in by_symbol.values()]))
    symbols = sorted(s for s, d in by_symbol.items()
                     if len(d) >= int(len(all_dates) * min_coverage))
    if len(symbols) < 2:
        return None, None
    common = [d for d in all_dates if all(d in by_symbol[s] for s in symbols)]
    if len(common) < min_obs:
        return None, None

    prices = np.array([[by_symbol[s][d] for d in common] for s in symbols], dtype=float)
    rets = prices[:, 1:] / prices[:, :-1] - 1.0          # (n_assets, n_obs-1)
    return symbols, rets.T                                # -> (n_obs-1, n_assets)


def build_artifact(symbols, returns, shrink=True):
    weights, delta = hrp_weights(returns, symbols, shrink=shrink)
    inputs_hash = hashlib.sha256(np.asarray(returns).tobytes()).hexdigest()[:16]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code_version": _git_sha(),
        "method": "HRP + Ledoit-Wolf(2004) scaled-identity shrinkage",
        "tier": "T2-research-artifact",
        "universe": symbols,
        "n_obs": int(np.asarray(returns).shape[0]),
        "shrinkage_delta": round(delta, 6),
        "weights": {s: round(w, 6) for s, w in sorted(weights.items())},
        "inputs_hash": inputs_hash,
        "note": ("ADVISORY target tilts. The trading path MUST clamp these inside "
                 "config/risk_limits.json caps. NOT yet wired to live allocation — "
                 "consumer wiring is a separate, explicitly-approved step."),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compute HRP weights -> static artifact.")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default=os.path.join("data", "hrp_weights.json"))
    ap.add_argument("--min-obs", type=int, default=60)
    ap.add_argument("--no-shrink", action="store_true")
    args = ap.parse_args(argv)

    symbols, returns = load_aligned_returns(args.data_dir, min_obs=args.min_obs)
    if symbols is None:
        print(f"[run_hrp] insufficient cached bars in {args.data_dir}/ — no artifact written.")
        return 1
    artifact = build_artifact(symbols, returns, shrink=not args.no_shrink)
    with open(args.out, "w") as fh:
        json.dump(artifact, fh, indent=2)
    top = sorted(artifact["weights"].items(), key=lambda kv: -kv[1])[:5]
    print(f"[run_hrp] wrote {args.out}: {len(symbols)} symbols, n_obs={artifact['n_obs']}, "
          f"shrinkage_delta={artifact['shrinkage_delta']}")
    print("[run_hrp] top weights:", ", ".join(f"{s}={w:.3f}" for s, w in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
