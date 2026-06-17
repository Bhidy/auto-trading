"""Tests for the deferred-item research artifacts (offline T2 lane):
P2 disclosure-lag study, options-sleeve feasibility, event-context evidence.

Covers BOTH the honest refuse-on-thin-data verdict on the real logs AND that the
PBO/DSR machinery genuinely activates on a sufficient synthetic sample — i.e. the
scripts are real research engines, not stubs that always refuse.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from research.event_context_backtest import build_evidence  # noqa: E402
from research.options_sleeve_spec import build_feasibility, build_spec  # noqa: E402
from research.p2_disclosure_lag_study import (  # noqa: E402
    build_study,
    reconstruct_round_trips,
)


# --- Options sleeve -------------------------------------------------------

def test_options_spec_conforms_to_validator():
    from backtest.strategy_spec import validate_spec
    ok, errors = validate_spec(build_spec())
    assert ok, errors


def test_options_feasibility_is_no_go_and_gated():
    feas = build_feasibility(build_spec())
    assert feas["verdict"] == "NO_GO"
    # The two structural blockers must be present; sizing must fit inside the caps.
    assert "equity_book_live_ready" in feas["blocking_gates"]
    assert "pure_python_options_data_path" in feas["blocking_gates"]
    gates = {g["gate"]: g["pass"] for g in feas["gates"]}
    assert gates["sizing_within_caps"] is True
    assert gates["defined_risk_only"] is True


# --- P2 disclosure-lag ----------------------------------------------------

def test_p2_refuses_on_real_thin_data():
    study = build_study(min_sample_n=30)
    assert study["verdict"] == "REFUSE_TO_ASSERT"
    assert study["n_round_trips"] < 30
    assert "data_needed" in study


def test_reconstruct_round_trips_fifo():
    log = [
        {"symbol": "AAA", "side": "buy", "entry_price": 100.0},
        {"symbol": "AAA", "side": "sell", "exit_price": 110.0},
        {"symbol": "BBB", "side": "buy", "entry_price": 50.0},  # never closed
    ]
    trips = reconstruct_round_trips(log)
    assert len(trips) == 1
    assert abs(trips[0]["ret"] - 0.10) < 1e-9


def test_p2_machinery_activates_on_sufficient_sample(tmp_path):
    rets = [0.01, 0.02, -0.005, 0.015, 0.008, -0.01, 0.025, 0.003]
    log = []
    for i in range(40):
        base = 100.0
        r = rets[i % len(rets)]
        log.append({"symbol": f"S{i}", "side": "buy", "entry_price": base,
                    "date": f"2026-01-{(i % 27) + 1:02d}", "disclosure_age_days": (i * 7) % 60})
        log.append({"symbol": f"S{i}", "side": "sell", "exit_price": base * (1 + r),
                    "date": f"2026-02-{(i % 27) + 1:02d}"})
    p = tmp_path / "p2_log.json"
    p.write_text(json.dumps(log))

    study = build_study(min_sample_n=30, log_path=str(p))
    # It must NOT refuse, and it must produce real PBO/DSR numbers (proof it is not a stub).
    assert study["verdict"] in ("GO", "NO_GO")
    assert study["n_round_trips"] == 40
    assert study["pbo"] is not None
    assert study["deflated_sharpe"] is not None
    assert study["best_combo"] is not None
    # The inert holding_days dimension must NOT reappear; the reported Sharpe is annualized.
    assert "holding_days" not in study["best_combo"]
    assert "sharpe_annualized" in study["best_combo"]


# --- Event-context evidence ----------------------------------------------

def test_event_context_refuses_without_labels():
    ev = build_evidence()
    assert ev["verdict"] == "REFUSE_TO_ASSERT"
    assert ev["labels_available"] is False
    # It still reads real closed trades (machinery works) and defines the forward test.
    assert ev["closed_trade_stats"]["portfolio_1"]["n_closed"] > 0
    assert "forward_metric" in ev and ev["forward_metric"]["needs"]
