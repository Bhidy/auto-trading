"""P3 crisis_core_v1 allocator sleeve — PAPER FORWARD TEST (2026-10-23).

Drives ``event-driven-bot/scripts/allocator.py`` against a fake broker with the
data/config dirs pointed at tmp, so the committed state is never touched and no
real order is ever placed. Covers: human-owned enablement (fail closed), the
explicit 7.6/11.4 scaling (no symbol > 8% at the live/limit price), band and
drift behaviour, the shared 15-trade budget with deterministic ordering, halt =>
no buys but trims, legacy lots never traded, same-session idempotency, month
completion only on full fills, client_order_id shape, 422 handling, no phantom
fills, P3 gross-exposure clipping, and cloud-path purity.
"""
import ast
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P3_SCRIPTS = os.path.join(REPO_ROOT, "event-driven-bot", "scripts")
for _p in (REPO_ROOT, P3_SCRIPTS, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import allocator as A  # noqa: E402
from shared.strategy_controls import allocator_control  # noqa: E402

NOW = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)      # Fri 10:00 ET
NEXT = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)     # Mon 10:00 ET
NOV = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)       # Mon 10:00 EST

P3_LIMITS = json.load(open(os.path.join(REPO_ROOT, "event-driven-bot", "config",
                                        "risk_limits.json")))

ENABLED = {"portfolio_3": {
    "new_entries_enabled": False, "reason": "quarantined", "changed_at": "2026-10-03",
    "changed_by": "owner",
    "allocator": {"strategy": "crisis_core_v1", "mode": "paper_forward_test",
                  "enabled": True, "scale_to_cap": True, "reason": "forward test",
                  "changed_at": "2026-10-23", "changed_by": "owner-delegated lead"}}}

PRICES = {"SPY": 600.0, "QQQ": 520.0, "IWM": 230.0, "EFA": 90.0, "DBMF": 28.0,
          "KMLM": 27.0, "CTA": 29.0, "IEF": 95.0, "BIL": 91.5, "SHV": 110.0,
          "SGOV": 100.5, "USFR": 50.3, "ANET": 140.0, "KO": 70.0}


def _http_error(code, text):
    resp = requests.Response()
    resp.status_code = code
    resp._content = text.encode()
    return requests.HTTPError(f"{code}", response=resp)


