"""Regression tests — P1 audit 2026-10-23 (C1, H1-H3, M1-M5, L1, L3).

Pure in-memory broker stubs; no network, no keys, no orders.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

import autonomous_runner as ar
import performance_tracker as pt
from portfolio_manager import schedule_managed_disaster_triggers
from risk_officer import drawdown_pct_from_peak, drawdown_reference_equity, validate_trade
from shared.strategy_controls import halt_clear_for, halt_clear_key, halt_clear_matches

LEGACY_REASON = "Kill switch: 73.94% drawdown"


# ---------------------------------------------------------------------------
# fixtures / stubs
# ---------------------------------------------------------------------------

@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ar, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ar, "JOURNAL_DIR", tmp_path)
    monkeypatch.setattr(pt, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ar.time, "sleep", lambda *_: None)
    return tmp_path


def _write(path, obj):
    path.write_text(json.dumps(obj))


def _read(path):
    return json.loads(path.read_text())


class Broker:
    """Configurable broker stub. ``equities`` is consumed one value per
    get_account() call (last value repeats)."""

    def __init__(self, equities=(97_000.0,), cash=60_000.0, positions=None, prices=None,
                 quotes=None, fills=None, orders_today=None):
        self.equities = list(equities)
        self.cash = cash
        self.positions = positions or []
        self.prices = prices or {}
        self.quotes = quotes or {}
        self.fills = fills or {}
        self.orders_today = orders_today or []
        self.placed = []
        self.open_orders = []
        self.canceled = []
        self.by_coid = {}
        self.closed_all = False
        self.account_reads = 0

    def is_market_open(self):
        return True

    def get_account(self):
        i = min(self.account_reads, len(self.equities) - 1)
        self.account_reads += 1
        e = self.equities[i]
        return {"equity": e, "cash": self.cash, "last_equity": e, "status": "ACTIVE",
                "portfolio_value": e, "account_number": "TEST"}

    def get_positions(self):
        return self.positions

    def get_position(self, sym):
        return next((p for p in self.positions if p["symbol"] == sym), None)

    def get_latest_trade(self, sym):
        return {"trade": {"p": self.prices.get(sym, 0)}}

    def get_latest_quote(self, sym):
        bp, ap = self.quotes.get(sym, (0, 0))
        return {"quote": {"bp": bp, "ap": ap}}

    def get_orders(self, status="open", after=None, limit=None, symbols=None):
        if status == "open":
            return [o for o in self.open_orders if o.get("id") not in self.canceled]
        return self.orders_today

    def cancel_order(self, oid):
        self.canceled.append(oid)

    def get_order_by_client_id(self, coid):
        return self.by_coid.get(coid, {})

    def place_order(self, **k):
        self.placed.append(k)
        return {"id": f"o{len(self.placed)}"}

    def get_order(self, oid):
        return self.fills.get(oid, {"status": "new", "filled_qty": "0"})

    def close_all_positions(self):
        self.closed_all = True

    def cancel_all_orders(self):
        pass


def _fake_confirm(results):
    """confirm_fill stand-in: results[order_id] -> (status, qty, price)."""
    def _cf(client, order_id, **_):
        return results.get(order_id, ("new", 0.0, None))
    return _cf


def _legacy_halted_state(**extra):
    st = {"starting_equity": 100_000.0, "equity": 97_150.12, "day_start_equity": 98_093.6,
          "week_start_equity": 97_970.98, "halted": True, "halt_reason": LEGACY_REASON,
          "halt_until": None}
    st.update(extra)
    return st


def _clear(**over):
    c = {"halt_reason_match": LEGACY_REASON, "reason": "phantom read 2026-07-07",
         "changed_at": "2026-10-23", "changed_by": "owner"}
    c.update(over)
    return c


# ---------------------------------------------------------------------------
# C1 — governed, evidence-based halt lifecycle
# ---------------------------------------------------------------------------

def test_halt_clear_reader_requires_key_and_provenance():
    ok = {"portfolio_1": {"new_entries_enabled": True, "halt_clear": _clear()}}
    clear, problem = halt_clear_for("portfolio_1", controls=ok)
    assert clear["halt_reason_match"] == LEGACY_REASON and problem is None
    no_key = {"portfolio_1": {"halt_clear": {"reason": "x", "changed_at": "d", "changed_by": "o"}}}
    assert halt_clear_for("portfolio_1", controls=no_key)[0] is None
    no_owner = {"portfolio_1": {"halt_clear": _clear(changed_by=None)}}
    clear, problem = halt_clear_for("portfolio_1", controls=no_owner)
    assert clear is None and "changed_by" in problem
    assert halt_clear_for("portfolio_1", controls={"portfolio_1": {}}) == (None, None)


def test_reason_clear_only_matches_legacy_unstamped_halt():
    assert halt_clear_matches(_clear(), _legacy_halted_state())[0] is True
    stamped = _legacy_halted_state(halt_set_at="2026-11-01T15:00:00+00:00")
    ok, why = halt_clear_matches(_clear(), stamped)
    assert ok is False and "legacy" in why
    keyed = _clear(clears_halt_set_at="2026-11-01T15:00:00+00:00", halt_reason_match=None)
    assert halt_clear_matches(keyed, stamped)[0] is True
    assert halt_clear_matches(keyed, _legacy_halted_state(halt_set_at="2026-12-01"))[0] is False
    consumed = _legacy_halted_state(halt_clears_consumed=[halt_clear_key(_clear())])
    assert halt_clear_matches(_clear(), consumed)[0] is False


def test_legacy_halt_flagged_unverified(data):
    st = _legacy_halted_state()
    assert ar.annotate_halt_verification(st) is False
    assert st["halt_verified"] is False and "UNVERIFIED HALT" in st["halt_unverified_reason"]
    assert ar.annotate_halt_verification({"halted": False}) is None


def test_kill_switch_latch_persists_full_evidence(data):
    st = {"starting_equity": 100_000.0, "peak_equity": 120_000.0}
    check = {"equity": 90_000.0, "cash": 10_000.0, "reference_equity": 119_000.0,
             "independent_equity": 90_100.0, "reason": "confirmed"}
    ar._latch_kill_switch(st, 25.0, check, source="intraday-monitor")
    ev = st["halt_evidence"]
    assert st["halted"] and st["halt_set_at"] and st["halt_kind"] == "kill_switch"
    assert ev["source"] == "intraday-monitor" and ev["drawdown_pct"] == 25.0
    assert ev["peak_reference_equity"] == 120_000.0 and ev["equity_reads"] == [90_000.0, 90_100.0]
    assert ar.annotate_halt_verification(st) is True


def test_halt_clear_applied_on_cross_checked_read_and_single_use(data, limits):
    st = _legacy_halted_state()
    book = [{"symbol": "AAA", "qty": "100", "side": "long", "market_value": "37000"}]
    br = Broker(equities=(97_000.0, 97_010.0), cash=60_000.0, positions=book,
                prices={"AAA": 370.0})
    controls = {"portfolio_1": {"new_entries_enabled": True, "halt_clear": _clear()}}

    assert ar.maybe_apply_halt_clear(br, st, limits, "trading-session", controls=controls)
    assert st["halted"] is False and st["halt_reason"] is None
    gov = _read(data / "halt_governance.json")
    assert gov[-1]["cleared_halt"]["halt_reason"] == LEGACY_REASON
    assert gov[-1]["verification"]["reads"] == [97_000.0, 97_010.0]
    assert gov[-1]["verified_equity"] == 97_000.0
    assert halt_clear_key(_clear()) in st["halt_clears_consumed"]

    # A FUTURE real halt (stamped, same reason text) is untouched by the stale block.
    ar._stamp_halt(st, kind="kill_switch", reason=LEGACY_REASON, source="t",
                   evidence={"equity": 1.0})
    assert not ar.maybe_apply_halt_clear(br, st, limits, "t", controls=controls)
    assert st["halted"] is True


def test_halt_clear_refused_on_inconsistent_reads(data, limits):
    st = _legacy_halted_state()
    br = Broker(equities=(97_000.0, 26_060.51))          # phantom second read
    controls = {"portfolio_1": {"halt_clear": _clear()}}
    assert not ar.maybe_apply_halt_clear(br, st, limits, "t", controls=controls)
    assert st["halted"] is True and st["halt_clear_last_attempt"]["applied"] is False
    assert not (data / "halt_governance.json").exists()


def test_halt_clear_refused_when_verified_drawdown_still_breaches(data, limits):
    st = _legacy_halted_state(peak_equity=130_000.0)
    br = Broker(equities=(100_000.0, 100_000.0), cash=100_000.0)   # 23% below peak
    controls = {"portfolio_1": {"halt_clear": _clear()}}
    assert not ar.maybe_apply_halt_clear(br, st, limits, "t", controls=controls)
    assert st["halted"] is True


def test_timed_halts_still_expire_kill_switch_does_not(data):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    st = {"halted": True, "halt_reason": "Daily loss: -4.5%", "halt_until": past}
    assert ar._expire_halt_if_due(st) and st["halted"] is False
    ks = _legacy_halted_state()
    assert not ar._expire_halt_if_due(ks) and ks["halted"] is True


# ---------------------------------------------------------------------------
# H1 — risk-reducing exits run while halted; entries do not
# ---------------------------------------------------------------------------

def _mom_lot(sym, oc="momentum_sleeve"):
    return {"id": 1, "symbol": sym, "status": "open", "order_class": oc, "qty": 10,
            "entry_price": 100.0, "side": "buy", "timestamp": "2026-07-06T14:00:00+00:00"}


def test_disaster_stop_fires_on_stop_exempt_momentum_lot():
    pos = [{"symbol": "CAT", "qty": "10", "side": "long", "avg_entry_price": "100",
            "current_price": "71.5"},
           {"symbol": "MSFT", "qty": "10", "side": "long", "avg_entry_price": "100",
            "current_price": "90"}]
    lots = [_mom_lot("CAT"), _mom_lot("MSFT")]
    trig = schedule_managed_disaster_triggers(pos, lots, {})
    assert [t["symbol"] for t in trig] == ["CAT"] and trig[0]["action"] == "DISASTER_STOP_SELL"
    # An invalid/zero param can never disable the floor.
    assert schedule_managed_disaster_triggers(pos, lots, {"momentum_disaster_stop_pct": 0})
    assert not schedule_managed_disaster_triggers(pos, lots, {"momentum_disaster_stop_pct": 30})
    # Active lots are NOT schedule-managed -> handled by their own stops, not this.
    assert not schedule_managed_disaster_triggers(pos, [_mom_lot("CAT", oc="simple")],
                                                  {"active_entries_enabled": True})


def _momentum_env(monkeypatch, data, targets):
    import momentum_selector
    _write(data / "strategy_params.json", {"momentum_sleeve_enabled": True,
                                           "momentum_top_k": 1, "momentum_vol_target": None})
    monkeypatch.setattr(ar, "_momentum_universe", lambda: (["AAA"], {"AAA": "tech"}))
    monkeypatch.setattr(momentum_selector, "select_top_momentum", lambda *a, **k: targets)


class MomBroker(Broker):
    def get_stock_bars(self, sym, **k):
        return {"bars": [{"c": 100.0}] * 300}


def _old_book():
    return [{"symbol": "OLD", "qty": "100", "side": "long", "market_value": "5000",
             "current_price": "50", "avg_entry_price": "60"}]


def test_momentum_exits_only_when_entries_blocked(data, monkeypatch, limits):
    _momentum_env(monkeypatch, data, {"AAA": 0.08})
    _write(data / "trade_log.json", [_mom_lot("OLD") | {"qty": 100, "entry_price": 60.0}])
    br = MomBroker(positions=_old_book(), quotes={"OLD": (50.0, 50.1), "AAA": (99.9, 100.0)})
    monkeypatch.setattr(ar, "confirm_fill", _fake_confirm({"o1": ("filled", 100.0, 49.95)}))

    assert ar.run_momentum_sleeve(br, 100_000.0, 60_000.0, {}, limits,
                                  budget=ar.TradeBudget(12), entries_allowed=False)
    assert [(o["symbol"], o["side"]) for o in br.placed] == [("OLD", "sell")]
    ms = _read(data / "momentum_state.json")
    assert ms["last_rebalance_month"] is None and ms["rebalance_incomplete"] is True
    lot = _read(data / "trade_log.json")[0]
    assert lot["status"] == "closed" and lot["exit_price"] == 49.95


def test_trading_session_halted_runs_preflight_then_exits_only(data, monkeypatch, limits):
    import analyst_v2
    import shared.preflight as spf
    _write(data / "risk_limits.json", limits)
    _write(data / "portfolio_state.json", _legacy_halted_state())
    calls = []
    monkeypatch.setattr(analyst_v2, "load_adaptive_params", lambda: {})
    monkeypatch.setattr(spf, "run_preflight",
                        lambda **k: (calls.append("preflight") or True,
                                     {"warnings": [], "hard_failures": []}))

    def _mom(alpaca, equity, cash, state, lim, budget=None, entries_allowed=True):
        calls.append(("momentum", entries_allowed, budget.cap))
        return True
    monkeypatch.setattr(ar, "run_momentum_sleeve", _mom)

    ar.run_trading_session(Broker(equities=(97_150.0,)))
    assert calls == ["preflight", ("momentum", False, 12)]
    st = _read(data / "portfolio_state.json")
    assert st["halted"] is True and st["halt_verified"] is False


# ---------------------------------------------------------------------------
# H2 — momentum counts against max_trades_per_day
# ---------------------------------------------------------------------------

def test_momentum_respects_trade_budget_sells_first(data, monkeypatch, limits):
    _momentum_env(monkeypatch, data, {"AAA": 0.08})
    br = MomBroker(positions=_old_book(), quotes={"OLD": (50.0, 50.1), "AAA": (99.9, 100.0)})
    monkeypatch.setattr(ar, "confirm_fill", _fake_confirm({"o1": ("filled", 100.0, 49.95)}))
    budget = ar.TradeBudget(12, used=11)                 # one slot left today

    ar.run_momentum_sleeve(br, 100_000.0, 60_000.0, {}, limits, budget=budget)
    assert [o["side"] for o in br.placed] == ["sell"] and budget.remaining == 0
    ms = _read(data / "momentum_state.json")
    assert ms["orders_deferred"][0]["why"] == "max_trades_per_day"
    assert ms["last_rebalance_month"] is None


def test_trade_budget_counts_todays_p1_broker_orders(data, limits):
    now = datetime.now(timezone.utc).isoformat()
    orders = [{"client_order_id": "p1mom-AAA-buy", "submitted_at": now}] * 5 + \
             [{"client_order_id": "p2-XYZ-buy", "submitted_at": now}]
    b = ar.build_trade_budget(Broker(orders_today=orders), limits, ar.et_session_date())
    assert b.used == 5 and b.remaining == 7


# ---------------------------------------------------------------------------
# H3 / L1 — exits booked at confirmed fills, FIFO, pending on no fill
# ---------------------------------------------------------------------------

def _two_lots(sym="XYZ"):
    return [{"id": 1, "symbol": sym, "status": "open", "qty": 6, "entry_price": 100.0,
             "side": "buy", "timestamp": "2026-10-01T14:00:00+00:00"},
            {"id": 2, "symbol": sym, "status": "open", "qty": 4, "entry_price": 110.0,
             "side": "buy", "timestamp": "2026-10-02T14:00:00+00:00"}]


def test_stop_exit_books_real_fill_fifo_and_pends_remainder(data, monkeypatch):
    _write(data / "trade_log.json", _two_lots())
    monkeypatch.setattr(ar, "confirm_fill", _fake_confirm({"o1": ("partially_filled", 8.0, 95.5)}))
    br = Broker(positions=[{"symbol": "XYZ", "qty": "10", "side": "long"}])
    res = ar.execute_exit(br, "XYZ", 10, reason="stop_loss", coid_prefix="p1stop", market=True)
    assert br.placed[0]["order_type"] == "market" and res["filled_qty"] == 8.0
    log = _read(data / "trade_log.json")
    assert log[0]["status"] == "closed" and log[0]["exit_price"] == 95.5
    assert log[1]["status"] == "open" and log[1]["qty"] == 2.0          # FIFO remainder
    assert _read(data / "pending_exits.json")[0]["order_id"] == "o1"
    assert _read(data / "booked_fills.json")["o1"]["qty"] == 8.0

    # EOD: the rest filled later -> booked at the INCREMENT's real price.
    br.fills["o1"] = {"status": "filled", "filled_qty": "10", "filled_avg_price": "95.0"}
    settled = ar.settle_pending_exits(br)
    assert settled[0]["qty"] == 2.0 and settled[0]["price"] == pytest.approx(93.0)
    assert _read(data / "pending_exits.json") == []
    assert all(t["status"] == "closed" for t in _read(data / "trade_log.json") if t["id"] in (1, 2))


def test_unfilled_exit_never_books_a_phantom_price(data, monkeypatch):
    _write(data / "trade_log.json", _two_lots())
    monkeypatch.setattr(ar, "confirm_fill", _fake_confirm({}))
    br = Broker(positions=[{"symbol": "XYZ", "qty": "10", "side": "long"}], quotes={"XYZ": (90.0, 90.2)})
    res = ar.execute_exit(br, "XYZ", 5, reason="take_profit", coid_prefix="p1tp")
    assert res["filled_qty"] == 0.0
    assert br.placed[0]["order_type"] == "limit" and br.placed[0]["limit_price"] == 89.91
    assert all(t["status"] == "open" for t in _read(data / "trade_log.json"))
    assert _read(data / "pending_exits.json")[0]["order_id"] == "o1"
    assert not (data / "booked_fills.json").exists()


def test_non_stop_exit_without_live_price_is_deferred_not_market(data):
    br = Broker()
    assert ar.execute_exit(br, "XYZ", 5, reason="active_time_stop", coid_prefix="p1time") is None
    assert br.placed == []


def test_marketable_limit_uses_live_quote_then_last_trade():
    br = Broker(quotes={"A": (10.0, 10.02)}, prices={"B": 20.0})
    assert ar.marketable_limit_price(br, "A", "sell") == 9.99
    assert ar.marketable_limit_price(br, "A", "buy") == 10.03
    assert ar.marketable_limit_price(br, "B", "sell") == 19.98      # no quote -> last trade
    assert ar.marketable_limit_price(br, "C", "buy") is None


# ---------------------------------------------------------------------------
# M1 — momentum month closes only on confirmed fills; limits off live quote
# ---------------------------------------------------------------------------

def test_momentum_month_open_until_fills_confirmed(data, monkeypatch, limits):
    _momentum_env(monkeypatch, data, {"AAA": 0.08})
    br = MomBroker(positions=[], quotes={"AAA": (101.9, 102.0)}, prices={"AAA": 100.0})
    monkeypatch.setattr(ar, "confirm_fill", _fake_confirm({}))     # nothing fills
    ar.run_momentum_sleeve(br, 100_000.0, 100_000.0, {}, limits, budget=ar.TradeBudget(12))
    assert br.placed[0]["limit_price"] == 102.1                     # live ask x 1.001, not close 100
    assert _read(data / "momentum_state.json")["last_rebalance_month"] is None

    monkeypatch.setattr(ar, "confirm_fill", _fake_confirm({"o2": ("filled", 72.0, 102.05)}))
    ar.run_momentum_sleeve(br, 100_000.0, 100_000.0, {}, limits, budget=ar.TradeBudget(12))
    assert _read(data / "momentum_state.json")["last_rebalance_month"] == ar.et_session_date()[:7]


# ---------------------------------------------------------------------------
# M2 / M3 — ET session calendar, EOD idempotency, ISO-week anchor
# ---------------------------------------------------------------------------

def test_et_session_date_crosses_utc_midnight():
    late = datetime(2026, 10, 23, 2, 30, tzinfo=timezone.utc)     # 22:30 EDT on the 22nd
    assert ar.et_session_date(late) == "2026-10-22"
    winter = datetime(2026, 12, 15, 4, 59, tzinfo=timezone.utc)   # 23:59 EST on the 14th
    assert ar.et_session_date(winter) == "2026-12-14"


def test_eod_is_idempotent_per_session(data):
    _write(data / "portfolio_state.json", {"last_eod_session_date": ar.et_session_date()})

    class Boom(Broker):
        def get_account(self):
            raise AssertionError("EOD must not run twice for one session")
    assert ar.run_end_of_day(Boom(), force=False) is False


def test_week_anchor_rolls_on_iso_week_to_prior_close():
    st = {"week_start_iso_week": "2026-W43", "week_start_equity": 95_000.0,
          "last_close_equity": 97_500.0, "last_close_session_date": "2026-10-23",
          "day_start_equity": 97_500.0}
    assert not ar.roll_session_anchors(st, "2026-10-23")             # same week
    assert ar.roll_session_anchors(st, "2026-10-26")                 # Monday, new week
    assert st["week_start_equity"] == 97_500.0 and st["week_start_iso_week"] == "2026-W44"
    fresh = {"week_start_equity": 95_000.0, "day_start_equity": 97_000.0}
    assert not ar.roll_session_anchors(fresh, "2026-10-22")          # stamp, no mid-week reset
    assert fresh["week_start_equity"] == 95_000.0 and fresh["week_start_iso_week"] == "2026-W43"


# ---------------------------------------------------------------------------
# M4 — every knob change gated; fail closed; log what happened
# ---------------------------------------------------------------------------

def _seed_tracker(tmp_path, monkeypatch, pnls):
    monkeypatch.setattr(pt, "DATA_DIR", str(tmp_path))
    _write(tmp_path / "strategy_params.json", {
        "position_size_multiplier": 1.0, "rsi_overbought": 70,
        "trailing_stop_atr_mult": 2.5, "confidence_buy_threshold": 0.50})
    now = datetime.now(timezone.utc).isoformat()
    _write(tmp_path / "trade_log.json", [
        {"id": i, "symbol": "AAA", "status": "closed", "pnl": p, "pnl_pct": p / 50,
         "exit_timestamp": now, "reasons": []} for i, p in enumerate(pnls)])


def test_no_bars_fails_closed_for_every_knob(tmp_path, monkeypatch):
    _seed_tracker(tmp_path, monkeypatch, [100.0] * 10)              # would lower the bar
    out = pt.adapt_parameters()
    assert out["updated_params"]["confidence_buy_threshold"] == 0.50
    d = out["param_decision"]
    assert d["approved"] is False and d["kept"] is False and d["proposed_changes"]


def test_derisk_change_rejected_by_gate_is_reverted_and_logged(tmp_path, monkeypatch):
    import backtest.walk_forward as wf
    _seed_tracker(tmp_path, monkeypatch, [50.0, 50.0] + [-100.0] * 6)   # losing book
    monkeypatch.setattr(wf, "gate_param_change", lambda *a, **k: (False, {"reason": "worse"}))
    out = pt.adapt_parameters(validate_with_bars=({"AAA": []}, []))
    p = out["updated_params"]
    assert p["position_size_multiplier"] == 1.0 and p["confidence_buy_threshold"] == 0.50
    assert p["trailing_stop_atr_mult"] == 2.5 and p["risk_off_active"] is True
    entry = _read(tmp_path / "param_change_log.json")[-1]
    assert entry["approved"] is False and entry["n_changes"] == 0   # nothing rejected was kept


def test_approved_change_kept_and_logged_approved(tmp_path, monkeypatch):
    import backtest.walk_forward as wf
    _seed_tracker(tmp_path, monkeypatch, [50.0, 50.0] + [-100.0] * 6)
    monkeypatch.setattr(wf, "gate_param_change", lambda *a, **k: (True, {"approved": True}))
    out = pt.adapt_parameters(validate_with_bars=({"AAA": []}, []))
    assert out["updated_params"]["position_size_multiplier"] < 1.0
    entry = _read(tmp_path / "param_change_log.json")[-1]
    assert entry["approved"] is True and entry["n_changes"] >= 1


# ---------------------------------------------------------------------------
# M5 — drawdown from the confirmed high-water mark
# ---------------------------------------------------------------------------

def test_drawdown_reference_is_confirmed_peak(portfolio, limits):
    st = {"starting_equity": 100_000.0, "peak_equity": 130_000.0}
    assert drawdown_reference_equity(st) == 130_000.0
    assert drawdown_pct_from_peak(st, 106_000.0) == pytest.approx(18.4615, rel=1e-3)
    assert drawdown_reference_equity({"starting_equity": 100_000.0}) == 100_000.0
    p = dict(portfolio, equity=106_000.0, day_start_equity=106_000.0,
             week_start_equity=106_000.0, peak_equity=130_000.0)
    sig = {"symbol": "AAA", "signal": "BUY", "indicators": {"price": 10.0},
           "risk_management": {"suggested_position_pct": 2.0}}
    r = validate_trade(sig, p, limits)
    assert r["approved"] is False and "KILL SWITCH" in r["rejections"][0]


def test_monitor_kill_switch_measures_from_peak(data, limits):
    _write(data / "risk_limits.json", limits)
    _write(data / "portfolio_state.json", {
        "starting_equity": 100_000.0, "peak_equity": 130_000.0, "equity": 106_000.0,
        "day_start_equity": 106_000.0, "halted": False})
    br = Broker(equities=(106_000.0,), cash=106_000.0)
    ar.run_intraday_monitor(br)
    st = _read(data / "portfolio_state.json")
    assert br.closed_all is True and st["halt_kind"] == "kill_switch"
    assert st["halt_evidence"]["peak_reference_equity"] == 130_000.0


def test_peak_raised_only_on_cross_checked_read(data):
    book = [{"symbol": "AAA", "qty": "100", "side": "long", "market_value": "50000"}]
    st = {"starting_equity": 100_000.0, "day_start_equity": 100_000.0}
    good = Broker(equities=(110_000.0, 110_200.0), cash=60_000.0, positions=book,
                  prices={"AAA": 500.0})
    assert ar.update_peak_equity(good, st, good.get_account(), book, 100_000.0)
    assert st["peak_equity"] == 110_000.0
    st2 = {"starting_equity": 100_000.0, "day_start_equity": 100_000.0}
    phantom = Broker(equities=(140_000.0, 140_000.0), cash=60_000.0, positions=book,
                     prices={"AAA": 500.0})                          # book says $110K
    assert not ar.update_peak_equity(phantom, st2, phantom.get_account(), book, 100_000.0)
    assert "peak_equity" not in st2


# ---------------------------------------------------------------------------
# L3 — partial trims excluded from win-rate
# ---------------------------------------------------------------------------

def test_partial_tp_then_smaller_losing_exit_is_one_winning_whole_trade(tmp_path, monkeypatch):
    """Codex #3 exact example: +$100 partial TP (5 @ $120 from $100), then the
    final 5 exit at $90 (-$50). ONE trade, net about +$50 on $1,000 cost -> a WIN."""
    monkeypatch.setattr(pt, "DATA_DIR", str(tmp_path))
    _write(tmp_path / "trade_log.json", [
        {"id": 1, "symbol": "AAA", "status": "open", "qty": 10, "entry_price": 100.0,
         "side": "buy", "timestamp": "2026-10-01T14:00:00+00:00", "bucket": "momentum"}])
    pt.reduce_open_position("AAA", 5, 120.0, reason="take_profit")
    log = _read(tmp_path / "trade_log.json")
    assert log[-1]["partial_trim"] is True and log[-1]["parent_id"] == 1
    m_open = pt.compute_metrics()
    assert m_open["total_trades"] == 0                               # lot still open
    assert m_open["total_pnl"] == pytest.approx(log[-1]["pnl"])      # trim P&L still booked
    pt.reduce_open_position("AAA", 5, 90.0, reason="stop")
    log = _read(tmp_path / "trade_log.json")
    whole = log[-1]["pnl"] + log[0]["pnl"]
    m = pt.compute_metrics()
    assert m["total_trades"] == 1 and m["wins"] == 1 and m["win_rate"] == 1.0
    assert m["avg_pnl_pct"] == pytest.approx(whole / 1000.0 * 100, abs=0.01)  # original basis
    assert m["expectancy"] == pytest.approx(whole, abs=0.01)
    assert m["total_pnl"] == pytest.approx(whole, abs=0.01)
    assert pt.compute_metrics_by_bucket()["momentum"]["win_rate"] == 1.0


def test_whole_trade_links_legacy_slices_by_id_and_by_entry_key():
    parent = {"id": 7, "symbol": "B", "status": "closed", "qty": 5, "entry_price": 10.0,
              "timestamp": "t0", "pnl": -5.0, "exit_timestamp": "2026-10-20"}
    by_id = dict(parent, id="7-trim-x", qty=5, pnl=20.0, status="closed",
                 exit_timestamp="2026-10-10")                       # legacy: no flag/parent_id
    p2 = {"id": None, "symbol": "C", "status": "closed", "qty": 2, "entry_price": 50.0,
          "timestamp": "t1", "pnl": -1.0, "exit_timestamp": "2026-10-21"}
    by_key = dict(p2, id="x", partial_trim=True, pnl=6.0, exit_timestamp="2026-10-11")
    done, partial = pt.whole_trades([parent, by_id, p2, by_key])
    got = {w["symbol"]: round(w["pnl"], 2) for w in done}
    assert got == {"B": 15.0, "C": 5.0} and partial == []
    # Window by FINAL exit: both trades end inside it even though a slice is older.
    assert len(pt.whole_trades([parent, by_id], cutoff="2026-10-15")[0]) == 1


def test_codex1_exit_beyond_logged_lots_keeps_unmatched_remainder(data):
    _write(data / "trade_log.json", [_two_lots()[0]])                # only 6 sh logged
    assert ar.book_exit_fill("e1", "XYZ", 10, 95.0, "stop_loss") == 6.0
    assert _read(data / "booked_fills.json")["e1"]["qty"] == 6.0     # ledger = booked only
    um = _read(data / "unmatched_exits.json")["e1"]
    assert um["unmatched_qty"] == 4.0
    # The late entry (4 sh) settles at EOD even though the position is gone,
    # and the remainder then books against it — once.
    _write(data / "pending_entries.json", [{"order_id": "b1", "symbol": "XYZ", "qty": 4,
                                            "bucket": "momentum", "order_class": "momentum_sleeve"}])
    br = Broker()
    br.fills["b1"] = {"status": "filled", "filled_qty": "4", "filled_avg_price": "100"}
    summary = ar.run_settlement(br, [])
    assert summary["unmatched_exits"] == 0 and summary["error"] is None
    assert _read(data / "booked_fills.json")["e1"]["qty"] == 10.0
    assert ar.retry_unmatched_exits() == 0.0
    closed = [t for t in _read(data / "trade_log.json") if t["status"] == "closed"]
    assert sum(t["qty"] for t in closed) == 10


def test_codex2_later_eod_still_settles_but_journal_runs_once(data, monkeypatch):
    _write(data / "portfolio_state.json", {"last_eod_session_date": ar.et_session_date(),
                                           "last_eod_completed_at": "x"})
    _write(data / "trade_log.json", _two_lots())
    _write(data / "pending_exits.json", [{"order_id": "p9", "symbol": "XYZ", "qty": 10,
                                          "reason": "stop_loss"}])
    monkeypatch.setattr(pt, "adapt_parameters",
                        lambda **k: (_ for _ in ()).throw(AssertionError("learning re-ran")))

    class NoAccount(Broker):
        def get_account(self):
            raise AssertionError("journal path must not re-run")
    br = NoAccount()
    br.fills["p9"] = {"status": "filled", "filled_qty": "10", "filled_avg_price": "95"}
    assert ar.run_end_of_day(br, force=False) is False
    assert _read(data / "pending_exits.json") == []
    assert all(t["status"] == "closed" for t in _read(data / "trade_log.json"))
    st = _read(data / "portfolio_state.json")
    assert st["eod_settlement"]["pending_exits"] == 0 and st["eod_settlement"]["error"] is None

    # Nothing outstanding -> a further run is a pure no-op (no broker calls at all).
    class Boom(Broker):
        def get_positions(self):
            raise AssertionError("no settlement needed")
    assert ar.run_end_of_day(Boom(), force=False) is False


def test_codex2_failed_settlement_is_retried_by_a_later_run(data, monkeypatch):
    _write(data / "portfolio_state.json", {"last_eod_session_date": ar.et_session_date(),
                                           "eod_settlement": {"error": "exits: boom"}})
    called = []
    monkeypatch.setattr(ar, "run_settlement",
                        lambda a, p: called.append(1) or {"error": None})
    ar.run_end_of_day(Broker(), force=False)
    assert called == [1]
    assert _read(data / "portfolio_state.json")["eod_settlement"]["error"] is None


def test_daily_loss_never_overwrites_a_kill_switch_halt(data, limits):
    """A daily-loss latch used to stamp a 24h expiry over a permanent kill-switch
    halt, silently converting it into a timed one."""
    _write(data / "risk_limits.json", limits)
    st = _legacy_halted_state(day_start_equity=100_000.0, equity=95_000.0)
    _write(data / "portfolio_state.json", st)
    br = Broker(equities=(95_000.0,), cash=95_000.0)
    ar.run_intraday_monitor(br)
    after = _read(data / "portfolio_state.json")
    assert after["halted"] is True and after["halt_reason"] == LEGACY_REASON
    assert after["halt_until"] is None and after["halt_verified"] is False


# ---------------------------------------------------------------------------
# Adversarial-review follow-ups (items 1-8)
# ---------------------------------------------------------------------------

import requests  # noqa: E402


def _http_422():
    r = requests.Response()
    r.status_code = 422
    r._content = b'{"message":"rejected"}'
    return requests.HTTPError(response=r)


class Rejecting(Broker):
    def place_order(self, **k):
        self.placed.append(k)
        raise _http_422()


def test_item1_stop_exit_cancels_working_sell_and_sizes_to_available(data, monkeypatch):
    _write(data / "trade_log.json", _two_lots())
    br = Broker(positions=[{"symbol": "XYZ", "qty": "7", "qty_available": "7"}])
    br.open_orders = [{"id": "w1", "symbol": "XYZ", "side": "sell"},
                      {"id": "b1", "symbol": "XYZ", "side": "buy"}]
    monkeypatch.setattr(ar, "confirm_fill", _fake_confirm(
        {"w1": ("canceled", 3.0, 101.0), "o1": ("filled", 7.0, 95.0)}))
    res = ar.execute_exit(br, "XYZ", 10, reason="stop_loss", coid_prefix="p1stop", market=True)
    assert br.canceled == ["w1"]                              # only the working SELL
    assert br.placed[0]["qty"] == 7 and br.placed[0]["order_type"] == "market"
    assert res["filled_qty"] == 7.0
    led = _read(data / "booked_fills.json")
    assert led["w1"]["qty"] == 3.0 and led["o1"]["qty"] == 7.0  # partial fill booked once
    assert all(t["status"] == "closed" for t in _read(data / "trade_log.json")
               if t["id"] in (1, 2))


def test_item2_422_without_prior_order_is_an_error(data):
    _write(data / "trade_log.json", _two_lots())
    br = Rejecting(positions=[{"symbol": "XYZ", "qty": "10", "side": "long"}])
    with pytest.raises(requests.HTTPError):
        ar.execute_exit(br, "XYZ", 5, reason="stop_loss", coid_prefix="p1stop", market=True)
    assert all(t["status"] == "open" for t in _read(data / "trade_log.json"))


def test_item2_422_duplicate_resolves_prior_order_and_books_once(data):
    _write(data / "trade_log.json", _two_lots())
    br = Rejecting(positions=[{"symbol": "XYZ", "qty": "10", "side": "long"}])
    coid = ar.make_client_order_id("p1stop", "XYZ", "sell")
    br.by_coid[coid] = {"id": "prior1", "status": "filled", "filled_qty": "10",
                        "filled_avg_price": "95"}
    res = ar.execute_exit(br, "XYZ", 10, reason="stop_loss", coid_prefix="p1stop", market=True)
    assert res["order_id"] == "prior1" and res["filled_qty"] == 10.0
    ar.execute_exit(br, "XYZ", 10, reason="stop_loss", coid_prefix="p1stop", market=True)
    closed = [t for t in _read(data / "trade_log.json") if t["status"] == "closed"]
    assert len(closed) == 2 and _read(data / "booked_fills.json")["prior1"]["qty"] == 10.0


def test_item2_momentum_422_rejection_is_failure_not_placed(data, monkeypatch, limits):
    _momentum_env(monkeypatch, data, {"AAA": 0.08})

    class MomReject(Rejecting, MomBroker):
        pass
    br = MomReject(positions=[], quotes={"AAA": (99.9, 100.0)})
    budget = ar.TradeBudget(12)
    ar.run_momentum_sleeve(br, 100_000.0, 100_000.0, {}, limits, budget=budget)
    ms = _read(data / "momentum_state.json")
    assert ms["orders_placed"] == 0 and "rejected" in ms["orders_deferred"][0]["why"]
    assert budget.used == 0 and ms["last_rebalance_month"] is None


def test_item3_july7_phantom_empty_book_never_latches_or_liquidates(data, limits):
    """2026-07-07: equity == cash ($26,060.51) and the broker returned NO
    positions — confirm_equity "confirms" that (cash == equity). Must refuse."""
    _write(data / "risk_limits.json", limits)
    st = {"starting_equity": 100_000.0, "equity": 92_583.88, "day_start_equity": 92_583.88,
          "halted": False, "positions": {"NVDA": {"qty": 100, "avg_price": 400.0}}}
    _write(data / "portfolio_state.json", st)
    _write(data / "trade_log.json", [{"id": 1, "symbol": "NVDA", "status": "open", "qty": 100,
                                      "entry_price": 400.0, "side": "buy",
                                      "timestamp": "2026-07-06T14:00:00+00:00"}])
    br = Broker(equities=(26_060.51,), cash=26_060.51, positions=[])
    ar.run_intraday_monitor(br)
    after = _read(data / "portfolio_state.json")
    assert br.closed_all is False and after["halted"] is False

    _write(data / "portfolio_state.json", st)
    ar.run_trading_session(Broker(equities=(26_060.51,), cash=26_060.51, positions=[]))
    assert _read(data / "portfolio_state.json")["halted"] is False


def test_item3_latch_requires_two_consistent_reads(data, limits):
    _write(data / "risk_limits.json", limits)
    _write(data / "portfolio_state.json", {"starting_equity": 100_000.0,
                                           "day_start_equity": 100_000.0, "halted": False})
    br = Broker(equities=(80_000.0, 99_000.0), cash=80_000.0)   # second read disagrees
    ar.run_intraday_monitor(br)
    assert br.closed_all is False
    assert _read(data / "portfolio_state.json")["halted"] is False


def test_item4_late_momentum_buy_fill_settled_once_at_eod(data, monkeypatch, limits):
    _momentum_env(monkeypatch, data, {"AAA": 0.08})
    br = MomBroker(positions=[], quotes={"AAA": (99.9, 100.0)})
    monkeypatch.setattr(ar, "confirm_fill", _fake_confirm({}))   # fills after the window
    ar.run_momentum_sleeve(br, 100_000.0, 100_000.0, {}, limits, budget=ar.TradeBudget(12))
    pend = _read(data / "pending_entries.json")
    assert pend[0]["symbol"] == "AAA" and pend[0]["order_class"] == "momentum_sleeve"

    br.fills["o1"] = {"status": "filled", "filled_qty": "72", "filled_avg_price": "100.05"}
    held = [{"symbol": "AAA", "qty": "72", "side": "long"}]
    assert ar.settle_pending_entries(br, held)[0]["qty"] == 72.0
    _write(data / "pending_entries.json", pend)                   # replay: must not double
    assert ar.settle_pending_entries(br, held) == []
    lots = [t for t in _read(data / "trade_log.json") if t["symbol"] == "AAA"]
    assert len(lots) == 1 and lots[0]["order_class"] == "momentum_sleeve"
    assert lots[0]["entry_price"] == 100.05


def test_item4_settle_never_doubles_a_lot_reconcile_already_logged(data):
    _write(data / "trade_log.json", [{"id": 1, "symbol": "AAA", "status": "open", "qty": 72,
                                      "entry_price": 100.0, "side": "buy",
                                      "timestamp": "2026-10-23T14:00:00+00:00"}])
    _write(data / "pending_entries.json", [{"order_id": "o1", "symbol": "AAA", "qty": 72}])
    br = Broker()
    br.fills["o1"] = {"status": "filled", "filled_qty": "72", "filled_avg_price": "100.05"}
    assert ar.settle_pending_entries(br, [{"symbol": "AAA", "qty": "72"}]) == []
    assert len(_read(data / "trade_log.json")) == 1


def test_item4_disaster_floor_covers_held_sleeve_names_without_lots():
    pos = [{"symbol": "UNL", "qty": "10", "side": "long", "avg_entry_price": "100",
            "current_price": "70"},
           {"symbol": "ACT", "qty": "10", "side": "long", "avg_entry_price": "100",
            "current_price": "70"},
           {"symbol": "MOM", "qty": "10", "side": "long", "avg_entry_price": "100",
            "current_price": "70"}]
    lots = [_mom_lot("ACT", oc="simple"), _mom_lot("MOM", oc="simple")]
    params = {"active_entries_enabled": True}
    hit = {t["symbol"] for t in schedule_managed_disaster_triggers(
        pos, lots, params, sleeve_symbols={"MOM"})}
    assert hit == {"UNL", "MOM"}          # no-lot name + sleeve name; active name left to its stops


def test_item6_existing_kill_switch_halt_is_not_restamped(data):
    st = {"starting_equity": 100_000.0}
    chk = {"equity": 80_000.0, "independent_equity": 80_000.0, "reason": "ok"}
    ar._latch_kill_switch(st, 20.0, chk, source="a")
    set_at, ev = st["halt_set_at"], dict(st["halt_evidence"])
    clear = _clear(clears_halt_set_at=set_at, halt_reason_match=None)
    assert ar._latch_kill_switch(st, 22.0, chk, source="b") is False
    assert st["halt_set_at"] == set_at and st["halt_evidence"] == ev
    assert st["halt_observations"][-1]["drawdown_pct"] == 22.0
    assert halt_clear_matches(clear, st)[0] is True


def test_item7_fill_booking_is_idempotent_by_order_id(data):
    _write(data / "trade_log.json", _two_lots())
    assert ar.book_exit_fill("x1", "XYZ", 6, 95.0, "stop_loss") == 6.0
    # A new lot opens; a replay of the same fill must not touch it.
    log = _read(data / "trade_log.json")
    log.append({"id": 3, "symbol": "XYZ", "status": "open", "qty": 5, "entry_price": 90.0,
                "side": "buy", "timestamp": "2026-10-23T15:00:00+00:00"})
    _write(data / "trade_log.json", log)
    assert ar.book_exit_fill("x1", "XYZ", 6, 95.0, "stop_loss") == 0.0
    assert next(t for t in _read(data / "trade_log.json") if t["id"] == 2)["status"] == "open"


def test_item7_eod_legacy_reconcile_skips_pending_and_booked_orders(data, monkeypatch):
    _write(data / "portfolio_state.json", {"day_start_equity": 97_000.0})
    _write(data / "trade_log.json", _two_lots())
    _write(data / "pending_exits.json", [{"order_id": "p9", "symbol": "XYZ", "qty": 10,
                                          "reason": "stop_loss"}])
    monkeypatch.setattr(pt, "adapt_parameters", lambda **k: {
        "metrics_7d": {"win_rate": None}, "metrics_30d": {"win_rate": None},
        "updated_params": {}})
    monkeypatch.setattr(pt, "generate_learning_report", lambda: {"insights": []})
    monkeypatch.setattr(ar, "reconcile_positions", lambda a: {})

    class PollFails(Broker):
        def get_order(self, oid):
            raise RuntimeError("poll down")
    br = PollFails(orders_today=[{"id": "p9", "symbol": "XYZ", "side": "sell",
                                  "filled_qty": "10", "filled_avg_price": "95"}])
    assert ar.run_end_of_day(br, force=True)
    assert all(t["status"] == "open" for t in _read(data / "trade_log.json"))
    assert _read(data / "pending_exits.json")[0]["order_id"] == "p9"

    # Next EOD: poll works -> settlement books it exactly once.
    br2 = Broker()
    br2.fills["p9"] = {"status": "filled", "filled_qty": "10", "filled_avg_price": "95"}
    ar.settle_pending_exits(br2)
    ar.settle_pending_exits(br2)
    assert sum(1 for t in _read(data / "trade_log.json") if t["status"] == "closed") == 2


def test_item8_unknown_broker_count_freezes_entries_not_exits(data, monkeypatch, limits):
    class NoCount(Broker):
        def get_orders(self, status="open", **k):
            if status == "all":
                raise RuntimeError("orders endpoint down")
            return []
    b = ar.build_trade_budget(NoCount(), limits, ar.et_session_date())
    assert b.entries_frozen and b.entry_remaining == 0
    assert b.take(entry=True) is False and b.take() is True

    _momentum_env(monkeypatch, data, {"AAA": 0.08})
    br = MomBroker(positions=_old_book(), quotes={"OLD": (50.0, 50.1), "AAA": (99.9, 100.0)})
    monkeypatch.setattr(ar, "confirm_fill", _fake_confirm({"o1": ("filled", 100.0, 49.95)}))
    ar.run_momentum_sleeve(br, 100_000.0, 60_000.0, {}, limits,
                           budget=ar.TradeBudget(12, entries_frozen=True))
    assert [o["side"] for o in br.placed] == ["sell"]
    assert "frozen" in _read(data / "momentum_state.json")["orders_deferred"][0]["why"]


# ---------------------------------------------------------------------------
# After-audit simulation follow-ups (H1/H2, M1-M5, L1-L4)
# ---------------------------------------------------------------------------

import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cat_lot(entry=1003.0, qty=5, oc="momentum_sleeve"):
    return {"id": "cat1", "symbol": "CAT", "status": "open", "qty": qty, "entry_price": entry,
            "side": "buy", "order_class": oc, "timestamp": "2026-07-06T14:00:00+00:00"}


def test_sim_h1_disaster_floor_is_per_lot_not_blended_average():
    # 5 @ $1003 then a rebalance add of 4 @ $704 -> blended ~$870, now $716.
    pos = [{"symbol": "CAT", "qty": "9", "side": "long", "avg_entry_price": "870",
            "current_price": "716"}]
    lots = [_cat_lot(), dict(_cat_lot(entry=704.0, qty=4), id="cat2")]
    t = schedule_managed_disaster_triggers(pos, lots, {})
    assert t and t[0]["basis_price"] == 1003.0 and t[0]["pnl_pct"] < -28


def test_sim_h1_session_runs_disaster_before_momentum_and_excludes_name(data, monkeypatch, limits):
    import analyst_v2
    import shared.preflight as spf
    _write(data / "risk_limits.json", limits)
    _write(data / "portfolio_state.json", {"starting_equity": 100_000.0,
                                           "day_start_equity": 97_000.0, "halted": False})
    _write(data / "trade_log.json", [_cat_lot()])
    calls = []
    monkeypatch.setattr(analyst_v2, "load_adaptive_params", lambda: {})
    monkeypatch.setattr(spf, "run_preflight", lambda **k: (True, {"warnings": [],
                                                                  "hard_failures": []}))
    monkeypatch.setattr(ar, "confirm_fill", _fake_confirm({"o1": ("filled", 5.0, 716.0)}))

    def _mom(alpaca, *a, **k):
        calls.append(("momentum", sorted(ar.disaster_excluded(ar.et_session_date()[:7]))))
        return True
    monkeypatch.setattr(ar, "run_momentum_sleeve", _mom)
    cat = [{"symbol": "CAT", "qty": "5", "qty_available": "5", "side": "long",
            "avg_entry_price": "1003", "current_price": "716", "market_value": "3580"}]
    br = Broker(equities=(97_000.0,), positions=cat, prices={"CAT": 716.0})
    ar.run_trading_session(br)
    assert br.placed[0]["symbol"] == "CAT" and br.placed[0]["order_type"] == "market"
    assert calls == [("momentum", ["CAT"])]                      # exit first, then excluded


def test_sim_h1_momentum_never_buys_a_disaster_excluded_name(data, monkeypatch, limits):
    _momentum_env(monkeypatch, data, {"CAT": 0.08})
    ar._record_disaster_exclusion("CAT")
    br = MomBroker(positions=[], quotes={"CAT": (715.0, 716.0)})
    ar.run_momentum_sleeve(br, 100_000.0, 100_000.0, {}, limits, budget=ar.TradeBudget(12))
    assert br.placed == []


def test_sim_h2_no_position_means_no_order_on_either_path(data):
    for market in (True, False):
        br = Broker(quotes={"XYZ": (10.0, 10.1)})
        assert ar.execute_exit(br, "XYZ", 10, reason="r", coid_prefix="p1stop",
                               market=market) is None
        assert br.placed == []
    br = Broker(positions=[{"symbol": "XYZ", "qty": "3", "side": "long"}],
                quotes={"XYZ": (10.0, 10.1)})
    ar.execute_exit(br, "XYZ", 10, reason="r", coid_prefix="p1tp")
    assert br.placed[0]["qty"] == 3                              # never more than held


def test_sim_m3_incomplete_month_retries_frozen_targets(data, monkeypatch, limits):
    import momentum_selector
    _momentum_env(monkeypatch, data, {"AAA": 0.08})
    br = MomBroker(positions=[], quotes={"AAA": (99.9, 100.0), "BBB": (49.9, 50.0)},
                   prices={"AAA": 100.0, "BBB": 50.0})
    ar.run_momentum_sleeve(br, 100_000.0, 100_000.0, {}, limits, budget=ar.TradeBudget(12))
    frozen_at = _read(data / "momentum_state.json")["targets_frozen_at"]
    monkeypatch.setattr(momentum_selector, "select_top_momentum",
                        lambda *a, **k: {"BBB": 0.08})            # today's ranking moved
    ar.run_momentum_sleeve(br, 100_000.0, 100_000.0, {}, limits, budget=ar.TradeBudget(12))
    assert {o["symbol"] for o in br.placed} == {"AAA"}            # no whipsaw into BBB
    ms = _read(data / "momentum_state.json")
    assert set(ms["targets"]) == {"AAA"} and ms["targets_frozen_at"] == frozen_at


def test_sim_m4_trade_ids_unique_and_legacy_ids_still_close(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "DATA_DIR", str(tmp_path))
    _write(tmp_path / "trade_log.json", [{"id": 1, "symbol": "OLD", "status": "open", "qty": 1,
                                          "entry_price": 10.0, "side": "buy",
                                          "timestamp": "2026-10-01T14:00:00+00:00"}])
    a = pt.log_trade("AAA", "buy", 1, 10.0, "momentum", None, [])
    b = pt.log_trade("AAA", "buy", 1, 10.0, "momentum", None, [])
    assert isinstance(a, str) and a != b and len(a) == 32
    pt.close_trade(a, 11.0, reason="t")
    pt.close_trade(1, 9.0, reason="t")
    st = {t["id"]: t["status"] for t in _read(tmp_path / "trade_log.json")}
    assert st == {1: "closed", a: "closed", b: "open"}


def test_sim_l2_intraday_regime_requests_explicit_start():
    seen = {}

    class B:
        def get_stock_bars(self, symbol, timeframe="1Day", start=None, limit=220):
            seen["start"] = start
            return {"bars": [{"c": 100.0 + i} for i in range(220)]}
    ar.refresh_intraday_regime(B(), {}, {"market_regime": "BULL"})
    assert seen["start"] and seen["start"] < ar.et_session_date()


def test_sim_l4_zero_jump_threshold_always_corroborates():
    from shared.equity_guard import confirm_equity
    acct = {"equity": 100_000.0, "cash": 100_000.0}
    out = confirm_equity(acct, [], reference_equity=100_000.0, get_price=lambda s: 0,
                         max_jump_pct=0.0)
    assert out["independent_equity"] == 100_000.0 and out["ok"]


def test_sim_l3_p2_non_stop_exits_are_marketable_limits():
    sys.path.insert(0, os.path.join(REPO_ROOT, "political-copy-bot", "scripts"))
    import politician_bot as pb

    class Q:
        def __init__(self, bp, p):
            self.bp, self.p = bp, p

        def get_latest_quote(self, s):
            return {"quote": {"bp": self.bp}}

        def get_latest_trade(self, s):
            return {"trade": {"p": self.p}}
    assert pb.exit_limit_price(Q(50.0, 0), "X") == 49.95
    assert pb.exit_limit_price(Q(0, 20.0), "X") == 19.98
    assert pb.exit_limit_price(Q(0, 0), "X") is None
    src = open(os.path.join(REPO_ROOT, "political-copy-bot", "scripts", "politician_bot.py")).read()
    for kind in ('"tx"', '"mh"', '"tp"'):
        i = src.index(f"exit_client_order_id({kind}, symbol)")
        assert 'order_type="market"' not in src[i - 700:i], kind


# --- commit_and_push.sh in a temp git repo (M1 / M2 / L1) ---------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
PSJ, TLJ, BFJ, SGJ = ("data/portfolio_state.json", "data/trade_log.json",
                      "data/booked_fills.json", "data/signals.json")


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


def _origin(tmp_path, files):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    _git(seed, "checkout", "-q", "-b", "main")
    for rel, content in files.items():
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed / rel).write_text(json.dumps(content, indent=2))
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", "origin", "main")
    return origin


def _clone(tmp_path, origin, name):
    _git(tmp_path, "clone", "-q", "-b", "main", str(origin), str(tmp_path / name))
    return tmp_path / name


def _push(repo, files):
    for rel, content in files.items():
        (repo / rel).write_text(json.dumps(content, indent=2))
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "newer")
    _git(repo, "push", "-q", "origin", "main")


def _commit_script(repo):
    return subprocess.run(["bash", os.path.join(REPO_ROOT, "scripts", "commit_and_push.sh"),
                           "P1: test", "data"], cwd=repo, capture_output=True, text=True)


def _remote(tmp_path, origin, rel):
    chk = _clone(tmp_path, origin, f"chk{len(list(tmp_path.iterdir()))}")
    p = chk / rel
    return json.loads(p.read_text()) if p.exists() else None


@needs_git
def test_sim_m1_newer_snapshot_cannot_erase_a_halt_latched_after_our_base(tmp_path):
    origin = _origin(tmp_path, {PSJ: {"last_updated": "2026-10-23T14:00:00+00:00",
                                      "halted": False, "equity": 1}})
    stale = _clone(tmp_path, origin, "stale")
    _push(_clone(tmp_path, origin, "monitor"), {PSJ: {
        "last_updated": "2026-10-23T14:30:00+00:00", "halted": True,
        "halt_reason": "Kill switch: 19.00% drawdown", "halt_set_at": "2026-10-23T14:30:00+00:00"}})
    (stale / PSJ).write_text(json.dumps({"last_updated": "2026-10-23T14:40:00+00:00",
                                         "halted": False, "equity": 2}))
    r = _commit_script(stale)
    assert r.returncode == 1 and "halt" in r.stdout, r.stdout + r.stderr
    assert _remote(tmp_path, origin, PSJ)["halted"] is True


@needs_git
def test_sim_m1_governed_clear_of_that_exact_halt_may_win(tmp_path):
    halt = {"halted": True, "halt_reason": "Kill switch: 73.94% drawdown", "halt_set_at": None}
    origin = _origin(tmp_path, {PSJ: {"last_updated": "2026-10-23T14:00:00+00:00", **halt}})
    ours_repo = _clone(tmp_path, origin, "ours")
    _push(_clone(tmp_path, origin, "monitor"), {PSJ: {
        "last_updated": "2026-10-23T14:30:00+00:00", **halt,
        "halt_observations": [{"at": "2026-10-23T14:30:00+00:00"}]}})
    (ours_repo / PSJ).write_text(json.dumps({
        "last_updated": "2026-10-23T14:40:00+00:00", "halted": False, "halt_reason": None,
        "last_halt": {"halt_reason": halt["halt_reason"], "halt_set_at": None,
                      "ended": "human_clear"}}))
    r = _commit_script(ours_repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _remote(tmp_path, origin, PSJ)["halted"] is False


@needs_git
def test_sim_l1_offset_aware_snapshot_compare(tmp_path):
    origin = _origin(tmp_path, {PSJ: {"last_updated": "2026-10-23T14:00:00+00:00", "equity": 1}})
    ours_repo = _clone(tmp_path, origin, "ours")
    _push(_clone(tmp_path, origin, "other"), {PSJ: {"last_updated": "2026-10-23T14:40:00Z",
                                                    "equity": 2}})
    # 11:00 EDT == 15:00Z: NEWER, though it sorts lower as a string.
    (ours_repo / PSJ).write_text(json.dumps({"last_updated": "2026-10-23T11:00:00-04:00",
                                             "equity": 3}))
    r = _commit_script(ours_repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _remote(tmp_path, origin, PSJ)["equity"] == 3


@needs_git
def test_sim_m2_ledger_group_is_withheld_atomically(tmp_path):
    origin = _origin(tmp_path, {TLJ: [{"id": 1, "status": "open"}], BFJ: {},
                                SGJ: {"timestamp": "2026-10-22T13:00:00+00:00"}})
    stale = _clone(tmp_path, origin, "stale")
    _push(_clone(tmp_path, origin, "newer"), {TLJ: [{"id": 1, "status": "closed", "by": "newer"}]})
    (stale / TLJ).write_text(json.dumps([{"id": 1, "status": "closed", "by": "stale"}]))
    (stale / BFJ).write_text(json.dumps({"o1": {"qty": 5}}))
    (stale / SGJ).write_text(json.dumps({"timestamp": "2026-10-23T13:00:00+00:00"}))
    r = _commit_script(stale)
    assert r.returncode == 1, r.stdout + r.stderr
    assert _remote(tmp_path, origin, BFJ) == {}                    # withheld WITH trade_log
    assert _remote(tmp_path, origin, TLJ)[0]["by"] == "newer"
    assert _remote(tmp_path, origin, SGJ)["timestamp"].startswith("2026-10-23")  # not in group


# --- Guardian P1 freshness uses the broker as ground truth (M5) ---------------

def _guardian_script():
    text = open(os.path.join(REPO_ROOT, ".github", "workflows", "guardian.yml")).read()
    tag = "cat > \"$RUNNER_TEMP/guardian_fresh.py\" << 'PY'\n"
    start = text.index(tag) + len(tag)
    end = text.index("\n          PY\n", start)
    return "\n".join(ln[10:] if ln.startswith(" " * 10) else ln.strip()
                     for ln in text[start:end].splitlines()) + "\n"


@needs_git
def test_sim_m5_guardian_p1_fresh_when_broker_has_todays_session_order(tmp_path):
    origin = _origin(tmp_path, {"data/signals.json": {"timestamp": "2026-01-02T15:00:00+00:00"}})
    repo = _clone(tmp_path, origin, "g")
    (repo / "config").mkdir()
    (repo / "config" / "alpaca_config.json").write_text(json.dumps(
        {"api_key": "k", "api_secret": "s", "base_url": "https://fake"}))
    fake = tmp_path / "fakemods"
    fake.mkdir()
    script = tmp_path / "guardian_fresh.py"
    script.write_text(_guardian_script())
    env = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}
    env["PYTHONPATH"] = str(fake)
    for coid, expect in (("p1stop-20261023-CAT-sell", 1), ("p1mom-20261023-AMD-buy", 0)):
        (fake / "requests.py").write_text(
            "class _R:\n"
            "    def raise_for_status(self): pass\n"
            f"    def json(self): return [{{'client_order_id': '{coid}'}}]\n"
            "def get(*a, **k): return _R()\n")
        r = subprocess.run([sys.executable, str(script), "p1"], cwd=repo, env=env,
                           capture_output=True, text=True)
        assert r.returncode == expect, (coid, r.stdout + r.stderr)
