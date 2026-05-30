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
    exceeds_aggregate_cap,
    portfolio_heat,
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
