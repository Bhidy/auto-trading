"""Readiness Engine v2 (shared/readiness.py + scripts/readiness_engine.py).

Pins the pre-registered statistics and the honesty rules: trading sessions (not
calendar days), version reset at start_date, benchmark-relative alpha with a HAC
t-stat and DSR at the honest trial count, an ETA that is a power projection (and
says "not converging" when alpha <= 0), NOT_ELIGIBLE for exits-only/quarantined
sleeves, missing data that never passes, and no percentage score anywhere.
"""
import json
import math
import os
import random
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest import metrics as M  # noqa: E402
from shared import readiness as R  # noqa: E402


def _series(n, alpha, beta=0.5, seed=7, rf=0.00015, noise=0.003, ar=0.0):
    rng = random.Random(seed)
    m, b, f, e_prev = [], [], [], 0.0
    for _ in range(n):
        mk = rng.gauss(0.0004, 0.01)
        e = ar * e_prev + rng.gauss(0.0, noise)
        e_prev = e
        m.append(mk)
        f.append(rf)
        b.append(rf + alpha + beta * (mk - rf) + e)
    return b, m, f


# --- sessions -----------------------------------------------------------------

def test_trading_days_skip_weekends_and_holidays():
    s = R.nyse_sessions("2026-06-29", "2026-07-10")
    assert "2026-07-03" not in s            # Independence Day observed (Jul 4 = Saturday)
    assert R.count_sessions(s, "2026-07-01", "2026-07-10") == 7
    nov = R.nyse_sessions("2026-11-23", "2026-11-27")
    assert nov == ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-27"]   # Thanksgiving
    assert "2026-04-03" not in R.nyse_sessions("2026-03-30", "2026-04-10")    # Good Friday
    assert "2027-01-01" not in R.nyse_sessions("2026-12-28", "2027-01-08")


def test_broker_calendar_overrides_rules_inside_its_span():
    broker = ["2026-07-06", "2026-07-08"]   # e.g. an ad-hoc closure on the 7th
    s = R.nyse_sessions("2026-07-01", "2026-07-10", broker)
    assert "2026-07-07" not in s and "2026-07-06" in s
    assert "2026-07-02" in s and "2026-07-09" in s   # rules outside the broker span


def test_trading_days_are_not_calendar_days():
    s = R.nyse_sessions("2026-01-01", "2026-12-31")
    assert R.count_sessions(s, "2026-01-01", "2026-12-31") == 251   # = Alpaca calendar 2026
    assert R.session_after(s, "2026-07-02", 1) == "2026-07-06"


# --- version reset / series -----------------------------------------------------

def test_window_excludes_pre_start_returns():
    s = R.nyse_sessions("2026-06-01", "2026-06-30")
    eq = {d: 100.0 for d in s}
    eq["2026-06-10"] = 200.0                 # huge pre-start jump
    eq["2026-06-11"] = 100.0
    for d in s:
        if d >= "2026-06-15":
            eq[d] = 101.0
    w = R.window_returns(eq, s, "2026-06-15", "2026-06-30")
    assert w["dates"][0] == "2026-06-15"     # first in-window return uses the prior close as base
    assert all(d >= "2026-06-15" for d in w["dates"])
    assert abs(w["returns"][0] - 0.01) < 1e-12
    assert max(abs(r) for r in w["returns"]) < 0.02


def test_missing_equity_is_reported_not_interpolated():
    s = R.nyse_sessions("2026-06-01", "2026-06-12")
    eq = {d: 100.0 + i for i, d in enumerate(s)}
    del eq["2026-06-05"]
    w = R.window_returns(eq, s, "2026-06-02", "2026-06-12")
    assert "2026-06-05" in w["missing"] and "2026-06-08" in w["missing"]
    assert "2026-06-05" not in w["dates"]


# --- edge test --------------------------------------------------------------------

def test_noise_free_regression_recovers_alpha_and_beta():
    x = [0.01 * math.sin(i) for i in range(50)]
    y = [0.0003 + 0.7 * xi for xi in x]
    reg = R.ols_hac(y, x, 5)
    assert abs(reg["alpha"] - 0.0003) < 1e-12 and abs(reg["beta"] - 0.7) < 1e-12


def test_hac_se_matches_iid_and_widens_under_autocorrelation():
    b, m, f = _series(1500, 0.0, seed=11)
    y = [bi - fi for bi, fi in zip(b, f)]
    x = [mi - fi for mi, fi in zip(m, f)]
    iid = R.ols_hac(y, x, lag=0)["se_alpha_hac"]
    hac = R.ols_hac(y, x, lag=5)["se_alpha_hac"]
    assert 0.8 < hac / iid < 1.25
    b2, m2, f2 = _series(1500, 0.0, seed=11, ar=0.6)
    y2 = [bi - fi for bi, fi in zip(b2, f2)]
    x2 = [mi - fi for mi, fi in zip(m2, f2)]
    assert R.ols_hac(y2, x2, 5)["se_alpha_hac"] > 1.3 * R.ols_hac(y2, x2, 0)["se_alpha_hac"]


def test_significant_positive_alpha_passes_only_after_enough_data():
    b, m, f = _series(700, 0.0008, seed=3)
    full = R.edge_test(b, m, f, trial_count=34)
    assert full["status"] == "pass" and full["cs_lower_daily"] > 0
    assert full["decision_rule"] == "confidence_sequence"
    assert abs(full["beta"] - 0.5) < 0.05
    early = R.edge_test(b[:40], m[:40], f[:40], trial_count=34)
    assert early["status"] == "insufficient"          # n < 60, whatever the numbers say


