"""Kill-switch + daily-loss safety drill.

Scripted simulated drawdown → assert the intraday monitor LIQUIDATES and LOCKS
DOWN. This is the drill required by docs/LIVE_READINESS.md §5 ("scripted
kill-switch drill in CI"). It runs in CI on every push so the hard safety stop
can never silently regress — exits never get blocked, entries do.
"""
import json

import autonomous_runner as ar


class _DrillAlpaca:
    """Minimal broker stub that records the liquidation calls the kill switch
    is required to make. No network — pure in-memory drill."""

    def __init__(self, equity, last_equity=None, positions=None, market_open=True):
        self._equity = float(equity)
        self._last_equity = float(last_equity if last_equity is not None else equity)
        self._positions = positions or []
        self._market_open = market_open
        self.closed_all = False
        self.canceled_all = False

    def is_market_open(self):
        return self._market_open

    def get_account(self):
        return {
            "equity": self._equity,
            "last_equity": self._last_equity,
            "cash": self._equity,
        }

    def get_positions(self):
        return self._positions

    def get_orders(self, status="all"):
        return []

    def close_all_positions(self):
        self.closed_all = True

    def cancel_all_orders(self):
        self.canceled_all = True


def _seed(tmp_path, monkeypatch, state, limits):
    monkeypatch.setattr(ar, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ar, "CONFIG_DIR", tmp_path)
    (tmp_path / "portfolio_state.json").write_text(json.dumps(state))
    (tmp_path / "risk_limits.json").write_text(json.dumps(limits))


def _base_state():
    return {
        "starting_equity": 100_000.0,
        "day_start_equity": 100_000.0,
        "equity": 100_000.0,
        "halted": False,
        "halt_reason": None,
        "halt_until": None,
    }


def test_kill_switch_liquidates_and_locks_down(tmp_path, monkeypatch, limits):
    """18% drawdown == kill_switch_drawdown_pct → liquidate everything + halt."""
    _seed(tmp_path, monkeypatch, _base_state(), limits)
    alpaca = _DrillAlpaca(equity=82_000.0, positions=[{"symbol": "NVDA"}])

    ar.run_intraday_monitor(alpaca)

    assert alpaca.closed_all is True, "kill switch MUST liquidate all positions"
    assert alpaca.canceled_all is True, "kill switch MUST cancel all open orders"
    state = json.loads((tmp_path / "portfolio_state.json").read_text())
    assert state["halted"] is True, "portfolio must be locked down after kill switch"
    assert "Kill switch" in (state["halt_reason"] or "")


def test_daily_loss_halts_without_liquidating(tmp_path, monkeypatch, limits):
    """10% daily loss (< 18% kill switch) → 24h halt, but NO liquidation."""
    _seed(tmp_path, monkeypatch, _base_state(), limits)
    alpaca = _DrillAlpaca(equity=90_000.0, positions=[{"symbol": "NVDA"}])

    ar.run_intraday_monitor(alpaca)

    assert alpaca.closed_all is False, "daily-loss halt must not force liquidation"
    state = json.loads((tmp_path / "portfolio_state.json").read_text())
    assert state["halted"] is True
    assert "Daily loss" in (state["halt_reason"] or "")
    assert state["halt_until"], "daily-loss halt must set a 24h expiry"


def test_healthy_drawdown_does_not_halt(tmp_path, monkeypatch, limits):
    """1% drawdown → no kill switch, no daily-loss halt."""
    _seed(tmp_path, monkeypatch, _base_state(), limits)
    alpaca = _DrillAlpaca(equity=99_000.0, positions=[])

    ar.run_intraday_monitor(alpaca)

    assert alpaca.closed_all is False
    state = json.loads((tmp_path / "portfolio_state.json").read_text())
    assert state["halted"] is False


# ---------------------------------------------------------------------------
# Phantom-read drills (forensic audit 2026-10-03): on 2026-07-07 Alpaca returned
# equity == cash with every position priced at $0. A kill switch must NOT act on
# such a read — and must STILL act on a genuine, corroborated crash.
# ---------------------------------------------------------------------------

class _PricedAlpaca(_DrillAlpaca):
    """Broker stub whose account snapshot can disagree with market data."""

    def __init__(self, equity, cash, positions, prices, **kw):
        super().__init__(equity=equity, positions=positions, **kw)
        self._cash = float(cash)
        self._prices = prices
        self.orders = []

    def get_account(self):
        return {"equity": self._equity, "last_equity": self._last_equity, "cash": self._cash}

    def get_latest_trade(self, sym):
        return {"trade": {"p": self._prices[sym]}}

    def get_position(self, sym):
        return next((p for p in self._positions if p["symbol"] == sym), None)

    def place_order(self, **k):
        self.orders.append(k)
        return {"id": "x"}


_BOOK = [{"symbol": "NVDA", "qty": "100", "side": "long", "avg_entry_price": "400",
          "market_value": "0", "current_price": "0"},
         {"symbol": "XOM", "qty": "300", "side": "long", "avg_entry_price": "110",
          "market_value": "0", "current_price": "0"}]
_PRICES = {"NVDA": 400.0, "XOM": 110.0}            # book = $73,000


def test_monitor_ignores_phantom_equity_equal_to_cash(tmp_path, monkeypatch, limits):
    _seed(tmp_path, monkeypatch, _base_state(), limits)
    alpaca = _PricedAlpaca(equity=26_060.51, cash=26_060.51, positions=_BOOK, prices=_PRICES)

    ar.run_intraday_monitor(alpaca)

    assert alpaca.closed_all is False, "a phantom read must never liquidate"
    state = json.loads((tmp_path / "portfolio_state.json").read_text())
    assert state["halted"] is False, "a phantom read must never latch a halt"


def test_monitor_still_liquidates_a_corroborated_crash(tmp_path, monkeypatch, limits):
    _seed(tmp_path, monkeypatch, _base_state(), limits)
    crashed = {"NVDA": 300.0, "XOM": 80.0}          # book really fell to $54,000
    alpaca = _PricedAlpaca(equity=26_000 + 54_000, cash=26_000, positions=_BOOK,
                           prices=crashed)

    ar.run_intraday_monitor(alpaca)

    assert alpaca.closed_all is True
    state = json.loads((tmp_path / "portfolio_state.json").read_text())
    assert state["halted"] is True and state["halt_evidence"]["independent_equity"] == 80_000.0


def test_trading_session_phantom_read_latches_nothing(tmp_path, monkeypatch, limits):
    _seed(tmp_path, monkeypatch, _base_state(), limits)
    alpaca = _PricedAlpaca(equity=26_060.51, cash=26_060.51, positions=_BOOK, prices=_PRICES)

    ar.run_trading_session(alpaca)

    state = json.loads((tmp_path / "portfolio_state.json").read_text())
    assert state["halted"] is False and alpaca.orders == []


def test_weekly_loss_breach_halts_seven_days_and_expires(tmp_path, monkeypatch, limits):
    state = _base_state()
    state.update(day_start_equity=91_500.0, equity=91_500.0, week_start_equity=100_000.0)
    _seed(tmp_path, monkeypatch, state, limits)
    alpaca = _PricedAlpaca(equity=91_000.0, cash=18_000.0, positions=_BOOK, prices=_PRICES)

    ar.run_trading_session(alpaca)

    st = json.loads((tmp_path / "portfolio_state.json").read_text())
    assert st["halted"] is True and "Weekly loss" in st["halt_reason"]
    assert st["halt_until"], "a weekly halt must expire, never latch permanently"
    assert alpaca.orders == []
