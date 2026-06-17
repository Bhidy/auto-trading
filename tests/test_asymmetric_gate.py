"""Phase-1 C5: the self-learning gate must be ASYMMETRIC — gate ADDING risk,
never gate REMOVING it. A losing book must de-risk immediately (ungated), even
when walk-forward validation rejects, because capital preservation is the prior.
"""
import json
from datetime import datetime, timezone

import performance_tracker as pt
from performance_tracker import _is_risk_increasing as ri


def test_is_risk_increasing_directions():
    assert ri("position_size_multiplier", 1.0, 1.2) is True      # bigger size
    assert ri("position_size_multiplier", 1.0, 0.8) is False     # smaller size = de-risk
    assert ri("confidence_buy_threshold", 0.50, 0.45) is True    # lower bar = more trades
    assert ri("confidence_buy_threshold", 0.50, 0.55) is False   # higher bar = de-risk
    assert ri("trailing_stop_atr_mult", 2.5, 3.0) is True        # wider stop = more risk
    assert ri("trailing_stop_atr_mult", 2.5, 2.0) is False       # tighter = de-risk
    assert ri("rsi_overbought", 70, 72) is True                  # unknown knob -> gated
    assert ri("position_size_multiplier", 1.0, 1.0) is False     # no change


def _seed_losing(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "DATA_DIR", str(tmp_path))
    knobs = {"ma_fast": 50, "ma_slow": 200, "position_size_multiplier": 1.0,
             "rsi_overbought": 70, "trailing_stop_atr_mult": 2.5,
             "confidence_buy_threshold": 0.50}
    (tmp_path / "strategy_params.json").write_text(json.dumps(knobs))
    now = datetime.now(timezone.utc).isoformat()
    # 2 small winners + 6 losers -> pf=100/600=0.17 (<1.0), wr=0.25, 8 trades.
    log = [{"id": i, "symbol": "AAA", "status": "closed", "pnl": 50.0,
            "pnl_pct": 1.5, "exit_timestamp": now, "reasons": []} for i in range(2)]
    log += [{"id": 100 + i, "symbol": "AAA", "status": "closed", "pnl": -100.0,
             "pnl_pct": -3.0, "exit_timestamp": now, "reasons": []} for i in range(6)]
    (tmp_path / "trade_log.json").write_text(json.dumps(log))


def test_losing_book_derisks_and_sticks_even_when_gate_rejects(tmp_path, monkeypatch):
    _seed_losing(tmp_path, monkeypatch)
    import backtest.walk_forward as wf
    monkeypatch.setattr(wf, "gate_param_change",
                        lambda *a, **k: (False, {"reason": "worse OOS"}))

    out = pt.adapt_parameters(validate_with_bars=({"AAA": []}, []))
    p = out["updated_params"]
    assert p["risk_off_active"] is True
    assert p["position_size_multiplier"] < 1.0          # size cut (de-risk)
    assert p["confidence_buy_threshold"] > 0.50          # entry bar raised (de-risk)
    # De-risk PERSISTS to disk despite the rejecting gate.
    saved = json.loads((tmp_path / "strategy_params.json").read_text())
    assert saved["position_size_multiplier"] < 1.0
    assert saved["confidence_buy_threshold"] > 0.50


def test_winning_book_does_not_flag_risk_off(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "DATA_DIR", str(tmp_path))
    (tmp_path / "strategy_params.json").write_text(json.dumps(
        {"position_size_multiplier": 1.0, "confidence_buy_threshold": 0.50,
         "rsi_overbought": 70, "trailing_stop_atr_mult": 2.5}))
    now = datetime.now(timezone.utc).isoformat()
    (tmp_path / "trade_log.json").write_text(json.dumps(
        [{"id": i, "symbol": "AAA", "status": "closed", "pnl": 100.0, "pnl_pct": 2.0,
          "exit_timestamp": now, "reasons": []} for i in range(10)]))
    out = pt.adapt_parameters()
    assert out["updated_params"]["risk_off_active"] is False