def test_zero_alpha_never_passes_and_stays_insufficient():
    b, m, f = _series(600, 0.0, seed=5)
    assert R.edge_test(b[:30], m[:30], f[:30], 34)["status"] == "insufficient"
    e = R.edge_test(b, m, f, 34)
    assert e["status"] == "insufficient" and e["cs_lower_daily"] < 0 < e["cs_upper_daily"]


def test_significantly_negative_alpha_fails_and_is_not_converging():
    b, m, f = _series(1000, -0.0006, seed=9)
    e = R.edge_test(b, m, f, 34)
    assert e["status"] == "fail" and e["cs_upper_daily"] < 0
    eta = R.edge_eta(e)
    assert eta["state"] == "not_converging" and eta["sessions_remaining"] is None


def test_live_decision_does_not_use_backtest_trial_count():
    """H3: selection inflates backtests, not post-selection live returns — the
    trial count only moves the informational DSR, never the decision."""
    b, m, f = _series(300, 0.0006, seed=4)
    e1, e40 = R.edge_test(b, m, f, 1), R.edge_test(b, m, f, 40)
    assert e1["dsr"] > e40["dsr"]
    assert (e1["status"], e1["cs_lower_daily"]) == (e40["status"], e40["cs_lower_daily"])
    assert R.z_required(1) < R.z_required(34) < R.z_required(40)


def test_confidence_sequence_boundary_math():
    rho, a = R.THRESHOLDS["cs_rho_sessions"], 0.01
    for v in (60, 252, 1260):
        b = R.cs_boundary(v, rho, a)
        assert abs(R._log_mixture(b, v, rho) - math.log(1 / a)) < 1e-6
    assert R.cs_boundary(252, rho, 0.001) > R.cs_boundary(252, rho, 0.01)   # stricter level, wider
    lo, hi = R.confidence_sequence(0.001, 0.01, 500, rho, a)
    assert abs((0.001 - lo) - (hi - 0.001)) < 1e-15


def test_family_alpha_bonferroni_with_floor():
    assert R.family_alpha_level(2) == 0.05 / 6
    assert R.family_alpha_level(9) == 0.05 / 9
    import readiness_engine as E
    reg = [{"claims_edge": True, "status": "active"}, {"claims_edge": False, "status": "active"},
           {"claims_edge": True, "status": "forward_test"}, {"claims_edge": True, "status": "quarantined"}]
    assert E.family_k(reg) == (6, 2)


def _path(seed, n, alpha_ann=0.0, ir=None):
    if ir is not None:
        alpha_ann = ir * 0.10
    rng = random.Random(seed)
    rf = 0.04 / 252
    y, x, f = [], [], []
    for _ in range(n):
        mk = rng.gauss(0.0004, 0.16 / math.sqrt(252))
        y.append(rf + alpha_ann / 252 + 0.5 * mk + rng.gauss(0, 0.10 / math.sqrt(252)))
        x.append(mk + rf)
        f.append(rf)
    return y, x, f


def _first_pass(y, x, f, level, step=5, start=60):
    for n in range(start, len(y) + 1, step):
        if R.edge_test(y[:n], x[:n], f[:n], 1, alpha_level=level)["status"] == "pass":
            return n
    return None


def test_sequential_validity_under_repeated_looks():
    """C1: zero true alpha, re-evaluated every 5 sessions for 2 years on 120
    fixed-seed paths (80). The always-valid rule must not manufacture a GO; the v2.0
    fixed-z rule (N=1) is shown for contrast on the same paths."""
    lvl = R.family_alpha_level(6)
    new_hits = old_hits = 0
    for seed in range(80):
        y, x, f = _path(1000 + seed, 504)
        if _first_pass(y, x, f, lvl, step=5) is not None:
            new_hits += 1
        for n in range(90, 505, 5):
            e = R.edge_test(y[:n], x[:n], f[:n], 1)
            if e["alpha_daily"] > 0 and e["dsr"] >= 0.95 and (e["t_hac"] or 0) >= e["z_required"]:
                old_hits += 1
                break
    assert new_hits <= 1               # expectation <= 80 * 0.0083 ~ 0.7
    assert old_hits > new_hits         # repeated looks inflate the fixed-z rule


def test_sequential_power_strong_alpha():
    """A strong edge (annual IR 3) is detected within 3 years on most paths. The
    v2.2 predictable plug-in CS pays ~10-30% more sessions than v2.1's
    full-sample plug-in for a valid time-uniform level (docs §2 power table)."""
    lvl = R.family_alpha_level(6)
    hits = [_first_pass(*_path(2000 + s, 756, ir=3.0), lvl, step=12) for s in range(10)]
    assert sum(h is not None for h in hits) >= 7
    assert R.sessions_to_cross(3.0 / math.sqrt(252), 1.0, 252, lvl, 2520) < 504
    assert R.sessions_to_cross(0.8 / math.sqrt(252), 1.0, 252, lvl, 10 ** 5) > 252 * 15


def _edge(n, alpha, sig=0.003, se=None, status="insufficient"):
    lvl = R.family_alpha_level(6)
    lo, hi = R.confidence_sequence(alpha, sig, n, R.THRESHOLDS["cs_rho_sessions"], lvl)
    return {"status": status, "n": n, "alpha_daily": alpha, "sigma_eff_daily": sig,
            "se_alpha_hac_daily": se if se is not None else sig / math.sqrt(n),
            "cs_lower_daily": lo, "cs_upper_daily": hi, "alpha_level": lvl}


