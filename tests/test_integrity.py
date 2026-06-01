"""Tests for shared.integrity — the loud anomaly detector.

The 2026-06-01 incident hid because a run "succeeded" while placing zero orders
and nothing said so. execution_integrity turns "approved but nothing placed" into
a loud, persisted flag. These tests lock that detection (and guard against false
positives on benign no-placement sessions).
"""
import json

from shared.integrity import (
    execution_integrity,
    is_anomalous,
    strategy_conformance,
    write_conformance_report,
    write_integrity_report,
)


# --- The incident replay ----------------------------------------------------

def test_incident_replay_is_anomalous():
    """7 approved, 0 placed, not halted, cash available, no benign skips —
    the exact 2026-06-01 silent no-op."""
    r = execution_integrity(total_signals=23, approved=7, placed=0, filled=0,
                            halted=False, cash_available=True, skipped=[])
    assert r["anomalous"] is True
    assert is_anomalous(r) is True
    assert "unexplained" in r["anomaly_reason"]
    assert r["unexplained"] == 7


# --- Healthy / benign sessions are NOT anomalous ----------------------------

def test_orders_placed_is_not_anomalous():
    r = execution_integrity(total_signals=10, approved=5, placed=5, filled=4)
    assert r["anomalous"] is False


def test_halted_is_not_anomalous():
    r = execution_integrity(total_signals=10, approved=5, placed=0, filled=0,
                            halted=True, cash_available=True)
    assert r["anomalous"] is False


def test_no_cash_is_not_anomalous():
    r = execution_integrity(total_signals=10, approved=5, placed=0, filled=0,
                            cash_available=False)
    assert r["anomalous"] is False


def test_all_benign_skips_explain_zero_placement():
    """Every approved order skipped for a benign reason (already held) is NOT an
    anomaly — that is a legitimate no-placement, not the incident."""
    skipped = [{"symbol": s, "reason": "already hold", "benign": True}
               for s in ("SPY", "QQQ", "IWM")]
    r = execution_integrity(total_signals=8, approved=3, placed=0, filled=0,
                            skipped=skipped)
    assert r["anomalous"] is False
    assert r["unexplained"] == 0


def test_partial_benign_still_flags_the_unexplained_one():
    """2 benign skips + 1 order that silently vanished -> still anomalous."""
    skipped = [{"symbol": "SPY", "reason": "already hold", "benign": True},
               {"symbol": "QQQ", "reason": "already hold", "benign": True}]
    r = execution_integrity(total_signals=9, approved=3, placed=0, filled=0,
                            skipped=skipped)
    assert r["anomalous"] is True
    assert r["unexplained"] == 1


def test_non_benign_skip_does_not_explain_away():
    """A qty<=0 skip (a contradiction — risk_officer should have rejected it) is
    NOT benign and must not suppress the anomaly."""
    skipped = [{"symbol": "NVDA", "reason": "non-positive qty/price", "benign": False}]
    r = execution_integrity(total_signals=5, approved=1, placed=0, filled=0,
                            skipped=skipped)
    assert r["anomalous"] is True


def test_no_approved_orders_is_never_anomalous():
    r = execution_integrity(total_signals=12, approved=0, placed=0, filled=0)
    assert r["anomalous"] is False


# --- Persistence ------------------------------------------------------------

def test_write_integrity_report_roundtrip(tmp_path):
    r = execution_integrity(total_signals=3, approved=2, placed=2, filled=2,
                            portfolio_id="portfolio_1")
    path = tmp_path / "sub" / "execution_integrity.json"   # parent dir created
    write_integrity_report(str(path), r)
    loaded = json.loads(path.read_text())
    assert loaded["portfolio_id"] == "portfolio_1"
    assert loaded["approved"] == 2
    assert loaded["anomalous"] is False


# --- Strategy conformance (Phase E helper) ----------------------------------

def test_strategy_conformance_all_ok():
    checks = [{"name": "has_stop", "ok": True, "detail": ""},
              {"name": "has_tp", "ok": True, "detail": ""}]
    r = strategy_conformance(portfolio_id="portfolio_1", checks=checks)
    assert r["conformant"] is True
    assert r["violations"] == []


def test_strategy_conformance_flags_violations(tmp_path):
    checks = [{"name": "has_stop", "ok": True, "detail": ""},
              {"name": "complete_bracket", "ok": False, "detail": "AAPL missing TP"}]
    r = strategy_conformance(portfolio_id="portfolio_3", checks=checks)
    assert r["conformant"] is False
    assert len(r["violations"]) == 1
    path = tmp_path / "strategy_conformance.json"
    write_conformance_report(str(path), r)
    assert json.loads(path.read_text())["conformant"] is False
