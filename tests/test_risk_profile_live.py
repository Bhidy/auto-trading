"""RISK_PROFILE=live binds the tighter limits END-TO-END (audit 2026-07-04).

The profile switch previously lived only in risk_officer.load_config, but the
core allocator, the intraday monitor, and the cap-trim logic loaded
risk_limits.json DIRECTLY — so a live run would have sized the core and set the
kill switch with PAPER limits. This is a live-safety precondition: every limits
load must route through shared.risk_config.load_risk_limits so 'live' means live
everywhere. Fails CLOSED to paper if the live file is missing.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.risk_config import active_profile, load_risk_limits, risk_limits_path  # noqa: E402


def test_default_profile_is_paper(monkeypatch):
    monkeypatch.delenv("RISK_PROFILE", raising=False)
    assert active_profile() == "paper"
    assert risk_limits_path().endswith("risk_limits.json")
    assert not risk_limits_path().endswith("risk_limits.live.json")


def test_live_profile_selects_the_tighter_file(monkeypatch):
    monkeypatch.setenv("RISK_PROFILE", "live")
    assert active_profile() == "live"
    assert risk_limits_path().endswith("risk_limits.live.json")


def test_live_limits_are_actually_tighter_than_paper(monkeypatch):
    monkeypatch.delenv("RISK_PROFILE", raising=False)
    paper = load_risk_limits()
    monkeypatch.setenv("RISK_PROFILE", "live")
    live = load_risk_limits()
    # The whole point of the live ramp: strictly tighter hard caps.
    assert live["max_daily_loss_pct"] < paper["max_daily_loss_pct"]
    assert live["kill_switch_drawdown_pct"] < paper["kill_switch_drawdown_pct"]
    assert live["max_single_position_pct"]["etf"] < paper["max_single_position_pct"]["etf"]
    assert live["max_trades_per_day"] <= paper["max_trades_per_day"]


def test_missing_live_file_fails_closed_to_paper(monkeypatch, tmp_path):
    # A live profile with NO live file must fall back to paper, never crash or widen.
    (tmp_path / "risk_limits.json").write_text(json.dumps({"max_daily_loss_pct": 4.0}))
    monkeypatch.setenv("RISK_PROFILE", "live")
    path = risk_limits_path(tmp_path)
    assert path.endswith("risk_limits.json")             # fell back, not .live.json
    assert load_risk_limits(tmp_path)["max_daily_loss_pct"] == 4.0


def test_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setenv("RISK_PROFILE", "  LIVE  ")
    assert active_profile() == "live"
    monkeypatch.setenv("RISK_PROFILE", "PAPER")
    assert active_profile() == "paper"
    monkeypatch.setenv("RISK_PROFILE", "production")     # anything != live -> paper
    assert active_profile() == "paper"


def test_risk_officer_load_config_honors_profile(monkeypatch):
    import risk_officer
    monkeypatch.setenv("RISK_PROFILE", "live")
    cfg = risk_officer.load_config()
    assert cfg["kill_switch_drawdown_pct"] == 10.0       # the live value, via shared loader
