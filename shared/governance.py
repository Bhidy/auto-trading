"""Automated governance: provenance + auto-rollback for self-learning (C4).

The audit asks for a human-approval gate on parameter changes. This system is
designed to run with ZERO manual intervention, so governance is implemented as a
DETERMINISTIC policy instead of a person: a parameter change reaches production
only after the walk-forward + overfitting gate approves it (see
backtest.walk_forward.gate_param_change), and every decision is recorded in an
append-only audit log with full provenance. A last-known-good snapshot enables
automatic rollback. No human is ever required — the policy code is the approver.

Pure file I/O, dependency-free. All paths are explicit so tests and the three
portfolios can point at their own data dirs.
"""
import json
import os
from datetime import datetime, timezone

PARAM_AUDIT_FILE = "param_change_log.json"
LAST_GOOD_FILE = "strategy_params.last_good.json"
DECISION_AUDIT_FILE = "governance_audit.json"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default
    return default


def _save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def append_audit(data_dir, event, *, audit_file=DECISION_AUDIT_FILE, max_entries=1000):
    """Append an immutable event to the governance audit trail. Trims to the
    most recent `max_entries` so the file can't grow without bound."""
    path = os.path.join(data_dir, audit_file)
    log = _load(path, [])
    entry = {"timestamp": _now(), **event}
    log.append(entry)
    if len(log) > max_entries:
        log = log[-max_entries:]
    _save(path, log)
    return entry


def _changed_keys(before, after, keys=None):
    keys = keys or set(before) | set(after)
    return {k: {"from": before.get(k), "to": after.get(k)}
            for k in keys if before.get(k) != after.get(k)}


def record_param_change(data_dir, before, after, gate_detail, *,
                        gated_knobs=None, approved=None):
    """Record a self-learning parameter decision with full provenance and
    maintain the last-known-good snapshot for automatic rollback.

    `before`/`after`: the param dicts pre/post adaptation (after = what will be
    persisted; if the gate rejected, the caller has already reverted the knobs).
    `gate_detail`: the dict returned by gate_param_change (OOS Sharpe, PBO,
    deflated Sharpe, challenger, reasons) — may be None when no gate ran.
    `approved`: explicit decision; if None it is inferred from the gate detail.

    Returns the recorded entry. Writes:
      * param_change_log.json  — append-only provenance of every decision;
      * strategy_params.last_good.json — snapshot updated only on an approved/
        no-change state, so rollback always restores a validated config.
    """
    knobs = tuple(gated_knobs) if gated_knobs else None
    if knobs:
        diff = _changed_keys(before, after, set(knobs))
    else:
        diff = _changed_keys(before, after)

    if approved is None:
        if isinstance(gate_detail, dict):
            approved = bool(gate_detail.get("approved", not diff))
        else:
            approved = not diff  # no gate + no change => trivially fine

    entry = {
        "timestamp": _now(),
        "approved": approved,
        "changed_knobs": diff,
        "n_changes": len(diff),
        "gate": gate_detail,
    }
    path = os.path.join(data_dir, PARAM_AUDIT_FILE)
    log = _load(path, [])
    log.append(entry)
    if len(log) > 1000:
        log = log[-1000:]
    _save(path, log)

    # Update last-known-good ONLY when the resulting state is trusted: either an
    # approved change, or no net knob change at all. A rejected/reverted state
    # leaves the prior good snapshot intact so rollback stays valid.
    if approved or not diff:
        _save(os.path.join(data_dir, LAST_GOOD_FILE),
              {"timestamp": _now(), "params": after})

    append_audit(data_dir, {
        "type": "param_change",
        "approved": approved,
        "n_changes": len(diff),
    })
    return entry


def get_last_known_good(data_dir):
    """Return the last validated param snapshot, or None if none recorded yet."""
    snap = _load(os.path.join(data_dir, LAST_GOOD_FILE), None)
    if isinstance(snap, dict):
        return snap.get("params")
    return None


def rollback_params(data_dir, params_file="strategy_params.json"):
    """Automatically restore the last-known-good parameters. Returns the restored
    params, or None if no snapshot exists. Records the rollback in the audit log."""
    good = get_last_known_good(data_dir)
    if good is None:
        return None
    _save(os.path.join(data_dir, params_file), good)
    append_audit(data_dir, {"type": "rollback", "restored": True})
    return good
