"""Execution-integrity + strategy-conformance audits (pure, tested).

The 2026-06-01 incident hid because a run "succeeded" while placing zero orders:
7 signals were approved, every order silently skipped (qty=0), and nothing in the
logs or state said so. These helpers turn that exact symptom — "approved but
nothing placed" — into a LOUD, persisted, alertable signal, for all three bots.

Pure and dependency-free so it is fully CI-testable; the only side effect lives
in write_integrity_report / write_conformance_report.
"""
import json
import os
from datetime import datetime, timezone


def execution_integrity(*, total_signals, approved, placed, filled,
                        halted=False, cash_available=True, skipped=None,
                        portfolio_id=None, now=None):
    """Summarize a session's money path and flag the silent no-op.

    Anomalous := there is at least one UNEXPLAINED approved order while placed==0,
    not halted, and cash is available — precisely the 2026-06-01 failure (orders
    approved, none submitted, no error).

    `placed` counts orders SUBMITTED to the broker (got an order id) or confirmed
    already-placed (idempotent duplicate) — NOT fills. A working limit that has not
    filled yet is *placed*, so it is not an anomaly (see F7 in the plan).

    `skipped` is [{symbol, reason, benign}]. BENIGN skips (already-held, sector cap,
    per-order cash shortfall, ETB gate) legitimately explain a no-placement and do
    NOT raise an anomaly; only orders neither placed nor benign-skipped are alarming.
    """
    skipped = list(skipped or [])
    total_signals = int(total_signals)
    approved = int(approved)
    placed = int(placed)
    filled = int(filled)
    benign = sum(1 for s in skipped if s.get("benign"))
    unexplained = max(approved - placed - benign, 0)
    anomalous = bool(approved > 0 and placed == 0 and not halted
                     and cash_available and unexplained > 0)
    reason = None
    if anomalous:
        reason = (f"{approved} approved, {placed} submitted, {unexplained} "
                  f"unexplained — silent no-op while not halted and cash available "
                  f"(the 2026-06-01 failure mode)")
    return {
        "timestamp": (now or datetime.now(timezone.utc)).isoformat(),
        "portfolio_id": portfolio_id,
        "total_signals": total_signals,
        "approved": approved,
        "placed": placed,
        "filled": filled,
        "unexplained": unexplained,
        "skipped": skipped,
        "halted": bool(halted),
        "cash_available": bool(cash_available),
        "anomalous": anomalous,
        "anomaly_reason": reason,
    }


def is_anomalous(report):
    """True if an execution-integrity report flags a silent no-op."""
    return bool(report.get("anomalous"))


def write_integrity_report(path, report):
    """Persist a report as JSON (best-effort; creates the parent dir)."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    return path


# --- Strategy conformance (Phase E) -----------------------------------------

def strategy_conformance(*, portfolio_id, checks, now=None):
    """Aggregate a strategy's per-mandate conformance checks.

    `checks` is a list of {"name": str, "ok": bool, "detail": str}. The report is
    conformant only if every check passed; failures are surfaced for the watchdog.
    """
    checks = list(checks or [])
    violations = [c for c in checks if not c.get("ok", False)]
    return {
        "timestamp": (now or datetime.now(timezone.utc)).isoformat(),
        "portfolio_id": portfolio_id,
        "conformant": len(violations) == 0,
        "checks": checks,
        "violations": violations,
    }


def write_conformance_report(path, report):
    """Persist a conformance report as JSON (best-effort; creates parent dir)."""
    return write_integrity_report(path, report)


def bracket_conformance(trades, *, stop_key="stop_loss", tp_key="take_profit"):
    """Mandate: every entry is a complete bracket (stop-loss + take-profit).
    Returns a conformance check ({name, ok, detail})."""
    missing = []
    for t in trades:
        sym = t.get("symbol", "?")
        if not t.get(stop_key):
            missing.append(f"{sym}:no-stop")
        if not t.get(tp_key):
            missing.append(f"{sym}:no-TP")
    return {"name": "complete_bracket", "ok": not missing,
            "detail": ("all entries carry stop+TP" if not missing
                       else f"incomplete brackets: {missing}")}


def sizing_band_conformance(trades, lo, hi, *, value_key="trade_value"):
    """Mandate: every executed trade value sits within [lo, hi]."""
    out = []
    for t in trades:
        v = t.get(value_key)
        if v is None:
            v = (t.get("qty", 0) or 0) * (t.get("entry_price") or t.get("limit_price") or 0)
        if v and not (lo <= v <= hi):
            out.append(f"{t.get('symbol', '?')}:${v:,.0f}")
    return {"name": "sizing_in_band", "ok": not out,
            "detail": (f"all within ${lo:,.0f}-${hi:,.0f}" if not out
                       else f"out of band: {out}")}
