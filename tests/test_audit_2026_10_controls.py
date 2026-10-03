"""Regression tests for the 2026-10-03 forensic audit's control defects.

Each test reproduces a real incident with the real numbers:
  * 2026-07-07 phantom kill switch — Alpaca returned P1 equity == cash
    ($26,060.51 vs a true ~$92.6K); the kill switch latched a permanent halt.
  * P3 orphan stops — a re-armed GTC stop outlived its position; DDOG's fired on
    2026-08-06 and opened a 14-share short in a long-only book.
  * P1 late-fill attribution — momentum orders that filled after the confirm
    window were reconciled with no order_class and stopped out as "active".
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P3_SCRIPTS = os.path.join(REPO_ROOT, "event-driven-bot", "scripts")
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts"), P3_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.equity_guard import confirm_equity  # noqa: E402
from shared.order_hygiene import (  # noqa: E402
    enforce_exit_hygiene,
    find_orphan_exit_orders,
    find_unintended_shorts,
)
from shared.reconcile import (  # noqa: E402
    order_classes_from_orders,
    reconcile_log_to_broker,
)
from portfolio_manager import (  # noqa: E402
    active_sleeve_exit_triggers,
    is_schedule_managed,
)

# ---------------------------------------------------------------------------
# Equity guard — the 2026-07-07 incident
# ---------------------------------------------------------------------------

# P1's book right after the 2026-07-06 momentum rebalance (approximate prices).
_P1_POSITIONS = [
    {"symbol": "C", "qty": "38"}, {"symbol": "CAT", "qty": "5"},
    {"symbol": "GOOGL", "qty": "15"}, {"symbol": "MPC", "qty": "20"},
    {"symbol": "PSX", "qty": "30"}, {"symbol": "SLB", "qty": "118"},
    {"symbol": "AMD", "qty": "9"}, {"symbol": "MU", "qty": "4"},
]
_PX = {"C": 142.0, "CAT": 980.0, "GOOGL": 355.0, "MPC": 272.0, "PSX": 179.0,
       "SLB": 45.5, "AMD": 2900.0, "MU": 6250.0}   # sized so the book ~= $66.5K


def _px(sym):
    return _PX[sym]


def _book_value():
    return sum(float(p["qty"]) * _PX[p["symbol"]] for p in _P1_POSITIONS)


def test_glitch_equity_equal_to_cash_is_rejected():
    cash = 26_060.51
    acct = {"equity": "26060.51", "cash": str(cash)}       # positions priced at 0
    out = confirm_equity(acct, _P1_POSITIONS, reference_equity=92_583.88, get_price=_px)
    assert out["ok"] is False
    assert out["independent_equity"] > 90_000              # cash + real book value
    assert "disagrees" in out["reason"]


def test_normal_day_needs_no_confirmation_calls():
    calls = []
    out = confirm_equity({"equity": "97000", "cash": "60000"}, _P1_POSITIONS,
                         reference_equity=97_500,
                         get_price=lambda s: calls.append(s) or _PX[s])
    assert out["ok"] is True and calls == []                # zero extra API calls


def test_genuine_crash_is_confirmed_and_still_trips():
    cash = 26_060.51
    crashed = {s: p * 0.5 for s, p in _PX.items()}          # book really halves
    true_equity = cash + sum(float(p["qty"]) * crashed[p["symbol"]] for p in _P1_POSITIONS)
    out = confirm_equity({"equity": str(true_equity), "cash": str(cash)}, _P1_POSITIONS,
                         reference_equity=cash + _book_value(),
                         get_price=lambda s: crashed[s])
    assert out["ok"] is True and "CONFIRMED" in out["reason"]


def test_large_move_without_price_source_is_not_acted_on():
    out = confirm_equity({"equity": "26060.51", "cash": "26060.51"}, _P1_POSITIONS,
                         reference_equity=92_583.88, get_price=None)
    assert out["ok"] is False


def test_unpriceable_position_blocks_confirmation():
    out = confirm_equity({"equity": "26060.51", "cash": "26060.51"}, _P1_POSITIONS,
                         reference_equity=92_583.88,
                         get_price=lambda s: 0.0 if s == "MU" else _PX[s])
    assert out["ok"] is False and out["unpriced"] == ["MU"]


def test_non_positive_equity_rejected_and_missing_reference_accepted():
    assert confirm_equity({"equity": "0", "cash": "0"}, [], reference_equity=1e5)["ok"] is False
    assert confirm_equity({"equity": "1000", "cash": "1000"}, [], reference_equity=None)["ok"] is True


# ---------------------------------------------------------------------------
# Order hygiene — the DDOG / V / LLY orphan stops
# ---------------------------------------------------------------------------

def _o(oid, sym, side, typ, status="new", qty="2", coid=""):
    return {"id": oid, "symbol": sym, "side": side, "type": typ, "status": status,
            "qty": qty, "client_order_id": coid}


def test_orphan_sell_stop_without_position_is_flagged():
    orders = [_o("1", "V", "sell", "stop", coid="p3-stop-20260731-V-sell"),
              _o("2", "LLY", "sell", "stop", qty="4", coid="p3-stop-20260710-LLY-sell")]
    positions = [{"symbol": "PSX", "qty": "30"}]
    assert {o["symbol"] for o in find_orphan_exit_orders(orders, positions)} == {"V", "LLY"}


def test_protective_legs_of_a_held_position_are_untouched():
    orders = [_o("1", "PSX", "sell", "limit", qty="30"),
              _o("2", "PSX", "sell", "stop", status="held", qty="30")]
    assert find_orphan_exit_orders(orders, [{"symbol": "PSX", "qty": "30"}]) == []


def test_unfilled_bracket_children_and_entries_are_untouched():
    orders = [_o("1", "NVDA", "buy", "market"),                       # pending entry
              _o("2", "NVDA", "sell", "limit", status="held"),        # child leg
              _o("3", "NVDA", "sell", "stop", status="held")]
    assert find_orphan_exit_orders(orders, []) == []


def test_sell_against_a_short_and_buy_stop_without_short_are_orphans():
    orders = [_o("1", "DDOG", "sell", "stop"), _o("2", "AAPL", "buy", "stop")]
    positions = [{"symbol": "DDOG", "qty": "-14", "side": "short"}]
    assert {o["symbol"] for o in find_orphan_exit_orders(orders, positions)} == {"DDOG", "AAPL"}


def test_unintended_short_detected_from_signed_or_side_qty():
    pos = [{"symbol": "DDOG", "qty": "-14"}, {"symbol": "X", "qty": "3", "side": "short"},
           {"symbol": "PSX", "qty": "30"}]
    assert [s["symbol"] for s in find_unintended_shorts(pos)] == ["DDOG", "X"]


class _FakeClient:
    def __init__(self, positions, orders):
        self.positions, self.orders, self.calls = positions, orders, []

    def get_positions(self):
        return self.positions

    def get_orders(self, status="open"):
        return self.orders

    def cancel_order(self, oid):
        self.calls.append(("cancel", oid))

    def close_position(self, sym):
        self.calls.append(("close", sym))


class _Log:
    def __init__(self):
        self.lines = []

    def error(self, m):
        self.lines.append(m)

    warning = info = error


def test_enforce_hygiene_cancels_orphans_before_flattening_shorts():
    c = _FakeClient([{"symbol": "DDOG", "qty": "-14", "market_value": "-3881.08"},
                     {"symbol": "PSX", "qty": "30"}],
                    [_o("v1", "V", "sell", "stop"), _o("p1", "PSX", "sell", "limit", qty="30")])
    out = enforce_exit_hygiene(c, _Log(), long_only=True, label="P3")
    assert c.calls == [("cancel", "v1"), ("close", "DDOG")]
    assert len(out["orphans_cancelled"]) == 1 and len(out["shorts_flattened"]) == 1


def test_enforce_hygiene_never_raises_on_read_failure():
    class Boom(_FakeClient):
        def get_positions(self):
            raise RuntimeError("503")
    out = enforce_exit_hygiene(Boom([], []), _Log(), label="P3")
    assert out["errors"] and not out["orphans_cancelled"]


def test_p3_rearm_skips_symbols_mid_exit():
    import event_driven_bot as edb
    placed = []

    class C:
        def get_positions(self):
            return [{"symbol": "DDOG", "qty": "14", "side": "long", "current_price": "248"},
                    {"symbol": "TMO", "qty": "9", "side": "long", "current_price": "700"}]

        def get_orders(self, status="open"):
            # DDOG: a pending market close is protection too.
            return [_o("m", "DDOG", "sell", "market", qty="14")]

        def place_oco_order(self, sym, *a, **k):
            placed.append(sym)

        def place_order(self, **k):
            placed.append(k["symbol"])

    edb._rearm_protective_stops(C(), {}, exclude={"TMO"})
    assert placed == []


# ---------------------------------------------------------------------------
# P1 late-fill attribution
# ---------------------------------------------------------------------------

_ORDERS = [
    {"symbol": "AMD", "side": "buy", "status": "filled", "filled_at": "2026-07-06T15:16:32Z",
     "client_order_id": "p1mom-20260706-AMD-buy"},
    {"symbol": "IWM", "side": "buy", "status": "filled", "filled_at": "2026-06-02T14:00:00Z",
     "client_order_id": "p1core-20260602-IWM-buy"},
    {"symbol": "NVDA", "side": "buy", "status": "filled", "filled_at": "2026-06-10T14:00:00Z",
     "client_order_id": "p1-20260610-NVDA-buy"},
    {"symbol": "AMD", "side": "sell", "status": "filled", "filled_at": "2026-07-07T16:43:00Z",
     "client_order_id": "p1-20260707-AMD-sell"},
]
_PREFIX = {"p1mom": "momentum_sleeve", "p1core": "passive_core"}


def test_order_classes_from_client_order_id_prefix():
    assert order_classes_from_orders(_ORDERS, _PREFIX) == {
        "AMD": "momentum_sleeve", "IWM": "passive_core"}      # active "p1-" unmapped


def test_reconciled_late_fill_keeps_its_sleeve():
    log, actions = reconcile_log_to_broker(
        [], [{"symbol": "AMD", "qty": "9", "avg_entry_price": "562.4"}],
        order_classes={"AMD": "momentum_sleeve"})
    assert actions[0]["action"] == "add_unlogged"
    assert log[0]["order_class"] == "momentum_sleeve" and log[0]["reconciled"] is True


def test_unknown_provenance_lot_is_not_stopped_while_active_entries_off():
    lot = {"symbol": "AMD", "status": "open", "reconciled": True,
           "timestamp": "2026-07-06T21:48:14+00:00"}
    stops = {"AMD": {"side": "long", "unrealized_pnl_pct": -7.33, "current": 521.19}}
    assert is_schedule_managed(lot, active_entries_enabled=False) is True
    assert active_sleeve_exit_triggers(stops, [lot], active_entries_enabled=False) == []
    fired = active_sleeve_exit_triggers(stops, [lot], active_entries_enabled=True)
    assert fired and fired[0]["action"] == "HARD_STOP_SELL"


def test_momentum_lot_is_never_active_stopped():
    lot = {"symbol": "AMD", "status": "open", "order_class": "momentum_sleeve",
           "timestamp": "2026-07-01T00:00:00+00:00"}
    stops = {"AMD": {"side": "long", "unrealized_pnl_pct": -9.0, "current": 500.0}}
    assert active_sleeve_exit_triggers(stops, [lot], active_entries_enabled=True) == []


# ---------------------------------------------------------------------------
# Confirm-before-act semantics (controls-audit follow-up)
# ---------------------------------------------------------------------------

def test_small_glitch_below_plausibility_screen_is_still_caught_before_action():
    # A 6% phantom drop would trip P3's 5% daily-loss liquidation. The screen
    # (15%) lets it through, but the before-action call (max_jump_pct=0) must not.
    true_eq = 26_060.51 + _book_value()
    acct = {"equity": str(true_eq * 0.94), "cash": "26060.51"}
    assert confirm_equity(acct, _P1_POSITIONS, reference_equity=true_eq,
                          get_price=_px)["ok"] is True                 # screen only
    out = confirm_equity(acct, _P1_POSITIONS, reference_equity=true_eq,
                         get_price=_px, max_jump_pct=0.0)
    assert out["ok"] is False                                          # before acting


def test_one_unpriceable_name_falls_back_to_broker_mark_in_a_real_crash():
    cash = 26_060.51
    crashed = {s: p * 0.5 for s, p in _PX.items()}
    positions = [dict(p, market_value=str(float(p["qty"]) * crashed[p["symbol"]]))
                 for p in _P1_POSITIONS]
    true_eq = cash + sum(float(p["market_value"]) for p in positions)
    out = confirm_equity({"equity": str(true_eq), "cash": str(cash)}, positions,
                         reference_equity=cash + _book_value(), max_jump_pct=0.0,
                         get_price=lambda s: 0.0 if s == "MU" else crashed[s])
    assert out["ok"] is True and out["unpriced"] == ["MU"]


def test_majority_unpriceable_book_stays_unconfirmed():
    out = confirm_equity({"equity": "26060.51", "cash": "26060.51"}, _P1_POSITIONS,
                         reference_equity=92_583.88, max_jump_pct=0.0,
                         get_price=lambda s: 0.0)
    assert out["ok"] is False


# ---------------------------------------------------------------------------
# Signed reconciliation — the DDOG short that reported in_sync for two months
# ---------------------------------------------------------------------------

def test_short_position_never_matches_a_logged_long_lot():
    from shared.reconcile import compute_drift
    pos = [{"symbol": "DDOG", "qty": "-14", "side": "short", "avg_entry_price": "231.53"}]
    lots = [{"symbol": "DDOG", "side": "buy", "qty": 14, "entry_price": 231.53,
             "status": "open"}]
    rep = compute_drift(["DDOG"], ["DDOG"], positions=pos, open_trades=lots)
    assert rep["in_sync"] is False and rep["short_positions"] == ["DDOG"]
    assert rep["qty_drift"][0]["broker_qty"] == -14.0


def test_reconcile_closes_long_lot_and_never_relogs_a_short_as_a_buy():
    pos = [{"symbol": "DDOG", "qty": "-14", "side": "short", "avg_entry_price": "231.53"}]
    lots = [{"symbol": "DDOG", "side": "buy", "qty": 14, "entry_price": 267.21,
             "status": "open"}]
    log, actions = reconcile_log_to_broker(lots, pos)
    assert [a["action"] for a in actions] == ["close_orphan"]
    assert all(t.get("status") != "open" for t in log)                 # no fake long


def test_long_book_reconciliation_unchanged():
    pos = [{"symbol": "PSX", "qty": "30", "avg_entry_price": "178.82"}]
    lots = [{"symbol": "PSX", "side": "buy", "qty": 30, "entry_price": 178.82,
             "status": "open"}]
    log, actions = reconcile_log_to_broker(lots, pos)
    assert actions == [] and log[0]["status"] == "open"


# ---------------------------------------------------------------------------
# Heartbeat safety state — the halt and the short that nobody was told about
# ---------------------------------------------------------------------------

def test_heartbeat_alerts_on_latched_halt_and_on_short_in_long_only_book():
    from heartbeat import assess_safety_state
    alert, summary = assess_safety_state({
        "P1 Self Improving Brain": {"state": {"halted": True, "halt_until": None,
                                              "halt_reason": "Kill switch: 73.94% drawdown"},
                                    "recon": {"short_positions": []}},
        "P3 Cautious Sniper": {"state": {"halted": False},
                               "recon": {"short_positions": ["DDOG"]}},
    })
    assert alert is True
    assert "73.94%" in summary and "MANUAL REVIEW" in summary and "DDOG" in summary


def test_heartbeat_quiet_when_books_are_healthy():
    from heartbeat import assess_safety_state
    alert, _ = assess_safety_state({
        "P1 Self Improving Brain": {"state": {"halted": False}, "recon": {"short_positions": []}},
        "P3 Cautious Sniper": {"state": {"halted": False}, "recon": None},
    })
    assert alert is False


# ---------------------------------------------------------------------------
# P2 position age — PG bought and time-exited 2 seconds later as "116d old"
# ---------------------------------------------------------------------------

def test_p2_age_ignores_unfilled_and_closed_lots():
    from datetime import datetime
    P2_SCRIPTS = os.path.join(REPO_ROOT, "political-copy-bot", "scripts")
    if P2_SCRIPTS not in sys.path:
        sys.path.insert(0, P2_SCRIPTS)
    from politician_bot import position_age_days
    log = [  # the real PG history from political-copy-bot/data/trade_log.json
        {"symbol": "PG", "side": "buy", "status": "closed", "order_status": "pending_new",
         "timestamp": "2026-05-27T19:04:23.439955", "qty": 10},
        {"symbol": "PG", "side": "buy", "status": "closed", "order_status": "filled",
         "timestamp": "2026-08-24T14:24:47.488068", "qty": 21, "filled_qty": 21.0},
        {"symbol": "PG", "side": "sell", "status": "exit_marker",
         "timestamp": "2026-08-26T19:21:39.762755", "qty": 31},
        {"symbol": "PG", "side": "buy", "status": None, "order_status": "filled",
         "timestamp": "2026-09-21T14:25:07.420824", "qty": 21, "filled_qty": 21.0},
        {"symbol": "PG", "side": "buy", "status": None, "order_status": "pending_new",
         "timestamp": "2026-05-28T10:00:00", "qty": 5},          # never filled
    ]
    assert position_age_days(log, "PG", now=datetime(2026, 9, 21, 14, 25, 9)) == 0
    assert position_age_days(log, "PG", now=datetime(2026, 11, 23, 15, 0, 0)) == 63
    assert position_age_days(log, "KR", now=datetime(2026, 9, 21)) is None


# ---------------------------------------------------------------------------
# Human strategy controls — quarantine gates NEW entries only, fails closed
# ---------------------------------------------------------------------------

def test_strategy_controls_fail_closed_and_quarantine():
    from shared.strategy_controls import entries_enabled
    assert entries_enabled("portfolio_3", controls={})[0] is False           # missing book
    assert entries_enabled("portfolio_3", controls=None,
                           path="/nonexistent/controls.json")[0] is False    # missing file
    assert entries_enabled("portfolio_3", controls={"portfolio_3": {
        "new_entries_enabled": "yes"}})[0] is False                          # malformed
    ok, why = entries_enabled("portfolio_3", controls={"portfolio_3": {
        "new_entries_enabled": False, "reason": "IC~0, PF 0.64", "changed_at": "2026-10-03"}})
    assert ok is False and "QUARANTINED" in why and "IC~0" in why
    assert entries_enabled("portfolio_1", controls={"portfolio_1": {
        "new_entries_enabled": True}}) == (True, "enabled")


def test_committed_controls_file_is_valid_for_every_book():
    from shared.strategy_controls import load_controls
    c = load_controls()
    for pid in ("portfolio_1", "portfolio_2", "portfolio_3"):
        assert isinstance(c[pid]["new_entries_enabled"], bool)


def test_p3_quarantine_places_nothing(monkeypatch):
    import event_driven_bot as edb
    import shared.strategy_controls as sc
    monkeypatch.setattr(sc, "load_controls", lambda path=None: {
        "portfolio_3": {"new_entries_enabled": False, "reason": "test"}})

    class Boom:
        def __getattr__(self, name):
            raise AssertionError(f"broker touched: {name}")
    assert edb.execute_signals(Boom(), [{"symbol": "AAPL"}], "core_swing") == []
