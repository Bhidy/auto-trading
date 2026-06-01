"""Tests for the persistent trial ledger and its DSR-deflation effect."""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.trial_ledger import (  # noqa: E402
    historical_oos_sharpes,
    load_trials,
    record_trial,
    trial_count,
)
from backtest.walk_forward import evaluate_overfitting_screens  # noqa: E402


# --- Ledger mechanics -------------------------------------------------------

def test_record_and_load_roundtrip(tmp_path):
    record_trial(str(tmp_path), {"oos_sharpe": 1.1, "approved": True})
    record_trial(str(tmp_path), {"oos_sharpe": 0.4, "approved": False})
    trials = load_trials(str(tmp_path))
    assert trial_count(str(tmp_path)) == 2
    assert all("timestamp" in t for t in trials)          # auto-stamped


def test_historical_oos_sharpes_filters_non_numeric(tmp_path):
    record_trial(str(tmp_path), {"oos_sharpe": 1.0})
    record_trial(str(tmp_path), {"oos_sharpe": None})     # gate produced no number
    record_trial(str(tmp_path), {"approved": True})       # no sharpe key
    assert historical_oos_sharpes(str(tmp_path)) == [1.0]


def test_missing_ledger_is_safe(tmp_path):
    assert load_trials(str(tmp_path / "nope")) == []
    assert historical_oos_sharpes(str(tmp_path / "nope")) == []


def test_ledger_is_capped(tmp_path):
    from shared import trial_ledger
    for i in range(trial_ledger.MAX_ENTRIES + 25):
        record_trial(str(tmp_path), {"oos_sharpe": float(i)})
    assert trial_count(str(tmp_path)) == trial_ledger.MAX_ENTRIES


# --- DSR deflation against cumulative trials --------------------------------

def _windows(sharpes):
    return [{"sharpe": s, "total_return": 0.0, "max_drawdown": 0.0} for s in sharpes]


def test_extra_trials_make_deflated_sharpe_stricter():
    # Representative case: prior trials sit at/below the candidate's level (a
    # proposed improvement is near the top of the search), so the candidate stays
    # the best trial while N grows -> higher expected-max hurdle -> lower DSR.
    cand = _windows([0.8, 1.0, 1.2, 0.9])           # best window Sharpe = 1.2
    history = [1.2, 1.1, 1.0, 0.9, 1.2, 1.1, 1.0, 0.9]   # none exceed 1.2
    base = evaluate_overfitting_screens(cand, cand)["deflated_sharpe"]
    with_hist = evaluate_overfitting_screens(
        cand, cand, extra_trial_sharpes=history)["deflated_sharpe"]
    assert base is not None and with_hist is not None
    assert with_hist < base                         # cumulative N tightened the gate


def test_no_extra_trials_preserves_prior_behavior():
    cand = _windows([0.8, 1.0, 1.2, 0.9])
    a = evaluate_overfitting_screens(cand, cand)["deflated_sharpe"]
    b = evaluate_overfitting_screens(cand, cand, extra_trial_sharpes=None)["deflated_sharpe"]
    assert a == b
