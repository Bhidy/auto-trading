"""Tests for the strategy-spec validator + the three committed per-portfolio specs."""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest.strategy_spec import load_and_validate, validate_spec  # noqa: E402

SPECS_DIR = os.path.join(REPO_ROOT, "docs", "specs")


def _valid_spec():
    return {
        "spec_id": "x", "portfolio": "portfolio_1", "universe": "SPY",
        "timeframe": "1Day",
        "indicators": [{"name": "SMA", "params": {"period": 50}}],
        "entry_rule": "score >= 0.5", "exit_rule": "stop",
        "signal_bar": "t", "fill": {"model": "next_open", "bar": "t+1"},
        "sizing": "1% risk", "fees_bps": 5.0, "slippage_bps": 5.0,
        "benchmark": "buy&hold SPY",
    }


def test_valid_spec_passes():
    ok, errors = validate_spec(_valid_spec())
    assert ok, errors


def test_missing_field_fails():
    s = _valid_spec()
    del s["benchmark"]
    ok, errors = validate_spec(s)
    assert not ok and any("benchmark" in e for e in errors)


def test_negative_friction_fails():
    s = _valid_spec()
    s["slippage_bps"] = -1
    ok, errors = validate_spec(s)
    assert not ok and any("slippage_bps" in e for e in errors)


def test_same_bar_fill_requires_ack():
    s = _valid_spec()
    s["fill"] = {"model": "same_bar", "bar": "t"}
    ok, errors = validate_spec(s)
    assert not ok and any("look_ahead" in e for e in errors)
    s["fill"]["look_ahead_ack"] = True
    ok, _ = validate_spec(s)
    assert ok


def test_signal_equals_fill_bar_without_ack_is_look_ahead():
    s = _valid_spec()
    s["signal_bar"] = "t"
    s["fill"] = {"model": "next_open", "bar": "t"}  # same bar, no ack
    ok, errors = validate_spec(s)
    assert not ok and any("look_ahead" in e for e in errors)


def test_indicator_without_params_fails():
    s = _valid_spec()
    s["indicators"] = [{"name": "RSI"}]
    ok, errors = validate_spec(s)
    assert not ok and any("indicator" in e for e in errors)


def test_committed_portfolio_specs_conform():
    for name in ("p1_spec.json", "p2_spec.json", "p3_spec.json"):
        ok, errors = load_and_validate(os.path.join(SPECS_DIR, name))
        assert ok, f"{name} failed validation: {errors}"
