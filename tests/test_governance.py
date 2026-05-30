"""Tests for automated governance: provenance + auto-rollback (C4).

The system runs with zero manual intervention, so governance is a deterministic
policy, not a human. These tests prove every parameter decision is recorded with
provenance and that the last-known-good snapshot enables automatic rollback.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.governance import (  # noqa: E402
    PARAM_AUDIT_FILE,
    DECISION_AUDIT_FILE,
    get_last_known_good,
    record_param_change,
    rollback_params,
)


def _read(tmp_path, name):
    p = os.path.join(str(tmp_path), name)
    with open(p) as f:
        return json.load(f)


def test_approved_change_recorded_and_snapshotted(tmp_path):
    before = {"confidence_buy_threshold": 0.50, "position_size_multiplier": 1.0}
    after = {"confidence_buy_threshold": 0.48, "position_size_multiplier": 1.0}
    gate = {"approved": True, "candidate_oos_sharpe": 1.2, "current_oos_sharpe": 1.1}
    entry = record_param_change(str(tmp_path), before, after, gate,
                                gated_knobs=("confidence_buy_threshold",
                                             "position_size_multiplier"))
    assert entry["approved"] is True
    assert "confidence_buy_threshold" in entry["changed_knobs"]
    assert entry["changed_knobs"]["confidence_buy_threshold"] == {"from": 0.50, "to": 0.48}

    log = _read(tmp_path, PARAM_AUDIT_FILE)
    assert len(log) == 1 and log[0]["approved"] is True

    # Approved => last-known-good updated to the new params.
    good = get_last_known_good(str(tmp_path))
    assert good["confidence_buy_threshold"] == 0.48


def test_rejected_change_does_not_update_snapshot(tmp_path):
    # First establish a good snapshot.
    base = {"confidence_buy_threshold": 0.50}
    record_param_change(str(tmp_path), base, base, {"approved": True},
                        gated_knobs=("confidence_buy_threshold",))
    assert get_last_known_good(str(tmp_path))["confidence_buy_threshold"] == 0.50

    # A rejected change (reverted by caller, so after == before) keeps the snapshot.
    gate = {"approved": False, "screen_reasons": ["PBO 0.7"]}
    entry = record_param_change(str(tmp_path), base, base, gate,
                                gated_knobs=("confidence_buy_threshold",),
                                approved=False)
    assert entry["approved"] is False
    assert get_last_known_good(str(tmp_path))["confidence_buy_threshold"] == 0.50


def test_rollback_restores_last_known_good(tmp_path):
    good = {"confidence_buy_threshold": 0.50, "position_size_multiplier": 1.0}
    record_param_change(str(tmp_path), good, good, {"approved": True},
                        gated_knobs=("confidence_buy_threshold",))

    # Simulate production params drifting to a bad state.
    params_path = os.path.join(str(tmp_path), "strategy_params.json")
    with open(params_path, "w") as f:
        json.dump({"confidence_buy_threshold": 0.30}, f)

    restored = rollback_params(str(tmp_path))
    assert restored["confidence_buy_threshold"] == 0.50
    with open(params_path) as f:
        assert json.load(f)["confidence_buy_threshold"] == 0.50


def test_rollback_without_snapshot_returns_none(tmp_path):
    assert rollback_params(str(tmp_path)) is None


def test_decision_audit_trail_appended(tmp_path):
    base = {"x": 1}
    record_param_change(str(tmp_path), base, base, {"approved": True})
    audit = _read(tmp_path, DECISION_AUDIT_FILE)
    assert any(e["type"] == "param_change" for e in audit)
    assert all("timestamp" in e for e in audit)


def test_no_change_is_trusted_and_snapshotted(tmp_path):
    base = {"confidence_buy_threshold": 0.50}
    entry = record_param_change(str(tmp_path), base, base, None,
                                gated_knobs=("confidence_buy_threshold",))
    assert entry["approved"] is True  # no change => trivially fine
    assert entry["n_changes"] == 0
    assert get_last_known_good(str(tmp_path))["confidence_buy_threshold"] == 0.50
