#!/usr/bin/env python3
"""Momentum-sleeve LIVE-READINESS tracker (2026-07-04).

Turns the committee's go/no-go from an opinion into an evidence panel. It reads
the sleeve's REAL forward, out-of-sample paper track record (from the committed
daily journals + trade log — no network, no look-ahead) and scores it against the
docs/LIVE_READINESS gates at the 30 / 60 / 90-day checkpoints. Writes
``data/momentum_readiness.json`` for the dashboard readiness page.

WHY it matters: a backtest can be curve-fit; only forward OOS results earn real
capital. This module is the ledger that says — with numbers — when (if ever) the
sleeve has cleared the bar. It is PURE (stdlib) and places NO orders.

The gate thresholds mirror docs/LIVE_READINESS.md:
  * >= 90 calendar days of paper track record
  * out-of-sample Sharpe (annualized, from the live equity curve) >= 1.0
  * max drawdown over the track record <= 15%
  * >= 26 momentum fills (>= ~2 monthly rebalances worth of names)
All four must pass before the sleeve is even ELIGIBLE for a fractional-live
satellite — and that is still a human decision, never automated.
"""
import glob
import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest import metrics as M  # noqa: E402

GATES = {
    "min_days": 90,
    "min_oos_sharpe": 1.0,
    "max_drawdown_pct": 15.0,
    "min_momentum_fills": 26,
}
CHECKPOINTS = (30, 60, 90)


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _date(s):
    """Parse an ISO date/datetime (with or without 'Z') to a date, or None."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def equity_curve_from_journals(journal_dir, since_date=None):
    """Chronological end-of-day equity from journal/YYYY-MM-DD.json files.

    Each file holds one or a list of entries; we take the 'end-of-day' entry when
    present (else the last entry with an equity), giving one point per day. Only
    dates on/after ``since_date`` are included. Returns ([(date, equity)], curve).
    """
    points = []
    for fp in sorted(glob.glob(os.path.join(journal_dir, "*.json"))):
        name = os.path.splitext(os.path.basename(fp))[0]
        d = _date(name)
        if d is None or (since_date and d < since_date):
            continue
        entries = _load(fp, [])
        if isinstance(entries, dict):
            entries = [entries]
        eod = [e for e in entries if isinstance(e, dict) and e.get("mode") == "end-of-day"]
        chosen = (eod or [e for e in entries if isinstance(e, dict)])
        eq = None
        for e in reversed(chosen):
            acc = e.get("account") or {}
            if isinstance(acc.get("equity"), (int, float)):
                eq = float(acc["equity"])
                break
        if eq is not None:
            points.append((d, eq))
    points.sort(key=lambda x: x[0])
    return points, [eq for _, eq in points]


def count_momentum_fills(trade_log):
    return sum(1 for t in trade_log
              if isinstance(t, dict) and t.get("order_class") == "momentum_sleeve")


def compute_readiness(journal_dir, momentum_state, trade_log, today=None,
                      gates=None):
    """Score the sleeve's live paper track record against the go-live gates."""
    gates = gates or GATES
    today = today or datetime.now(timezone.utc).date()
    activated = _date((momentum_state or {}).get("activated_at"))

    if activated is None:
        return {
            "status": "not_started",
            "as_of": today.isoformat(),
            "note": "Momentum sleeve has not run its first rebalance yet.",
            "gates": gates,
        }

    days = (today - activated).days
    points, curve = equity_curve_from_journals(journal_dir, since_date=activated)
    fills = count_momentum_fills(trade_log)

    have_curve = len(curve) >= 2
    rets = M.returns_from_equity(curve) if have_curve else []
    oos_sharpe = M.sharpe_ratio(rets) if len(rets) >= 2 else None
    max_dd = round(M.max_drawdown(curve) * 100, 2) if have_curve else None

    checks = {
        "days_on_paper": {
            "value": days, "threshold": gates["min_days"], "op": ">=",
            "pass": days >= gates["min_days"]},
        "oos_sharpe": {
            "value": round(oos_sharpe, 2) if oos_sharpe is not None else None,
            "threshold": gates["min_oos_sharpe"], "op": ">=",
            "pass": oos_sharpe is not None and oos_sharpe >= gates["min_oos_sharpe"]},
        "max_drawdown_pct": {
            "value": max_dd, "threshold": gates["max_drawdown_pct"], "op": "<=",
            "pass": max_dd is not None and max_dd <= gates["max_drawdown_pct"]},
        "momentum_fills": {
            "value": fills, "threshold": gates["min_momentum_fills"], "op": ">=",
            "pass": fills >= gates["min_momentum_fills"]},
    }
    all_pass = all(c["pass"] for c in checks.values())
    # data sufficiency: a verdict needs a real curve, not just an activation stamp.
    measurable = have_curve and oos_sharpe is not None

    milestones = []
    for cp in CHECKPOINTS:
        milestones.append({
            "day": cp,
            "reached": days >= cp,
            "eta_date": None if days >= cp
            else (activated.toordinal() + cp),  # ordinal; formatted below
        })
    for m in milestones:
        if m["eta_date"] is not None:
            m["eta_date"] = datetime.fromordinal(m["eta_date"]).date().isoformat()

    if all_pass:
        status = "eligible_for_review"        # human decision, still not automatic
    elif not measurable:
        status = "accruing_track_record"      # too early to judge
    else:
        status = "in_progress"

    return {
        "status": status,
        "as_of": today.isoformat(),
        "activated_at": activated.isoformat(),
        "days_on_paper": days,
        "track_days_measured": len(curve),
        "oos_sharpe": checks["oos_sharpe"]["value"],
        "max_drawdown_pct": max_dd,
        "momentum_fills": fills,
        "rebalance_count": (momentum_state or {}).get("rebalance_count"),
        "latest_vol_scale": (momentum_state or {}).get("vol_scale"),
        "latest_deployed_pct": (momentum_state or {}).get("deployed_pct"),
        "gates": gates,
        "checks": checks,
        "all_gates_pass": all_pass,
        "milestones": milestones,
        "verdict": (
            "ELIGIBLE for fractional-live REVIEW (human sign-off required)."
            if all_pass else
            "NOT yet eligible — PAPER ONLY. Keep accruing the track record."),
    }


def build_and_save(data_dir=None, journal_dir=None):
    data_dir = data_dir or os.path.join(REPO_ROOT, "data")
    journal_dir = journal_dir or os.path.join(REPO_ROOT, "journal")
    mstate = _load(os.path.join(data_dir, "momentum_state.json"), {})
    trade_log = _load(os.path.join(data_dir, "trade_log.json"), [])
    report = compute_readiness(journal_dir, mstate, trade_log)
    out = os.path.join(data_dir, "momentum_readiness.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    return report


if __name__ == "__main__":
    r = build_and_save()
    print(json.dumps(r, indent=2))
