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
    assert full["status"] == "pass" and full["alpha_daily"] > 0 and full["dsr"] >= 0.95
    assert abs(full["beta"] - 0.5) < 0.05
    early = R.edge_test(b[:40], m[:40], f[:40], trial_count=34)
    assert early["status"] == "insufficient"          # n < 60, whatever the numbers say


def test_zero_alpha_is_insufficient_then_fail():
    b, m, f = _series(600, 0.0, seed=5)
    assert R.edge_test(b[:30], m[:30], f[:30], 34)["status"] == "insufficient"
    assert R.edge_test(b, m, f, 34)["status"] == "fail"


def test_negative_alpha_is_not_converging():
    b, m, f = _series(200, -0.0006, seed=9)
    e = R.edge_test(b, m, f, 34)
    assert e["status"] == "fail" and e["alpha_daily"] < 0
    eta = R.edge_eta(e)
    assert eta["state"] == "not_converging" and eta["sessions_remaining"] is None


def test_trial_count_deflates():
    b, m, f = _series(300, 0.0006, seed=4)
    assert R.edge_test(b, m, f, 1)["dsr"] > R.edge_test(b, m, f, 40)["dsr"]
    assert R.z_required(1) < R.z_required(34) < R.z_required(40)


def test_eta_monotonic():
    def eta(n, alpha, sig=0.003, trials=34):
        e = {"status": "fail", "n": n, "alpha_daily": alpha, "sigma_eff_daily": sig,
             "z_required": R.z_required(trials)}
        return R.edge_eta(e)
    rem = [eta(n, 0.0004)["sessions_remaining"] for n in (60, 100, 150, 200)]
    assert all(a >= b for a, b in zip(rem, rem[1:]))                     # more data -> sooner
    assert eta(60, 0.0008)["n_required"] < eta(60, 0.0004)["n_required"]  # bigger alpha -> sooner
    assert eta(60, 0.0004, trials=40)["n_required"] > eta(60, 0.0004, trials=1)["n_required"]
    assert eta(10, 0.0004)["state"] == "too_early"


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
        assert s["verdict"] in ("GO", "NOT_READY", "NOT_ELIGIBLE")
        assert {"start", "end", "trading_days"} <= set(s["window"])
        assert {"alpha", "beta", "t_hac", "ir", "psr", "dsr", "n"} <= set(s["edge"])
        if s["status"] in ("exits_only", "quarantined"):
            assert s["verdict"] == "NOT_ELIGIBLE"
        ex = next(g for g in s["gates"] if g["id"] == "exception_free")
        assert ex["status"] == "not_measured"            # offline: never a default pass
        assert s["verdict"] != "GO"
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
