"""Pure-helper tests for the deployed core-satellite backtest (the full study
needs the gitignored deep_wide cache, so the metric helpers are pinned here)."""
import pytest

from research.backtest_core_satellite import _equity_from_returns, _stats


def test_equity_from_returns_compounds():
    eq = _equity_from_returns([0.1, -0.05, 0.02])
    assert eq[0] == 1.0
    assert eq[-1] == pytest.approx(1.1 * 0.95 * 1.02)


def test_stats_reports_full_risk_profile():
    rets = [0.01, -0.02, 0.015, -0.005, 0.008, 0.012, -0.01]
    s = _stats(rets)
    for k in ("sharpe", "total_return", "max_drawdown", "win_rate_days", "worst_day"):
        assert k in s
    assert s["worst_day"] == -0.02                 # honest worst-day (no strategy avoids losses)
    assert 0.0 <= s["win_rate_days"] <= 1.0
    assert s["max_drawdown"] >= 0.0


def test_stats_none_on_tiny_sample():
    assert _stats([0.01, 0.02]) is None            # refuse to report on < 5 obs
