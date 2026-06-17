"""Friction loader for the backtest / self-learning path.

Pure-stdlib by design — this module is imported on the requests-only cloud/EOD
path (via performance_tracker.adapt_parameters), so it MUST NOT pull any heavy
dependency. Enforced by tests/test_trading_path_purity.py.

It reads ``data/fee_source.json`` — a STATIC artifact emitted OFFLINE by
``scripts/research/calibrate_friction.py`` from realized broker fills — and
returns the per-portfolio ``(cost_bps, slippage_bps)`` to use in backtests and
the walk-forward self-learning gate.

Conservative by construction (model-risk requirement, per the red-team):
  * applied friction is NEVER below the documented default — favorable PAPER
    fills must not make a backtest look better than a flat 5 bps assumption;
  * if the artifact is absent / malformed, the portfolio is missing, or the
    calibrated sample is below the floor, fall back to the documented default
    (refuse-on-small-N).
"""
import json
import os

DEFAULT_COST_BPS = 5.0
DEFAULT_SLIPPAGE_BPS = 5.0


def _default_data_dir():
    # scripts/backtest/friction.py -> repo root -> data/
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "data")


def load_friction(portfolio=None, data_dir=None,
                  default_cost_bps=DEFAULT_COST_BPS,
                  default_slippage_bps=DEFAULT_SLIPPAGE_BPS):
    """Return ``(cost_bps, slippage_bps)`` for ``portfolio``.

    Always floored at the documented defaults (never returns LOWER friction).
    Falls back to the defaults on any missing/malformed/below-floor condition.
    """
    path = os.path.join(data_dir or _default_data_dir(), "fee_source.json")
    try:
        with open(path) as f:
            fee = json.load(f)
    except (OSError, ValueError):
        return default_cost_bps, default_slippage_bps

    pf = (fee.get("portfolios") or {}).get(portfolio or "")
    if not isinstance(pf, dict) or pf.get("below_floor"):
        return default_cost_bps, default_slippage_bps

    try:
        cost = max(float(pf.get("applied_cost_bps", default_cost_bps)), default_cost_bps)
        slip = max(float(pf.get("applied_slippage_bps", default_slippage_bps)), default_slippage_bps)
    except (TypeError, ValueError):
        return default_cost_bps, default_slippage_bps
    return cost, slip
