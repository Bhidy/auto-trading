"""Tests for cross-portfolio aggregate risk + heat (R1) and live limits (R4)."""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.portfolio_risk import (  # noqa: E402
    aggregate_exposure,
    conditional_var,
    covariance_matrix,
    exceeds_aggregate_cap,
    marginal_risk_contributions,
    portfolio_heat,
    value_at_risk,
    var_circuit_breaker,
)


def _books():
    return [
        {"portfolio_id": "p1", "equity": 100_000.0, "positions": [
            {"symbol": "AAPL", "market_value": 8_000, "sector": "Technology"},
            {"symbol": "NVDA", "market_value": 7_000, "sector": "Technology"},
        ]},
        {"portfolio_id": "p3", "equity": 100_000.0, "positions": [
            {"symbol": "AAPL", "market_value": 7_000, "sector": "Technology"},
            {"symbol": "JPM", "market_value": 5_000, "sector": "Financials"},
        ]},
    ]


# --- Aggregate exposure -----------------------------------------------------

def test_aggregate_combines_same_name_across_books():
    rep = aggregate_exposure(_books())
    # AAPL = 8k + 7k = 15k of 200k total = 7.5%
    assert rep["by_symbol"]["AAPL"]["market_value"] == 15_000
    assert rep["by_symbol"]["AAPL"]["pct_of_total"] == 7.5
    assert rep["by_symbol"]["AAPL"]["books"] == ["p1", "p3"]


def test_single_name_breach_flagged():
    rep = aggregate_exposure(_books(), single_name_cap_pct=7.0)
    assert "AAPL" in rep["single_name_breaches"]  # 7.5% > 7%
    assert rep["ok"] is False


def test_sector_breach_flagged():
    # Tech = 8+7+7 = 22k = 11% of 200k.
    rep = aggregate_exposure(_books(), sector_cap_pct=10.0)
    assert "Technology" in rep["sector_breaches"]


def test_no_breach_when_caps_high():
    rep = aggregate_exposure(_books(), single_name_cap_pct=20.0, sector_cap_pct=50.0)
    assert rep["ok"] is True
    assert rep["single_name_breaches"] == []


def test_empty_books_safe():
    rep = aggregate_exposure([])
    assert rep["total_equity"] == 0.0
    assert rep["ok"] is True


# --- Pre-trade aggregate cap ------------------------------------------------

def test_exceeds_aggregate_cap_true():
    # AAPL already 15k (7.5%); adding 10k -> 25k = 12.5% > 10%.
    assert exceeds_aggregate_cap(_books(), "AAPL", 10_000, single_name_cap_pct=10.0) is True


def test_exceeds_aggregate_cap_false():
    assert exceeds_aggregate_cap(_books(), "AAPL", 1_000, single_name_cap_pct=10.0) is False


def test_exceeds_aggregate_cap_new_symbol():
    assert exceeds_aggregate_cap(_books(), "TSLA", 5_000, single_name_cap_pct=10.0) is False


# --- Portfolio heat ---------------------------------------------------------

def test_portfolio_heat_sums_open_risk():
    positions = [
        {"qty": 100, "entry_price": 100.0, "stop_loss": 95.0, "side": "long"},
        {"qty": 50, "entry_price": 200.0, "stop_loss": 190.0, "side": "long"},
    ]
    # risk = 100*5 + 50*10 = 1000 on 100k equity = 1.0%
    h = portfolio_heat(positions, 100_000.0)
    assert h["open_risk"] == 1000.0
    assert h["heat_pct"] == 1.0
    assert h["positions_at_risk"] == 2


def test_portfolio_heat_short_side():
    positions = [{"qty": 100, "entry_price": 50.0, "stop_loss": 55.0, "side": "short"}]
    h = portfolio_heat(positions, 100_000.0)
    assert h["open_risk"] == 500.0  # 100 * (55-50)


def test_portfolio_heat_ignores_incomplete():
    positions = [{"qty": 100, "entry_price": 100.0}]  # no stop
    h = portfolio_heat(positions, 100_000.0)
    assert h["open_risk"] == 0.0


# --- R4 live limits ---------------------------------------------------------

