"""Tests for the ADVISORY HRP tilt consumer in portfolio_manager.

Off by default (no live effect); when on, weights are clamped to the single-name
cap with the remainder routed to cash (never renormalized back over the cap).
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from portfolio_manager import hrp_advisory_tilts  # noqa: E402

_LIMITS = {"max_single_position_pct": {"stock": 8, "etf": 12, "crypto": 5, "penny": 1}}


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HRP_TILTS_ENABLED", raising=False)
    res = hrp_advisory_tilts()
    assert res["enabled"] is False
    assert res["weights"] is None          # zero effect on allocation


def test_enabled_via_env(monkeypatch, tmp_path):
    monkeypatch.setenv("HRP_TILTS_ENABLED", "1")
    res = hrp_advisory_tilts(hrp_path=str(tmp_path / "missing.json"))
    assert res["enabled"] is True
    assert res["weights"] is None          # enabled but no artifact -> still no effect


def test_clamps_to_single_name_cap_and_routes_remainder_to_cash(tmp_path):
    art = {"weights": {"A": 0.50, "B": 0.30, "C": 0.20},
           "generated_at": "2026-06-02T00:00:00Z", "shrinkage_delta": 0.5}
    p = tmp_path / "hrp.json"
    p.write_text(json.dumps(art))
    res = hrp_advisory_tilts(enabled=True, hrp_path=str(p), limits=_LIMITS)
    w = res["weights"]
    # 8% cap -> every name clamped to 0.08; remainder (1 - 0.24) -> cash.
    assert all(v <= 0.08 + 1e-9 for v in w.values())
    assert w == {"A": 0.08, "B": 0.08, "C": 0.08}
    assert res["cash_residual"] == round(1 - 0.24, 6)


def test_small_weights_pass_through_unclamped(tmp_path):
    # Realistic HRP artifact: every weight already under the cap -> unchanged.
    art = {"weights": {"BIL": 0.068, "SHY": 0.067, "TLT": 0.066, "SPY": 0.058}}
    p = tmp_path / "hrp.json"
    p.write_text(json.dumps(art))
    res = hrp_advisory_tilts(enabled=True, hrp_path=str(p), limits=_LIMITS)
    assert res["weights"] == {"BIL": 0.068, "SHY": 0.067, "TLT": 0.066, "SPY": 0.058}
    assert all(v <= 0.08 for v in res["weights"].values())
