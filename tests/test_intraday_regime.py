"""Intraday regime refresh (committee rec #5) — the stored regime label must not
lag a midday pullback. refresh_intraday_regime recomputes SPY regime each monitor
cycle, stores a fresh timestamped label on portfolio_state, and flags
deterioration vs the morning read. Advisory: it places no orders."""
import autonomous_runner as ar


class _FakeAlpaca:
    def __init__(self, closes):
        self._closes = closes

    def get_stock_bars(self, symbol, timeframe="1Day", limit=220):
        return {"bars": [{"c": c} for c in self._closes]}


def _rising(n=220):
    return [100.0 + i for i in range(n)]      # strong uptrend -> STRONG_BULL/BULL


def _falling(n=220):
    return [320.0 - i * 0.5 for i in range(n)]  # downtrend -> BEAR/CORRECTION


def test_regime_rank_orders_bearish_higher():
    assert ar._regime_rank("STRONG_BULL") < ar._regime_rank("CORRECTION")
    assert ar._regime_rank("CORRECTION") < ar._regime_rank("STRONG_BEAR")
    assert ar._regime_rank("garbage") == ar._regime_rank("UNKNOWN")


def test_refresh_stores_fresh_label_no_deterioration_in_bull():
    state = {}
    r = ar.refresh_intraday_regime(_FakeAlpaca(_rising()), state, {"market_regime": "STRONG_BULL"})
    assert r in ("STRONG_BULL", "BULL")
    assert state["current_regime"] == r
    assert "current_regime_at" in state
    assert "equity_mult" in state["current_regime_modifiers"]
    assert state["regime_deteriorated_intraday"] is False


def test_refresh_flags_deterioration_when_market_fades():
    state = {}
    r = ar.refresh_intraday_regime(_FakeAlpaca(_falling()), state, {"market_regime": "STRONG_BULL"})
    assert r in ("BEAR", "STRONG_BEAR", "CORRECTION")
    assert state["regime_deteriorated_intraday"] is True
    assert state["morning_regime"] == "STRONG_BULL"


def test_refresh_is_best_effort_on_bad_data():
    class _Bad:
        def get_stock_bars(self, *a, **k):
            raise RuntimeError("boom")

    state = {}
    assert ar.refresh_intraday_regime(_Bad(), state, {}) is None
    assert "current_regime" not in state          # no partial/garbage write, no crash


def test_refresh_skips_on_insufficient_history():
    state = {}
    assert ar.refresh_intraday_regime(_FakeAlpaca([100.0] * 10), state, {}) is None
    assert "current_regime" not in state
