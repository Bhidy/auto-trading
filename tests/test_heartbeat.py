"""Heartbeat watchdog decision-logic tests."""
import heartbeat as hb


TODAY = "2026-05-29"


def test_all_fresh_no_alert():
    fresh = {
        "P1 Self Improving Brain": TODAY,
        "P2 Capitol Shadow": TODAY,
        "P3 Cautious Sniper": TODAY,
    }
    alert, summary = hb.assess(TODAY, fresh)
    assert alert is False
    assert "All 3" in summary


def test_one_stale_triggers_alert():
    fresh = {
        "P1 Self Improving Brain": TODAY,
        "P2 Capitol Shadow": "2026-05-28",  # yesterday -> stale
        "P3 Cautious Sniper": TODAY,
    }
    alert, summary = hb.assess(TODAY, fresh)
    assert alert is True
    assert "P2 Capitol Shadow" in summary
    assert "2026-05-28" in summary


def test_never_ran_triggers_alert():
    fresh = {
        "P1 Self Improving Brain": None,
        "P2 Capitol Shadow": TODAY,
        "P3 Cautious Sniper": TODAY,
    }
    alert, summary = hb.assess(TODAY, fresh)
    assert alert is True
    assert "never" in summary


def test_all_stale_triggers_alert():
    fresh = {k: "2026-05-20" for k in (
        "P1 Self Improving Brain", "P2 Capitol Shadow", "P3 Cautious Sniper")}
    alert, summary = hb.assess(TODAY, fresh)
    assert alert is True
    assert summary.count("-") >= 3  # multiple stale lines


def test_date_of_parses_iso():
    assert hb._date_of("2026-05-29T15:17:10.294980+00:00") == "2026-05-29"
    assert hb._date_of(None) is None
    assert hb._date_of("") is None


def test_reconciliation_in_sync_no_alert():
    reports = {
        "P1 Self Improving Brain": {"in_sync": True},
        "P3 Cautious Sniper": {"in_sync": True},
    }
    alert, summary = hb.assess_reconciliation(reports)
    assert alert is False
    assert "in sync" in summary


def test_reconciliation_drift_triggers_alert():
    reports = {
        "P1 Self Improving Brain": {
            "in_sync": False,
            "orphan_open_trades": ["NVDA"],
            "unlogged_positions": ["TSLA"],
        },
        "P3 Cautious Sniper": {"in_sync": True},
    }
    alert, summary = hb.assess_reconciliation(reports)
    assert alert is True
    assert "P1 Self Improving Brain" in summary
    assert "NVDA" in summary and "TSLA" in summary
    assert "P3 Cautious Sniper" not in summary  # in_sync portfolio not flagged


def test_reconciliation_missing_report_is_not_drift():
    # A missing/unreadable report must NOT be treated as drift.
    reports = {"P1 Self Improving Brain": None, "P3 Cautious Sniper": None}
    alert, _ = hb.assess_reconciliation(reports)
    assert alert is False


def test_reconciliation_surfaces_qty_and_cost_basis_drift():
    # Future-proof: qty/cost-basis drift classes (roadmap C6) are surfaced too.
    reports = {"P1 Self Improving Brain": {
        "in_sync": False, "qty_drift": ["AAPL"], "cost_basis_drift": ["MSFT"]}}
    alert, summary = hb.assess_reconciliation(reports)
    assert alert is True
    assert "qty drift: AAPL" in summary
    assert "cost-basis drift: MSFT" in summary


# --- Execution integrity / conformance / preflight surfacing (Phase F) ------

def _wrap(integrity=None, conformance=None, preflight=None):
    return {"integrity": integrity, "conformance": conformance, "preflight": preflight}


def test_integrity_all_clear_no_alert():
    reports = {label: _wrap() for label in (
        "P1 Self Improving Brain", "P2 Capitol Shadow", "P3 Cautious Sniper")}
    alert, summary = hb.assess_integrity(reports, TODAY)
    assert alert is False
    assert "all clear" in summary


def test_integrity_execution_anomaly_alerts():
    reports = {"P1 Self Improving Brain": _wrap(integrity={
        "timestamp": f"{TODAY}T14:00:00+00:00", "anomalous": True,
        "anomaly_reason": "7 approved, 0 submitted"})}
    alert, summary = hb.assess_integrity(reports, TODAY)
    assert alert is True
    assert "EXECUTION ANOMALY" in summary and "P1 Self Improving Brain" in summary


def test_integrity_stale_anomaly_does_not_alert():
    """A yesterday-dated anomaly file must not raise a perpetual alert."""
    reports = {"P1 Self Improving Brain": _wrap(integrity={
        "timestamp": "2026-05-28T14:00:00+00:00", "anomalous": True,
        "anomaly_reason": "stale"})}
    alert, _ = hb.assess_integrity(reports, TODAY)
    assert alert is False


def test_integrity_preflight_failure_alerts():
    reports = {"P3 Cautious Sniper": _wrap(preflight={
        "ok": False, "hard_failures": ["SIZING CANARY FAILED: ..."]})}
    alert, summary = hb.assess_integrity(reports, TODAY)
    assert alert is True
    assert "PREFLIGHT FAILED" in summary


def test_integrity_conformance_violation_alerts():
    reports = {"P3 Cautious Sniper": _wrap(conformance={
        "timestamp": f"{TODAY}T16:00:00+00:00", "conformant": False,
        "violations": [{"name": "complete_bracket"}]})}
    alert, summary = hb.assess_integrity(reports, TODAY)
    assert alert is True
    assert "CONFORMANCE" in summary and "complete_bracket" in summary


def test_integrity_missing_reports_no_alert():
    alert, _ = hb.assess_integrity({"P1 Self Improving Brain": _wrap()}, TODAY)
    assert alert is False