def test_eta_is_a_range_and_monotonic():
    e = R.edge_eta(_edge(100, 0.0008))
    assert e["state"] == "estimate"
    assert e["optimistic_sessions"] < e["median_sessions"] < (e["pessimistic_sessions"] or 10 ** 9)
    rem = [R.edge_eta(_edge(n, 0.0008))["median_sessions"] for n in (60, 100, 150)]
    assert all(a > b for a, b in zip(rem, rem[1:]))                    # more data -> sooner
    assert (R.edge_eta(_edge(60, 0.0012))["n_required"]
            < R.edge_eta(_edge(60, 0.0008))["n_required"])            # bigger alpha -> sooner
    assert R.edge_eta(_edge(10, 0.0004))["state"] == "too_early"


def test_not_converging_only_when_upper_bound_is_negative():
    # alpha estimate <= 0 but the upper bound is still positive: NOT "not converging"
    e = R.edge_eta(_edge(80, -0.0001))
    assert e["state"] == "uncertain" and e["median_sessions"] is None
    hi_neg = _edge(80, -0.01)
    assert hi_neg["cs_upper_daily"] < 0
    assert R.edge_eta(hi_neg)["state"] == "not_converging"


# --- parity with metrics.py ---------------------------------------------------------

def test_drawdown_and_dsr_parity_with_metrics():
    b, _m, _f = _series(120, 0.0002, seed=2)
    dd = R.drawdown_stats(b)
    assert dd["max_drawdown"] == M.max_drawdown(R.equity_curve(b))
    g = {x["id"]: x for x in R.risk_gates(b)}
    assert g["max_drawdown"]["value"] == round(M.max_drawdown(R.equity_curve(b)), 4)
    # DSR with one trial is PSR vs 0; equals the metrics deflated Sharpe on one trial.
    sr = 0.08
    assert abs(M.deflated_sharpe_at_trial_count(sr, 120, 1)
               - M.deflated_sharpe_ratio([sr], 120)) < 1e-12
    # Appraisal ratio of a zero-beta book equals its Sharpe (up to the n-1 vs n-2 dof).
    rng = random.Random(1)
    x = [rng.gauss(0, 0.01) for _ in range(400)]
    y = [0.0005 + rng.gauss(0, 0.004) for _ in range(400)]
    e = R.edge_test(y, x, [0.0] * 400, 1)
    assert abs(e["ir_annual"] - M.sharpe_ratio(y)) < 0.1


def test_research_lane_dsr_formula_matches_cloud_copy():
    import importlib
    pce = importlib.import_module("research.passive_core_eval")
    for sr, n, k in ((0.05, 250, 1), (0.08, 300, 34), (0.02, 90, 40)):
        assert abs(pce.dsr_with_trial_count(sr, n, k) - M.deflated_sharpe_at_trial_count(sr, n, k)) < 1e-12


# --- gates never pass on missing data --------------------------------------------------

def test_missing_data_never_passes():
    th = R.THRESHOLDS
    assert all(g["status"] == "insufficient" for g in R.risk_gates([]))
    assert R.reconciliation_gate(None, "2026-10-22", [])["status"] == "not_measured"
    assert R.reconciliation_gate({"timestamp": "2026-10-22T20:00:00Z", "working_orders": []},
                                 "2026-10-22", ["2026-10-22"])["status"] == "not_measured"
    assert R.slippage_gate([])["status"] == "not_measured"
    assert R.duplicate_gate(None, 0)["status"] == "not_measured"
    assert R.exception_gate(None, "2026-10-22", [])["status"] == "not_measured"
    assert R.freshness_gate(None, "2026-10-22", [])["status"] == "not_measured"
    assert {g["status"] for g in R.trade_gates(None, 50)} == {"not_measured"}
    assert R.regime_gate([], [], {})["status"] == "not_measured"
    rets = [0.001] * 59
    cv = next(g for g in R.risk_gates(rets) if g["id"] == "cvar95")
    assert cv["status"] == "insufficient" and th["min_cvar_sessions"] == 60


def test_profit_factor_not_judged_below_sample_floor():
    gates = {g["id"]: g for g in R.trade_gates([100.0] * 10, 50)}
    assert gates["sample"]["status"] == "insufficient"
    assert gates["profit_factor"]["status"] == "insufficient"
    gates = {g["id"]: g for g in R.trade_gates([100.0, -50.0] * 30, 50)}
    assert gates["sample"]["status"] == "pass" and gates["profit_factor"]["status"] == "pass"


def test_regime_coverage_needs_two_groups():
    dates = [f"2026-08-{d:02d}" for d in range(3, 15)]
    rets = [0.001] * len(dates)
    one = {d: "BULL" for d in dates}
    assert R.regime_gate(dates, rets, one)["status"] == "insufficient"
    two = {d: ("BULL" if i < 6 else "CORRECTION") for i, d in enumerate(dates)}
    assert R.regime_gate(dates, rets, two)["status"] == "pass"
    crash = [(-0.02 if two[d] == "CORRECTION" else 0.001) for d in dates]
    assert R.regime_gate(dates, crash, two)["status"] == "fail"


# --- verdicts ------------------------------------------------------------------------------

def _all_pass_gates():
    return [R.gate(gid, gid, "", 1, "pass") for gid in R.GATE_PRIORITY]


