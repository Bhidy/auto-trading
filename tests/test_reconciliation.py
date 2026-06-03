"""Tests for the read-only EOD position-vs-trade-log reconciliation audit."""
import json
import types

import autonomous_runner as ar


def _alpaca(position_symbols):
    return types.SimpleNamespace(
        get_positions=lambda: [{"symbol": s} for s in position_symbols]
    )


def _seed_trade_log(tmp_path, monkeypatch, entries):
    monkeypatch.setattr(ar, "DATA_DIR", tmp_path)
    (tmp_path / "trade_log.json").write_text(json.dumps(entries))


def test_in_sync_when_positions_match_open_trades(tmp_path, monkeypatch):
    _seed_trade_log(tmp_path, monkeypatch, [
        {"id": 1, "symbol": "AAPL", "status": "open"},
        {"id": 2, "symbol": "MSFT", "status": "closed"},
    ])
    report = ar.reconcile_positions(_alpaca(["AAPL"]))
    assert report["in_sync"] is True
    assert report["orphan_open_trades"] == []
    assert report["unlogged_positions"] == []


def test_orphan_open_trade_self_healed(tmp_path, monkeypatch):
    # Trade log says NVDA is open but the broker has no such position.
    # reconcile_positions now REPAIRS to broker truth (closes the orphan) rather
    # than only flagging it, so the post-repair report is in sync and records the
    # corrective action. No exit price is known -> closed_reconciled, pnl=None.
    _seed_trade_log(tmp_path, monkeypatch, [
        {"id": 1, "symbol": "NVDA", "side": "buy", "qty": 5, "entry_price": 200.0,
         "status": "open"},
    ])
    report = ar.reconcile_positions(_alpaca([]))
    assert report["in_sync"] is True
    assert report["orphan_open_trades"] == []
    assert any(a["action"] == "close_orphan" and a["symbol"] == "NVDA"
               for a in report["reconcile_actions"])
    saved_log = json.loads((tmp_path / "trade_log.json").read_text())
    nvda = next(t for t in saved_log if t["symbol"] == "NVDA")
    assert nvda["status"] == "closed_reconciled"
    assert nvda["pnl"] is None


def test_unlogged_position_detected(tmp_path, monkeypatch):
    # Broker holds TSLA but there's no open trade for it.
    _seed_trade_log(tmp_path, monkeypatch, [])
    report = ar.reconcile_positions(_alpaca(["TSLA"]))
    assert report["in_sync"] is False
    assert report["unlogged_positions"] == ["TSLA"]


def test_report_is_persisted(tmp_path, monkeypatch):
    _seed_trade_log(tmp_path, monkeypatch, [])
    ar.reconcile_positions(_alpaca(["SPY"]))
    saved = json.loads((tmp_path / "reconciliation_report.json").read_text())
    assert saved["unlogged_positions"] == ["SPY"]
    assert "timestamp" in saved
