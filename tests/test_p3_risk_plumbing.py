"""P3 risk plumbing (audit 2026-07-04, defects D6 + D11).

D11 — the blanket re-entry cooldown blocked the SINGLE-stop recoveries that
carried P3's P&L (MU stopped -> re-bought -> +2,719; MPC -> +1,573). With
exit_reason now logged (D2), cool a name only on >= N consecutive stop-outs
(the churn signature), never on one stop then a winner.

D6 — the tranche cap was only a per-trade ceiling and max_gross_exposure_pct
was dead config never read (P3 hit 99.5% deployed on 6/22); cash/sector/tranche
squeezes shipped dust brackets (UNH 1sh, EMR 2sh). Enforce cumulative tranche +
gross ceilings and a minimum-notional floor. These tests drive execute_signals
against a fake broker with module DATA_DIR/CONFIG_DIR pointed at a tmp dir, so
the real committed trade log is never touched.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P3_SCRIPTS = os.path.join(REPO_ROOT, "event-driven-bot", "scripts")
for _p in (REPO_ROOT, P3_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import event_driven_bot as EDB  # noqa: E402
from event_driven_bot import symbols_on_reentry_cooldown  # noqa: E402

NOW = datetime(2026, 6, 30, 16, 0, tzinfo=timezone.utc)


def _exit(symbol, days_ago, reason, status="closed"):
    return {"symbol": symbol, "status": status,
            "exit_timestamp": (NOW - timedelta(days=days_ago)).isoformat(),
            "exit_reason": reason}


# --------------------------------------------------------------------------
# D11 — conditional (consecutive-stop) cooldown
# --------------------------------------------------------------------------

def test_two_consecutive_stops_is_cooled():
    log = [_exit("INTC", 2, "stop_loss"), _exit("INTC", 5, "stop_loss")]
    on_cd = symbols_on_reentry_cooldown(log, 10, now=NOW, min_consecutive_stops=2)
    assert "INTC" in on_cd


def test_single_stop_then_winner_is_not_cooled():
    # The MU/MPC pattern: one stop, then a take-profit — a recovery, not churn.
    log = [_exit("MU", 2, "take_profit"), _exit("MU", 5, "stop_loss")]
    on_cd = symbols_on_reentry_cooldown(log, 10, now=NOW, min_consecutive_stops=2)
    assert "MU" not in on_cd


def test_one_stop_alone_is_not_cooled_under_threshold_2():
    log = [_exit("FCX", 1, "stop_loss")]
    assert symbols_on_reentry_cooldown(log, 10, now=NOW, min_consecutive_stops=2) == set()


def test_most_recent_run_only_counts_newest_first():
    # newest is a take_profit -> run breaks immediately even if older ones stopped
    log = [_exit("X", 1, "take_profit"),
           _exit("X", 3, "stop_loss"), _exit("X", 4, "stop_loss")]
    assert symbols_on_reentry_cooldown(log, 10, now=NOW, min_consecutive_stops=2) == set()


def test_stops_outside_window_do_not_count():
    log = [_exit("Y", 2, "stop_loss"), _exit("Y", 30, "stop_loss")]  # 2nd is >10d
    assert symbols_on_reentry_cooldown(log, 10, now=NOW, min_consecutive_stops=2) == set()


def test_threshold_1_preserves_blanket_behavior():
    log = [_exit("ANY", 2, "take_profit")]        # any recent exit -> cooled
    assert symbols_on_reentry_cooldown(log, 10, now=NOW, min_consecutive_stops=1) == {"ANY"}


def test_missing_reason_breaks_the_stop_run():
    log = [{"symbol": "Z", "status": "closed",
            "exit_timestamp": (NOW - timedelta(days=1)).isoformat()},  # no reason
           _exit("Z", 3, "stop_loss")]
    assert symbols_on_reentry_cooldown(log, 10, now=NOW, min_consecutive_stops=2) == set()


# --------------------------------------------------------------------------
# D6 — cumulative tranche / gross ceilings / min-notional floor
# --------------------------------------------------------------------------

LIMITS = {
    "max_risk_per_trade_pct": 1.5,
    "max_sector_exposure_pct": 20.0,
    "max_position_pct_per_symbol": 8.0,
    "symbol_reentry_cooldown_days": 10,
    "cooldown_consecutive_stops": 2,
    "min_position_notional_usd": 2000,
    "max_trades_per_day": 15,
    "max_gross_exposure_pct": 80.0,
    "sector_rotation_enabled": False,
    "max_sector_rotations_per_day": 0,
    "capital_tranches": {"core_swing": 0.60, "event_driven": 0.20, "cash_reserve": 0.20},
    "atr_stop_multiplier": 1.5,
    "atr_tp1_multiplier": 3.0,
    "catalyst_max_hold_days": 2,
}


class FakeAlpaca:
    def __init__(self, positions):
        self._positions = positions
        self.placed = []
        self._last = None

    def get_account(self):
        return {"equity": "100000", "cash": "100000", "last_equity": "100000"}

    def get_positions(self):
        return self._positions

    def get_latest_trade(self, sym):
        return {}                       # keep the signal's own price

    def place_bracket_order(self, symbol, qty, side, take_profit_price,
                            stop_loss_price, client_order_id=None):
        self._last = {"qty": qty, "price": self._price}
        order = {"id": f"ord-{symbol}", "status": "accepted", "symbol": symbol,
                 "qty": qty}
        self.placed.append(order)
        return order


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """execute_signals wired to a tmp data/config dir and a fake broker."""
    (tmp_path / "risk_limits.json").write_text(json.dumps(LIMITS))
    (tmp_path / "watchlist.json").write_text(json.dumps({"universe": []}))
    monkeypatch.setattr(EDB, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(EDB, "DATA_DIR", tmp_path)
    monkeypatch.setattr("shared.preflight.run_preflight",
                        lambda **kw: (True, {"hard_failures": []}))

    def run(signals, positions=None, trade_log=None, price=50.0):
        (tmp_path / "trade_log.json").write_text(json.dumps(trade_log or []))
        alpaca = FakeAlpaca(positions or [])
        alpaca._price = price

        def fake_confirm(client, order_id):
            return ("filled", client._last["qty"], client._last["price"])
        monkeypatch.setattr(EDB, "confirm_fill", fake_confirm)
        executed = EDB.execute_signals(alpaca, signals, "core_swing")
        final_log = json.loads((tmp_path / "trade_log.json").read_text())
        return executed, alpaca, final_log
    return run


def _signal(sym, sector, price=50.0, atr=2.0):
    return {"symbol": sym, "sector": sector, "price": price, "atr": atr,
            "score": 0.8, "reasons": ["test"], "signal": "BUY"}


def _positions(specs):
    return [{"symbol": s, "market_value": str(mv), "qty": "1"} for s, mv in specs]


def test_clean_book_places_a_bounded_trade(harness):
    executed, alpaca, _ = harness([_signal("RTX", "Industrials")])
    assert len(alpaca.placed) == 1
    # 8% per-symbol cap on $100k / $50 -> 160 shares = $8,000
    assert alpaca.placed[0]["qty"] == 160
    assert executed[0]["trade_value"] == 8000


def test_gross_cap_blocks_when_book_full(harness):
    pos = _positions([("AAPL", 15000), ("JPM", 15000), ("XOM", 15000),
                      ("UNH", 15000), ("PG", 20000)])       # 80,000 = 80% gross
    executed, alpaca, _ = harness([_signal("RTX", "Industrials")], positions=pos)
    assert alpaca.placed == []
    assert executed == []


def test_min_notional_skips_dust(harness):
    pos = _positions([("AAPL", 15000), ("JPM", 15000), ("XOM", 15000),
                      ("UNH", 15000), ("PG", 18500)])       # 78,500 -> $1,500 room
    executed, alpaca, _ = harness([_signal("RTX", "Industrials")], positions=pos)
    # squeezed to $1,500 < $2,000 floor -> no dust bracket
    assert alpaca.placed == []
    assert executed == []


def test_cumulative_tranche_ceiling_blocks_overfill(harness):
    # tranche already fully deployed via open core_swing log entries (3 x $20k)
    log = [{"symbol": s, "status": "open", "tranche": "core_swing",
            "trade_value": 20000, "date": "2026-06-01"}
           for s in ("AAA", "BBB", "CCC")]
    executed, alpaca, _ = harness([_signal("RTX", "Industrials")], trade_log=log)
    assert alpaca.placed == []
    assert executed == []


def test_second_signal_stops_at_gross_ceiling(harness):
    # First fills ($8k); make the rest of the book pre-consume gross so the
    # second candidate has no room and is skipped, first still placed.
    pos = _positions([("AAPL", 18000), ("JPM", 18000), ("XOM", 18000),
                      ("UNH", 18000)])                       # 72,000 gross
    executed, alpaca, _ = harness(
        [_signal("RTX", "Industrials"), _signal("LIN", "Materials")], positions=pos)
    # RTX sized to $8k pushes gross to 80k -> LIN has 0 room
    assert [o["symbol"] for o in alpaca.placed] == ["RTX"]
    assert len(executed) == 1
