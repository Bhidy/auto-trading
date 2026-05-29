"""Risk-adjusted metric tests — verified against hand-computed known values."""
import math

from backtest import metrics as m


def test_total_return():
    assert abs(m.total_return([100, 110]) - 0.10) < 1e-9
    assert abs(m.total_return([100, 50]) - (-0.50)) < 1e-9
    assert m.total_return([100]) == 0.0


def test_max_drawdown_known_value():
    # peak 120, trough 90 -> 30/120 = 0.25
    assert abs(m.max_drawdown([100, 120, 90, 110]) - 0.25) < 1e-9


def test_max_drawdown_monotonic_up_is_zero():
    assert m.max_drawdown([100, 110, 120, 130]) == 0.0


def test_cagr_doubling_in_one_year():
    curve = [100.0] * 253
    curve[-1] = 200.0  # 252 periods later -> exactly 1 year of daily bars
    assert abs(m.cagr(curve) - 1.0) < 1e-6


def test_profit_factor_known_value():
    assert abs(m.profit_factor([100, -50, 50]) - 3.0) < 1e-9


def test_profit_factor_no_losses_is_inf():
    assert m.profit_factor([10, 20]) == float("inf")


def test_win_rate():
    assert m.win_rate([1, -1, 1, 1]) == 0.75
    assert m.win_rate([]) is None


def test_sharpe_positive_for_positive_drift():
    rets = [0.001, 0.002, -0.001, 0.003, 0.0, 0.002] * 10
    assert m.sharpe_ratio(rets) > 0


def test_sharpe_zero_when_no_variance():
    assert m.sharpe_ratio([0.001] * 20) == 0.0


def test_sortino_at_least_sharpe_when_downside_limited():
    # Mostly-up series: downside deviation < total deviation -> sortino >= sharpe
    rets = [0.01, 0.012, -0.002, 0.008, 0.011, -0.001, 0.009] * 5
    assert m.sortino_ratio(rets) >= m.sharpe_ratio(rets) - 1e-9


def test_returns_from_equity():
    rets = m.returns_from_equity([100, 110, 99])
    assert abs(rets[0] - 0.10) < 1e-9
    assert abs(rets[1] - (-0.10)) < 1e-9


def test_calmar_uses_cagr_over_maxdd():
    curve = [100, 120, 90, 200]
    expected = m.cagr(curve) / m.max_drawdown(curve)
    assert abs(m.calmar_ratio(curve) - expected) < 1e-9


def test_summary_shape():
    curve = [100 + math.sin(i) * 5 + i * 0.3 for i in range(300)]
    s = m.summary(curve, trade_pnls=[50, -20, 30])
    for key in ("sharpe", "sortino", "max_drawdown", "calmar", "cagr",
                "total_return", "win_rate", "profit_factor"):
        assert key in s
    assert s["num_trades"] == 3
