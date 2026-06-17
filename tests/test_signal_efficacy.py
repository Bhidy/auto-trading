"""Phase-3 C1: the signal-efficacy diagnostic — does the entry score predict
outcome? It is the gate metric any entry re-fit must flip to a significant
POSITIVE correlation. Pure-stdlib correlation + significance + N-floor."""
import json

import pytest

from research.signal_efficacy import _pearson, _spearman, build_diagnostic


def test_pearson_perfect_and_inverse():
    assert _pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert _pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)


def test_spearman_monotonic_nonlinear():
    # Spearman = 1 for any increasing relationship, even nonlinear.
    assert _spearman([1, 2, 3, 4], [1, 4, 9, 16]) == pytest.approx(1.0)


def _write(tmp_path, pairs):
    log = [{"status": "closed", "signal_score": s, "pnl_pct": r} for s, r in pairs]
    p = tmp_path / "trade_log.json"
    p.write_text(json.dumps(log))
    return str(p)


def test_positive_edge_detected(tmp_path):
    pairs = [(0.5 + i * 0.01, (0.5 + i * 0.01 - 0.7) * 40 + (i % 3 - 1) * 0.1)
             for i in range(40)]
    out = build_diagnostic(min_sample=30, log_path=_write(tmp_path, pairs))
    assert out["verdict"] == "POSITIVE_EDGE"
    assert out["pearson_r"] > 0 and out["significant_at_5pct"] is True


def test_negative_edge_detected(tmp_path):
    pairs = [(0.5 + i * 0.01, -(0.5 + i * 0.01 - 0.7) * 40 + (i % 3 - 1) * 0.1)
             for i in range(40)]
    out = build_diagnostic(min_sample=30, log_path=_write(tmp_path, pairs))
    assert out["verdict"] == "NEGATIVE_EDGE"
    assert out["pearson_r"] < 0


def test_insufficient_data_refuses(tmp_path):
    pairs = [(0.6, 1.0), (0.7, -1.0)] * 5   # 10 trades < floor 30
    out = build_diagnostic(min_sample=30, log_path=_write(tmp_path, pairs))
    assert out["verdict"] == "INSUFFICIENT_DATA"
    assert out["n"] == 10


def test_real_p1_log_is_measured_honestly():
    out = build_diagnostic()   # the real committed P1 trade log
    assert out["n"] >= 30
    assert out["verdict"] in ("NO_EDGE", "NEGATIVE_EDGE", "POSITIVE_EDGE")
    assert out["pearson_r"] is not None and "terciles" in out