def test_go_only_when_every_hard_gate_passes():
    s = R.nyse_sessions("2026-01-01", "2027-12-31")
    assert R.verdict("active", _all_pass_gates(), s, "2026-10-22")["verdict"] == "GO"
    gates = _all_pass_gates()
    gates[-1] = R.gate("exception_free", "x", "", None, "not_measured")
    v = R.verdict("active", gates, s, "2026-10-22")
    assert v["verdict"] == "NOT_READY" and v["measurement_gaps"] == ["exception_free"]


def test_exits_only_and_quarantined_are_not_eligible():
    s = R.nyse_sessions("2026-01-01", "2027-12-31")
    for status in ("exits_only", "quarantined"):
        assert R.verdict(status, _all_pass_gates(), s, "2026-10-22")["verdict"] == "NOT_ELIGIBLE"


def test_binding_gate_is_longest_eta_and_skips_measurement_gaps():
    s = R.nyse_sessions("2026-01-01", "2027-12-31")
    gates = _all_pass_gates()
    gates[0] = R.gate("edge", "edge", "", None, "fail", eta_sessions=150)
    gates[1] = R.gate("track_record", "t", "", 30, "insufficient", eta_sessions=60)
    gates[-1] = R.gate("exception_free", "x", "", None, "not_measured")
    v = R.verdict("active", gates, s, "2026-10-22")
    assert v["binding_gate"] == "edge"
    assert v["eta"]["sessions_remaining"] == 150
    assert v["eta"]["projected_date"] == R.session_after(s, "2026-10-22", 150)
    assert v["eta"]["excludes_measurement_gaps"] == ["exception_free"]
    gates[1] = R.gate("track_record", "t", "", 30, "insufficient", eta_sessions=None)
    assert R.verdict("active", gates, s, "2026-10-22")["eta"]["projected_date"] is None


# --- engine (offline, committed artifacts only) ---------------------------------------------

def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_engine_offline_report_shape_and_honesty(monkeypatch):
    import readiness_engine as E
    for k in ("GITHUB_TOKEN", "SUPABASE_URL", "SUPABASE_ANON_KEY"):
        monkeypatch.delenv(k, raising=False)
    reg = json.load(open(os.path.join(REPO_ROOT, "config", "strategy_registry.json")))
    rep = E.build_report(reg, as_of="2026-10-22", offline=True)
    assert rep["methodology_version"] == R.METHODOLOGY_VERSION
    assert {s["id"] for s in rep["sleeves"]} == {s["id"] for s in reg["sleeves"]}
    for s in rep["sleeves"]:
        assert s["verdict"] in rep["verdict_values"]
        assert {"start", "end", "trading_days"} <= set(s["window"])
        assert {"alpha", "beta", "t_hac", "ir", "psr", "dsr", "n"} <= set(s["edge"])
        if s["status"] in ("exits_only", "quarantined"):
            assert s["verdict"] == "NOT_ELIGIBLE"
        ex = next(g for g in s["gates"] if g["id"] == "exception_free")
        assert ex["status"] == "not_measured"            # offline: never a default pass
        assert s["verdict"] != "GO"
    by = {s["id"]: s for s in rep["sleeves"]}
    beta = by["p2-benchmark-etf-v1"]
    assert beta["verdict"] == "BETA_SLEEVE" and beta["attribution"] == "book_level_shared"
    assert next(g for g in beta["gates"] if g["id"] == "edge")["status"] == "not_applicable"
    assert beta["edge"]["alpha"] is None                    # book series never credited to it
    assert by["p2-copy-v2"]["owns_edge_test"] is True
    assert by["p3-crisis-core-v1-forward"]["verdict"] in ("NOT_READY", "FORWARD_TEST_PASS")
    mom = by["p1-momentum-v1"]["window"]
    assert mom["halted_sessions"] > 70 and mom["active_trading_days"] == mom["trading_days"] - mom["halted_sessions"]
    assert rep["edge_decision"]["k_family"] >= 6
    banned = ("pct_ready", "percent", "readiness_pct", "score", "overall_pct")
    assert not [k for k in _keys(rep["sleeves"]) if any(b in str(k).lower() for b in banned)]


def test_registry_is_well_formed_and_never_written_by_code():
    reg = json.load(open(os.path.join(REPO_ROOT, "config", "strategy_registry.json")))
    ids = set()
    for s in reg["sleeves"]:
        assert s["id"] not in ids
        ids.add(s["id"])
        assert s["book"] in ("portfolio_1", "portfolio_2", "portfolio_3")
        assert s["status"] in ("active", "forward_test", "exits_only", "quarantined")
        assert s["evidence_basis"] in ("daily_returns", "trades", "both")
        assert isinstance(s["trial_count"], int) and s["trial_count"] >= 1 and s["trial_count_source"]
        R._d(s["start_date"])
        assert s["benchmark"] == "SPY"
    src = open(os.path.join(REPO_ROOT, "scripts", "readiness_engine.py")).read()
    assert 'open(REGISTRY_PATH, "w")' not in src and "open(CONTROLS_PATH, \"w\")" not in src


def test_alpaca_daily_stamps_map_to_the_right_session():
    """Portfolio-history 1D points are stamped 00:00Z of the NEXT day (Mon close =
    Tue 00:00Z); bars at 04:00/05:00Z of the session. A naive UTC date shifted every
    book return by a session (caught on the first real run)."""
    import readiness_engine as E
    assert E._stamp_date(1783382400) == "2026-07-06"           # 2026-07-07T00:00Z -> Mon 07-06
    assert E._stamp_date(1782518400) == "2026-06-26"           # Sat 00:00Z -> Fri close
    assert E._stamp_date("2025-12-01T05:00:00Z") == "2025-12-01"
    assert E._stamp_date("2026-07-06T04:00:00Z") == "2026-07-06"