class FakeBroker:
    base_url = "https://paper-api.alpaca.markets"

    def __init__(self, equity=100_000.0, cash=100_000.0, positions=None, *,
                 market_open=True, fill="filled", missing_bars=(), existing=None):
        self.equity, self.cash = equity, cash
        self.positions = {p["symbol"]: dict(p) for p in (positions or [])}
        self.market_open = market_open
        self.fill = fill              # filled | accepted | partial_canceled | partial_working
        self.missing_bars = set(missing_bars)
        self.orders = {}              # id -> order
        self.by_coid = dict(existing or {})
        self.placed = []
        self.reject_422 = set()       # coids that 422 with NO broker record
        self.race = {}                # coid -> order that appears at placement time

    # --- account / market --------------------------------------------------
    def get_account(self):
        return {"equity": str(self.equity), "cash": str(self.cash),
                "last_equity": str(self.equity), "status": "ACTIVE"}

    def is_market_open(self):
        return self.market_open

    def get_positions(self):
        out = []
        for s, p in self.positions.items():
            q = float(p["qty"])
            out.append({"symbol": s, "qty": str(q), "side": "long",
                        "current_price": str(PRICES[s]),
                        "market_value": str(q * PRICES[s])})
        return out

    def get_orders(self, status="open", after=None, limit=None):
        return [o for o in self.orders.values()
                if status != "open" or o["status"] in ("new", "accepted", "partially_filled")]

    def get_latest_trade(self, s):
        return {"trade": {"p": PRICES[s]}}

    def get_latest_quote(self, s):
        return {"quote": {"bp": round(PRICES[s] * 0.9998, 4), "ap": round(PRICES[s] * 1.0002, 4)}}

    def get_stock_bars(self, s, timeframe="1Day", start=None, limit=50, end=None):
        if s in self.missing_bars:
            return {"bars": []}
        return {"bars": [{"t": "2026-10-21T04:00:00Z", "c": PRICES[s] * 0.99},
                         {"t": "2026-10-22T04:00:00Z", "c": PRICES[s]},
                         {"t": "2026-10-23T04:00:00Z", "c": PRICES[s] * 1.01}]}

    # --- orders ------------------------------------------------------------
    def place_order(self, symbol, qty=None, side="buy", order_type="market",
                    limit_price=None, time_in_force="day", client_order_id=None, **kw):
        assert order_type == "limit" and time_in_force == "day" and limit_price
        if client_order_id in self.reject_422:
            raise _http_error(422, '{"message":"insufficient buying power"}')
        if client_order_id in self.race:
            # Another run placed this exact id after our broker check (a race).
            o = self.race.pop(client_order_id)
            self.orders[o["id"]] = o
            self.by_coid[client_order_id] = o
        if client_order_id in self.by_coid:
            raise _http_error(422, '{"message":"client_order_id must be unique"}')
        oid = f"o-{client_order_id}"
        o = {"id": oid, "client_order_id": client_order_id, "symbol": symbol,
             "side": side, "qty": str(qty), "limit_price": str(limit_price),
             "status": "accepted", "filled_qty": "0", "filled_avg_price": None}
        self.orders[oid] = o
        self.by_coid[client_order_id] = o
        self.placed.append(o)
        self._apply_fill_mode(o)
        return dict(o)

    def _apply_fill_mode(self, o):
        q = float(o["qty"])
        px = PRICES[o["symbol"]]  # real fill at the market, NOT the limit
        if self.fill == "filled":
            self._fill(o, q, px, "filled")
        elif self.fill == "partial_canceled":
            self._fill(o, max(1.0, q // 2), px, "canceled")
        elif self.fill == "partial_working":
            self._fill(o, max(1.0, q // 2), px, "partially_filled")
        # "accepted": nothing fills

    def _fill(self, o, q, px, status):
        o.update(status=status, filled_qty=str(q), filled_avg_price=str(px))
        sign = 1 if o["side"] == "buy" else -1
        p = self.positions.setdefault(o["symbol"], {"symbol": o["symbol"], "qty": 0.0})
        p["qty"] = float(p["qty"]) + sign * q
        if p["qty"] <= 0:
            self.positions.pop(o["symbol"])
        self.cash -= sign * q * px

    def get_order(self, oid):
        return dict(self.orders[oid])

    def get_order_by_client_id(self, coid):
        if coid in self.by_coid:
            return dict(self.by_coid[coid])
        raise _http_error(404, '{"message":"order not found"}')


def _confirm(broker, oid):
    o = broker.get_order(oid)
    fap = o.get("filled_avg_price")
    return o["status"], float(o.get("filled_qty") or 0), (float(fap) if fap else None)


@pytest.fixture
def env(tmp_path):
    (tmp_path / "risk_limits.json").write_text(json.dumps(P3_LIMITS))
    (tmp_path / "bot_state.json").write_text(json.dumps({"halted": False}))
    (tmp_path / "trade_log.json").write_text("[]")
    return tmp_path


def run(broker, d, now=NOW, controls=ENABLED):
    return A.run_allocator(broker, data_dir=d, config_dir=d, controls=controls,
                           now=now, confirm=_confirm)


def tlog(d):
    return json.loads((d / "trade_log.json").read_text())


def state(d):
    return json.loads((d / "allocator_state.json").read_text())


def params():
    return A.build_params(P3_LIMITS)


# ---------------------------------------------------------------------------
# Enablement — human-owned, fail closed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("controls", [
    {},
    {"portfolio_3": {"new_entries_enabled": False}},
    {"portfolio_3": {"allocator": "yes"}},
    {"portfolio_3": {"allocator": dict(ENABLED["portfolio_3"]["allocator"], enabled="true")}},
    {"portfolio_3": {"allocator": dict(ENABLED["portfolio_3"]["allocator"], enabled=False)}},
    {"portfolio_3": {"allocator": dict(ENABLED["portfolio_3"]["allocator"], strategy="matf_v1")}},
    {"portfolio_3": {"allocator": dict(ENABLED["portfolio_3"]["allocator"], mode="live")}},
    {"portfolio_3": {"allocator": dict(ENABLED["portfolio_3"]["allocator"], scale_to_cap=False)}},
    {"portfolio_3": {"allocator": dict(ENABLED["portfolio_3"]["allocator"], changed_by="")}},
])
def test_disabled_or_malformed_control_places_no_orders(env, controls):
    b = FakeBroker()
    out = run(b, env, controls=controls)
    assert out["status"] == "disabled"
    assert b.placed == []
    assert not (env / "allocator_state.json").exists()
    assert allocator_control("portfolio_3", controls=controls) is None


def test_missing_controls_file_fails_closed(tmp_path):
    problems = []
    assert allocator_control("portfolio_3", path=tmp_path / "nope.json", problems=problems) is None
    assert problems and "disabled" in problems[0]


def test_valid_control_is_returned_and_live_file_has_no_block_yet():
    assert allocator_control("portfolio_3", controls=ENABLED)["strategy"] == "crisis_core_v1"
    # The lead adds the block by hand; code never writes it.
    live = json.load(open(os.path.join(REPO_ROOT, "config", "strategy_controls.json")))
    assert isinstance(live["portfolio_3"].get("new_entries_enabled"), bool)


def test_non_paper_endpoint_is_refused(env):
    b = FakeBroker()
    b.base_url = "https://api.alpaca.markets"
    assert run(b, env)["status"] == "refused_not_paper" and b.placed == []


def test_market_closed_places_nothing(env):
    b = FakeBroker(market_open=False)
    assert run(b, env)["status"] == "market_closed" and b.placed == []


# ---------------------------------------------------------------------------
# Scaling math
# ---------------------------------------------------------------------------

def test_scale_is_explicit_and_derived_from_the_cap():
    p = params()
    assert p["hard_cap"] == pytest.approx(0.08)
    assert p["live_cap"] == pytest.approx(0.076)
    assert p["scale"] == pytest.approx(0.076 / 0.114)
    assert p["band"] == pytest.approx(0.02 * 0.076 / 0.114)       # ~1.333% absolute
    assert p["drift_trigger"] == pytest.approx(0.08)              # 12% x scale
    # A different headroom is a different explicit parameter, not a hidden constant.
    p2 = A.build_params(P3_LIMITS, drift_headroom=0.01)
    assert p2["scale"] == pytest.approx(0.07 / 0.114)


def test_scaled_targets_match_spec_times_scale():
    raw = A.spec_target_weights(set(A.UNIVERSE))
    t = A.scale_targets(raw, params())
    for s in ("SPY", "QQQ", "IWM", "EFA", "DBMF", "KMLM", "CTA", "IEF"):
        assert raw[s] == pytest.approx(0.114) and t[s] == pytest.approx(0.076)
    assert raw["BIL"] == pytest.approx(0.088) and t["BIL"] == pytest.approx(0.088 * 0.076 / 0.114)
    assert set(t) == {"SPY", "QQQ", "IWM", "EFA", "DBMF", "KMLM", "CTA", "IEF", "BIL"}
    assert sum(t.values()) == pytest.approx(2 / 3, abs=1e-6)
    assert max(t.values()) <= 0.076 + 1e-12


def test_bad_cap_config_fails_closed(env):
    (env / "risk_limits.json").write_text(json.dumps({"max_trades_per_day": 15}))
    b = FakeBroker()
    assert run(b, env)["status"] == "limits_invalid" and b.placed == []


def test_initial_build_no_symbol_over_8pct_at_live_or_limit_price(env):
    b = FakeBroker()
    out = run(b, env)
    assert out["status"] == "month_complete"
    assert len(b.placed) == 9                    # 8 risky ETFs + BIL
    for o in b.placed:
        q, lim = float(o["qty"]), float(o["limit_price"])
        px = max(lim, PRICES[o["symbol"]])
        assert q == int(q) and q >= 1           # whole shares
        assert q * px <= 0.076 * b.equity + 1e-6 < 0.08 * b.equity
        assert lim == pytest.approx(round(PRICES[o["symbol"]] * 1.0002 * 1.0025, 2), abs=0.011)
    st = state(env)
    assert st["last_rebalance_month"] == "2026-10" and st["targets_frozen_at"] == "2026-10-22"


# ---------------------------------------------------------------------------
# Band / drift (pure planner)
# ---------------------------------------------------------------------------

def _prices(*syms):
    return {s: {"last": PRICES[s], "buy_limit": round(PRICES[s] * 1.003, 2),
                "sell_limit": round(PRICES[s] * 0.997, 2)} for s in syms}


def test_band_suppresses_small_diffs_and_trades_large_ones():
    p = params()
    eq = 100_000.0
    t = {"SPY": 0.076}
    # 7.0% held vs 7.6% target: |0.6%| < 1.333% band => no trade
    sells, buys, _ = A.plan_rebalance(t, eq, {"SPY": 7000 / 600}, {}, _prices("SPY"), p)
    assert sells == [] and buys == []
    # 6.0% held: 1.6% gap >= band => buy up toward 7.6%
    sells, buys, _ = A.plan_rebalance(t, eq, {"SPY": 10.0}, {}, _prices("SPY"), p)
    assert sells == [] and len(buys) == 1
    assert (10 + buys[0]["qty"]) * max(600, buys[0]["limit_price"]) <= 0.076 * eq


def test_above_live_cap_trades_regardless_of_band_and_target_zero_exits():
    p = params()
    eq = 100_000.0
    # 7.8% held vs 7.6% target: inside the band, but above live cap => trim
    sells, _, _ = A.plan_rebalance({"SPY": 0.076}, eq, {"SPY": 13.0}, {}, _prices("SPY"), p)
    assert len(sells) == 1 and sells[0]["reason"] == "cap_trim"
    assert (13 - sells[0]["qty"]) * 600 <= 0.076 * eq
    # Symbol dropped from targets with holdings => sell all allocator qty
    sells, _, _ = A.plan_rebalance({}, eq, {"KMLM": 50.0}, {}, _prices("KMLM"), p)
    assert sells[0]["qty"] == 50.0 and sells[0]["reason"] == "exit"


def test_drift_guard_only_trims_above_8pct():
    p = params()
    eq = 100_000.0
    t = {"SPY": 0.076, "QQQ": 0.076}
    alloc = {"SPY": 14.0, "QQQ": 10.0}            # SPY 8.4% (> 8%), QQQ 5.2% (band-wide gap)
    sells, buys, _ = A.plan_rebalance(t, eq, alloc, {}, _prices("SPY", "QQQ"), p, drift_only=True)
    assert [s["symbol"] for s in sells] == ["SPY"] and buys == []
    assert sells[0]["reason"] == "drift_trim"


# ---------------------------------------------------------------------------
# Trade budget + deterministic ordering
# ---------------------------------------------------------------------------

def _legacy_rows_today(n):
    return [{"symbol": f"L{i}", "side": "buy", "qty": 1, "date": "2026-10-23",
             "tranche": "core_swing", "status": "closed"} for i in range(n)]


def test_initial_build_respects_shared_15_trade_cap_with_deterministic_order(env):
    (env / "trade_log.json").write_text(json.dumps(_legacy_rows_today(7)))   # 8 slots left
    b = FakeBroker()
    out = run(b, env)
    syms = [o["symbol"] for o in b.placed]
    # |delta w| desc (8 x 7.6% tie -> alphabetical), BIL (5.87%) deferred.
    assert syms == ["CTA", "DBMF", "EFA", "IEF", "IWM", "KMLM", "QQQ", "SPY"]
    assert out["deferred"] == ["BIL:buy"]
    assert out["status"] == "month_in_progress"
    assert state(env)["last_rebalance_month"] is None
    # Leftover is placed next session against the SAME frozen targets.
    out2 = run(b, env, now=NEXT)
    assert [o["symbol"] for o in b.placed[8:]] == ["BIL"]
    assert out2["status"] == "month_complete"
    assert state(env)["targets_frozen_at"] == "2026-10-22"


def test_ordering_is_deterministic_across_runs(tmp_path):
    seqs = []
    for k in range(2):
        d = tmp_path / str(k)
        d.mkdir()
        (d / "risk_limits.json").write_text(json.dumps(P3_LIMITS))
        (d / "trade_log.json").write_text("[]")
        b = FakeBroker()
        run(b, d)
        seqs.append([o["client_order_id"] for o in b.placed])
    assert seqs[0] == seqs[1]


def test_sells_go_first_and_consume_the_budget_first(env):
    lots = [{"symbol": "SPY", "side": "buy", "qty": 16.0, "entry_price": 500.0,
             "date": "2026-10-01", "status": "open", "tranche": A.TRANCHE}]
    (env / "trade_log.json").write_text(json.dumps(_legacy_rows_today(14) + lots))  # 1 slot
    b = FakeBroker(positions=[{"symbol": "SPY", "qty": 16.0}])
    run(b, env)
    assert [(o["symbol"], o["side"]) for o in b.placed] == [("SPY", "sell")]


# ---------------------------------------------------------------------------
# Halt => no buys, trims allowed; legacy never traded
# ---------------------------------------------------------------------------

def test_halted_book_blocks_buys_but_allows_trims(env):
    halt_until = (NOW + timedelta(hours=12)).isoformat()
    (env / "bot_state.json").write_text(json.dumps(
        {"halted": True, "halt_reason": "Kill switch", "halt_until": halt_until}))
    lots = [{"symbol": "SPY", "side": "buy", "qty": 15.0, "entry_price": 500.0,
             "date": "2026-10-01", "status": "open", "tranche": A.TRANCHE}]
    (env / "trade_log.json").write_text(json.dumps(lots))
    b = FakeBroker(positions=[{"symbol": "SPY", "qty": 15.0}])        # 9% > 7.6%
    out = run(b, env)
    assert [o["side"] for o in b.placed] == ["sell"]
    assert out["buys_blocked"].startswith("P3 halted")
    assert out["status"] == "month_in_progress"


def test_daily_loss_at_kill_switch_blocks_buys(env):
    (env / "bot_state.json").write_text(json.dumps(
        {"halted": False, "day_start_date": "2026-10-23", "day_start_equity": 106_000}))
    b = FakeBroker()                                  # 100k vs 106k = -5.7%
    out = run(b, env)
    assert b.placed == [] and "daily loss" in out["buys_blocked"]


def test_legacy_symbols_and_lots_are_never_traded(env):
    legacy = [{"symbol": "ANET", "side": "buy", "qty": 43, "entry_price": 171.0,
               "status": "open", "tranche": "core_swing"},
              {"symbol": "SPY", "side": "buy", "qty": 15, "entry_price": 500.0,
               "status": "open", "tranche": "core_swing"}]           # legacy SPY = 9%
    (env / "trade_log.json").write_text(json.dumps(legacy))
    b = FakeBroker(positions=[{"symbol": "ANET", "qty": 43}, {"symbol": "SPY", "qty": 15}],
                   cash=100_000 - 43 * 140 - 15 * 600)
    run(b, env)
    traded = {o["symbol"] for o in b.placed}
    assert "ANET" not in traded
    assert "SPY" not in traded          # over cap via LEGACY: no buy, and never sells legacy
    assert all(o["side"] == "buy" for o in b.placed)
    rows = tlog(env)
    assert [r for r in rows if r["symbol"] in ("ANET", "SPY")] == legacy


# ---------------------------------------------------------------------------
# Idempotency, client_order_ids, 422
# ---------------------------------------------------------------------------

def test_rerun_same_session_places_zero_new_orders(env):
    b = FakeBroker()
    run(b, env)
    n = len(b.placed)
    out = run(b, env, now=NOW + timedelta(minutes=45))
    assert out["status"] == "already_ran_today" and len(b.placed) == n
    rows = [r for r in tlog(env) if r.get("tranche") == A.TRANCHE]
    assert len(rows) == n == len({r["order_id"] for r in rows})


def test_client_order_ids_prefixed_unique_and_deterministic(env):
    b = FakeBroker()
    run(b, env)
    coids = [o["client_order_id"] for o in b.placed]
    assert len(coids) == len(set(coids))
    assert all(c.startswith("p3alloc-20261023-") and c.endswith("-buy") for c in coids)


def _race_order(coid="p3alloc-20261023-SPY-buy"):
    return coid, {"id": "prior-1", "client_order_id": coid, "symbol": "SPY", "side": "buy",
                  "qty": "12", "status": "filled", "filled_qty": "12",
                  "filled_avg_price": "599.5"}


def test_422_duplicate_is_recorded_pending_never_booked_in_the_racing_run(env):
    coid, existing = _race_order()
    b = FakeBroker()
    b.race[coid] = existing
    run(b, env)
    rec = state(env)["orders"][coid]
    assert rec["duplicate"] is True and rec["order_id"] == "prior-1" and not rec["booked"]
    assert not [r for r in tlog(env) if r["symbol"] == "SPY"]      # not booked here
    # Settlement (EOD / next run, on the merged log) books it exactly once.
    assert A.settle_allocator_orders(b, env, now=NOW) == 1
    spy = [r for r in tlog(env) if r["symbol"] == "SPY"]
    assert len(spy) == 1 and spy[0]["order_id"] == "prior-1" and spy[0]["entry_price"] == 599.5
    assert A.settle_allocator_orders(b, env, now=NOW) == 0


def test_422_order_already_booked_by_the_other_run_is_never_booked_again(env):
    coid, existing = _race_order()
    b = FakeBroker()
    b.race[coid] = existing
    run(b, env)
    # The other run's commit (with its booking) merges into our trade log first.
    rows = tlog(env) + [{"symbol": "SPY", "side": "buy", "qty": 12.0, "entry_price": 599.5,
                         "order_id": "prior-1", "status": "open", "tranche": A.TRANCHE}]
    (env / "trade_log.json").write_text(json.dumps(rows))
    A.settle_allocator_orders(b, env, now=NOW)
    assert len([r for r in tlog(env) if r.get("order_id") == "prior-1"]) == 1


def test_broker_orders_unknown_to_state_mean_a_stale_checkout_do_nothing(env):
    coid, existing = _race_order()
    b = FakeBroker(existing={coid: existing})
    b.orders["prior-1"] = existing
    out = run(b, env)
    assert out["status"] == "concurrent_run_detected" and out["foreign"] == [coid]
    assert b.placed == [] and not (env / "allocator_state.json").exists()
    assert tlog(env) == []
    assert not A.run_failed(out)


def test_broker_order_history_unavailable_fails_closed(env):
    class B(FakeBroker):
        def get_orders(self, status="open", after=None, limit=None):
            raise RuntimeError("503")
    b = B()
    out = run(b, env)
    assert out["status"] == "broker_orders_unavailable" and b.placed == []
    assert A.run_failed(out)


def test_duplicate_rows_for_one_order_id_count_once_and_are_voided(env):
    row = {"symbol": "SPY", "side": "buy", "qty": 12.0, "entry_price": 599.5,
           "order_id": "o1", "status": "open", "tranche": A.TRANCHE, "timestamp": "a"}
    dup = dict(row, timestamp="b")                    # same fill booked by two runs
    assert A.allocator_holdings([row, dup]) == {"SPY": 12.0}
    log_ = [row, dup]
    assert A.void_duplicate_allocator_rows(log_) == 1
    assert log_[0]["status"] == "open" and log_[1]["status"] == "void_duplicate"
    assert A.allocator_holdings(log_) == {"SPY": 12.0}


def test_422_without_broker_record_is_a_rejection_not_a_duplicate(env):
    b = FakeBroker()
    b.reject_422.add("p3alloc-20261023-QQQ-buy")
    out = run(b, env)
    rec = state(env)["orders"]["p3alloc-20261023-QQQ-buy"]
    assert rec["status"] == "rejected_422" and not rec.get("order_id")
    assert not [r for r in tlog(env) if r["symbol"] == "QQQ"]
    assert out["status"] == "month_in_progress"       # a rejection never completes a month


# ---------------------------------------------------------------------------
# Fills: real prices only, month done only when all filled
# ---------------------------------------------------------------------------

def test_unfilled_order_is_pending_never_booked_at_a_phantom_price(env):
    b = FakeBroker(fill="accepted")
    out = run(b, env)
    assert out["status"] == "month_in_progress"
    assert [r for r in tlog(env) if r.get("tranche") == A.TRANCHE] == []
    assert all(r.get("pending") for r in state(env)["orders"].values())
    # The broker later fills SPY at its real price; EOD settlement books THAT.
    spy = next(o for o in b.orders.values() if o["symbol"] == "SPY")
    spy.update(status="filled", filled_qty=spy["qty"], filled_avg_price="598.25")
    for o in b.orders.values():
        if o["symbol"] != "SPY":
            o.update(status="expired")
    assert A.settle_allocator_orders(b, env, now=NOW) == 9
    rows = [r for r in tlog(env) if r.get("tranche") == A.TRANCHE]
    assert len(rows) == 1 and rows[0]["entry_price"] == 598.25
    assert rows[0]["entry_price"] != float(spy["limit_price"])
    assert A.settle_allocator_orders(b, env, now=NOW) == 0       # idempotent


def test_partial_terminal_fill_books_filled_qty_only_and_month_stays_open(env):
    b = FakeBroker(fill="partial_canceled")
    out = run(b, env)
    assert out["status"] == "month_in_progress"
    for r in [r for r in tlog(env) if r.get("tranche") == A.TRANCHE]:
        o = b.orders[r["order_id"]]
        assert r["qty"] == float(o["filled_qty"]) < float(o["qty"])
        assert r["entry_price"] == PRICES[r["symbol"]]
    # Next session retries the remaining diff against the frozen targets.
    b.fill = "filled"
    out2 = run(b, env, now=NEXT)
    assert out2["status"] == "month_complete"


def test_working_partial_is_pending_then_settled_before_next_plan(env):
    b = FakeBroker(fill="partial_working")
    run(b, env)
    assert [r for r in tlog(env) if r.get("tranche") == A.TRANCHE] == []
    for o in b.orders.values():           # day orders expire at the close
        o["status"] = "expired"
    b.fill = "filled"
    run(b, env, now=NEXT)                 # settles first, then tops up within band
    rows = [r for r in tlog(env) if r.get("tranche") == A.TRANCHE]
    held = {}
    for r in rows:
        held[r["symbol"]] = held.get(r["symbol"], 0) + r["qty"]
    for s, q in held.items():
        assert q == pytest.approx(b.positions[s]["qty"])          # log == broker


def test_sell_books_fifo_at_real_fill_with_net_pnl(env):
    lots = [{"symbol": "SPY", "side": "buy", "qty": 10.0, "entry_price": 500.0,
             "status": "open", "tranche": A.TRANCHE, "order_id": "b1"},
            {"symbol": "SPY", "side": "buy", "qty": 8.0, "entry_price": 550.0,
             "status": "open", "tranche": A.TRANCHE, "order_id": "b2"}]
    (env / "trade_log.json").write_text(json.dumps(lots))
    b = FakeBroker(positions=[{"symbol": "SPY", "qty": 18.0}])        # 10.8%
    run(b, env)
    sell = next(o for o in b.placed if o["side"] == "sell")
    q = float(sell["qty"])
    assert q <= 18
    rows = [r for r in tlog(env) if r["symbol"] == "SPY"]
    closed = [r for r in rows if r["status"] == "closed"]
    assert closed[0]["order_id"] == "b1" and closed[0]["exit_price"] == 600.0
    assert q == 6                                   # ceil((10.8% - 7.6%) x 100k / 600)
    assert closed[0]["qty"] == 6 and closed[0]["entry_price"] == 500.0   # oldest lot first
    assert closed[0]["pnl"] == pytest.approx(600.0, abs=1.0)         # net of tiny reg fees
    remaining_b1 = [r for r in rows if r.get("order_id") == "b1" and r["status"] == "open"]
    assert remaining_b1 and remaining_b1[0]["qty"] == 4
    assert rows.index(remaining_b1[0]) < rows.index(next(r for r in rows if r.get("order_id") == "b2"))
    assert sum(r["qty"] for r in closed) == pytest.approx(q)
    assert sum(r["qty"] for r in rows if r["status"] == "open") == pytest.approx(18 - q)


# ---------------------------------------------------------------------------
# P3 limits shared with legacy: gross clipping, preflight, snapshot
# ---------------------------------------------------------------------------

def test_gross_exposure_room_scales_buys_and_never_sells_legacy(env):
    # Today's real P3 shape: ~$32K legacy on ~$99K equity => 80% gross cap binds.
    legacy = [{"symbol": "ANET", "qty": 120}, {"symbol": "KO", "qty": 216}]   # 16.8K + 15.1K
    b = FakeBroker(equity=99_155.66, cash=67_201.88, positions=legacy)
    out = run(b, env)
    assert out["status"] == "month_in_progress" and out["room"]["factor"] < 1
    spent = sum(float(o["qty"]) * float(o["limit_price"]) for o in b.placed)
    assert spent <= out["room"]["room"] + 1e-6
    gross_after = sum(float(p["qty"]) * PRICES[s] for s, p in b.positions.items())
    assert gross_after <= 0.80 * b.equity
    assert {o["symbol"] for o in b.placed}.isdisjoint({"ANET", "KO"})


def test_preflight_failure_places_no_orders(env, monkeypatch):
    monkeypatch.setattr(A.preflight_mod, "run_preflight",
                        lambda **kw: (False, {"hard_failures": ["account blocked"]}))
    b = FakeBroker()
    assert run(b, env)["status"] == "preflight_failed" and b.placed == []


def test_incomplete_snapshot_is_never_read_as_unlisted(env):
    b = FakeBroker(missing_bars={"DBMF"})
    out = run(b, env)
    assert out["status"] == "snapshot_incomplete" and b.placed == []
    assert out["missing"] == ["DBMF"]


def test_snapshot_excludes_the_current_session_bar(env):
    b = FakeBroker()
    run(b, env)
    st = state(env)
    assert st["targets_frozen_at"] == "2026-10-22"
    assert st["snapshot_closes"]["SPY"] == PRICES["SPY"]


def test_new_month_refreezes_targets(env):
    b = FakeBroker()
    run(b, env)
    out = run(b, env, now=NOV)
    st = state(env)
    assert st["targets_month"] == "2026-11" and st["last_rebalance_month"] == "2026-11"
    assert out["status"] == "month_complete"


# ---------------------------------------------------------------------------
# Integration with the legacy P3 code paths
# ---------------------------------------------------------------------------

def test_rearm_never_arms_stops_on_allocator_lots(env, monkeypatch):
    import event_driven_bot as EDB
    monkeypatch.setattr(EDB, "DATA_DIR", env)
    lots = [{"symbol": "SPY", "side": "buy", "qty": 12.0, "entry_price": 600.0,
             "status": "open", "tranche": A.TRANCHE},
            {"symbol": "ANET", "side": "buy", "qty": 43, "entry_price": 171.0,
             "status": "open", "tranche": "core_swing", "stop_loss": 146.0,
             "take_profit_1": 220.0}]
    (env / "trade_log.json").write_text(json.dumps(lots))
    armed = []

    class B(FakeBroker):
        def place_oco_order(self, symbol, qty, side, **kw):
            armed.append((symbol, qty))
            return {"id": "x"}

    b = B(positions=[{"symbol": "SPY", "qty": 12.0}, {"symbol": "ANET", "qty": 43}])
    EDB._rearm_protective_stops(b, P3_LIMITS)
    assert armed == [("ANET", 43)]


def test_allocator_orders_count_toward_legacy_daily_budget(env):
    b = FakeBroker()
    run(b, env)
    assert A.allocator_orders_on("2026-10-23", data_dir=env) == 9
    assert A.trades_used_today(tlog(env), state(env), "2026-10-23") == 9


# ---------------------------------------------------------------------------
# Spec + purity
# ---------------------------------------------------------------------------

def test_constants_pinned_to_the_registered_spec():
    spec = json.load(open(os.path.join(REPO_ROOT, "docs", "specs", "crisis_core_v1.json")))
    assert A.DEFAULTS["spec_cap"] == spec["params"]["cap"]
    assert A.DEFAULTS["spec_band"] == spec["params"]["band"]
    assert set(A.UNIVERSE) == set(spec["symbols"])


def test_forward_spec_is_valid_and_honest():
    from backtest.strategy_spec import load_and_validate
    path = os.path.join(REPO_ROOT, "docs", "specs", "crisis_core_v1_forward.json")
    ok, errors = load_and_validate(path)
    assert ok, errors
    spec = json.load(open(path))
    assert "FAILED its backtest promotion gate" in spec["status"]
    assert "paper only, not a promotion" in spec["status"]
    assert spec["evaluation"]["checkpoints_trading_days"] == [60, 90]
    acc = spec["acceptance"]
    assert acc["F1_tracking_error"]["threshold"] == 0.03
    assert acc["F2_max_drawdown"]["threshold"] == 0.10
    assert acc["F4_slippage"]["threshold"] == 15.0
    assert acc["F3_no_cap_breach"]["threshold"] == acc["F5_no_duplicates"]["threshold"] == 0


def test_allocator_module_is_cloud_path_pure():
    banned = {"numpy", "pandas", "scipy", "sklearn", "statsmodels", "torch",
              "anthropic", "openai", "alpaca_cli", "alpaca_skills", "matplotlib"}
    for rel in ("event-driven-bot/scripts/allocator.py", "scripts/backtest/allocators.py",
                "shared/strategy_controls.py"):
        tree = ast.parse(open(os.path.join(REPO_ROOT, rel)).read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
        assert not (mods & banned), (rel, mods & banned)


# ---------------------------------------------------------------------------
# Adversarial-review fixes (2026-10-23)
# ---------------------------------------------------------------------------

class _ArmBroker(FakeBroker):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.armed = []

    def place_oco_order(self, symbol, qty, side, **kw):
        self.armed.append((symbol, qty))
        return {"id": "x"}


def _rearm(env, b, monkeypatch):
    import event_driven_bot as EDB
    monkeypatch.setattr(EDB, "DATA_DIR", env)
    EDB._rearm_protective_stops(b, P3_LIMITS)
    return b.armed


def test_rearm_ignores_filled_but_unbooked_allocator_buys(env, monkeypatch):
    # Partial fill still working after the 8s confirm => pending, NOT booked.
    b = _ArmBroker(fill="partial_working")
    run(b, env)
    assert [r for r in tlog(env) if r.get("tranche") == A.TRANCHE] == []
    assert b.positions                                    # ETF shares are held...
    b.orders.clear()                                      # (no working sells)
    assert _rearm(env, b, monkeypatch) == []              # ...and never get stops


def test_rearm_with_withheld_trade_log_arms_only_legacy_lot_qty(env, monkeypatch):
    # The allocator rows were withheld from this checkout: the log only knows
    # legacy lots. SPY: 5 legacy shares + 12 allocator shares at the broker.
    legacy = [{"symbol": "ANET", "side": "buy", "qty": 43, "entry_price": 171.0,
               "status": "open", "tranche": "core_swing", "stop_loss": 146.0,
               "take_profit_1": 220.0},
              {"symbol": "SPY", "side": "buy", "qty": 5, "entry_price": 590.0,
               "status": "open", "tranche": "core_swing"}]
    (env / "trade_log.json").write_text(json.dumps(legacy))
    b = _ArmBroker(positions=[{"symbol": "ANET", "qty": 43}, {"symbol": "SPY", "qty": 17},
                              {"symbol": "QQQ", "qty": 14}])
    assert sorted(_rearm(env, b, monkeypatch)) == [("ANET", 43), ("SPY", 5)]


def test_price_outage_never_marks_the_month_complete(env):
    class NoPx(FakeBroker):
        def get_latest_trade(self, s):
            raise RuntimeError("data 503")

        def get_positions(self):
            return []
    b = NoPx()
    out = run(b, env)
    assert b.placed == [] and out["status"] == "month_in_progress"
    assert state(env)["last_rebalance_month"] is None
    b2 = FakeBroker()
    assert run(b2, env, now=NEXT)["status"] == "month_complete" and len(b2.placed) == 9


@pytest.mark.parametrize("status,failed", [
    ("limits_invalid", True), ("preflight_failed", True), ("snapshot_failed", True),
    ("snapshot_incomplete", True), ("refused_not_paper", True),
    ("broker_orders_unavailable", True), ("month_complete", False), ("disabled", False),
    ("market_closed", False), ("concurrent_run_detected", False)])
def test_run_failed_statuses(status, failed):
    assert A.run_failed({"status": status, "orders": []}) is failed


def test_order_error_or_rejection_fails_the_run(env):
    b = FakeBroker()
    b.reject_422.add("p3alloc-20261023-QQQ-buy")
    assert A.run_failed(run(b, env))
    assert not A.run_failed(run(FakeBroker(), env, now=NEXT + timedelta(days=1)))


def test_main_exits_nonzero_when_the_allocator_fails(env, monkeypatch):
    import event_driven_bot as EDB

    class B(FakeBroker):
        def get_account(self):
            return dict(super().get_account(), account_number="PA3")

    monkeypatch.setattr(EDB, "AlpacaClient", lambda: B())
    monkeypatch.setattr(EDB, "DATA_DIR", env)
    monkeypatch.setattr(EDB, "CONFIG_DIR", env)
    monkeypatch.setattr(A, "run_allocator", lambda *a, **k: {"status": "preflight_failed"})
    monkeypatch.setattr(sys, "argv", ["event_driven_bot.py", "allocator"])
    with pytest.raises(SystemExit) as e:
        EDB.main()
    assert e.value.code == 1
    monkeypatch.setattr(A, "run_allocator", lambda *a, **k: {"status": "month_complete",
                                                             "orders": []})
    EDB.main()                                            # success: no exit


def test_catalyst_decay_never_closes_an_allocator_universe_symbol(env, monkeypatch):
    import event_driven_bot as EDB
    monkeypatch.setattr(EDB, "DATA_DIR", env)
    old = (NOW - timedelta(days=5)).isoformat()
    lots = [{"symbol": "SPY", "side": "buy", "qty": 5, "status": "open",
             "tranche": "event_driven", "timestamp": old},
            {"symbol": "ANET", "side": "buy", "qty": 10, "status": "open",
             "tranche": "event_driven", "timestamp": old}]
    (env / "trade_log.json").write_text(json.dumps(lots))
    closed = []

    class B(FakeBroker):
        def close_position(self, sym, qty=None):
            closed.append(sym)
            return {}

    b = B(positions=[{"symbol": "SPY", "qty": 17}, {"symbol": "ANET", "qty": 10}])
    EDB._enforce_catalyst_decay(b, b.get_positions(), P3_LIMITS)
    assert closed == ["ANET"]


def test_sector_rotation_never_rotates_out_of_allocator_etfs(env, monkeypatch):
    import event_driven_bot as EDB
    monkeypatch.setattr(EDB, "DATA_DIR", env)
    monkeypatch.setattr(EDB, "CONFIG_DIR", env)
    monkeypatch.setattr("shared.strategy_controls.entries_enabled", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr("shared.preflight.run_preflight", lambda **kw: (True, {"hard_failures": []}))
    closed = []

    class B(FakeBroker):
        def close_position(self, sym, qty=None):
            closed.append(sym)
            return {"id": "c"}

    # 9 allocator ETFs (all sector "Unknown") ~ 60% of equity.
    pos = [{"symbol": s, "qty": round(6600 / PRICES[s])} for s in
           ("SPY", "QQQ", "IWM", "EFA", "DBMF", "KMLM", "CTA", "IEF", "BIL")]
    b = B(positions=pos, cash=40_000)
    sig = [{"symbol": "ZZZZ", "price": 50.0, "atr": 1.0, "sector": "Unknown",
            "score": 0.9, "reasons": ["x"], "rs_vs_spy": 99.0, "tranche": "core_swing"}]
    PRICES.setdefault("ZZZZ", 50.0)
    EDB.execute_signals(b, sig, "core_swing")
    assert closed == [] and b.placed == []


def test_done_for_day_is_not_final(env):
    b = FakeBroker(fill="partial_working")
    run(b, env)
    for o in b.orders.values():
        o["status"] = "done_for_day"
    assert A.settle_allocator_orders(b, env, now=NOW) == 0
    assert [r for r in tlog(env) if r.get("tranche") == A.TRANCHE] == []
    for o in b.orders.values():
        o["status"] = "expired"
    assert A.settle_allocator_orders(b, env, now=NOW) == 9
    rows = [r for r in tlog(env) if r.get("tranche") == A.TRANCHE]
    assert all(r["qty"] == float(b.orders[r["order_id"]]["filled_qty"]) for r in rows)


def test_reconcile_lot_carries_order_id_so_settlement_never_double_books(env):
    from shared.reconcile import order_ids_from_orders, reconcile_log_to_broker
    b = FakeBroker(fill="accepted")
    run(b, env)                                    # pending, unbooked
    spy = next(o for o in b.orders.values() if o["symbol"] == "SPY")
    spy.update(status="filled", filled_qty=spy["qty"], filled_avg_price="600.0", filled_at="t")
    b.positions["SPY"] = {"symbol": "SPY", "qty": float(spy["qty"])}
    for o in b.orders.values():
        if o["symbol"] != "SPY":
            o["status"] = "expired"
    # EOD settlement FAILED; the reconcile re-logs the position, tagged.
    oids = order_ids_from_orders(list(b.orders.values()), ("p3alloc",))
    repaired, _ = reconcile_log_to_broker(
        tlog(env), b.get_positions(), order_classes={"SPY": A.TRANCHE}, order_ids=oids)
    assert repaired[-1]["order_id"] == spy["id"] and repaired[-1]["order_class"] == A.TRANCHE
    (env / "trade_log.json").write_text(json.dumps(repaired))
    A.settle_allocator_orders(b, env, now=NOW)     # next settle must not re-book
    rows = [r for r in tlog(env) if r.get("symbol") == "SPY"]
    assert len(rows) == 1 and A.allocator_holdings(tlog(env)) == {"SPY": float(spy["qty"])}


def test_constrained_target_and_cap_shortfall_are_recorded(env):
    legacy = [{"symbol": "ANET", "qty": 120}, {"symbol": "KO", "qty": 216}]
    b = FakeBroker(equity=99_155.66, cash=67_201.88, positions=legacy)
    out = run(b, env)
    st = state(env)
    rec = st["session_targets"]["2026-10-23"]
    assert rec["cap_shortfall_pct"] == st["cap_shortfall_pct"] == out["cap_shortfall_pct"] > 0
    assert rec["room_factor"] < 1
    for s, w in st["targets"].items():
        assert 0 <= rec["targets_constrained"][s] <= w
    implied = sum(st["targets"].values()) * 100 - sum(rec["targets_constrained"].values()) * 100
    assert implied == pytest.approx(rec["cap_shortfall_pct"], abs=1e-3)


def test_unconstrained_run_records_zero_shortfall(env):
    run(FakeBroker(), env)
    st = state(env)
    assert st["cap_shortfall_pct"] == 0
    assert st["targets_constrained"] == pytest.approx(st["targets"])


def test_guardian_p3_fresh_when_broker_has_todays_p3alloc_order(tmp_path):
    import subprocess
    from zoneinfo import ZoneInfo
    import test_audit_2026_10_23_p1 as G
    if G.shutil.which("git") is None:
        pytest.skip("git unavailable")
    origin = G._origin(tmp_path, {"event-driven-bot/data/signals.json":
                                  {"timestamp": "2026-01-02T15:00:00+00:00"}})
    repo = G._clone(tmp_path, origin, "g")
    (repo / "event-driven-bot" / "config").mkdir(parents=True, exist_ok=True)
    (repo / "event-driven-bot" / "config" / "alpaca_config.json").write_text(json.dumps(
        {"api_key": "k", "api_secret": "s", "base_url": "https://fake"}))
    fake = tmp_path / "fakemods"
    fake.mkdir()
    script = tmp_path / "guardian_fresh.py"
    script.write_text(G._guardian_script())
    env = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}
    env["PYTHONPATH"] = str(fake)
    # The fake module is rewritten each iteration, sometimes with the SAME byte
    # length within the same second; Python's mtime+size .pyc check would then
    # reuse the previous iteration's bytecode (flaky on fast CI runners).
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    day = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
    for coid, expect in ((f"p3-rearm-{day}-SPY-sell", 1), ("p3alloc-20200101-SPY-buy", 1),
                         (f"p3alloc-{day}-SPY-buy", 0), (f"p3-{day}-ANET-buy", 0)):
        (fake / "requests.py").write_text(
            "class _R:\n"
            "    def raise_for_status(self): pass\n"
            f"    def json(self): return [{{'client_order_id': '{coid}'}}]\n"
            "def get(*a, **k): return _R()\n")
        G.shutil.rmtree(fake / "__pycache__", ignore_errors=True)
        r = subprocess.run([sys.executable, str(script), "p3"], cwd=repo, env=env,
                           capture_output=True, text=True)
        assert r.returncode == expect, (coid, r.stdout + r.stderr)
