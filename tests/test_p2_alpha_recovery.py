"""P2 alpha-recovery changes (audit 2026-07-04, defects D7 / D10 / D12).

D7 — the 25% take-profit destroyed the signal's edge (backtest: live rule alpha
t=0.41, median trade -2.43%, vs a ~63-trading-day hold alpha +1.64%, t=3.76,
median +2.57%). The PRIMARY exit is now the ~91-calendar-day (≈63-trading-day)
alpha-capture time exit; the price take-profit is OFF by default (reversible);
the trailing stop stays only as a disaster brake.

D10 — the enforced technical-confirmation gate halved the sample and lowered
alpha significance; it now runs advisory (logs, does not block) by default.

D12 — 29% of copy BUYs never filled because the limit was pegged to the mid;
peg to the ask so copies are marketable.
"""
import json
import os
import sys
from datetime import datetime, timedelta

import pytest

P2_SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "political-copy-bot", "scripts")
if P2_SCRIPTS not in sys.path:
    sys.path.insert(0, P2_SCRIPTS)

politician_bot = pytest.importorskip("politician_bot")


def _iso_days_ago(days):
    return (datetime.now() - timedelta(days=days)).isoformat()


class FakeAlpaca:
    def __init__(self, positions=None, quote=None, bars=None):
        self._positions = positions or []
        self._quote = quote or {"ap": 100.0, "bp": 99.0}
        self._bars = bars or []
        self.orders = []

    def get_account(self):
        return {"equity": "100000", "cash": "100000", "last_equity": "100000"}

    def get_positions(self):
        return self._positions

    def get_position(self, sym):
        return next((p for p in self._positions if p["symbol"] == sym), None)

    def get_latest_quote(self, sym):
        return {"quote": self._quote}

    def get_latest_trade(self, sym):
        return {"trade": {"p": self._quote.get("ap", 100.0)}}

    def get_stock_bars(self, sym, limit=40):
        return self._bars

    def place_order(self, **kw):
        o = {"id": f"ord-{len(self.orders)}", "status": "accepted", **kw}
        self.orders.append(o)
        return o


class FakeRisk:
    def __init__(self, trade_log=None, limits=None):
        self.trade_log = trade_log or []
        self.limits = limits or {}
        self.exits = []
        self.logged = []

    # execute_trade dependencies
    def validate_ticker(self, t):
        return t or None

    def check_kill_switch(self, account):
        return True

    def check_daily_loss(self, account):
        return True

    def check_daily_trade_count(self):
        return True

    def check_duplicate_trade(self, ticker):
        return True

    def check_portfolio_exposure(self, positions, equity):
        return True

    def check_position_size(self, trade_value, equity):
        return True

    def get_trade_size(self, reported_size, equity):
        return 4000.0

    # check_stops dependencies
    def apply_exit(self, symbol, qty, price, reason):
        self.exits.append({"symbol": symbol, "qty": qty, "price": price, "reason": reason})
        return qty

    def log_trade(self, rec):
        self.logged.append(rec)


P2_LIMITS = {
    "limit_offset_pct": 0.15, "min_trade_value_usd": 200, "max_trade_value_usd": 8000,
    "max_single_position_pct": 8.0, "conviction": {"enabled": False},
    "benchmark_sleeve": {"enabled": False},
}
SELL_CFG = {"trailing_stop_pct": 15.0, "take_profit_enabled": False,
            "take_profit_pct": 25.0, "alpha_capture_days": 91, "max_hold_days": 252}


