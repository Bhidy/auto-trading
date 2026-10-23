"""Deterministic tests for the pre-registered passive-core evaluator (no network,
synthetic fixtures only)."""
import json
import math
import os
from datetime import date, timedelta

import pytest

from backtest import metrics
from backtest.strategy_spec import load_and_validate
from research.passive_core_eval import (
    SPEC_PATH, align, combine_acceptance, dsr_with_trial_count, evaluate_dataset, load_spec, run,
    simulate_buy_hold, simulate_core, spec_hash, splice_sources, window_bounds,
)

SYMS = ["SPY", "AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]


def _weekdays(n, start=date(2022, 1, 3)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _series(n, drift, amp, phase, base=100.0):
    """Deterministic price path: drift + sinusoidal noise (no RNG)."""
    px, out = base, []
    for t in range(n):
        px *= 1.0 + drift + amp * math.sin(0.7 * t + phase)
        out.append(round(px, 6))
    return out


def _dataset(n=700, syms=SYMS, rally=None):
    dates = _weekdays(n)
    closes = {}
    for i, s in enumerate(syms):
        drift = 0.0004 + 0.0001 * i
        if rally == s:
            drift = 0.01                               # one symbol runs away -> cap trims
        closes[s] = _series(n, drift, 0.008 + 0.001 * i, i)
    opens = {s: [c[0]] + c[:-1] for s, c in closes.items()}   # open = prior close
    return {"dates": dates, "closes": closes, "opens": opens, "dropped_dates": 0}


def _spec(**over):
    spec = load_spec()
    spec = json.loads(json.dumps(spec))
    spec["symbols"] = list(SYMS)
    spec.update(over)
    return spec


# --- spec ----------------------------------------------------------------------

def test_committed_spec_validates_and_hash_is_stable():
    ok, errors = load_and_validate(SPEC_PATH)
    assert ok, errors
    spec = load_spec()
    assert spec_hash(spec) == spec_hash(json.loads(json.dumps(spec)))
    assert spec["target_weight"] * len(spec["symbols"]) <= 0.92
    assert spec["target_weight"] <= spec["max_weight"] <= 0.12
    assert spec["evaluation"]["min_windows"] >= 10
    assert spec["acceptance"]["C1_sharpe_vs_spy"]["threshold"] == -0.15


def test_spec_hash_changes_on_any_edit():
    spec = load_spec()
    other = json.loads(json.dumps(spec))
    other["acceptance"]["C1_sharpe_vs_spy"]["threshold"] = -0.30
    assert spec_hash(spec) != spec_hash(other)


# --- rebalance math --------------------------------------------------------------

def test_day0_buys_every_symbol_to_target_and_keeps_cash():
    ds = _dataset(n=5)
    out = simulate_core(ds["dates"], ds["closes"], ds["opens"], SYMS, 0.114, 0.12, 0.0)
    # zero friction, day-0 at open: invested 91.2%, cash 8.8%; equity at close 0 consistent
    eq0 = out["equity"][1]
    inv = sum(0.114 / ds["opens"][s][0] * ds["closes"][s][0] for s in SYMS)
    assert eq0 == pytest.approx(0.088 + inv)
    assert out["n_rebalances"] == 1


def test_monthly_rebalance_resets_weights_at_the_open():
    ds = _dataset(n=130)
    months = {d[:7] for d in ds["dates"]}
    out = simulate_core(ds["dates"], ds["closes"], ds["opens"], SYMS, 0.114, 0.50, 0.0)
    assert out["n_rebalances"] == len(months)
    assert out["max_post_trade_weight"] == pytest.approx(0.114, abs=1e-9)


def test_cap_compliance_no_post_trade_weight_above_cap():
    ds = _dataset(n=400, rally="CCC")
    out = simulate_core(ds["dates"], ds["closes"], ds["opens"], SYMS, 0.114, 0.12, 0.001)
    assert out["n_cap_trims"] > 0                       # the drift guard actually fired
    assert out["max_post_trade_weight"] <= 0.12 + 1e-12
    assert out["max_close_weight"] > 0.12               # drift between trades is reported honestly


# --- costs -------------------------------------------------------------------------

def test_costs_equal_turnover_times_rate_and_reduce_equity():
    ds = _dataset(n=300)
    free = simulate_core(ds["dates"], ds["closes"], ds["opens"], SYMS, 0.114, 0.12, 0.0)
    paid = simulate_core(ds["dates"], ds["closes"], ds["opens"], SYMS, 0.114, 0.12, 0.001)
    assert paid["costs"] == pytest.approx(paid["turnover"] * 0.001)
    assert paid["equity"][-1] < free["equity"][-1]


def test_buy_hold_charges_entry_friction_once():
    closes, opens = [100.0, 110.0, 121.0], [100.0, 100.0, 110.0]
    eq = simulate_buy_hold(closes, opens, 0.001)
    assert eq[0] == 1.0
    assert eq[-1] == pytest.approx(1.21 / 1.001)


# --- windows / stats ---------------------------------------------------------------

def test_windows_are_non_overlapping_and_end_aligned():
    b = window_bounds(700, 63)
    assert len(b) == 11
    assert b[-1][1] == 700
    assert all(b[i][1] == b[i + 1][0] for i in range(len(b) - 1))


def test_dsr_n1_equals_psr_and_more_trials_deflate():
    sr, n = 0.07, 800
    psr = metrics.probabilistic_sharpe_ratio(sr, 0.0, n)
    assert dsr_with_trial_count(sr, n, 1) == pytest.approx(psr)
    assert dsr_with_trial_count(sr, n, 34) < psr


# --- refuse on insufficient data ----------------------------------------------------

def test_refuses_when_fewer_than_min_windows():
    ds = _dataset(n=63 * 9)                              # 9 windows < 10
    r = evaluate_dataset(ds, _spec(), 0.001)
    assert r["status"] == "INSUFFICIENT_DATA"
    assert "criteria" not in r


def test_evaluates_with_enough_windows_and_scores_criteria():
    ds = _dataset(n=63 * 11)
    r = evaluate_dataset(ds, _spec(), 0.001)
    assert r["status"] == "EVALUATED"
    assert r["n_windows"] == 11 and len(r["windows"]) == 11
    for k in ("C1_sharpe_vs_spy", "C2_drawdown_vs_spy"):
        assert r["criteria"][k]["result"] in ("PASS", "FAIL")
    assert r["psr_dsr"]["n_trials"] == 1
    assert r["cpcv"]["n_splits"] == 15


# --- acceptance logic ------------------------------------------------------------------

def _res(c1, c2):
    return {"status": "EVALUATED",
            "criteria": {"C1_sharpe_vs_spy": {"result": c1}, "C2_drawdown_vs_spy": {"result": c2}}}


def test_acceptance_requires_pass_on_every_dataset():
    spec = load_spec()
    a = combine_acceptance({"x": _res("PASS", "PASS"), "y": _res("FAIL", "PASS")}, spec)
    assert a["C1_sharpe_vs_spy"] == "FAIL" and a["C2_drawdown_vs_spy"] == "PASS"
    assert a["C3_live_tracking_error"] == "PENDING_LIVE"
    assert a["overall"] == "FAIL"


def test_acceptance_all_pass_is_still_pending_live():
    a = combine_acceptance({"x": _res("PASS", "PASS")}, load_spec())
    assert a["overall"] == "PASS_BACKTEST_PENDING_LIVE"


def test_acceptance_with_no_evaluated_dataset_is_insufficient():
    a = combine_acceptance({"x": {"status": "INSUFFICIENT_DATA"}, "y": {"status": "NOT_AVAILABLE"}}, load_spec())
    assert a["C1_sharpe_vs_spy"] == "INSUFFICIENT_DATA"
    assert a["overall"] == "INSUFFICIENT_DATA"


# --- data splice ------------------------------------------------------------------------

def _bars(dates, closes):
    return {d: {"t": d + "T04:00:00Z", "o": c, "c": c} for d, c in zip(dates, closes)}


def test_splice_appends_only_after_base_when_overlap_consistent():
    d = _weekdays(6)
    a = {"SPY": _bars(d[:4], [1, 2, 3, 4])}
    b = {"SPY": _bars(d[2:], [3.001, 4.001, 5, 6])}
    merged, checks = splice_sources([a, b], ["SPY"])
    assert sorted(merged["SPY"]) == d
    assert merged["SPY"][d[2]]["c"] == 3                 # base wins on overlap
    assert checks[0]["accepted"] and checks[0]["appended_days"] == 2


def test_splice_refused_when_overlap_disagrees():
    d = _weekdays(6)
    a = {"SPY": _bars(d[:4], [1, 2, 3, 4])}
    b = {"SPY": _bars(d[2:], [6, 8, 10, 12])}           # e.g. split-adjustment mismatch
    merged, checks = splice_sources([a, b], ["SPY"])
    assert sorted(merged["SPY"]) == d[:4]
    assert checks[0]["accepted"] is False


def test_align_drops_dates_missing_for_any_symbol():
    d = _weekdays(5)
    merged = {"SPY": _bars(d, [1, 2, 3, 4, 5]), "BIL": _bars(d[:2] + d[3:], [1, 1, 1, 1])}
    dates, closes, _, dropped = align(merged, ["SPY", "BIL"])
    assert dates == d[:2] + d[3:] and dropped == 1


# --- end to end on a synthetic repo root -----------------------------------------------

def test_run_end_to_end_writes_artifact_and_provenance(tmp_path):
    ds = _dataset(n=63 * 11)
    spec = _spec()
    spec["evaluation"]["datasets"] = [{"id": "committed", "sources": ["data/deep", "data"], "required": True},
                                      {"id": "extended_5y", "sources": ["data/nope"], "required": False}]
    (tmp_path / "data" / "deep").mkdir(parents=True)
    payload = {"bars": {s: [{"t": d + "T04:00:00Z", "o": o, "c": c}
                            for d, o, c in zip(ds["dates"], ds["opens"][s], ds["closes"][s])] for s in SYMS}}
    (tmp_path / "data" / "deep" / "bucket.json").write_text(json.dumps(payload))
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))
    out_file = tmp_path / "data" / "passive_core_validation.json"

    out = run(str(spec_file), str(out_file), root=str(tmp_path))
    assert out["spec_hash"] == spec_hash(spec)
    assert out["datasets"]["committed"]["status"] == "EVALUATED"
    assert out["datasets"]["extended_5y"]["status"] == "NOT_AVAILABLE"
    assert out["friction_bps_per_side"] == {"cost": 5.0, "slippage": 5.0}
    assert out["acceptance"]["C3_live_tracking_error"] == "PENDING_LIVE"
    assert os.path.exists(str(out_file) + ".provenance.json")
    assert json.loads(out_file.read_text())["spec_id"] == spec["spec_id"]