def test_journal_equity_dated_by_et_session(tmp_path):
    import readiness_engine as E
    (tmp_path / "2026-10-22.json").write_text(json.dumps([
        {"timestamp": "2026-10-22T00:00:01+00:00", "mode": "end-of-day", "account": {"equity": 100.0}},
        {"timestamp": "2026-10-22T15:00:00+00:00", "mode": "intraday-monitor", "account": {"equity": 999.0}},
    ]))
    eq, _ = E.equity_from_journals(str(tmp_path))
    assert eq == {"2026-10-21": 100.0}          # EOD written 20:00 ET belongs to 10-21; intraday ignored


# --- v2.1 review fixes (H2, H4, H5, M7, M8, L9, slippage, cron dedup) ------------------

def test_forward_test_can_never_be_go():
    s = R.nyse_sessions("2026-01-01", "2027-12-31")
    v = R.verdict("forward_test", _all_pass_gates(), s, "2026-10-22")
    assert v["verdict"] == "FORWARD_TEST_PASS" and "new registry version" in v["verdict_note"]


def test_no_edge_sleeve_is_beta_sleeve():
    s = R.nyse_sessions("2026-01-01", "2027-12-31")
    assert R.verdict("active", _all_pass_gates(), s, "2026-10-22", claims_edge=False)["verdict"] == "BETA_SLEEVE"
    assert R.verdict("quarantined", _all_pass_gates(), s, "2026-10-22", claims_edge=False)["verdict"] == "NOT_ELIGIBLE"


def test_only_one_sleeve_owns_a_shared_book_series():
    import readiness_engine as E
    a = {"id": "a", "book": "portfolio_2", "start_date": "2026-07-06", "claims_edge": True}
    b = {"id": "b", "book": "portfolio_2", "start_date": "2026-06-02", "claims_edge": True}
    reg = [a, b]
    assert E.edge_ownership(a, reg, "2026-10-22")[:2] == ("book_level_shared", False)   # ambiguous: nobody
    a["owns_book_edge"] = True
    assert E.edge_ownership(a, reg, "2026-10-22")[:2] == ("book_level", True)
    assert E.edge_ownership(b, reg, "2026-10-22")[:2] == ("book_level_shared", False)
    solo = {"id": "c", "book": "portfolio_3", "start_date": "2026-10-23", "claims_edge": True}
    old = {"id": "d", "book": "portfolio_3", "start_date": "2026-05-27", "end_date": "2026-10-03"}
    assert E.edge_ownership(solo, [solo, old], "2026-10-30")[:2] == ("book_level", True)   # no overlap


def test_kill_headroom_uses_live_reference_not_window_peak():
    rets = [0.01] * 30 + [-0.005] * 10            # window peak is mid-window
    kill = {"reference_equity": 100000.0, "current_equity": 86000.0, "kill_drawdown": 0.15,
            "source": "P2 $100K"}
    g = next(x for x in R.risk_gates(rets, kill=kill) if x["id"] == "kill_switch_headroom")
    assert g["status"] == "fail" and abs(g["value"] - 0.01) < 1e-9 and g["reference_equity"] == 100000.0
    import readiness_engine as E
    k2 = E.kill_reference("portfolio_2", 99000.0)
    assert k2["reference_equity"] == 100000.0 and k2["kill_drawdown"] == 0.15


def test_max_drawdown_gates_on_stricter_of_window_and_book():
    window = [0.001] * 20
    book = [-0.02] * 10 + [0.001] * 20             # 18% drawdown before the version started
    g = next(x for x in R.risk_gates(window, book_returns=book) if x["id"] == "max_drawdown")
    assert g["status"] == "fail" and g["value"] == g["book_value"] > g["window_value"]


def test_data_faults_and_flows_are_excluded_never_used():
    s = R.nyse_sessions("2026-07-01", "2026-07-15")
    eq = {d: 100000.0 for d in s}
    eq["2026-07-07"] = 27900.0                      # phantom read
    w = R.window_returns(eq, s, "2026-07-01", "2026-07-15", exclude={"2026-07-13"}, max_abs=0.25)
    assert w["faults"] == ["2026-07-07", "2026-07-08"]
    assert "2026-07-13" in w["excluded"] and "2026-07-13" not in w["dates"]
    assert max(abs(r) for r in w["returns"]) == 0.0


def test_halted_sessions_excluded_from_track_record(tmp_path, monkeypatch):
    import readiness_engine as E
    s = R.nyse_sessions("2026-05-01", "2026-12-31")
    doc = {"book_halts": [{"book": "portfolio_1", "from": "2026-07-07", "to": "2026-10-22"}]}
    monkeypatch.setattr(E, "_load", lambda path, default=None: {} if "state" in str(path) else default)
    halts, unknown = E.halted_sessions("portfolio_1", doc, s, "2026-10-22")
    assert not unknown and min(halts) == "2026-07-07" and max(halts) == "2026-10-22"
    assert len(halts) == R.count_sessions(s, "2026-07-07", "2026-10-22")


