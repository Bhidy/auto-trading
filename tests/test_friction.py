"""Tests for the friction loader (scripts/backtest/friction.py) and the offline
calibrator (scripts/research/calibrate_friction.py).

Core invariant: applied friction is NEVER below the documented default, even when
PAPER fills are favorable — and below the sample floor we refuse-on-small-N.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest.friction import DEFAULT_COST_BPS, DEFAULT_SLIPPAGE_BPS, load_friction  # noqa: E402


def _write_fee(tmp_path, portfolios):
    (tmp_path / "fee_source.json").write_text(json.dumps({"portfolios": portfolios}))


# --- loader ---------------------------------------------------------------

def test_missing_artifact_falls_back_to_default(tmp_path):
    assert load_friction("portfolio_1", data_dir=str(tmp_path)) == (DEFAULT_COST_BPS, DEFAULT_SLIPPAGE_BPS)


def test_below_floor_falls_back_to_default(tmp_path):
    _write_fee(tmp_path, {"portfolio_2": {"below_floor": True, "applied_slippage_bps": 99.0}})
    assert load_friction("portfolio_2", data_dir=str(tmp_path)) == (DEFAULT_COST_BPS, DEFAULT_SLIPPAGE_BPS)


def test_favorable_paper_is_floored_at_default(tmp_path):
    # Calibrator emits applied=5.0 for favorable fills; loader must not go below 5.
    _write_fee(tmp_path, {"portfolio_1": {"below_floor": False,
                                          "applied_slippage_bps": 5.0, "applied_cost_bps": 5.0}})
    assert load_friction("portfolio_1", data_dir=str(tmp_path)) == (5.0, 5.0)


def test_calibrated_above_default_is_applied(tmp_path):
    _write_fee(tmp_path, {"portfolio_3": {"below_floor": False,
                                          "applied_slippage_bps": 18.0, "applied_cost_bps": 7.0}})
    assert load_friction("portfolio_3", data_dir=str(tmp_path)) == (7.0, 18.0)


def test_artifact_below_default_is_clamped_up(tmp_path):
    # Defensive: even if the artifact somehow records sub-default friction, the
    # loader floors it (never returns LOWER friction than the documented default).
    _write_fee(tmp_path, {"portfolio_1": {"below_floor": False, "applied_slippage_bps": 1.0}})
    assert load_friction("portfolio_1", data_dir=str(tmp_path)) == (5.0, 5.0)


def test_unknown_portfolio_falls_back(tmp_path):
    _write_fee(tmp_path, {"portfolio_1": {"below_floor": False, "applied_slippage_bps": 12.0}})
    assert load_friction("portfolio_X", data_dir=str(tmp_path)) == (DEFAULT_COST_BPS, DEFAULT_SLIPPAGE_BPS)


def test_malformed_artifact_falls_back(tmp_path):
    (tmp_path / "fee_source.json").write_text("{not json")
    assert load_friction("portfolio_1", data_dir=str(tmp_path)) == (DEFAULT_COST_BPS, DEFAULT_SLIPPAGE_BPS)


# --- calibrator -----------------------------------------------------------

def test_calibrator_floors_favorable_fills():
    from research.calibrate_friction import calibrate_portfolio
    # All buys filled BELOW intended (favorable) -> p90 adverse is negative ->
    # applied must floor to the default, never go lower.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        log = [{"side": "buy", "intended_price": 100.0, "entry_price": 99.8} for _ in range(30)]
        p = os.path.join(d, "tl.json")
        with open(p, "w") as f:
            json.dump(log, f)
        out = calibrate_portfolio(p, min_sample_n=25)
    assert out["sample_n"] == 30
    assert out["below_floor"] is False
    assert out["p90_adverse_slippage_bps"] < 0      # favorable
    assert out["applied_slippage_bps"] == DEFAULT_SLIPPAGE_BPS  # floored, not lowered


def test_calibrator_raises_on_adverse_fills():
    from research.calibrate_friction import calibrate_portfolio
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        # Buys filled ABOVE intended by ~20 bps (adverse) -> applied should rise.
        log = [{"side": "buy", "intended_price": 100.0, "entry_price": 100.2} for _ in range(30)]
        p = os.path.join(d, "tl.json")
        with open(p, "w") as f:
            json.dump(log, f)
        out = calibrate_portfolio(p, min_sample_n=25)
    assert out["applied_slippage_bps"] > DEFAULT_SLIPPAGE_BPS
    assert round(out["applied_slippage_bps"]) == 20


def test_calibrator_refuses_small_sample():
    from research.calibrate_friction import calibrate_portfolio
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        log = [{"side": "buy", "intended_price": 100.0, "entry_price": 100.5} for _ in range(3)]
        p = os.path.join(d, "tl.json")
        with open(p, "w") as f:
            json.dump(log, f)
        out = calibrate_portfolio(p, min_sample_n=25)
    assert out["below_floor"] is True
    assert out["applied_slippage_bps"] == DEFAULT_SLIPPAGE_BPS