def _bot(alpaca, risk, watchlist_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(politician_bot, "BASE_DIR", tmp_path)
    monkeypatch.setattr(politician_bot, "confirm_fill",
                        lambda client, oid: ("filled",
                                             client.orders[-1]["qty"],
                                             client.orders[-1].get("limit_price") or 100.0))
    (tmp_path / "data").mkdir(exist_ok=True)
    bot = politician_bot.PoliticianBot.__new__(politician_bot.PoliticianBot)
    bot.alpaca = alpaca
    bot.risk = risk
    bot.watchlist_cfg = watchlist_cfg
    return bot


def _position(symbol, plpc, qty):
    return {"symbol": symbol, "unrealized_plpc": str(plpc), "qty": str(qty)}


# --------------------------------------------------------------------------
# D7 — alpha-capture time exit replaces the 25% take-profit
# --------------------------------------------------------------------------

def test_alpha_capture_exit_fires_at_horizon(tmp_path, monkeypatch):
    risk = FakeRisk(trade_log=[{"symbol": "AAPL", "side": "buy",
                                "timestamp": _iso_days_ago(95)}], limits=P2_LIMITS)
    alpaca = FakeAlpaca(positions=[_position("AAPL", 0.05, 10)])
    bot = _bot(alpaca, risk, {"sell_logic": SELL_CFG}, tmp_path, monkeypatch)
    bot.check_stops()
    assert len(alpaca.orders) == 1 and alpaca.orders[0]["side"] == "sell"
    assert alpaca.orders[0]["qty"] == 10                 # FULL position, not half
    assert risk.exits[-1]["reason"] == "time_exit"


def test_take_profit_off_by_default_holds_the_winner(tmp_path, monkeypatch):
    # +30% (over the 25% TP) but young and not trailing-triggered -> HOLD.
    risk = FakeRisk(trade_log=[{"symbol": "NVDA", "side": "buy",
                                "timestamp": _iso_days_ago(10)}], limits=P2_LIMITS)
    alpaca = FakeAlpaca(positions=[_position("NVDA", 0.30, 10)])
    bot = _bot(alpaca, risk, {"sell_logic": SELL_CFG}, tmp_path, monkeypatch)
    bot.check_stops()
    assert alpaca.orders == []                           # the 25% TP no longer truncates


def test_take_profit_still_available_when_explicitly_enabled(tmp_path, monkeypatch):
    cfg = dict(SELL_CFG, take_profit_enabled=True)
    risk = FakeRisk(trade_log=[{"symbol": "NVDA", "side": "buy",
                                "timestamp": _iso_days_ago(10)}], limits=P2_LIMITS)
    alpaca = FakeAlpaca(positions=[_position("NVDA", 0.30, 10)])
    bot = _bot(alpaca, risk, {"sell_logic": cfg}, tmp_path, monkeypatch)
    bot.check_stops()
    assert len(alpaca.orders) == 1 and alpaca.orders[0]["qty"] == 5   # sells half


def test_trailing_stop_still_fires_as_disaster_brake(tmp_path, monkeypatch):
    risk = FakeRisk(trade_log=[{"symbol": "TSLA", "side": "buy",
                                "timestamp": _iso_days_ago(10)}], limits=P2_LIMITS)
    alpaca = FakeAlpaca(positions=[_position("TSLA", 0.02, 10)])   # now +2%
    bot = _bot(alpaca, risk, {"sell_logic": SELL_CFG}, tmp_path, monkeypatch)
    (tmp_path / "data" / "trailing_peaks.json").write_text(json.dumps({"TSLA": 25.0}))
    bot.check_stops()                                    # dropped 23% from a +25% peak
    assert len(alpaca.orders) == 1
    assert risk.exits[-1]["reason"] == "trailing_stop"


# --------------------------------------------------------------------------
# D10 — technical confirmation is advisory by default
# --------------------------------------------------------------------------

FALLING_BARS = [{"c": 100 - i} for i in range(40)]       # below MA -> confirm fails
WATCHLIST_ADVISORY = {"copy_filters": {"technical_confirmation_mode": "advisory"}}
WATCHLIST_ENFORCE = {"copy_filters": {"technical_confirmation_mode": "enforce"}}
BUY = {"issuer": {"ticker": "AAPL", "name": "Apple"}, "politician": {"name": "X"},
       "transaction": {"type": "BUY", "size": "1K–15K"}, "_source": "primary"}


def test_advisory_mode_copies_even_without_technical_confirmation(tmp_path, monkeypatch):
    risk = FakeRisk(limits=P2_LIMITS)
    alpaca = FakeAlpaca(bars=FALLING_BARS)
    bot = _bot(alpaca, risk, WATCHLIST_ADVISORY, tmp_path, monkeypatch)
    rec = bot.execute_trade(dict(BUY))
    assert rec is not None and len(alpaca.orders) == 1   # advisory: not blocked


def test_enforce_mode_still_blocks_without_confirmation(tmp_path, monkeypatch):
    risk = FakeRisk(limits=P2_LIMITS)
    alpaca = FakeAlpaca(bars=FALLING_BARS)
    bot = _bot(alpaca, risk, WATCHLIST_ENFORCE, tmp_path, monkeypatch)
    assert bot.execute_trade(dict(BUY)) is None
    assert alpaca.orders == []


# --------------------------------------------------------------------------
# D12 — copy BUYs peg to the ask (marketable)
# --------------------------------------------------------------------------

def test_buy_limit_is_marketable_pegged_to_ask(tmp_path, monkeypatch):
    risk = FakeRisk(limits=P2_LIMITS)
    # wide spread: ask 100, bid 98 -> mid 99. Old mid+0.15% = 99.15 < ask (no fill).
    alpaca = FakeAlpaca(bars=FALLING_BARS, quote={"ap": 100.0, "bp": 98.0})
    bot = _bot(alpaca, risk, WATCHLIST_ADVISORY, tmp_path, monkeypatch)
    bot.execute_trade(dict(BUY))
    assert len(alpaca.orders) == 1
    limit = alpaca.orders[0]["limit_price"]
    assert limit >= 100.0                                # crosses the ask -> fills
    assert limit == round(100.0 * 1.0015, 2)             # ask + offset, bounded slippage


# --------------------------------------------------------------------------
# Rec C — disclosure lineage on copies + structured skip register
# --------------------------------------------------------------------------

BUY_WITH_DATES = dict(BUY, dates={"trade": "2026-05-15", "disclosed": "2026-06-03"})


def test_copy_record_carries_disclosure_lineage(tmp_path, monkeypatch):
    risk = FakeRisk(limits=P2_LIMITS)
    alpaca = FakeAlpaca(bars=FALLING_BARS)
    bot = _bot(alpaca, risk, WATCHLIST_ADVISORY, tmp_path, monkeypatch)
    rec = bot.execute_trade(BUY_WITH_DATES)
    assert rec is not None
    # The lag study REFUSED without these — now every copy carries them.
    assert rec["transaction_date"] == "2026-05-15"
    assert rec["disclosure_date"] == "2026-06-03"
    assert "observed_date" in rec and rec["observed_date"]
    assert isinstance(rec["disclosure_lag_days"], int)   # measurable lag
    assert rec["feed_source"] in ("capitol_trades", "house_fd")


def test_skip_register_records_structured_reasons(tmp_path, monkeypatch):
    import politician_bot as pb
    from datetime import datetime, timedelta
    monkeypatch.setattr(pb, "BASE_DIR", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    bot = pb.PoliticianBot.__new__(pb.PoliticianBot)
    bot.watchlist_cfg = {"copy_filters": {"transaction_types": ["BUY"],
                                          "max_transaction_age_days": 30,
                                          "skip_treasury_bills": True}}
    bot._freshness_evaluated = 0
    bot._unparseable_dates = 0
    bot._skips = []
    fresh = (datetime.now() - timedelta(days=5)).strftime("%m/%d/%Y")
    old = (datetime.now() - timedelta(days=90)).strftime("%m/%d/%Y")
    # a SELL (wrong type), a stale BUY, a treasury BUY -> all skipped with reasons
    assert bot._is_copyable_trade({"transaction": {"type": "SELL"},
                                   "issuer": {"ticker": "X"}, "dates": {"trade": fresh}}) is False
    assert bot._is_copyable_trade({"transaction": {"type": "BUY"},
                                   "issuer": {"ticker": "Y"}, "dates": {"trade": old}}) is False
    assert bot._is_copyable_trade({"transaction": {"type": "BUY"},
                                   "issuer": {"ticker": "Z", "name": "US TREASURY NOTE"},
                                   "dates": {"trade": fresh}}) is False
    reasons = [s["reason"] for s in bot._skips]
    assert any("transaction_type" in r for r in reasons)
    assert any("stale_disclosure" in r for r in reasons)
    assert any("treasury" in r for r in reasons)
    assert all("ticker" in s and "reason" in s for s in bot._skips)