def test_idless_rows_are_distinct_orders():
    import readiness_engine as E
    rows = [{"symbol": "X", "side": "buy", "timestamp": "2026-08-03T15:00:00Z", "status": "closed"},
            {"symbol": "X", "side": "buy", "timestamp": "2026-08-03T16:00:00Z", "status": "closed"}]
    assert E.duplicate_entries(rows) == (1, 1)


def test_slippage_only_against_an_arrival_reference():
    import readiness_engine as E
    p2 = [{"symbol": "KR", "side": "buy", "intended_price": 56.58, "limit_price": 56.58,
           "entry_price": 56.5, "order_id": "1", "timestamp": "2026-08-10T15:00:00Z"}]
    assert E.slippage_for_sleeve("p2-copy-v2", p2)["status"] == "not_measured"
    alloc = [{"symbol": "CTA", "side": "buy", "intended_price": 30.48, "limit_price": 30.64,
              "entry_price": 30.56, "order_id": "a", "timestamp": "2026-10-23T14:11:00Z"},
             {"symbol": "SPY", "side": "buy", "intended_price": 762.4, "limit_price": 762.4,
              "entry_price": 760.0, "order_id": "b", "timestamp": "2026-10-23T14:11:00Z"}]
    g = E.slippage_for_sleeve("p3-crisis-core-v1-forward", alloc)
    assert abs(g["value"] - (30.56 - 30.48) / 30.48 * 1e4) < 0.01   # limit-ref row skipped
    assert g["status"] == "fail"                                     # 26 bps > 15 bps


def test_cron_dedup_only_when_todays_session_is_complete():
    import readiness_engine as E
    v = R.METHODOLOGY_VERSION
    full = {"as_of_session": "2026-10-23", "methodology_version": v,
            "books": {"p": {"equity_source": "alpaca", "last_date": "2026-10-23"}}}
    lagging = {"as_of_session": "2026-10-23", "methodology_version": v,
               "books": {"p": {"equity_source": "alpaca", "last_date": "2026-10-22"}}}
    assert E.report_is_current(full, "2026-10-23", "2026-10-23") is True
    assert E.report_is_current(lagging, "2026-10-23", "2026-10-23") is False   # 19:45 retry must run
    assert E.report_is_current(full, "2026-10-22", "2026-10-23") is False


# --- v2.2 two-stage path (research proof + live incubation) --------------------

def _lab_result(overall="PASS", dd=0.10, sr=0.8, vol=0.09, sha="a" * 64):
    return {"spec_sha256": sha, "spec_path": "docs/specs/x.json",
            "acceptance": {"C1": "PASS" if overall == "PASS" else "FAIL", "overall": overall},
            "main": {"sharpe_excess": sr, "vol": vol, "drawdown": {"max_drawdown": dd}}}


CFG = {"artifact": "data/strategy_lab_results.json", "result_key": "x"}


def test_research_gate_never_passes_without_a_registered_result():
    g, prof = R.research_gate(None, None, None)
    assert g["status"] == "not_measured" and prof is None and g["hard"] is False
    g, _ = R.research_gate(CFG, None, "a" * 64)
    assert g["status"] == "not_measured"


def test_research_gate_voids_a_result_whose_spec_changed():
    g, prof = R.research_gate(CFG, _lab_result(), "b" * 64)
    assert g["status"] == "fail" and "mismatch" in g["detail"] and prof is None


def test_research_gate_fails_on_acceptance_or_drawdown():
    g, prof = R.research_gate(CFG, _lab_result(overall="FAIL"), "a" * 64)
    assert g["status"] == "fail" and prof is not None   # profile kept for display only
    g, _ = R.research_gate(CFG, _lab_result(dd=0.148), "a" * 64)  # artifact PASS but DD > 12%
    assert g["status"] == "fail" and "max DD" in g["detail"]
    g, _ = R.research_gate(CFG, _lab_result(sr=-0.1), "a" * 64)
    assert g["status"] == "fail"


def test_research_gate_passes_a_clean_preregistered_result():
    g, prof = R.research_gate(CFG, _lab_result(), "a" * 64)
    assert g["status"] == "pass" and prof["sharpe_excess"] == 0.8 and prof["max_drawdown"] == 0.10


def _incubation_series(n, sharpe, vol=0.09, seed=3, rf=0.00015):
    rng = random.Random(seed)
    sd = vol / math.sqrt(252)
    mu = sharpe / math.sqrt(252) * sd
    return [rf + rng.gauss(mu, sd) for _ in range(n)], [rf] * n


PROFILE = {"sharpe_excess": 0.8, "vol": 0.09, "max_drawdown": 0.10, "source": "t"}


def test_incubation_waits_for_its_minimum_and_projects_an_eta():
    r, f = _incubation_series(40, 0.8)
    g = R.incubation_gate(r, f, PROFILE)
    assert g["status"] == "insufficient" and g["eta_sessions"] == 20
    assert R.incubation_gate(r, f, None)["status"] == "not_applicable"


def test_incubation_passes_a_book_that_behaves_like_its_backtest():
    r, f = _incubation_series(90, 0.8)
    g = R.incubation_gate(r, f, PROFILE)
    assert g["status"] == "pass", g["detail"]


def test_incubation_fails_a_book_not_running_the_tested_strategy():
    r, f = _incubation_series(90, 0.8, vol=0.25)          # ~2.8x the backtest vol
    g = R.incubation_gate(r, f, PROFILE)
    assert g["status"] == "fail" and g["value"]["checks"]["vol_ratio_in_band"] is False


