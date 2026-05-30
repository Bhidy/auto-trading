"""Tests for overfitting statistics (V1) + challenger gate (V2)."""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest import metrics  # noqa: E402
from backtest.walk_forward import evaluate_overfitting_screens  # noqa: E402
from backtest.challenger import challenger_backtest  # noqa: E402


# --- Normal CDF / inverse ---------------------------------------------------

def test_normal_cdf_known_values():
    assert abs(metrics.normal_cdf(0.0) - 0.5) < 1e-9
    assert abs(metrics.normal_cdf(1.96) - 0.975) < 1e-3
    assert abs(metrics.normal_cdf(-1.96) - 0.025) < 1e-3


def test_inverse_normal_cdf_roundtrip():
    for p in (0.025, 0.1, 0.5, 0.9, 0.975):
        x = metrics.inverse_normal_cdf(p)
        assert abs(metrics.normal_cdf(x) - p) < 1e-3


# --- Probabilistic / Deflated Sharpe ---------------------------------------

def test_psr_increases_with_observations():
    low = metrics.probabilistic_sharpe_ratio(0.1, 0.0, n_obs=10)
    high = metrics.probabilistic_sharpe_ratio(0.1, 0.0, n_obs=1000)
    assert high > low
    assert 0.0 <= low <= 1.0 and 0.0 <= high <= 1.0


def test_psr_benchmark_above_observed_is_low():
    assert metrics.probabilistic_sharpe_ratio(0.05, 0.30, n_obs=100) < 0.5


def test_deflated_sharpe_penalizes_many_trials():
    """The same best Sharpe is less significant when many trials were run."""
    few = metrics.deflated_sharpe_ratio([0.3, 0.1], n_obs=200)
    many = metrics.deflated_sharpe_ratio([0.3] + [0.0] * 50, n_obs=200)
    assert few >= many
    assert 0.0 <= many <= 1.0


def test_deflated_sharpe_single_trial():
    v = metrics.deflated_sharpe_ratio([0.5], n_obs=200)
    assert 0.0 <= v <= 1.0


def test_deflated_sharpe_empty():
    assert metrics.deflated_sharpe_ratio([], n_obs=200) == 0.0


# --- PBO via CSCV -----------------------------------------------------------

def test_pbo_anticorrelated_is_high():
    """When the in-sample winner is systematically the out-of-sample loser
    (anti-correlated slice performance), PBO is high — the hallmark of an
    overfit selection. This is exactly what the screen must catch."""
    rows = [[0.30, 0.10, 0.30, 0.10, 0.30, 0.10],
            [0.10, 0.30, 0.10, 0.30, 0.10, 0.30]]
    pbo = metrics.probability_of_backtest_overfitting(rows)
    assert pbo is not None
    assert pbo >= 0.5


def test_pbo_genuine_edge_is_low():
    """A configuration that is consistently best in every slice is not overfit."""
    rows = [
        [0.5, 0.6, 0.55, 0.5, 0.6, 0.58],   # consistently strong
        [0.0, 0.05, -0.1, 0.02, 0.0, 0.01],  # consistently weak
    ]
    pbo = metrics.probability_of_backtest_overfitting(rows)
    assert pbo is not None
    assert pbo < 0.5


def test_pbo_insufficient_data_returns_none():
    assert metrics.probability_of_backtest_overfitting([[0.1, 0.2]]) is None
    assert metrics.probability_of_backtest_overfitting([[0.1], [0.2]]) is None


# --- Overfitting screens helper --------------------------------------------

def _windows(sharpes):
    return [{"sharpe": s} for s in sharpes]


def test_screens_pass_for_strong_candidate():
    cur = _windows([0.2, 0.1, 0.15, 0.2])
    cand = _windows([0.8, 0.7, 0.75, 0.85])
    out = evaluate_overfitting_screens(cur, cand, challenger_sharpe=0.3,
                                       cand_sharpe=0.78)
    assert out["ok"] is True
    assert out["beats_challenger"] is True


def test_screens_veto_when_below_challenger():
    cur = _windows([0.2, 0.1, 0.15, 0.2])
    cand = _windows([0.25, 0.2, 0.22, 0.24])
    out = evaluate_overfitting_screens(cur, cand, challenger_sharpe=1.5,
                                       cand_sharpe=0.23)
    assert out["ok"] is False
    assert out["beats_challenger"] is False
    assert any("challenger" in r for r in out["reasons"])


def test_screens_veto_negative_edge_via_deflated_sharpe():
    """A candidate with a negative OOS Sharpe edge fails the deflated-Sharpe
    screen (best Sharpe below the coin-flip threshold)."""
    cur = _windows([-0.1, -0.2, -0.1, -0.15])
    cand = _windows([-0.2, -0.3, -0.1, -0.15])
    out = evaluate_overfitting_screens(cur, cand)
    assert out["ok"] is False
    assert any("deflated" in r.lower() for r in out["reasons"])


# --- Challenger backtest ----------------------------------------------------

def _trending_bars(n, start=100.0, drift=0.5):
    bars = []
    px = start
    for _ in range(n):
        o = px
        px = px + drift
        bars.append({"o": o, "h": px + 1, "l": o - 1, "c": px, "v": 1_000_000})
    return bars


def test_challenger_runs_and_reports_metrics():
    n = 260
    spy = _trending_bars(n, 400.0, 0.4)
    syms = {"AAA": _trending_bars(n, 100.0, 0.5),
            "BBB": _trending_bars(n, 50.0, 0.2)}
    out = challenger_backtest(syms, spy, warmup=200)
    assert "equity_curve" in out and "metrics" in out
    assert len(out["equity_curve"]) > 0
    # Uptrending market + above-MA regime => challenger should be net positive.
    assert out["metrics"]["total_return"] > 0


def test_challenger_requires_enough_bars():
    import pytest
    spy = _trending_bars(50)
    syms = {"AAA": _trending_bars(50)}
    with pytest.raises(ValueError):
        challenger_backtest(syms, spy, warmup=200)
