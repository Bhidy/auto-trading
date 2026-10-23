"""Deterministic tests for the P2 satellite scorecard (synthetic fixtures, no network)."""
import json
import os
from datetime import date, timedelta

import pytest

from backtest.strategy_spec import load_and_validate
from research.p2_scorecard import (
    SPEC_PATH, build_lots, classify_lot, close_on_or_before, cohort_stats, honest_trial_count, run,
    score_lot, verdict,
)

ACC = {"min_n": 50, "alpha_t_min": 2.0, "profit_factor_min": 1.3, "dsr_min": 0.95}


def _weekdays(n, start=date(2026, 5, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _buy(oid, sym, d, qty, entry, pnl=None, exit_d=None, status=None, **kw):
    row = {"symbol": sym, "side": "buy", "qty": qty, "entry_price": entry, "limit_price": entry,
           "order_id": oid, "date": d, "politician": "X", "source": "backup"}
    if exit_d:
        row["exit_timestamp"] = exit_d + "T17:00:00+00:00"
        row["status"] = status or "closed"
    if pnl is not None:
        row["pnl"] = row["realized_pnl"] = pnl
    row.update(kw)
    return row


def test_committed_spec_validates():
    ok, errors = load_and_validate(SPEC_PATH)
    assert ok, errors
    spec = json.load(open(SPEC_PATH))
    assert spec["acceptance"] == {**spec["acceptance"], **ACC}
    assert spec["cohorts"]["split_date"] == "2026-07-04"


def test_lots_group_by_order_and_skip_sleeve_and_sells():
    log = [
        _buy("o1", "AAA", "2026-08-01", 2, 10.0, 2.0, "2026-08-10"),
        _buy("o1", "AAA", "2026-08-01", 3, 10.0, 6.0, "2026-08-20"),
        {"symbol": "AAA", "side": "sell", "qty": 5, "date": "2026-08-20", "status": "exit_marker"},
        {"symbol": "SPY", "side": "buy", "qty": 1, "date": "2026-08-01", "order_id": "s1",
         "politician": "BENCHMARK_SLEEVE", "source": "benchmark_sleeve"},
    ]
    lots = build_lots(log)
    assert list(lots) == ["o1"] and len(lots["o1"]) == 2


def test_classify_lot_states():
    closed = _buy("a", "A", "2026-08-01", 1, 10.0, 1.0, "2026-08-05")
    open_ = _buy("a", "A", "2026-08-01", 1, 10.0)
    orphan = _buy("b", "B", "2026-08-01", 1, 10.0, None, "2026-08-05", status="closed_reconciled")
    assert classify_lot([closed]) == "CLOSED"
    assert classify_lot([closed, open_]) == "PARTIAL"
    assert classify_lot([open_]) == "OPEN"
    assert classify_lot([orphan]) == "UNPRICED"


def test_partial_exits_are_summed_per_lot_and_spy_is_cost_weighted():
    dates = _weekdays(30)
    spy = {d: 100.0 + i for i, d in enumerate(dates)}
    sl = [_buy("o", "A", dates[0], 2, 10.0, 2.0, dates[10]),      # +10% on cost 20
          _buy("o", "A", dates[0], 3, 10.0, 6.0, dates[20])]      # +20% on cost 30
    rec, why = score_lot(sl, spy, sorted(spy), beta=1.0)
    assert why is None
    assert rec["return"] == pytest.approx(8.0 / 50.0)
    spy_r = (20 * (110 / 100 - 1) + 30 * (120 / 100 - 1)) / 50
    assert rec["spy_return"] == pytest.approx(spy_r, abs=1e-6)
    assert rec["alpha"] == pytest.approx(0.16 - spy_r, abs=1e-6)
    assert rec["exit_date"] == dates[20] and rec["n_slices"] == 2


def test_limit_price_basis_is_flagged_and_outside_history_refused():
    dates = _weekdays(10)
    spy = {d: 100.0 for d in dates}
    row = _buy("o", "A", dates[0], 1, None, 1.0, dates[5])
    row["limit_price"] = 10.0
    rec, _ = score_lot([row], spy, sorted(spy))
    assert rec["basis_from_limit_price"] is True
    late = _buy("p", "A", dates[0], 1, 10.0, 1.0, "2030-01-02")
    rec, why = score_lot([late], spy, sorted(spy))
    assert rec is None and why == "outside_spy_history"


def test_close_on_or_before_uses_prior_trading_day():
    spy = {"2026-05-01": 1.0, "2026-05-04": 2.0}
    ds = sorted(spy)
    assert close_on_or_before(spy, ds, "2026-05-03") == 1.0     # weekend -> Friday
    assert close_on_or_before(spy, ds, "2026-05-04") == 2.0
    assert close_on_or_before(spy, ds, "2026-04-30") is None


def _recs(n, alpha, spread):
    out = []
    for i in range(n):
        a = alpha + (spread if i % 2 else -spread)
        out.append({"return": a + 0.01, "spy_return": 0.01, "alpha": a, "pnl": a * 1000,
                    "basis_from_limit_price": False})
    return out


def test_dsr_refused_below_min_n_and_verdict_insufficient():
    st = cohort_stats(_recs(10, 0.02, 0.01), n_trials=34, min_n=50)
    assert st["dsr"] is None and "refused" in st["dsr_reason"]
    status, checks = verdict(st, ACC)
    assert status == "INSUFFICIENT_N"
    assert all(c["result"] == "INSUFFICIENT_N" for c in checks.values())


def test_verdict_pass_and_fail_at_sufficient_n():
    strong = cohort_stats(_recs(60, 0.03, 0.01), n_trials=34, min_n=50)
    status, checks = verdict(strong, ACC)
    assert strong["alpha_t"] > 2.0 and strong["dsr"] >= 0.95
    assert status == "PASS"
    assert strong["profit_factor_no_losses"] is True and checks["profit_factor"]["result"] == "PASS"
    mixed = cohort_stats(_recs(60, 0.02, 0.03), n_trials=34, min_n=50)   # +0.05 / -0.01 alternating
    status, checks = verdict(mixed, ACC)
    assert mixed["profit_factor"] == pytest.approx(5.0) and checks["profit_factor"]["result"] == "PASS"
    weak = cohort_stats(_recs(60, 0.001, 0.05), n_trials=34, min_n=50)
    status, checks = verdict(weak, ACC)
    assert status == "FAIL" and checks["alpha_t"]["result"] == "FAIL"


def test_honest_trial_count_from_artifacts(tmp_path):
    (tmp_path / "p2_congress_copy_backtest.json").write_text(json.dumps(
        {"strategies": {"a": {"overall": {}}, "b": {"overall": {}}}}))
    (tmp_path / "p2_disclosure_lag_study.json").write_text(json.dumps(
        {"search": {"max_disclosure_age_days": [15, 30, 45]}}))
    n, parts = honest_trial_count(str(tmp_path))
    assert parts["p2_congress_copy_backtest.json"] == 2
    assert parts["p2_disclosure_lag_study.json"] == 3
    assert n == 2 + 3 + parts["live_pipeline_versions"]


def test_run_end_to_end_splits_cohorts(tmp_path):
    dates = _weekdays(150, start=date(2026, 5, 1))
    (tmp_path / "data" / "deep").mkdir(parents=True)
    (tmp_path / "data" / "deep" / "core.json").write_text(json.dumps(
        {"bars": {"SPY": [{"t": d + "T04:00:00Z", "o": 100 + i * 0.1, "c": 100 + i * 0.1}
                          for i, d in enumerate(dates)]}}))
    pre_d = [d for d in dates if d <= "2026-07-04"]
    post_d = [d for d in dates if d > "2026-07-04"]
    log = [_buy("p1", "A", pre_d[0], 1, 10.0, 1.0, pre_d[5]),
           _buy("q1", "B", post_d[0], 1, 10.0, -0.5, post_d[5]),
           _buy("q2", "C", post_d[1], 1, 10.0)]                      # open -> excluded
    tl = tmp_path / "trade_log.json"
    tl.write_text(json.dumps(log))
    (tmp_path / "journal").mkdir()
    out_file = tmp_path / "data" / "p2_scorecard.json"
    out = run(SPEC_PATH, str(tl), str(tmp_path / "journal"), str(out_file), root=str(tmp_path))
    assert out["status"] == "INSUFFICIENT_N"
    assert out["cohorts"]["pre"]["stats"]["n"] == 1 and out["cohorts"]["post"]["stats"]["n"] == 1
    assert out["lot_counts"]["OPEN"] == 1
    assert out["book_beta_diagnostic"]["beta"] is None
    assert os.path.exists(str(out_file) + ".provenance.json")
