"""End-to-end: the self-learning loop must REVERT a strategy-knob change when
walk-forward validation rejects it (no tuning on noise)."""
import json
from datetime import datetime, timezone

import performance_tracker as pt


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "DATA_DIR", str(tmp_path))
    knobs = {
        "ma_fast": 50, "ma_slow": 200,
        "position_size_multiplier": 1.0,
        "rsi_overbought": 70,
        "trailing_stop_atr_mult": 2.5,
        "confidence_buy_threshold": 0.50,
    }
    (tmp_path / "strategy_params.json").write_text(json.dumps(knobs))
    # 10 recent closed WINNERS -> wr_30d=1.0 (>0.55) -> code lowers
    # confidence_buy_threshold by 0.02 (a knob change to be gated).
    now = datetime.now(timezone.utc).isoformat()
    log = [{
        "id": i, "symbol": "AAA", "status": "closed",
        "pnl": 100.0, "pnl_pct": 2.0,
        "exit_timestamp": now, "reasons": [],
    } for i in range(10)]
    (tmp_path / "trade_log.json").write_text(json.dumps(log))
    return knobs


def test_gate_rejection_reverts_knob(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    import backtest.walk_forward as wf
    monkeypatch.setattr(wf, "gate_param_change",
                        lambda *a, **k: (False, {"reason": "worse OOS"}))

    out = pt.adapt_parameters(validate_with_bars=({"AAA": []}, []))
    # Rejected -> confidence_buy_threshold reverted to the original 0.50.
    assert out["updated_params"]["confidence_buy_threshold"] == 0.50
    assert out["walk_forward_gate"] == {"reason": "worse OOS"}
    # Persisted file also reverted.
    saved = json.loads((tmp_path / "strategy_params.json").read_text())
    assert saved["confidence_buy_threshold"] == 0.50


def test_gate_approval_keeps_knob(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    import backtest.walk_forward as wf
    monkeypatch.setattr(wf, "gate_param_change",
                        lambda *a, **k: (True, {"approved": True}))

    out = pt.adapt_parameters(validate_with_bars=({"AAA": []}, []))
    # Approved -> the lowered threshold (0.48) is kept.
    assert out["updated_params"]["confidence_buy_threshold"] == 0.48


def test_no_bars_preserves_legacy_behavior(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    # Without bars, no gating: the knob change applies (bounded legacy path).
    out = pt.adapt_parameters()
    assert out["updated_params"]["confidence_buy_threshold"] == 0.48
    assert out["walk_forward_gate"] is None
