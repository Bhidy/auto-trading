"""Tests for the heartbeat's advisory tail-risk surfacing (assess_tail_risk)."""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import heartbeat  # noqa: E402


def _rets():
    """30 returns: mostly small moves with a few sharp losses (so VaR > 0)."""
    base = [0.005, -0.004, 0.006, -0.003, 0.004, -0.005] * 5
    base[3], base[10], base[20] = -0.03, -0.04, -0.05
    return base


def test_informational_when_no_ceiling():
    alert, summary = heartbeat.assess_tail_risk({"P1": _rets()}, confidence=0.95)
    assert alert is False                      # advisory: no ceiling -> no alert
    assert "VaR" in summary and "CVaR" in summary


def test_breach_when_var_exceeds_low_ceiling():
    alert, summary = heartbeat.assess_tail_risk(
        {"P1": _rets()}, confidence=0.95, var_ceiling_pct=0.5)
    assert alert is True
    assert "BREACH" in summary


def test_insufficient_history_is_reported_not_alerted():
    alert, summary = heartbeat.assess_tail_risk({"P1": [0.01, -0.01, 0.02]}, confidence=0.95)
    assert alert is False
    assert "insufficient" in summary


def test_no_data():
    alert, summary = heartbeat.assess_tail_risk({}, confidence=0.95)
    assert alert is False
    assert "no data" in summary
