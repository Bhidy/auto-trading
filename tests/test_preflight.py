"""Tests for shared.preflight — the pre-trade self-check that fails CLOSED.

The 2026-06-01 incident shipped broken sizing to production. The canary here would
have caught it before a single order. These tests lock the canary, the param-bounds
clamp (the one allowed auto-remediation), account/risk-limit sanity, and — crucially
— that the REAL P1/P2/P3 configs all pass (a false fail-closed would halt trading).
"""
import json
import os

from shared.preflight import run_preflight

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GOOD_ACCOUNT = {"status": "ACTIVE", "trading_blocked": False,
                "account_blocked": False, "equity": "100000"}
GOOD_PARAMS = {"atr_risk_target_pct": 1.0, "trailing_stop_atr_mult": 2.5,
               "position_size_multiplier": 1.0}
P1_LIMITS = {"max_daily_loss_pct": 4.0, "kill_switch_drawdown_pct": 18.0,
             "max_single_position_pct": {"etf": 12.0, "stock": 8.0, "crypto": 5.0}}


def _broken_sizing(*_a, **_k):
    """Simulates the *100 bug: every size comes out ~100x too small."""
    return 0.2


def test_healthy_preflight_passes():
    ok, r = run_preflight(limits=P1_LIMITS, account=GOOD_ACCOUNT, params=GOOD_PARAMS,
                          sizing_canary=True, crypto_canary=True, data_fresh=True)
    assert ok is True
    assert r["hard_failures"] == []
    assert r["checks"]["sizing_canary"]["ok"] is True


def test_canary_catches_reintroduced_100x_bug():
    ok, r = run_preflight(limits=P1_LIMITS, account=GOOD_ACCOUNT, params=GOOD_PARAMS,
                          sizing_canary=True, sizing_fn=_broken_sizing)
    assert ok is False
    assert any("CANARY" in f for f in r["hard_failures"])


def test_param_clamp_is_the_one_remediation():
    ok, r = run_preflight(limits=P1_LIMITS, account=GOOD_ACCOUNT,
                          params={**GOOD_PARAMS, "position_size_multiplier": 5.0},
                          sizing_canary=True, data_fresh=True)
    assert ok is True  # clamp is non-blocking remediation
    assert r["clamped_params"]["position_size_multiplier"] == 1.5
    assert any("position_size_multiplier" in w for w in r["warnings"])


def test_blocked_account_fails_closed():
    ok, r = run_preflight(limits=P1_LIMITS, account={**GOOD_ACCOUNT, "trading_blocked": True})
    assert ok is False
    assert any("trading_blocked" in f for f in r["hard_failures"])


def test_zero_equity_fails_closed():
    ok, _ = run_preflight(limits=P1_LIMITS, account={**GOOD_ACCOUNT, "equity": "0"})
    assert ok is False


def test_corrupt_risk_limit_fails_closed():
    bad = {**P1_LIMITS, "max_daily_loss_pct": 50.0}   # > 25 corruption bound
    ok, r = run_preflight(limits=bad, account=GOOD_ACCOUNT)
    assert ok is False
    assert any("max_daily_loss_pct" in f for f in r["hard_failures"])


def test_stale_data_fails_closed():
    ok, r = run_preflight(limits=P1_LIMITS, account=GOOD_ACCOUNT, params=GOOD_PARAMS,
                          sizing_canary=True, data_fresh=False)
    assert ok is False
    assert any("stale" in f.lower() for f in r["hard_failures"])


def test_crypto_canary_failure_is_warning_not_hard_fail():
    """A crypto sizing regression must NOT block equity trading — warning only.
    Use a fn that sizes equity ($100) fine but returns dust for crypto ($100k)."""
    def crypto_broken(_atr, price, *_a, **_k):
        return 0.0 if price > 1000 else 11.0
    ok, r = run_preflight(limits=P1_LIMITS, account=GOOD_ACCOUNT, params=GOOD_PARAMS,
                          sizing_canary=True, crypto_canary=True, data_fresh=True,
                          sizing_fn=crypto_broken)
    assert ok is True                                   # equity canary passed
    assert r["checks"]["crypto_canary"]["ok"] is False
    assert any("crypto" in w.lower() for w in r["warnings"])
    assert not any("crypto" in f.lower() for f in r["hard_failures"])


def test_real_configs_do_not_false_block():
    candidates = [
        ("config/risk_limits.json", "portfolio_1"),
        ("event-driven-bot/config/risk_limits.json", "portfolio_3"),
        ("political-copy-bot/config/risk_limits.json", "portfolio_2"),
    ]
    for path, pid in candidates:
        full = os.path.join(REPO, path)
        if not os.path.exists(full):
            continue
        with open(full) as f:
            limits = json.load(f)
        ok, r = run_preflight(limits=limits, account=GOOD_ACCOUNT, portfolio_id=pid)
        assert ok is True, f"{pid} false-blocked: {r['hard_failures']}"
