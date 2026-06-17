"""Phase-1 H1: cap-maintenance trims a position that DRIFTS past its asset-class
cap (entry-time caps don't catch appreciation), with honest FIFO partial-close
accounting. Risk-reducing (sells only)."""
import json
from datetime import datetime, timezone

import performance_tracker as pt
from performance_tracker import reduce_open_position
from portfolio_manager import compute_cap_trims

LIMITS = {"max_single_position_pct": {"etf": 12.0, "stock": 8.0, "crypto": 5.0, "penny": 1.0},
          "min_position_notional_usd": 500}


def _pos(sym, mv, price, qty):
    return {"symbol": sym, "market_value": mv, "current_price": price, "qty": qty}


def test_etf_over_cap_is_trimmed_to_cap():
    pos = [_pos("IWM", 13000, 260.0, 50)]          # 13% of 100k, ETF cap 12%
    trims = compute_cap_trims(pos, 100000, LIMITS, {"IWM": {"bucket": "core_equity"}})
    assert len(trims) == 1
    assert trims[0]["symbol"] == "IWM" and trims[0]["cap_pct"] == 12.0
    assert trims[0]["trim_qty"] == 3                # (13000-12000)/260 = 3 whole shares


def test_within_cap_plus_buffer_no_trim():
    pos = [_pos("SPY", 12300, 600.0, 20)]          # 12.3% <= 12% + 0.5% buffer
    assert compute_cap_trims(pos, 100000, LIMITS, {"SPY": {"bucket": "core_equity"}}) == []


def test_stock_uses_tighter_8pct_cap():
    pos = [_pos("AMZN", 9000, 180.0, 50)]          # 9% > 8.5, stock cap 8%
    trims = compute_cap_trims(pos, 100000, LIMITS, {"AMZN": {"bucket": "aggressive_growth"}})
    assert trims and trims[0]["cap_pct"] == 8.0


def test_unknown_bucket_defaults_to_tighter_stock_cap():
    pos = [_pos("XYZ", 9000, 90.0, 100)]           # no bucket -> stock cap 8%
    trims = compute_cap_trims(pos, 100000, LIMITS, {})
    assert trims and trims[0]["cap_pct"] == 8.0


def test_sub_min_notional_trim_skipped():
    pos = [_pos("GLD", 12700, 400.0, 31)]          # breach, but trim ~1 share*400 < 500
    assert compute_cap_trims(pos, 100000, LIMITS, {"GLD": {"bucket": "defensive"}}) == []


def test_never_trims_when_equity_zero():
    assert compute_cap_trims([_pos("IWM", 13000, 260.0, 50)], 0, LIMITS, {}) == []


# --- FIFO partial-close accounting --------------------------------------

def _seed(tmp_path, monkeypatch, lots):
    monkeypatch.setattr(pt, "DATA_DIR", str(tmp_path))
    now = datetime.now(timezone.utc).isoformat()
    log = [{"id": i, "symbol": "IWM", "side": "buy", "qty": q, "entry_price": e,
            "timestamp": now, "status": "open"} for i, (q, e) in enumerate(lots)]
    (tmp_path / "trade_log.json").write_text(json.dumps(log))


def test_partial_trim_reduces_lot_and_books_realized_pnl(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [(50, 250.0)])
    reduced = reduce_open_position("IWM", 10, 260.0, reason="cap_maintenance")
    assert reduced == 10
    log = json.loads((tmp_path / "trade_log.json").read_text())
    open_lots = [t for t in log if t["status"] == "open"]
    closed = [t for t in log if t["status"] == "closed"]
    assert open_lots[0]["qty"] == 40                # remainder stays open
    assert len(closed) == 1 and closed[0]["qty"] == 10
    assert closed[0]["realized_pnl"] is not None and closed[0]["realized_pnl"] > 0  # +~$100 - fees


def test_full_trim_closes_whole_lot(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [(50, 250.0)])
    reduce_open_position("IWM", 50, 260.0)
    log = json.loads((tmp_path / "trade_log.json").read_text())
    assert all(t["status"] == "closed" for t in log)


def test_trim_spans_lots_fifo(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [(30, 250.0), (30, 255.0)])
    reduced = reduce_open_position("IWM", 40, 260.0)
    assert reduced == 40
    log = json.loads((tmp_path / "trade_log.json").read_text())
    open_qty = sum(t["qty"] for t in log if t["status"] == "open")
    closed_qty = sum(t["qty"] for t in log if t["status"] == "closed")
    assert open_qty == 20 and closed_qty == 40