def test_live_limits_strictly_tighter_than_paper():
    cfg_dir = os.path.join(REPO_ROOT, "config")
    with open(os.path.join(cfg_dir, "risk_limits.json")) as f:
        paper = json.load(f)
    with open(os.path.join(cfg_dir, "risk_limits.live.json")) as f:
        live = json.load(f)
    assert live["max_daily_loss_pct"] < paper["max_daily_loss_pct"]
    assert live["max_weekly_loss_pct"] < paper["max_weekly_loss_pct"]
    assert live["kill_switch_drawdown_pct"] < paper["kill_switch_drawdown_pct"]
    assert live["max_trades_per_day"] < paper["max_trades_per_day"]
    assert live["max_gross_exposure_pct"] < paper["max_gross_exposure_pct"]
    assert live["max_short_exposure_pct"] < paper["max_short_exposure_pct"]
    for k in ("etf", "stock", "penny", "crypto"):
        assert live["max_single_position_pct"][k] < paper["max_single_position_pct"][k]


def test_load_config_defaults_to_paper(monkeypatch):
    import risk_officer
    monkeypatch.delenv("RISK_PROFILE", raising=False)
    cfg = risk_officer.load_config()
    assert cfg["max_daily_loss_pct"] == 4.0  # paper value


def test_load_config_live_profile(monkeypatch):
    import risk_officer
    monkeypatch.setenv("RISK_PROFILE", "live")
    cfg = risk_officer.load_config()
    assert cfg["max_daily_loss_pct"] == 2.0  # live value


# --- Tail risk: VaR / CVaR --------------------------------------------------

_RETS = [-0.10, -0.05, -0.02, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06]


def test_historical_var_matches_interpolated_quantile():
    # alpha = 1 - 0.90 = 0.10; pos = 0.1*9 = 0.9 -> -0.10*0.1 + -0.05*0.9 = -0.055.
    assert value_at_risk(_RETS, confidence=0.90, method="historical") == 0.055


def test_historical_cvar_is_tail_mean_and_ge_var():
    # Tail at/below the 0.10 quantile (-0.055) is just {-0.10} -> CVaR 0.10.
    cvar = conditional_var(_RETS, confidence=0.90)
    assert cvar == 0.1
    assert cvar >= value_at_risk(_RETS, confidence=0.90, method="historical")


def test_parametric_var_positive_and_loss_orientation():
    v = value_at_risk(_RETS, confidence=0.99, method="parametric")
    assert v > 0  # reported as a positive loss fraction


def test_var_insufficient_data_is_zero():
    assert value_at_risk([0.01], confidence=0.99) == 0.0
    assert conditional_var([], confidence=0.99) == 0.0


# --- Marginal contribution to risk ------------------------------------------

def test_marginal_contributions_sum_to_portfolio_vol():
    # Two uncorrelated assets, vols 0.2 and 0.3, equal weight.
    cov = [[0.04, 0.0], [0.0, 0.09]]
    res = marginal_risk_contributions([0.5, 0.5], cov)
    # sigma_p = sqrt(0.5^2*0.04 + 0.5^2*0.09) = sqrt(0.0325) ~ 0.180278
    assert round(res["portfolio_vol"], 6) == 0.180278
    assert round(sum(res["component"]), 6) == res["portfolio_vol"]  # Euler identity
    assert round(sum(res["pct"]), 6) == 1.0
    # Higher-vol asset contributes more risk.
    assert res["component"][1] > res["component"][0]


def test_marginal_contributions_zero_vol_safe():
    res = marginal_risk_contributions([0.5, 0.5], [[0.0, 0.0], [0.0, 0.0]])
    assert res["portfolio_vol"] == 0.0
    assert res["component"] == [0.0, 0.0]


def test_covariance_matrix_symmetric_with_positive_diagonal():
    syms, cov = covariance_matrix({"B": [0.01, -0.01, 0.02, -0.02],
                                   "A": [0.02, -0.02, 0.01, -0.01]})
    assert syms == ["A", "B"]            # sorted
    assert cov[0][1] == cov[1][0]        # symmetric
    assert cov[0][0] > 0 and cov[1][1] > 0


# --- Advisory circuit breaker (no orders) -----------------------------------

def test_circuit_breaker_flags_breach_but_only_recommends():
    # VaR(90%) ~ 5.5%; a 5% ceiling is breached.
    res = var_circuit_breaker(_RETS, confidence=0.90, max_var_pct=5.0)
    assert res["breach"] is True
    assert res["recommended_action"] == "FLATTEN"
    assert res["reasons"]


def test_circuit_breaker_ok_when_within_limits():
    res = var_circuit_breaker(_RETS, confidence=0.90, max_var_pct=10.0)
    assert res["breach"] is False
    assert res["recommended_action"] == "OK"


def test_circuit_breaker_drawdown_ceiling():
    res = var_circuit_breaker(_RETS, confidence=0.90, max_var_pct=99.0,
                              current_drawdown_pct=16.0, max_drawdown_pct=15.0)
    assert res["breach"] is True
    assert any("drawdown" in r for r in res["reasons"])