def test_incubation_fails_a_book_significantly_worse_than_its_backtest():
    r, f = _incubation_series(250, -3.0)                  # deep, persistent bleed
    g = R.incubation_gate(r, f, PROFILE)
    assert g["status"] == "fail" and g["value"]["checks"]["sharpe_not_contradicted"] is False


def test_incubation_false_fail_rate_is_bounded_under_the_haircut_null():
    # True live Sharpe = exactly haircut x backtest: the always-valid bound may
    # wrongly flag it at most ~incubation_alpha of the time.
    fails = 0
    for seed in range(200):
        r, f = _incubation_series(90, 0.5 * PROFILE["sharpe_excess"], seed=seed)
        g = R.incubation_gate(r, f, {**PROFILE, "max_drawdown": 1.0})
        fails += not g["value"]["checks"]["sharpe_not_contradicted"]
    assert fails / 200 <= R.THRESHOLDS["incubation_alpha"]


def _gates_all_pass_except(edge_status):
    g = [R.gate("track_record", "t", "", 90, "pass"), R.gate("edge", "e", "", None, edge_status),
         R.gate("max_drawdown", "d", "", 0.05, "pass")]
    return g


def test_two_stage_path_reaches_go_without_a_live_edge_proof():
    import readiness_engine as E
    gates = _gates_all_pass_except("insufficient")
    res = R.gate("research", "r", "", None, "pass", hard=False)
    inc = R.gate("incubation_consistency", "i", "", None, "pass", hard=False)
    path = E.select_path(True, True, gates[1], res, inc)
    assert path == "two_stage" and gates[1]["hard"] is False and res["hard"] and inc["hard"]
    v = R.verdict("active", gates + [res, inc], R.nyse_sessions("2026-01-01", "2027-12-31"), "2026-10-22")
    assert v["verdict"] == "GO"


def test_two_stage_path_blocked_by_failed_incubation_or_research():
    import readiness_engine as E
    sessions = R.nyse_sessions("2026-01-01", "2027-12-31")
    gates = _gates_all_pass_except("insufficient")
    res = R.gate("research", "r", "", None, "pass", hard=False)
    inc = R.gate("incubation_consistency", "i", "", None, "fail", hard=False)
    E.select_path(True, True, gates[1], res, inc)
    assert R.verdict("active", gates + [res, inc], sessions, "2026-10-22")["verdict"] == "NOT_READY"
    gates = _gates_all_pass_except("insufficient")
    res = R.gate("research", "r", "", None, "fail", hard=False)
    inc = R.gate("incubation_consistency", "i", "", None, "pass", hard=False)
    assert E.select_path(True, True, gates[1], res, inc) == "live_edge"
    assert R.verdict("active", gates + [res, inc], sessions, "2026-10-22")["verdict"] == "NOT_READY"


def test_two_stage_never_applies_to_shared_series_or_forward_tests():
    import readiness_engine as E
    sessions = R.nyse_sessions("2026-01-01", "2027-12-31")
    gates = _gates_all_pass_except("not_measured")
    res = R.gate("research", "r", "", None, "pass", hard=False)
    inc = R.gate("incubation_consistency", "i", "", None, "pass", hard=False)
    assert E.select_path(True, False, gates[1], res, inc) == "live_edge"   # does not own the series
    gates = _gates_all_pass_except("insufficient")
    E.select_path(True, True, gates[1], res, inc)
    assert R.verdict("forward_test", gates + [res, inc], sessions, "2026-10-22")["verdict"] == "FORWARD_TEST_PASS"


# --- review round 2026-10-23: exposure-based attribution + predictable CS ------

def test_exposure_lasts_until_the_last_lot_exits():
    import readiness_engine as E
    leg = {"id": "p3-event-driven-legacy", "book": "portfolio_3",
           "start_date": "2026-05-27", "end_date": "2026-10-03"}
    open_lot = [{"symbol": "KO", "status": "open", "timestamp": "2026-09-30T14:00:00Z"}]
    closed = [{"symbol": "KO", "status": "closed", "timestamp": "2026-09-30T14:00:00Z",
               "exit_timestamp": "2026-10-15T15:00:00Z"}]
    assert E.exposure_end(leg, open_lot, "2026-10-30") == "2026-10-30"          # still exposed
    assert E.exposure_end(leg, closed, "2026-10-30") == "2026-10-15"            # last exit
    assert E.exposure_end(leg, None, "2026-10-30") == "2026-10-30"              # unknown => exposed
    assert E.exposure_end({**leg, "id": "no-selector"}, closed, "2026-10-30") == "2026-10-30"
    assert E.exposure_end({**leg, "end_date": None}, closed, "2026-10-30") == "2026-10-30"


def test_open_legacy_lots_keep_a_new_sleeve_off_the_book_edge():
    import readiness_engine as E
    new = {"id": "p3-crisis-core-v1-forward", "book": "portfolio_3", "start_date": "2026-10-23", "claims_edge": True}
    leg = {"id": "p3-event-driven-legacy", "book": "portfolio_3", "start_date": "2026-05-27",
           "end_date": "2026-10-03", "claims_edge": True}
    reg = [new, leg]
    # Lots still open: the new sleeve may NOT claim the whole book's returns.
    assert E.edge_ownership(new, reg, "2026-10-30", {leg["id"]: "2026-10-30"})[:2] == ("book_level_shared", False)
    # The legacy sleeve's own evidence window (to 10-03) never overlapped the new one.
    assert E.edge_ownership(leg, reg, "2026-10-30", {leg["id"]: "2026-10-30", new["id"]: "2026-10-30"})[:2] \
        == ("book_level", True)
    # All legacy lots exited before the new sleeve started: it owns the series again.
    assert E.edge_ownership(new, reg, "2026-10-30", {leg["id"]: "2026-10-15"})[:2] == ("book_level", True)


