"""P2 readiness evidence (2026-10-23).

Two hard readiness gates could never pass for either P2 sleeve because P2 did
not record the evidence:

* slippage — P2 logged its LIMIT price as ``intended_price``, so fill-vs-limit
  measured headroom under its own cap, never execution cost. P2 now records the
  ARRIVAL price (quote mid read just before submit) and the benchmark sleeve
  books its real fill via confirm_fill.
* reconciliation — P2 wrote a working-orders report only (no ``in_sync``). Its
  monitor now writes a shared.reconcile.compute_drift audit into the same file.
"""
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts"),
           os.path.join(REPO_ROOT, "political-copy-bot", "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pb = pytest.importorskip("politician_bot")
import readiness_engine as E  # noqa: E402
from shared import readiness as R  # noqa: E402


# ---------------------------------------------------------------------------
# arrival_reference
# ---------------------------------------------------------------------------

def test_arrival_is_the_quote_mid_not_the_limit():
    assert pb.arrival_reference({"ap": 100.2, "bp": 99.8}) == (100.0, "quote_mid")


def test_arrival_one_sided_quote_and_trade_fallback():
    assert pb.arrival_reference({"ap": 50.0, "bp": 0}) == (50.0, "quote_ask")
    assert pb.arrival_reference({"ap": 0, "bp": 49.0}) == (49.0, "quote_bid")
    assert pb.arrival_reference({}, 48.5) == (48.5, "last_trade")
    assert pb.arrival_reference(None, None) == (None, None)


def test_crossed_quote_is_not_a_mid():
    # bid > ask is a bad print: use the ask side, never a meaningless mid.
    assert pb.arrival_reference({"ap": 10.0, "bp": 11.0}) == (10.0, "quote_ask")


# ---------------------------------------------------------------------------
# Writers: copy BUY + benchmark sleeve record the arrival AND keep the limit
# ---------------------------------------------------------------------------

class FakeAlpaca:
    def __init__(self, quote, fill_price=100.1, fill_status="filled"):
        self._quote = quote
        self._fill = fill_price
        self._status = fill_status
        self.orders = []

    def get_account(self):
        return {"equity": "100000", "cash": "100000", "last_equity": "100000"}

    def get_positions(self):
        return []

    def get_position(self, sym):
        return None

    def get_latest_quote(self, sym):
        return {"quote": self._quote}

    def get_latest_trade(self, sym):
        return {"trade": {"p": 100.0}}

    def place_order(self, **kw):
        o = {"id": f"ord-{len(self.orders)}", "status": "accepted", **kw}
        self.orders.append(o)
        return o

    def get_order(self, oid):
        filled = self._status == "filled"
        return {"status": self._status,
                "filled_qty": self.orders[-1]["qty"] if filled else 0,
                "filled_avg_price": str(self._fill) if filled else None}


class FakeRisk:
    def __init__(self, limits):
        self.limits = limits
        self.trade_log = []
        self.logged = []

    def check_position_size(self, v, e):
        return True

    def check_duplicate_trade(self, ticker):
        return True

    def check_portfolio_exposure(self, positions, equity):
        return True

    def get_trade_size(self, size, equity):
        return 4000.0

    def log_trade(self, rec):
        self.logged.append(rec)


LIMITS = {"limit_offset_pct": 0.15, "min_trade_value_usd": 200, "max_trade_value_usd": 8000,
          "max_single_position_pct": 8.0, "conviction": {"enabled": False},
          "benchmark_sleeve": {"enabled": True, "symbols": ["SPY"], "per_name_target_pct": 7.0,
                               "min_cash_reserve_pct": 10.0, "rebalance_band_pct": 2.0,
                               "max_orders_per_run": 1}}


def _bot(alpaca, tmp_path, monkeypatch):
    monkeypatch.setattr(pb, "BASE_DIR", tmp_path)
    monkeypatch.setattr(pb.time, "sleep", lambda s: None)
    (tmp_path / "data").mkdir(exist_ok=True)
    bot = pb.PoliticianBot.__new__(pb.PoliticianBot)
    bot.alpaca, bot.risk = alpaca, FakeRisk(LIMITS)
    bot._entries_blocked = None
    bot.watchlist_cfg = {"copy_filters": {"technical_confirmation_mode": "off"}}
    return bot


def test_copy_buy_records_arrival_separately_from_limit(tmp_path, monkeypatch):
    bot = _bot(FakeAlpaca({"ap": 100.2, "bp": 99.8}), tmp_path, monkeypatch)
    rec = bot._execute_buy({"politician": {"name": "X"}, "transaction": {"size": "1K–15K"}},
                           "KR", 100_000, 100_000, {"equity": "100000"})
    assert rec["limit_price"] == round(100.2 * 1.0015, 2)
    assert rec["arrival_price"] == rec["intended_price"] == 100.0
    assert rec["arrival_source"] == "quote_mid"
    assert rec["entry_price"] == 100.1
    assert rec["slippage_pct"] == pytest.approx(0.1, abs=1e-4)   # vs arrival, not limit


def test_copy_buy_unfilled_has_no_slippage_sample(tmp_path, monkeypatch):
    bot = _bot(FakeAlpaca({"ap": 100.2, "bp": 99.8}, fill_status="canceled"), tmp_path, monkeypatch)
    rec = bot._execute_buy({"politician": {"name": "X"}, "transaction": {"size": "1K–15K"}},
                           "KR", 100_000, 100_000, {"equity": "100000"})
    assert rec["slippage_pct"] is None and rec["filled_qty"] == 0
    assert E.adverse_slippage_bps([{**rec, "timestamp": "2026-10-23T15:00:00Z"}]) == []


def test_sleeve_books_the_real_fill_and_arrival(tmp_path, monkeypatch):
    bot = _bot(FakeAlpaca({"ap": 100.2, "bp": 99.8}, fill_price=100.10), tmp_path, monkeypatch)
    assert bot.run_benchmark_sleeve()
    rec = bot.risk.logged[0]
    assert rec["source"] == "benchmark_sleeve" and rec["side"] == "buy"
    assert rec["limit_price"] == round(100.2 * 1.0015, 2)
    assert rec["intended_price"] == rec["arrival_price"] == 100.0
    assert rec["entry_price"] == 100.1                       # confirm_fill, never the limit
    assert rec["client_order_id"].startswith("p2sleeve")
    g = E.slippage_for_sleeve("p2-benchmark-etf-v1", [{**rec, "timestamp": "2026-10-23T15:00:00Z"}])
    assert g["status"] == "pass" and g["value"] == pytest.approx(10.0, abs=0.01)


def test_sleeve_unfilled_books_no_entry_price(tmp_path, monkeypatch):
    bot = _bot(FakeAlpaca({"ap": 100.2, "bp": 99.8}, fill_status="new"), tmp_path, monkeypatch)
    monkeypatch.setattr(pb, "confirm_fill", lambda client, oid: ("new", 0.0, None))
    bot.run_benchmark_sleeve()
    rec = bot.risk.logged[0]
    assert "entry_price" not in rec and rec["order_status"] == "new"


# ---------------------------------------------------------------------------
# Readiness engine: both P2 sleeves measured against the arrival reference
# ---------------------------------------------------------------------------

def test_both_p2_sleeves_have_an_arrival_reference():
    for sid in ("p2-copy-v2", "p2-benchmark-etf-v1"):
        assert sid in E.ARRIVAL_REFERENCE and "mid" in E.ARRIVAL_REFERENCE[sid]


def test_legacy_p2_rows_stay_excluded_new_rows_measured():
    legacy = {"symbol": "KR", "side": "buy", "intended_price": 56.58, "limit_price": 56.58,
              "entry_price": 56.5, "order_id": "1", "timestamp": "2026-08-10T15:00:00Z"}
    g = E.slippage_for_sleeve("p2-copy-v2", [legacy])
    assert g["status"] == "not_measured" and "no fills with a recorded reference" in g["detail"]
    new = {"symbol": "T", "side": "buy", "intended_price": 23.20, "arrival_price": 23.20,
           "limit_price": 23.29, "entry_price": 23.22, "filled_qty": 133.0,
           "order_id": "2", "timestamp": "2026-10-23T15:00:00Z"}
    g = E.slippage_for_sleeve("p2-copy-v2", [legacy, new])
    assert g["status"] == "pass" and g["value"] == pytest.approx((23.22 - 23.20) / 23.20 * 1e4, abs=0.01)
    assert "1 fills measured" in g["detail"]


# ---------------------------------------------------------------------------
# Reconciliation: P2 monitor writes a compute_drift audit the gate can read
# ---------------------------------------------------------------------------

class ReconAlpaca:
    def __init__(self, positions, open_orders=None):
        self._positions = positions
        self._open = open_orders or []
        self.placed = []

    def get_orders(self, status="open"):
        return self._open if status == "open" else []

    def get_positions(self):
        return self._positions

    def get_account_activities(self, activity_type="FILL"):
        return []

    def place_order(self, **kw):          # must never be called: read-only audit
        self.placed.append(kw)
        raise AssertionError("reconcile_orders placed an order")


def _recon(tmp_path, monkeypatch, positions, trade_log, open_orders=None):
    monkeypatch.setattr(pb, "BASE_DIR", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "trade_log.json").write_text(json.dumps(trade_log))
    bot = pb.PoliticianBot.__new__(pb.PoliticianBot)
    bot.alpaca = ReconAlpaca(positions, open_orders)
    bot.reconcile_orders()
    assert bot.alpaca.placed == []
    return json.loads((tmp_path / "data" / "reconciliation_report.json").read_text())


LOT = {"symbol": "T", "side": "buy", "qty": 133, "entry_price": 23.22, "status": "open",
       "order_id": "o1", "timestamp": "2026-10-19T14:25:16"}
POS = {"symbol": "T", "qty": "133", "side": "long", "avg_entry_price": "23.22"}


def test_p2_report_carries_drift_and_working_orders(tmp_path, monkeypatch):
    working = [{"symbol": "KR", "side": "buy", "qty": "5", "status": "new", "limit_price": "56"}]
    rep = _recon(tmp_path, monkeypatch, [POS], [LOT], open_orders=working)
    assert rep["in_sync"] is True
    assert rep["positions_held"] == 1 and rep["open_trades_logged"] == 1
    assert rep["working_count"] == 1 and rep["working_orders"][0]["symbol"] == "KR"
    assert rep["short_positions"] == [] and "timestamp" in rep


def test_p2_report_flags_drift_the_repair_cannot_fix(tmp_path, monkeypatch):
    # The repair trims qty to broker truth first; a cost-basis gap is audit-only.
    rep = _recon(tmp_path, monkeypatch, [{**POS, "avg_entry_price": "25.00"}], [LOT])
    assert rep["in_sync"] is False and rep["cost_basis_drift"][0]["symbol"] == "T"


def test_reconciliation_gate_reads_the_p2_report(tmp_path, monkeypatch):
    rep = _recon(tmp_path, monkeypatch, [POS], [LOT])
    as_of = R.iso_date_et(rep["timestamp"])
    sessions = R.nyse_sessions("2026-01-01", "2027-12-31")
    if as_of not in sessions:                       # weekend/holiday test run
        as_of = max(s for s in sessions if s <= as_of)
    g = R.reconciliation_gate(rep, as_of, sessions)
    assert g["status"] == "pass", g
    legacy = {"timestamp": rep["timestamp"], "working_orders": [], "working_count": 0}
    assert R.reconciliation_gate(legacy, as_of, sessions)["status"] == "not_measured"


def test_heartbeat_watches_p2_drift():
    import heartbeat
    assert heartbeat.RECONCILE_SOURCES["P2 Capitol Shadow"] == \
        "political-copy-bot/data/reconciliation_report.json"
    alert, summary = heartbeat.assess_reconciliation(
        {"P2 Capitol Shadow": {"in_sync": False, "orphan_open_trades": ["HD"]}})
    assert alert and "P2 Capitol Shadow" in summary and "HD" in summary
