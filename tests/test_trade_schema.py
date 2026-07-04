"""Tests for trade schema v2 + canonical metric source (D1/D6)."""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import performance_tracker as pt  # noqa: E402


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "DATA_DIR", str(tmp_path))


# --- D1: schema v2 ----------------------------------------------------------

def test_log_trade_records_schema_v2_fields(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    tid = pt.log_trade("AAPL", "buy", 10, 100.0, "core", 0.8, ["r"],
                       stop_loss=95.0, take_profit=110.0,
                       intended_price=99.5, order_class="simple")
    log = json.loads((tmp_path / "trade_log.json").read_text())
    rec = next(t for t in log if t["id"] == tid)
    assert rec["schema_version"] == 2
    assert rec["intended_price"] == 99.5
    assert rec["order_class"] == "simple"
    assert rec["borrow_status"] is None
    # slippage = (100 - 99.5)/99.5 * 100
    assert rec["slippage_pct"] == round((100.0 - 99.5) / 99.5 * 100, 4)


def test_log_trade_short_records_borrow_status(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    pt.log_trade("XYZ", "sell", 10, 50.0, "agg", -0.7, ["short"],
                 borrow_status="etb")
    log = json.loads((tmp_path / "trade_log.json").read_text())
    assert log[-1]["borrow_status"] == "etb"


def test_close_trade_records_realized_and_fees(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    tid = pt.log_trade("AAPL", "buy", 100, 100.0, "core", 0.8, ["r"])
    pt.close_trade(tid, 110.0)
    log = json.loads((tmp_path / "trade_log.json").read_text())
    rec = next(t for t in log if t["id"] == tid)
    assert rec["status"] == "closed"
    assert rec["gross_pnl"] == 1000.0
    assert rec["fees"] > 0
    assert rec["realized_pnl"] == rec["pnl"]
    assert rec["pnl"] < rec["gross_pnl"]  # net of fees


# --- D6: canonical metric source -------------------------------------------

def test_compute_metrics_labels_per_trade_sharpe(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    tid = pt.log_trade("AAPL", "buy", 100, 100.0, "core", 0.8, ["r"])
    pt.close_trade(tid, 110.0)
    m = pt.compute_metrics()
    assert "per_trade_sharpe" in m
    assert m["per_trade_sharpe"] == m["sharpe_estimate"]  # alias kept


def test_equity_curve_metrics_is_annualized_and_canonical():
    # A steadily rising curve WITH genuine day-to-day dispersion => positive
    # annualized Sharpe. (A perfectly-constant-return curve has zero variance
    # and is intentionally scored 0.0, not a rounding-noise-driven +1e16 — see
    # test_sharpe_zero_when_no_variance.)
    rets = [0.002 if i % 2 == 0 else -0.0005 for i in range(259)]  # mean +0.00075
    curve = [100_000]
    for r in rets:
        curve.append(curve[-1] * (1 + r))
    m = pt.equity_curve_metrics(curve)
    assert m is not None
    assert "sharpe" in m and "sortino" in m and "calmar" in m
    assert m["sharpe"] > 0
    # Cross-check it equals the backtest metrics summary (single source of truth).
    from backtest.metrics import summary
    assert m["sharpe"] == summary(curve)["sharpe"]


def test_equity_curve_metrics_insufficient_data():
    assert pt.equity_curve_metrics([100_000]) is None
    assert pt.equity_curve_metrics([]) is None
