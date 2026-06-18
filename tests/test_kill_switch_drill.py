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