def test_predictable_cs_uses_only_past_information():
    y, x, _ = _series(300, 0.0, seed=11)
    full = R.predictable_cs(y, x, 252, 0.05)
    # Rewriting the LAST return cannot change how earlier increments were scaled:
    # only the last increment's own value moves the sum.
    y2 = y[:-1] + [y[-1] + 0.05]
    moved = R.predictable_cs(y2, x, 252, 0.05)
    assert moved["m"] == full["m"]
    assert abs((moved["upper"] - moved["lower"]) - (full["upper"] - full["lower"])) < 1e-12


def test_predictable_cs_holds_its_level_through_a_volatility_jump():
    # Zero alpha; residual vol 5% for a year, then 30% (the regime shift that
    # broke an expanding-only scale). Daily-ish looks must stay below level.
    a = R.family_alpha_level(6)
    false_go = 0
    for seed in range(40):
        rng = random.Random(1000 + seed)
        y, x = [], []
        for t in range(756):
            mk = rng.gauss(0.0004, 0.01)
            x.append(mk)
            y.append(0.5 * mk + rng.gauss(0, (0.05 if t < 252 else 0.30) / 16))
        for n in range(60, 757, 20):
            lo = R.predictable_cs(y[:n], x[:n], 252, a)["lower"]
            if lo is not None and lo > 0:
                false_go += 1
                break
    assert false_go <= 1


# --- chart series (readiness page draws these; it computes nothing itself) -----

def test_cs_path_ends_at_the_decision_bounds_and_uses_only_the_past():
    y, x, _ = _series(200, 0.0004, seed=5)
    th = R.THRESHOLDS
    full = R.predictable_cs(y, x, 252, 0.05, path=True)
    assert full["path"], "a path is recorded"
    t_last, lo, hi, pt = full["path"][-1]
    assert t_last == len(y) - 1 and lo == full["lower"] and hi == full["upper"] and pt == full["point"]
    # Every path point equals the decision the engine would have made stopping there.
    for t, lo_t, hi_t, _pt in full["path"][::37]:
        pre = R.predictable_cs(y[:t + 1], x[:t + 1], 252, 0.05)
        assert abs(pre["lower"] - lo_t) < 1e-12 and abs(pre["upper"] - hi_t) < 1e-12
    assert th["cs_burn_in"] == 20


def test_chart_series_compounds_and_drawdown_is_peak_relative():
    s = R.chart_series(["d1", "d2", "d3"], [0.10, -0.10, 0.05], {"d1": 0.01, "d3": 0.02})
    assert s["cum_return"] == [0.1, round(1.1 * 0.9 - 1, 5), round(1.1 * 0.9 * 1.05 - 1, 5)]
    assert s["drawdown"][0] == 0.0 and s["drawdown"][1] == round(0.99 / 1.1 - 1, 5)
    # A missing benchmark day is a gap, never an invented 0% return.
    assert s["benchmark_cum"] == [0.01, None, round(1.01 * 1.02 - 1, 5)]
    assert s["benchmark_missing"] == ["d2"]

# --- review round 2 (Codex on PR #105) -----------------------------------------

def test_near_flat_burn_in_cannot_give_one_return_unbounded_weight():
    # Codex counterexample: 20 alternating +/-1e-8 returns, one -1% return, 39
    # zeros. An ordinary t-statistic is ~ -1; without a scale floor the CS upper
    # bound went negative and the incubation Sharpe check FAILED on one return.
    y = [1e-8 if i % 2 else -1e-8 for i in range(20)] + [-0.01] + [0.0] * 39
    th = R.THRESHOLDS
    up = R.predictable_cs(y, [0.0] * 60, th["cs_rho_sessions"], th["incubation_alpha"], fit_beta=False,
                          sigma_floor=th["cs_sigma_floor_daily"])["upper"]
    assert up is not None and up > 0
    g = R.incubation_gate(y, [0.0] * 60, {"sharpe_excess": 0.0, "vol": 0.05, "max_drawdown": 0.1})
    assert g["value"]["checks"]["sharpe_not_contradicted"] is True


def test_status_less_legacy_lot_counts_as_open_exposure():
    import readiness_engine as E
    leg = {"id": "p3-event-driven-legacy", "book": "portfolio_3",
           "start_date": "2026-05-27", "end_date": "2026-10-03"}
    rows = [{"symbol": "KO", "side": "buy", "timestamp": "2026-09-30T14:00:00Z"}]   # no status => open
    assert E.exposure_end(leg, rows, "2026-10-30") == "2026-10-30"
    marker = [{"symbol": "KO", "side": "sell", "timestamp": "2026-09-30T14:00:00Z"}]  # P2-style exit marker
    assert E.exposure_end(leg, marker, "2026-10-30") == "2026-10-03"


def test_edge_eta_scale_respects_the_decision_floor():
    # Tiny residual vol: the ETA must project on the FLOORED scale the test uses.
    y, x, f = _series(80, 0.0001, noise=0.0001, seed=9)
    e = R.edge_test(y, x, f, 1)
    assert e["sigma_eff_daily"] >= R.THRESHOLDS["cs_sigma_floor_daily"]
    assert R.METHODOLOGY_VERSION == "2.3.0"
