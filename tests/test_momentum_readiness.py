"""Momentum-sleeve live-readiness tracker (audit 2026-07-04).

Verifies the go/no-go ledger: fail-safe when not started, honest 'too early'
before a curve exists, correct gate math, and the eligible verdict ONLY when all
four LIVE_READINESS gates pass on real forward paper data.
"""
import json
import os
import sys
from datetime import date

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from momentum_readiness import (  # noqa: E402
    compute_readiness, count_momentum_fills, equity_curve_from_journals)


def _write_journal(d, day, equity, mode="end-of-day"):
    with open(os.path.join(d, f"{day}.json"), "w") as f:
        json.dump([{"date": day, "mode": mode, "account": {"equity": equity}}], f)


def test_not_started_when_no_activation():
    r = compute_readiness("/nonexistent", {}, [])
    assert r["status"] == "not_started"


def test_too_early_before_a_curve_exists(tmp_path):
    # Activated today, no journals yet -> accruing, never a premature pass.
    mstate = {"activated_at": date.today().isoformat()}
    r = compute_readiness(str(tmp_path), mstate, [], today=date.today())
    assert r["status"] == "accruing_track_record"
    assert r["all_gates_pass"] is False


def test_gates_fail_when_track_record_too_short(tmp_path):
    _write_journal(str(tmp_path), "2026-06-01", 100_000)
    _write_journal(str(tmp_path), "2026-06-02", 100_500)
    _write_journal(str(tmp_path), "2026-06-03", 101_000)
    mstate = {"activated_at": "2026-06-01T14:00:00Z"}
    r = compute_readiness(str(tmp_path), mstate, [], today=date(2026, 6, 20))
    # only ~19 days, few fills -> days & fills gates fail, not eligible.
    assert r["checks"]["days_on_paper"]["pass"] is False
    assert r["checks"]["momentum_fills"]["pass"] is False
    assert r["status"] != "eligible_for_review"


def test_eligible_only_when_all_gates_pass(tmp_path):
    # Build a >90-day rising curve with mild dispersion (positive Sharpe, shallow DD).
    start = date(2026, 1, 1).toordinal()
    eq = 100_000.0
    for i in range(120):
        d = date.fromordinal(start + i).isoformat()
        eq *= (1 + (0.004 if i % 2 == 0 else -0.001))   # mean +0.0015/day
        _write_journal(str(tmp_path), d, round(eq, 2))
    mstate = {"activated_at": "2026-01-01T14:00:00Z"}
    trade_log = [{"order_class": "momentum_sleeve"} for _ in range(30)]
    r = compute_readiness(str(tmp_path), mstate, trade_log, today=date(2026, 5, 5))
    assert r["checks"]["days_on_paper"]["pass"] is True
    assert r["checks"]["momentum_fills"]["pass"] is True
    assert r["checks"]["oos_sharpe"]["pass"] is True
    assert r["checks"]["max_drawdown_pct"]["pass"] is True
    assert r["all_gates_pass"] is True
    assert r["status"] == "eligible_for_review"


def test_high_drawdown_blocks_eligibility(tmp_path):
    # Long track, many fills, but a >15% drawdown must fail the DD gate.
    start = date(2026, 1, 1).toordinal()
    curve = [100_000] * 30 + [80_000] + [100_000] * 89   # ~20% dd mid-way
    for i, eq in enumerate(curve):
        _write_journal(str(tmp_path), date.fromordinal(start + i).isoformat(), eq)
    mstate = {"activated_at": "2026-01-01T14:00:00Z"}
    trade_log = [{"order_class": "momentum_sleeve"} for _ in range(30)]
    r = compute_readiness(str(tmp_path), mstate, trade_log, today=date(2026, 5, 5))
    assert r["checks"]["max_drawdown_pct"]["pass"] is False
    assert r["all_gates_pass"] is False


def test_count_momentum_fills_ignores_other_classes():
    log = [{"order_class": "momentum_sleeve"}, {"order_class": "passive_core"},
           {"order_class": "momentum_sleeve"}, {"foo": 1}]
    assert count_momentum_fills(log) == 2


def test_equity_curve_prefers_eod_entry(tmp_path):
    with open(os.path.join(str(tmp_path), "2026-06-01.json"), "w") as f:
        json.dump([{"mode": "morning", "account": {"equity": 111}},
                   {"mode": "end-of-day", "account": {"equity": 222}}], f)
    _pts, curve = equity_curve_from_journals(str(tmp_path))
    assert curve == [222]                       # takes the end-of-day snapshot
