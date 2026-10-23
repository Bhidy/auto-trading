#!/usr/bin/env python3
"""
Autonomous Runner — Production orchestrator for Portfolio 1 (Quantitative Multi-Factor).
Replaces Claude's /schedule by calling the existing analysis scripts and executing via Alpaca REST API.
Runs entirely via cron — no Claude window needed.

Modes:
  morning-research   Pull bars, compute signals, detect regime
  trading-session     Validate signals, execute limit orders
  intraday-monitor    Check P&L, enforce stops, kill switch
  end-of-day-journal  Log performance, run self-learning, adapt parameters
  weekly-review       Deep analysis, rebalancing, strategy tuning
"""

import json
import os
import sys
import time
import logging
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
JOURNAL_DIR = BASE_DIR / "journal"
LOGS_DIR = BASE_DIR / "logs"

LOGS_DIR.mkdir(exist_ok=True)
JOURNAL_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(BASE_DIR))

from shared.alpaca_http import (  # noqa: E402  (path set above)
    confirm_fill,
    make_client_order_id,
    resilient_request,
)
from shared.risk_config import load_risk_limits  # noqa: E402

# client_order_id prefix -> trade-log sleeve, for attributing broker-reconstructed
# lots (shared.reconcile.order_classes_from_orders). Active entries ("p1-") are
# deliberately unmapped: an active lot carries no rebalanced-sleeve class.
P1_ORDER_CLASS_BY_PREFIX = {"p1mom": "momentum_sleeve", "p1core": "passive_core"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / f"p1_{datetime.now().strftime('%Y-%m-%d')}.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("p1_autonomous")

# ---------------------------------------------------------------------------
# ALPACA CLIENT
# ---------------------------------------------------------------------------

class AlpacaClient:
    def __init__(self):
        with open(CONFIG_DIR / "alpaca_config.json") as f:
            cfg = json.load(f)
        self.api_key = cfg["api_key"]
        self.api_secret = cfg["api_secret"]
        self.base_url = cfg["base_url"]
        self.data_url = cfg["data_url"]
        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }

    def _request(self, method, url, params=None, data=None):
        """Resilient HTTP via the shared core (retry/backoff on 429/5xx + network)."""
        return resilient_request(method, url, self.headers,
                                 params=params, json_body=data, logger=log)

    def _get(self, url, params=None):
        return self._request("GET", url, params=params)

    def _post(self, url, data):
        return self._request("POST", url, data=data)

    def _delete(self, url):
        return self._request("DELETE", url)

    def get_account(self):
        return self._get(f"{self.base_url}/v2/account")

    def get_clock(self):
        return self._get(f"{self.base_url}/v2/clock")

    def is_market_open(self):
        return self.get_clock().get("is_open", False)

    def get_positions(self):
        return self._get(f"{self.base_url}/v2/positions")

    def get_position(self, symbol):
        try:
            return self._get(f"{self.base_url}/v2/positions/{symbol}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def get_orders(self, status="open", after=None, limit=None, symbols=None):
        params = {"status": status}
        if after:
            params["after"] = after
        if limit:
            params["limit"] = limit
        if symbols:
            params["symbols"] = symbols
        return self._get(f"{self.base_url}/v2/orders", params)

    def cancel_order(self, order_id):
        return self._delete(f"{self.base_url}/v2/orders/{order_id}")

    def get_order_by_client_id(self, client_order_id):
        """The broker's record for one of OUR deterministic client_order_ids —
        used to resolve an idempotent 422 duplicate to its real fill state."""
        return self._get(f"{self.base_url}/v2/orders:by_client_order_id",
                         {"client_order_id": client_order_id})

    def get_asset(self, symbol):
        """Fetch the broker asset record (tradable/shortable/easy_to_borrow/status).
        Returns None on 404 so callers fail-closed on shorts."""
        try:
            return self._get(f"{self.base_url}/v2/assets/{symbol}")
        except requests.HTTPError as e:
            if getattr(e, "response", None) is not None and e.response.status_code == 404:
                return None
            raise

    def get_stock_bars(self, symbol, timeframe="1Day", start=None, limit=220):
        # adjustment=split so MA50/MA200, momentum, ATR and Bollinger never see a false
        # jump across a stock split. Matches fetch_bars.py and the accounting ledger
        # (shared/accounting.apply_split / apply_cash_dividend handles dividends as cash,
        # so split-only keeps price series and ledger consistent).
        params = {"timeframe": timeframe, "limit": limit, "feed": "sip", "adjustment": "split"}
        if start:
            params["start"] = start
        return self._get(f"{self.data_url}/v2/stocks/{symbol}/bars", params)

    def get_crypto_bars(self, symbol, timeframe="1Day", limit=220):
        return self._get(f"{self.data_url}/v1beta3/crypto/us/bars",
                         {"symbols": symbol, "timeframe": timeframe, "limit": limit})

    def get_latest_quote(self, symbol):
        return self._get(f"{self.data_url}/v2/stocks/{symbol}/quotes/latest")

    def get_latest_trade(self, symbol):
        return self._get(f"{self.data_url}/v2/stocks/{symbol}/trades/latest")

    def place_order(self, symbol, qty, side, order_type="limit",
                    limit_price=None, time_in_force="day", client_order_id=None):
        data = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        if limit_price and order_type == "limit":
            data["limit_price"] = str(round(limit_price, 2))
        if client_order_id:
            data["client_order_id"] = client_order_id
        return self._post(f"{self.base_url}/v2/orders", data)

    def place_crypto_order(self, symbol, qty, side, order_type="limit",
                           limit_price=None, time_in_force="gtc", client_order_id=None):
        data = {
            "symbol": symbol.replace("/", ""),
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        if limit_price and order_type == "limit":
            data["limit_price"] = str(round(limit_price, 2))
        if client_order_id:
            data["client_order_id"] = client_order_id
        return self._post(f"{self.base_url}/v2/orders", data)

    def get_order(self, order_id):
        return self._get(f"{self.base_url}/v2/orders/{order_id}")

    def cancel_all_orders(self):
        return self._delete(f"{self.base_url}/v2/orders")

    def close_position(self, symbol):
        return self._delete(f"{self.base_url}/v2/positions/{symbol}")

    def close_all_positions(self):
        return self._delete(f"{self.base_url}/v2/positions")


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def load_json(path, default=None):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default if default is not None else {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def get_bucket_for_symbol(symbol):
    watchlist = load_json(CONFIG_DIR / "watchlist.json", {})
    for bucket, info in watchlist.items():
        if symbol in info.get("symbols", []):
            return bucket
    return "unknown"

def get_instrument_type(symbol):
    watchlist = load_json(CONFIG_DIR / "watchlist.json", {})
    for bucket, info in watchlist.items():
        if symbol in info.get("symbols", []):
            return info.get("instrument_type", "stock")
    return "stock"

# make_client_order_id and confirm_fill are imported from shared.alpaca_http
# (single source of truth shared by P1/P2/P3).


def _quote_is_fresh(alpaca, symbol, max_age_s=900):
    """Best-effort halt proxy: is the latest trade recent during market hours?
    Returns True on any error so a data hiccup never blocks risk-reducing flow;
    the ETB short gate is enforced independently and remains fail-closed."""
    try:
        tr = alpaca.get_latest_trade(symbol).get("trade", {})
        ts = tr.get("t")
        if not ts:
            return True
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - t).total_seconds()
        return age <= max_age_s
    except Exception:
        return True


def _build_asset_lookup(alpaca):
    """Return `symbol -> asset_info` for the risk officer. Carries the broker
    asset record (tradable/shortable/easy_to_borrow/status) plus a `quote_fresh`
    halt proxy. Cached per session to avoid duplicate calls."""
    cache = {}

    def lookup(symbol):
        if not symbol:
            return None
        if symbol in cache:
            return cache[symbol]
        asset = alpaca.get_asset(symbol)
        info = dict(asset) if isinstance(asset, dict) else None
        if info is not None:
            info["quote_fresh"] = _quote_is_fresh(alpaca, symbol)
        cache[symbol] = info
        return info

    return lookup


# ---------------------------------------------------------------------------
# SESSION CALENDAR (ET) — audit 2026-10-23, M2/M3
# ---------------------------------------------------------------------------
# A US trading session is an America/New_York date. Dating journals, EOD
# idempotency and the weekly anchor off UTC (or the runner's local clock) splits
# or skips sessions around midnight UTC — the cause of 4 EOD runs for one session
# and of the skipped Monday week_start reset.

def _et_now(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        # No tz database: apply the US DST rule directly (2nd Sun Mar 07:00Z ->
        # 1st Sun Nov 06:00Z is EDT, else EST). Pure stdlib, never raises.
        def _nth_sunday(month, n):
            d = datetime(now.year, month, 1, tzinfo=timezone.utc)
            d += timedelta(days=(6 - d.weekday()) % 7)
            return d + timedelta(weeks=n - 1)
        start = _nth_sunday(3, 2) + timedelta(hours=7)
        end = _nth_sunday(11, 1) + timedelta(hours=6)
        offset = -4 if start <= now.astimezone(timezone.utc) < end else -5
        return now.astimezone(timezone(timedelta(hours=offset)))


def et_session_date(now=None):
    """The ET calendar date (YYYY-MM-DD) of the trading session at ``now``."""
    return _et_now(now).strftime("%Y-%m-%d")


def iso_week_key(session_date):
    """ISO week of an ET session date, e.g. '2026-W43'."""
    y, w, _ = datetime.strptime(session_date, "%Y-%m-%d").isocalendar()
    return f"{y}-W{w:02d}"


def roll_session_anchors(state, session_date):
    """Roll ``week_start_equity`` when the ET session enters a new ISO week (M3).

    The week anchor is the PRIOR week's last close (normally Friday's; Thursday's
    in a holiday week) — ``last_close_equity`` written by the EOD journal, falling
    back to ``day_start_equity`` (also the last close) for state written before
    this field existed. Called at the top of every mode, so whichever run first
    sees the new week rolls it — independent of UTC weekday or of the EOD firing.
    Returns True if it rolled. A state with no recorded week is stamped with the
    current week WITHOUT resetting the anchor (no surprise mid-week reset).
    """
    wk = iso_week_key(session_date)
    prev = state.get("week_start_iso_week")
    if prev == wk:
        return False
    if prev is None:
        state["week_start_iso_week"] = wk
        if not state.get("week_start_equity"):
            anchor = state.get("last_close_equity") or state.get("day_start_equity")
            if anchor:
                state["week_start_equity"] = anchor
        return False
    anchor = (state.get("last_close_equity") or state.get("day_start_equity")
              or state.get("equity"))
    if anchor:
        state["week_start_equity"] = anchor
    state["week_start_iso_week"] = wk
    state["week_start_set_at"] = datetime.now(timezone.utc).isoformat()
    state["week_start_source"] = (f"prior close {state.get('last_close_session_date') or 'unknown'}")
    log.info(f"  New ISO week {wk}: week_start_equity=${float(anchor or 0):,.2f} "
             f"(prior close {state.get('last_close_session_date') or 'unknown'})")
    return True


# ---------------------------------------------------------------------------
# HIGH-WATER MARK + HALT GOVERNANCE — audit 2026-10-23, C1/M5
# ---------------------------------------------------------------------------

def kill_switch_drawdown_pct(state, equity):
    """Drawdown from the confirmed high-water mark (M5) — the kill-switch metric."""
    from risk_officer import drawdown_pct_from_peak
    return drawdown_pct_from_peak(state, equity)


def update_peak_equity(alpaca, state, account, positions, last_equity):
    """Raise ``peak_equity`` ONLY on a cross-checked read (M5).

    A new high must (1) agree with an independent valuation of the book (cash +
    qty x market-data price, shared.equity_guard) and (2) be repeated by a second
    account read within 1%. The lower of the two reads is recorded, so a phantom
    spike can never inflate the mark the kill switch measures from (an inflated
    peak would make the next ordinary read look like a crash). Cheap in the
    normal case: no extra calls unless equity exceeds the current mark.
    """
    from risk_officer import drawdown_reference_equity
    try:
        equity = float(account.get("equity") or 0)
    except (TypeError, ValueError):
        return False
    if equity <= drawdown_reference_equity(state):
        return False
    check = _confirmed_equity(alpaca, account, positions, state, last_equity,
                              before_action=True)
    if not check.get("ok"):
        log.warning(f"  Peak equity NOT raised — new high ${equity:,.2f} not corroborated: "
                    f"{check.get('reason')}")
        return False
    try:
        second = float((alpaca.get_account() or {}).get("equity") or 0)
    except Exception:
        second = 0.0
    if second <= 0 or abs(second / equity - 1.0) * 100 > 1.0:
        log.warning(f"  Peak equity NOT raised — second read ${second:,.2f} disagrees "
                    f"with ${equity:,.2f}")
        return False
    peak = round(min(equity, second), 2)
    state["peak_equity"] = peak
    state["peak_equity_at"] = datetime.now(timezone.utc).isoformat()
    state["peak_equity_evidence"] = {"reads": [equity, second],
                                     "independent_equity": check.get("independent_equity"),
                                     "confirmation": check.get("reason")}
    log.info(f"  New confirmed high-water mark: ${peak:,.2f}")
    return True


def _stamp_halt(state, *, kind, reason, evidence, source, until=None):
    """Latch a halt WITH its evidence (C1a). Every halt this code latches is
    stamped with ``halt_set_at`` — the key a human-owned clear must name, so a
    clear can never reach a halt it was not written for."""
    now = datetime.now(timezone.utc).isoformat()
    state["halted"] = True
    state["halt_reason"] = reason
    state["halt_until"] = until
    state["halt_set_at"] = now
    state["halt_kind"] = kind
    state["halt_evidence"] = {"at": now, "source": source, **(evidence or {})}
    state["halt_verified"] = True
    state["halt_unverified_reason"] = None


def _expire_halt_if_due(state):
    """Daily/weekly halts carry ``halt_until`` and expire on their own (unchanged
    behaviour). A kill-switch halt has no expiry and never passes here."""
    if not (state.get("halted") and state.get("halt_until")):
        return False
    try:
        halt_until = datetime.fromisoformat(str(state["halt_until"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    if halt_until.tzinfo is None:
        halt_until = halt_until.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) <= halt_until:
        return False
    log.info("Halt period expired — resuming trading")
    state["last_halt"] = {"reason": state.get("halt_reason"), "set_at": state.get("halt_set_at"),
                          "until": state.get("halt_until"), "evidence": state.get("halt_evidence"),
                          "ended": "expired"}
    for k in ("halt_reason", "halt_until", "halt_set_at", "halt_kind", "halt_evidence"):
        state[k] = None
    state["halted"] = False
    return True


UNVERIFIED_HALT_MSG = ("UNVERIFIED HALT: latched with no recorded evidence (no equity "
                       "reads, reference equity, drawdown or timestamp) — cannot be "
                       "audited. Clear only via a halt_clear block in "
                       "config/strategy_controls.json, which the runner applies after "
                       "a fresh cross-checked equity read.")


def annotate_halt_verification(state):
    """C1d: mark a halt that carries no evidence as UNVERIFIED in state, so the
    heartbeat/dashboard can surface it. Returns True/False (verified) while
    halted, None when not halted."""
    if not state.get("halted"):
        state["halt_verified"] = None
        state["halt_unverified_reason"] = None
        return None
    ev = state.get("halt_evidence")
    verified = isinstance(ev, dict) and bool(ev.get("at")) and ev.get("equity") is not None
    state["halt_verified"] = verified
    state["halt_unverified_reason"] = None if verified else UNVERIFIED_HALT_MSG
    return verified


def _warn_if_unverified_halt(state):
    if annotate_halt_verification(state) is False:
        log.warning(f"::warning::P1 {UNVERIFIED_HALT_MSG} halt_reason="
                    f"{state.get('halt_reason')!r}")


def cross_checked_equity(alpaca, state, tol_pct=1.0):
    """(ok, equity, evidence): equity read TWICE from the account endpoint (both
    > 0, agreeing within ``tol_pct``) AND corroborated by an independent
    valuation of the book. The lower read is returned (conservative)."""
    ev = {"at": datetime.now(timezone.utc).isoformat(), "reads": []}
    try:
        a1 = alpaca.get_account() or {}
        a2 = alpaca.get_account() or {}
        e1, e2 = float(a1.get("equity") or 0), float(a2.get("equity") or 0)
    except Exception as e:
        ev["reason"] = f"account read failed: {e}"
        return False, None, ev
    ev["reads"] = [e1, e2]
    if e1 <= 0 or e2 <= 0:
        ev["reason"] = "non-positive equity read"
        return False, None, ev
    gap = abs(e1 - e2) / max(e1, e2) * 100
    ev["read_gap_pct"] = round(gap, 3)
    if gap > tol_pct:
        ev["reason"] = f"two equity reads disagree by {gap:.2f}% (> {tol_pct}%)"
        return False, None, ev
    try:
        positions = alpaca.get_positions()
        check = _confirmed_equity(alpaca, a2, positions, state,
                                  float(a2.get("last_equity") or 0), before_action=True)
    except Exception as e:
        ev["reason"] = f"independent valuation failed: {e}"
        return False, None, ev
    ev["independent_equity"] = check.get("independent_equity")
    ev["confirmation"] = check.get("reason")
    if not check.get("ok"):
        ev["reason"] = f"independent valuation disagrees: {check.get('reason')}"
        return False, None, ev
    ev["reason"] = "two consistent reads + independent valuation"
    return True, min(e1, e2), ev


def maybe_apply_halt_clear(alpaca, state, limits, source, controls=None):
    """C1c: honour a human-owned ``halt_clear`` request — only on evidence.

    Applies when (1) the request names THIS halt (``halt_set_at``, or the exact
    reason of a legacy unstamped halt) and has not been consumed, (2) a fresh
    cross-checked equity read succeeds, and (3) drawdown from the confirmed peak
    on that read is below the kill threshold. Then it un-halts, appends a
    governance record with the evidence to data/halt_governance.json, and
    consumes the request (single-use). The config file is never written.
    Returns True if the halt was cleared.
    """
    if not state.get("halted"):
        return False
    from shared.strategy_controls import halt_clear_for, halt_clear_key, halt_clear_matches
    clear, problem = halt_clear_for("portfolio_1", controls=controls)
    if problem:
        log.warning(f"::warning::P1 halt_clear ignored: {problem}")
    if clear is None:
        return False
    matches, why = halt_clear_matches(clear, state)
    if not matches:
        log.warning(f"::warning::P1 halt_clear present but not applied: {why}")
        return False
    ok, equity, ev = cross_checked_equity(alpaca, state)
    attempt = {"at": ev.get("at"), "source": source, "evidence": ev}
    if not ok:
        state["halt_clear_last_attempt"] = {**attempt, "applied": False}
        log.warning(f"::warning::P1 halt_clear NOT applied — equity not cross-checked: "
                    f"{ev.get('reason')}")
        return False
    dd = kill_switch_drawdown_pct(state, equity)
    ev["drawdown_pct_from_peak"] = round(dd, 3)
    from risk_officer import drawdown_reference_equity
    ev["peak_reference_equity"] = drawdown_reference_equity(state)
    if dd >= float(limits["kill_switch_drawdown_pct"]):
        state["halt_clear_last_attempt"] = {**attempt, "applied": False}
        log.error(f"::error::P1 halt_clear REFUSED — verified drawdown {dd:.2f}% is still "
                  f">= kill threshold {limits['kill_switch_drawdown_pct']}%")
        return False
    record = {
        "type": "halt_clear", "portfolio_id": "portfolio_1", "applied_at": ev["at"],
        "source": source, "clear_key": halt_clear_key(clear), "request": clear,
        "cleared_halt": {k: state.get(k) for k in
                         ("halt_reason", "halt_set_at", "halt_kind", "halt_until",
                          "halt_evidence", "halt_verified")},
        "verification": ev, "verified_equity": equity,
        "kill_switch_drawdown_pct": limits["kill_switch_drawdown_pct"],
    }
    gpath = DATA_DIR / "halt_governance.json"
    history = load_json(gpath, [])
    if not isinstance(history, list):
        history = []
    history.append(record)
    save_json(gpath, history)
    consumed = list(state.get("halt_clears_consumed") or [])
    consumed.append(record["clear_key"])
    state["halt_clears_consumed"] = consumed
    state["last_halt"] = {**record["cleared_halt"], "ended": "human_clear",
                          "ended_at": ev["at"]}
    state["last_halt_clear"] = {"applied_at": ev["at"], "clear_key": record["clear_key"],
                                "verified_equity": equity, "drawdown_pct_from_peak": round(dd, 3),
                                "changed_by": clear.get("changed_by")}
    state["halt_clear_last_attempt"] = {**attempt, "applied": True}
    for k in ("halt_reason", "halt_until", "halt_set_at", "halt_kind", "halt_evidence"):
        state[k] = None
    state["halted"] = False
    annotate_halt_verification(state)
    save_json(DATA_DIR / "portfolio_state.json", state)
    log.warning(f"::warning::P1 HALT CLEARED by human-owned control "
                f"({clear.get('changed_by')}, {clear.get('changed_at')}): verified equity "
                f"${equity:,.2f}, drawdown {dd:.2f}% from peak — {clear.get('reason')}")
    return True


# ---------------------------------------------------------------------------
# ORDER BUDGET, PRICING AND FILL-CONFIRMED EXITS — audit 2026-10-23, H2/H3/L1
# ---------------------------------------------------------------------------

class TradeBudget:
    """The hardcoded ``max_trades_per_day`` as ONE budget shared by every P1
    allocator in a session (momentum, core, rotation, active). ``used`` starts
    at the larger of today's logged trades and today's P1 orders at the broker,
    so a re-fired session, an unfilled limit, or an earlier sleeve all count.

    ``entries_frozen`` (set when today's broker order count is unknowable) fails
    CLOSED for ENTRIES: no new-risk order may take a slot, while risk-reducing
    exits still can, within the cap."""

    def __init__(self, cap, used=0, entries_frozen=False):
        self.cap = int(cap)
        self.used = int(used)
        self.entries_frozen = bool(entries_frozen)

    @property
    def remaining(self):
        return max(0, self.cap - self.used)

    @property
    def entry_remaining(self):
        return 0 if self.entries_frozen else self.remaining

    def take(self, entry=False):
        if self.used >= self.cap or (entry and self.entries_frozen):
            return False
        self.used += 1
        return True

    def refund(self):
        self.used = max(0, self.used - 1)


def _p1_orders_today(alpaca, session_date):
    """P1 orders submitted during this ET session (any status), from the broker."""
    after = (_et_now().replace(hour=0, minute=0, second=0, microsecond=0)
             .astimezone(timezone.utc).isoformat())
    orders = alpaca.get_orders(status="all", after=after, limit=500) or []
    n = 0
    for o in orders:
        coid = str(o.get("client_order_id") or "")
        created = o.get("submitted_at") or o.get("created_at")
        if not coid.startswith("p1") or not created:
            continue
        try:
            ts = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        except ValueError:
            continue
        if et_session_date(ts) == session_date:
            n += 1
    return n


def build_trade_budget(alpaca, limits, session_date):
    cap = int(limits["max_trades_per_day"])
    logged = sum(1 for t in load_json(DATA_DIR / "trade_log.json", [])
                 if isinstance(t, dict) and t.get("timestamp")
                 and et_session_date(datetime.fromisoformat(
                     str(t["timestamp"]).replace("Z", "+00:00"))) == session_date)
    frozen = False
    try:
        at_broker = _p1_orders_today(alpaca, session_date)
    except Exception as e:
        # Fail CLOSED for entries: without today's broker count the cap cannot be
        # proven, so no new-risk order this session. Exits stay allowed.
        log.warning(f"::warning::P1 trade budget: broker order count unavailable ({e}) — "
                    f"NEW ENTRIES frozen this session (fail closed); exits still allowed")
        at_broker, frozen = 0, True
    budget = TradeBudget(cap, used=max(logged, at_broker), entries_frozen=frozen)
    log.info(f"  Trade budget: {budget.used}/{cap} used today "
             f"(log={logged}, broker={at_broker}); {budget.entry_remaining} entry / "
             f"{budget.remaining} exit slots remaining")
    return budget


def marketable_limit_price(alpaca, symbol, side, slip=0.001, max_spread_pct=5.0):
    """A marketable limit off the LIVE quote (M1/L1): sells at bid x (1-slip),
    buys at ask x (1+slip). A missing, crossed or absurdly wide quote falls back
    to the latest trade print. Returns None when no live price exists — callers
    then SKIP the order this run (retry next run) rather than send a market order."""
    bid = ask = 0.0
    try:
        q = (alpaca.get_latest_quote(symbol) or {}).get("quote") or {}
        bid, ask = float(q.get("bp") or 0), float(q.get("ap") or 0)
    except Exception:
        pass
    ref = bid if side == "sell" else ask
    sane = bid > 0 and ask > 0 and ask >= bid and (ask - bid) / ((ask + bid) / 2) * 100 <= max_spread_pct
    if ref <= 0 or not sane:
        try:
            ref = float(((alpaca.get_latest_trade(symbol) or {}).get("trade") or {}).get("p") or 0)
        except Exception:
            ref = 0.0
    if ref <= 0:
        return None
    return round(ref * (1 - slip) if side == "sell" else ref * (1 + slip), 2)


PENDING_EXITS_FILE = "pending_exits.json"
PENDING_ENTRIES_FILE = "pending_entries.json"
FILL_LEDGER_FILE = "booked_fills.json"
_TERMINAL = ("filled", "canceled", "expired", "rejected", "done_for_day")


# --- fill ledger: a broker fill is booked into the trade log AT MOST ONCE ------
# Keyed by broker order id -> cumulative qty already booked (and its avg px).
# Every booking path (exit confirm, momentum, pending settlement, the legacy
# EOD reconcile, cancel-before-stop) books only the increment beyond this, so
# no combination of retries / failed polls / overlapping paths can double-book.

def _ledger():
    led = load_json(DATA_DIR / FILL_LEDGER_FILE, {})
    return led if isinstance(led, dict) else {}


def _ledger_booked(order_id):
    e = _ledger().get(str(order_id)) if order_id else None
    return (float(e.get("qty") or 0), float(e.get("px") or 0)) if isinstance(e, dict) else (0.0, 0.0)


def _ledger_mark(order_id, qty, px, kind, symbol):
    if not order_id:
        return
    led = _ledger()
    led[str(order_id)] = {"qty": float(qty), "px": float(px or 0), "kind": kind,
                          "symbol": symbol, "at": datetime.now(timezone.utc).isoformat()}
    if len(led) > 3000:                                  # bounded; oldest first out
        for k in sorted(led, key=lambda k: led[k].get("at") or "")[:len(led) - 3000]:
            led.pop(k, None)
    save_json(DATA_DIR / FILL_LEDGER_FILE, led)


def _increment(order_id, cum_qty, cum_px):
    """(new_qty, new_px) not yet booked for this order, priced so the already-
    booked slice is not re-priced. (0, None) when nothing new."""
    booked, booked_px = _ledger_booked(order_id)
    cum_qty, cum_px = float(cum_qty or 0), float(cum_px or 0)
    new = cum_qty - booked
    if new <= 1e-9 or cum_px <= 0:
        return 0.0, None
    px = (cum_qty * cum_px - booked * booked_px) / new if booked > 0 and booked_px > 0 else cum_px
    return new, round(px if px > 0 else cum_px, 4)


def book_exit_fill(order_id, symbol, cum_qty, cum_px, reason):
    """Book the unbooked part of an exit fill FIFO across open lots. Idempotent."""
    new, px = _increment(order_id, cum_qty, cum_px)
    if not new:
        return 0.0
    from performance_tracker import reduce_open_position
    booked = reduce_open_position(symbol, new, px, reason=reason)
    _ledger_mark(order_id, cum_qty, cum_px, "exit", symbol)
    return booked


def _record_pending(fname, order_id, client_order_id, symbol, qty, reason, source, **extra):
    """An order not fully filled inside the confirmation window is recorded by
    ORDER ID for EOD settlement — never booked at a phantom price (H3)."""
    if not order_id:
        return
    path = DATA_DIR / fname
    pending = load_json(path, [])
    if not isinstance(pending, list):
        pending = []
    if any(p.get("order_id") == order_id for p in pending):
        return
    pending.append({"order_id": order_id, "client_order_id": client_order_id,
                    "symbol": symbol, "qty": qty, "reason": reason, "source": source,
                    "submitted_at": datetime.now(timezone.utc).isoformat(), **extra})
    save_json(path, pending)


def _record_pending_exit(order_id, client_order_id, symbol, qty, reason, source):
    _record_pending(PENDING_EXITS_FILE, order_id, client_order_id, symbol, qty, reason, source)


def _record_pending_entry(order_id, client_order_id, symbol, qty, *, bucket, order_class,
                          reasons, intended_price, source):
    _record_pending(PENDING_ENTRIES_FILE, order_id, client_order_id, symbol, qty, "entry",
                    source, bucket=bucket, order_class=order_class, reasons=reasons,
                    intended_price=intended_price)


def _resolve_duplicate(alpaca, coid, symbol, reason):
    """A 422 is an idempotent duplicate ONLY if the broker holds an order under
    our deterministic client_order_id. Returns that order, else None."""
    try:
        prior = alpaca.get_order_by_client_id(coid) or {}
    except Exception as e:
        log.error(f"::error::P1 {reason} {symbol}: 422 and duplicate lookup failed ({e})")
        return None
    return prior if prior.get("id") else None


def _cancel_open_sells(alpaca, symbol, reason):
    """Cancel this book's working SELL orders on ``symbol`` (they reserve shares,
    so a stop-class market exit would 403 'insufficient qty' every cycle). Any
    partial fill of a cancelled order is booked idempotently first-hand."""
    try:
        open_orders = alpaca.get_orders(status="open", symbols=symbol) or []
    except Exception as e:
        log.warning(f"  {symbol}: open-order lookup failed before {reason} ({e})")
        return 0
    n = 0
    for o in open_orders:
        if o.get("symbol") != symbol or o.get("side") != "sell" or not o.get("id"):
            continue
        try:
            alpaca.cancel_order(o["id"])
        except Exception as e:
            log.warning(f"  {symbol}: cancel of working sell {o['id']} failed ({e})")
            continue
        n += 1
        st, fq, fp = confirm_fill(alpaca, o["id"], logger=log)
        if fq > 0 and fp:
            book_exit_fill(o["id"], symbol, fq, fp, reason=f"{reason}_preempted_fill")
        log.warning(f"  {symbol}: cancelled working sell {o['id']} ({st}, filled {fq:g}) "
                    f"to free shares for {reason}")
    return n


def execute_exit(alpaca, symbol, qty, *, reason, coid_prefix, market=False,
                 source="monitor"):
    """Place one risk-reducing SELL and book it at the REAL fill (H3).

    * ``market=True`` only for stop-loss-class exits (CLAUDE.md); everything else
      is a marketable limit off the live bid, skipped (None) when unpriceable.
      A stop-class exit first cancels working sells on the symbol and sizes to
      the broker's ``qty_available``.
    * The fill is confirmed via shared.alpaca_http.confirm_fill and booked FIFO
      across every open lot (idempotent by order id — see the fill ledger).
    * Any unfilled remainder is recorded by order id for EOD settlement.
    * A 422 is a duplicate only if the broker holds our client_order_id;
      anything else is an error and re-raised.
    Returns {order_id, status, filled_qty, filled_price} or None if not placed.
    """
    coid = make_client_order_id(coid_prefix, symbol, "sell")
    lp = None
    if market:
        _cancel_open_sells(alpaca, symbol, reason)
    # Size against the LIVE long position, on every path. No position (e.g. a
    # working sell filled during the cancel) -> NO order: selling what we don't
    # hold would open a short and book a phantom exit.
    pos = alpaca.get_position(symbol)
    held = float((pos or {}).get("qty") or 0)
    if not pos or held <= 0 or (pos.get("side") or "long") != "long":
        log.warning(f"  {reason} {symbol}: no long position at the broker — no order")
        return None
    avail = float(pos.get("qty_available", held) or 0)
    qty = int(min(float(qty), held, avail))
    if qty <= 0:
        log.warning(f"  {reason} {symbol}: no shares available (all reserved/sold) — no order")
        return None
    if not market:
        lp = marketable_limit_price(alpaca, symbol, "sell")
        if lp is None:
            log.warning(f"  {reason}: no live price for {symbol} — exit deferred to next run "
                        f"(no market-order fallback)")
            return None
    try:
        r = alpaca.place_order(symbol=symbol, qty=qty, side="sell",
                               order_type="market" if market else "limit",
                               limit_price=lp, time_in_force="day",
                               client_order_id=coid)
        order_id = (r or {}).get("id")
        status, fq, fp = confirm_fill(alpaca, order_id, logger=log)
    except requests.HTTPError as e:
        resp = getattr(e, "response", None)
        if resp is None or resp.status_code != 422:
            raise
        prior = _resolve_duplicate(alpaca, coid, symbol, reason)
        if prior is None:
            log.error(f"::error::P1 {reason} {symbol}: order REJECTED (422, no prior order "
                      f"under {coid}): {getattr(resp, 'text', '')[:200]}")
            raise
        log.info(f"  {symbol}: {reason} exit already placed today (order {prior['id']})")
        order_id, status = prior["id"], prior.get("status", "unknown")
        fq = float(prior.get("filled_qty") or 0)
        fp = float(prior.get("filled_avg_price") or 0) or None
    booked = book_exit_fill(order_id, symbol, fq, fp, reason) if (fq > 0 and fp) else 0.0
    if fq < float(qty) or not fp:
        _record_pending_exit(order_id, coid, symbol, qty, reason, source)
        log.warning(f"  {reason} {symbol}: {status}, filled {fq:g}/{qty} — remainder pending "
                    f"(order {order_id}) for EOD settlement")
    return {"order_id": order_id, "status": status, "filled_qty": fq,
            "filled_price": fp, "booked_qty": booked}


def pending_exit_symbols():
    p = load_json(DATA_DIR / PENDING_EXITS_FILE, [])
    return {r.get("symbol") for r in p if isinstance(r, dict)} if isinstance(p, list) else set()


def settle_pending_exits(alpaca):
    """EOD: book late exit fills at the real broker price, FIFO, idempotent by
    order id; drop records once the order is terminal. Never fabricates a price."""
    path = DATA_DIR / PENDING_EXITS_FILE
    pending = load_json(path, [])
    if not isinstance(pending, list) or not pending:
        return []
    keep, settled = [], []
    for p in pending:
        oid = p.get("order_id")
        if not oid:
            continue
        try:
            o = alpaca.get_order(oid) or {}
        except Exception as e:
            log.warning(f"  Pending exit {oid} ({p.get('symbol')}): poll failed ({e}); kept")
            keep.append(p)
            continue
        new, px = _increment(oid, o.get("filled_qty"), o.get("filled_avg_price"))
        if new:
            book_exit_fill(oid, p["symbol"], o.get("filled_qty"), o.get("filled_avg_price"),
                           p.get("reason"))
            settled.append({"order_id": oid, "symbol": p["symbol"], "qty": new, "price": px})
            log.info(f"  Settled pending exit {p['symbol']}: {new:g} @ ${px:.2f} "
                     f"(order {oid}, {o.get('status')})")
        if o.get("status") not in _TERMINAL:
            keep.append(p)
    save_json(path, keep)
    return settled


def settle_pending_entries(alpaca, positions):
    """EOD: log late ENTRY fills (momentum buys that filled after the 8s confirm)
    as lots carrying their sleeve class, at the real price, idempotent by order
    id. Never logs more than the broker actually holds beyond the open lots, so
    it cannot double a lot the reconciliation already logged."""
    path = DATA_DIR / PENDING_ENTRIES_FILE
    pending = load_json(path, [])
    if not isinstance(pending, list) or not pending:
        return []
    from performance_tracker import log_trade
    held = {p.get("symbol"): float(p.get("qty") or 0) for p in (positions or [])
            if p.get("side", "long") == "long"}
    keep, settled = [], []
    for p in pending:
        oid, sym = p.get("order_id"), p.get("symbol")
        if not oid:
            continue
        try:
            o = alpaca.get_order(oid) or {}
        except Exception as e:
            log.warning(f"  Pending entry {oid} ({sym}): poll failed ({e}); kept")
            keep.append(p)
            continue
        new, px = _increment(oid, o.get("filled_qty"), o.get("filled_avg_price"))
        if new:
            open_qty = sum(float(t.get("qty") or 0) for t in load_json(DATA_DIR / "trade_log.json", [])
                           if isinstance(t, dict) and t.get("symbol") == sym
                           and t.get("status") == "open")
            room = max(0.0, held.get(sym, 0.0) - open_qty)
            qty = min(new, room)
            if qty > 1e-9:
                log_trade(sym, "buy", qty, px, p.get("bucket") or "momentum", None,
                          p.get("reasons") or ["late fill settled at EOD"],
                          intended_price=p.get("intended_price"),
                          order_class=p.get("order_class"))
                settled.append({"order_id": oid, "symbol": sym, "qty": qty, "price": px})
                log.info(f"  Settled pending entry {sym}: {qty:g} @ ${px:.2f} (order {oid})")
            _ledger_mark(oid, o.get("filled_qty"), o.get("filled_avg_price"), "entry", sym)
        if o.get("status") not in _TERMINAL:
            keep.append(p)
    save_json(path, keep)
    return settled


def _sleeve_symbols(params=None):
    """Names that belong to the schedule-managed sleeves by provenance other than
    a logged lot: the momentum book's targets, its pending late-fill entries, and
    the passive-core basket."""
    syms = set((load_json(DATA_DIR / "momentum_state.json", {}) or {}).get("targets") or {})
    pend = load_json(DATA_DIR / PENDING_ENTRIES_FILE, [])
    if isinstance(pend, list):
        syms |= {p.get("symbol") for p in pend if isinstance(p, dict) and p.get("symbol")}
    syms |= set((params or {}).get("core_basket") or ["SPY", "QQQ", "IWM", "DIA"])
    return syms


DISASTER_EXCLUSIONS_FILE = "momentum_exclusions.json"


def disaster_excluded(month):
    d = load_json(DATA_DIR / DISASTER_EXCLUSIONS_FILE, {})
    return set((d.get(month) or [])) if isinstance(d, dict) else set()


def _record_disaster_exclusion(symbol, month=None):
    month = month or et_session_date()[:7]
    path = DATA_DIR / DISASTER_EXCLUSIONS_FILE
    d = load_json(path, {})
    if not isinstance(d, dict):
        d = {}
    syms = set(d.get(month) or [])
    syms.add(symbol)
    d[month] = sorted(syms)
    for k in sorted(d)[:-6]:                 # keep ~6 months of history
        d.pop(k, None)
    save_json(path, d)


def run_disaster_exits(alpaca, positions, params, source):
    """Fire the schedule-managed disaster floor NOW (H1). In the trading session
    this runs BEFORE the momentum rebalance, so a crashed lot is exited at its
    own entry basis before any add could dilute the broker's blended average;
    the name is then excluded from that month's buys. Returns symbols exited."""
    from portfolio_manager import schedule_managed_disaster_triggers
    lots = [t for t in load_json(DATA_DIR / "trade_log.json", [])
            if isinstance(t, dict) and t.get("status") == "open"]
    exited = []
    for t in schedule_managed_disaster_triggers(positions, lots, params,
                                                sleeve_symbols=_sleeve_symbols(params)):
        sym = t["symbol"]
        log.warning(f"  DISASTER STOP ({source}): {sym} — {t['reason']}")
        _record_disaster_exclusion(sym)
        try:
            res = execute_exit(alpaca, sym, float(
                (alpaca.get_position(sym) or {}).get("qty") or 0),
                reason="disaster_stop", coid_prefix="p1stop", market=True, source=source)
        except Exception as e:
            log.error(f"::error::P1 disaster stop for {sym} failed: {e}")
            continue
        if res:
            exited.append(sym)
    return exited


def _book_has_holdings(state):
    """Does OUR record say the book holds positions (state or open lots)?"""
    if (state or {}).get("positions"):
        return True
    return any(isinstance(t, dict) and t.get("status") == "open"
               for t in load_json(DATA_DIR / "trade_log.json", []))


def verified_loss_read(alpaca, state, limits_unused=None):
    """(ok, equity, evidence) for a read that may LATCH a halt or LIQUIDATE.

    Same bar as the human halt clear (two consistent account reads + independent
    valuation), plus the 2026-07-07 signature: the broker returning NO positions
    while our state/trade log shows open holdings is treated as a data fault —
    equity==cash then "confirms" itself, so no halt and no liquidation."""
    ok, equity, ev = cross_checked_equity(alpaca, state)
    if not ok:
        return False, None, ev
    try:
        broker_positions = alpaca.get_positions() or []
    except Exception as e:
        ev["reason"] = f"positions re-read failed: {e}"
        return False, None, ev
    if not broker_positions and _book_has_holdings(state):
        ev["reason"] = ("broker returned NO positions while state/trade log show open "
                        "holdings — suspected phantom read (2026-07-07 signature)")
        log.warning(f"::warning::P1 {ev['reason']}; no halt, no liquidation this cycle")
        return False, None, ev
    return True, equity, ev


# ---------------------------------------------------------------------------
# MODE 1: MORNING RESEARCH
# ---------------------------------------------------------------------------

def run_morning_research(alpaca: AlpacaClient):
    log.info("=" * 60)
    log.info("MORNING RESEARCH — Pulling bars, computing signals")
    log.info("=" * 60)

    watchlist = load_json(CONFIG_DIR / "watchlist.json", {})
    start_date = (datetime.now(timezone.utc) - timedelta(days=330)).strftime("%Y-%m-%d")

    for bucket, info in watchlist.items():
        symbols = info.get("symbols", [])
        itype = info.get("instrument_type", "stock")
        bucket_data = {}

        for sym in symbols:
            log.info(f"  Fetching {sym} ({bucket})...")
            try:
                if itype == "crypto":
                    resp = alpaca.get_crypto_bars(sym, limit=220)
                    bars_raw = resp.get("bars", {}).get(sym, [])
                else:
                    resp = alpaca.get_stock_bars(sym, start=start_date, limit=220)
                    bars_raw = resp.get("bars", [])

                bars = []
                for b in bars_raw:
                    bars.append({
                        "t": b.get("t", ""),
                        "o": b.get("o", 0),
                        "h": b.get("h", 0),
                        "l": b.get("l", 0),
                        "c": b.get("c", 0),
                        "v": b.get("v", 0),
                    })
                bucket_data[sym] = bars
                log.info(f"    Got {len(bars)} bars for {sym}")
                time.sleep(0.3)
            except Exception as e:
                log.error(f"    Failed to fetch {sym}: {e}")

        save_json(DATA_DIR / f"{bucket}.json", {"bars": bucket_data})
        log.info(f"  Saved {bucket}.json with {len(bucket_data)} symbols")

    log.info("Running analyst_v2 signal generation...")
    from analyst_v2 import run_full_analysis
    result = run_full_analysis()

    regime = result.get("market_regime", "UNKNOWN")
    signals = result.get("signals", [])
    buy_signals = [s for s in signals if s["signal"] == "BUY"]
    short_signals = [s for s in signals if s["signal"] == "SHORT"]
    hold_signals = [s for s in signals if s["signal"] == "HOLD"]

    log.info(f"Regime: {regime}")
    log.info(f"Signals: {len(buy_signals)} BUY, {len(short_signals)} SHORT, {len(hold_signals)} HOLD")
    for s in buy_signals:
        log.info(f"  BUY  {s['symbol']:6s} score={s['score']:+.3f} | {'; '.join(s['reasons'][:2])}")
    for s in short_signals:
        log.info(f"  SHORT {s['symbol']:6s} score={s['score']:+.3f}")

    return result


# ---------------------------------------------------------------------------
# MODE 2: TRADING SESSION
# ---------------------------------------------------------------------------

def _momentum_universe():
    """(symbols, sector_map) for the momentum sleeve, from universe_wide.json.
    The bucket name is the sector, used for the per-sector concentration cap."""
    u = load_json(CONFIG_DIR / "universe_wide.json", {})
    syms, sector_map = [], {}
    for bucket, b in (u.get("buckets", {}) or {}).items():
        if b.get("instrument_type") == "stock":
            for s in b.get("symbols", []):
                syms.append(s)
                sector_map[s] = bucket
    return sorted(set(syms)), sector_map


def run_momentum_sleeve(alpaca, equity, cash, portfolio_state, limits, budget=None,
                        entries_allowed=True):
    """High-return MOMENTUM sleeve for P1 (PAPER, 2026-07-04 research).

    When ``strategy_params.momentum_sleeve_enabled`` is true, this is the PRIMARY
    allocator for P1 and replaces the passive-core + active-satellite logic. It
    rebalances MONTHLY to the top-K highest 12-1-momentum large-caps, equal
    weight, <=8%/name (guaranteed by momentum_selector), scaled by
    ``momentum_sleeve_weight``, with an optional 200-day market-trend filter (go to
    cash when SPY < its 200SMA). Fully reversible via momentum_sleeve_enabled=false.

    Returns True if it HANDLED this session (caller skips the old logic), False if
    the sleeve is disabled. Runs AFTER the kill-switch guards and the preflight.

    ``entries_allowed=False`` (halted / daily-loss / quarantined book) runs the
    RISK-REDUCING half only: rebalance SELLS execute, buys do not, and the month
    is not closed (audit 2026-10-23, H1). Every order consumes the session's
    shared ``budget`` (max_trades_per_day, H2) — sells first, so exits are
    prioritized but never exceed the cap; whatever does not fit retries next
    session. Orders are marketable limits off the LIVE quote and the month is
    marked done only when every order is CONFIRMED filled (M1).

    HONEST NOTE: the backtest CAGR was survivorship-inflated; realistic edge is
    modest with real crash risk. PAPER-ONLY until it earns a live track record.
    """
    params = load_json(DATA_DIR / "strategy_params.json", {})
    if not params.get("momentum_sleeve_enabled"):
        return False
    log.info("MOMENTUM SLEEVE active (paper high-return strategy)")

    month = et_session_date()[:7]
    mstate = load_json(DATA_DIR / "momentum_state.json", {})
    if mstate.get("last_rebalance_month") == month:
        log.info(f"  Momentum: already rebalanced for {month}; holding to next month.")
        return True

    top_k = int(params.get("momentum_top_k", 13))
    sleeve_weight = float(params.get("momentum_sleeve_weight", 0.90))
    use_trend = bool(params.get("momentum_use_trend", False))
    max_per_sector = params.get("momentum_max_per_sector", 4)

    # M3: a month's targets are FROZEN at its first attempt. An incomplete month
    # (12/day cap spill-over, unfilled limits, halt) retries only the remaining
    # diff against those SAME targets — re-ranking every session would whipsaw
    # the book daily as names cross the top-K boundary.
    frozen = (mstate.get("targets_month") == month and mstate.get("rebalance_incomplete")
              and isinstance(mstate.get("targets"), dict))
    if frozen:
        targets = {s: float(w) for s, w in mstate["targets"].items()}
        vol_scale = float(mstate.get("vol_scale") or 1.0)
        book_vol = mstate.get("book_vol")
        closes_by_sym = {}
        universe_size = int(mstate.get("universe_size") or 0)
        prices = {}
        for sym in targets:
            try:
                px = float(((alpaca.get_latest_trade(sym) or {}).get("trade") or {}).get("p") or 0)
            except Exception:
                px = 0.0
            if px > 0:
                prices[sym] = px
        log.info(f"  Momentum: retrying {month} against FROZEN targets "
                 f"({len(targets)} names, frozen {mstate.get('targets_frozen_at')}).")
    else:
        # Daily closes for the universe (need >=274 bars for 12-1 momentum). An
        # explicit start is REQUIRED — without it the free feed returns a stub (the
        # documented empty-period trap); ~420 calendar days ≈ 290 trading days.
        _start = (datetime.now(timezone.utc) - timedelta(days=420)).strftime("%Y-%m-%d")
        universe, sector_map = _momentum_universe()
        closes_by_sym, prices = {}, {}
        for sym in universe:
            try:
                bars = alpaca.get_stock_bars(sym, timeframe="1Day", start=_start, limit=500).get("bars") or []
                closes = [float(b["c"]) for b in bars if b.get("c")]
                if len(closes) >= 274:
                    closes_by_sym[sym] = closes
                    prices[sym] = closes[-1]
            except Exception as e:
                log.warning(f"  Momentum: bars unavailable for {sym}: {e}")
        if len(closes_by_sym) < top_k:
            log.error(f"::error::Momentum: only {len(closes_by_sym)} names have enough history "
                      f"(need >= {top_k}); skipping rebalance to avoid a thin book.")
            return True

        spy_closes = None
        try:
            spy_bars = alpaca.get_stock_bars("SPY", timeframe="1Day", start=_start, limit=500).get("bars") or []
            spy_closes = [float(b["c"]) for b in spy_bars if b.get("c")]
            if spy_closes:
                prices["SPY"] = spy_closes[-1]
        except Exception as e:
            log.warning(f"  Momentum: SPY bars unavailable ({e}); trend filter off this run.")

        from momentum_selector import select_top_momentum, vol_target_scalar
        raw = select_top_momentum(closes_by_sym, k=top_k, max_weight=0.08,
                                  use_trend=use_trend, market_closes=spy_closes,
                                  sector_map=sector_map, max_per_sector=max_per_sector)

        # Volatility targeting (crash protection, 2026-07-04): scale gross exposure
        # DOWN toward a target realized vol when the book is hot. Only de-risks
        # (max_scale=1.0) so it can never breach a size cap. Off if vol_target unset.
        vol_scale, book_vol = 1.0, None
        vol_target = params.get("momentum_vol_target")
        if raw and vol_target:
            vol_scale, book_vol = vol_target_scalar(
                closes_by_sym, raw, target_vol=float(vol_target),
                lookback=int(params.get("momentum_vol_lookback", 63)),
                min_scale=float(params.get("momentum_vol_min_scale", 0.30)))

        targets = {s: w * sleeve_weight * vol_scale for s, w in raw.items()}  # rest cash
        if not targets:
            log.warning("  Momentum: RISK-OFF / no eligible names — target is cash; "
                        "liquidating the momentum book.")
        else:
            _secs = {}
            for s in targets:
                _secs[sector_map.get(s, "?")] = _secs.get(sector_map.get(s, "?"), 0) + 1
            _vol = (f"vol_scale={vol_scale:.2f} "
                    f"(book_vol={book_vol*100:.0f}%, target={float(vol_target)*100:.0f}%)"
                    if vol_target and book_vol else "vol_target off")
            log.info(f"  Momentum: {len(targets)} names, per-sector {dict(_secs)} "
                     f"(cap {max_per_sector}/sector), trend_filter={use_trend}, {_vol}.")
            log.info(f"  Momentum: deploying {sum(targets.values())*100:.1f}% of equity "
                     f"(rest cash).")
        universe_size = len(closes_by_sym)

    # H1: a name disaster-stopped this month is OUT of this month's book — never
    # bought back by the rebalance (it would average down into the crash).
    excluded = disaster_excluded(month)
    if excluded & set(targets):
        log.warning(f"  Momentum: excluding disaster-stopped {sorted(excluded & set(targets))} "
                    f"from {month}'s targets")
        targets = {s: w for s, w in targets.items() if s not in excluded}

    from portfolio_manager import compute_momentum_rebalance_orders
    positions = alpaca.get_positions()
    # Seed prices for CURRENTLY-held names (e.g. the core ETFs we're exiting) so
    # they aren't stranded — the momentum universe doesn't include them.
    for p in positions:
        s = p.get("symbol")
        if s and s not in prices and p.get("current_price"):
            prices[s] = float(p["current_price"])
    orders = compute_momentum_rebalance_orders(
        positions, targets, equity, prices,
        min_notional=float(limits.get("min_position_notional_usd", 500)))
    # A target with no price produces no order — that must keep the month OPEN,
    # never read as "nothing left to do".
    unpriced = sorted(s for s in targets if not prices.get(s))
    if len(orders) > 45:
        log.error(f"::error::Momentum: {len(orders)} rebalance orders is abnormally high; "
                  f"aborting as a safety stop.")
        return True

    skipped_entries = 0
    if not entries_allowed:
        skipped_entries = sum(1 for o in orders if o["side"] != "sell")
        orders = [o for o in orders if o["side"] == "sell"]
        log.warning(f"  Momentum: EXITS ONLY (entries blocked) — {len(orders)} risk-reducing "
                    f"sell(s) run, {skipped_entries} buy(s) withheld; month stays open.")

    from performance_tracker import log_trade
    placed = confirmed = 0
    deferred = [{"symbol": u, "side": "buy", "why": "no price"} for u in unpriced]
    pending = []
    for o in orders:
        sym, side, qty = o["symbol"], o["side"], o["qty"]
        if budget is not None and not budget.take(entry=(side == "buy")):
            why = ("entries frozen (trade count unknown)"
                   if side == "buy" and budget.entries_frozen else "max_trades_per_day")
            deferred.append({"symbol": sym, "side": side, "why": why})
            continue
        lp = marketable_limit_price(alpaca, sym, side)
        if lp is None:
            if budget is not None:
                budget.refund()
            deferred.append({"symbol": sym, "side": side, "why": "no live quote"})
            log.warning(f"  Momentum: no live quote for {sym} — {side} deferred (no market fallback)")
            continue
        coid = make_client_order_id("p1mom", sym, side)
        try:
            r = alpaca.place_order(symbol=sym, qty=qty, side=side, order_type="limit",
                                   limit_price=lp, client_order_id=coid)
            order_id = (r or {}).get("id")
            _st, _fq, _fp = confirm_fill(alpaca, order_id, logger=log)
        except requests.HTTPError as e:
            resp = getattr(e, "response", None)
            prior = (_resolve_duplicate(alpaca, coid, sym, "momentum")
                     if resp is not None and resp.status_code == 422 else None)
            if budget is not None:
                budget.refund()     # a duplicate is already counted at the broker;
                                    # a rejection is not an order at all
            if prior is None:
                log.error(f"::error::Momentum {side} {sym} FAILED: {e}")
                deferred.append({"symbol": sym, "side": side, "why": f"rejected: {e}"[:160]})
                continue
            # Placed by an earlier fire today: resolve its REAL state; booking is
            # idempotent by order id, so this never double-books.
            order_id, _st = prior["id"], prior.get("status", "unknown")
            _fq = float(prior.get("filled_qty") or 0)
            _fp = float(prior.get("filled_avg_price") or 0) or None
        except Exception as e:
            log.error(f"  Momentum order failed for {sym}: {e}")
            if budget is not None:
                budget.refund()
            deferred.append({"symbol": sym, "side": side, "why": f"error: {e}"[:160]})
            continue
        placed += 1
        if side == "sell":
            if _fq > 0 and _fp:
                # FIFO across ALL open lots at the REAL fill (never limit/close).
                book_exit_fill(order_id, sym, _fq, _fp, "momentum_rebalance")
            if _fq < qty or not _fp:
                _record_pending_exit(order_id, coid, sym, qty, "momentum_rebalance", "momentum")
        else:
            new_q, new_px = _increment(order_id, _fq, _fp)
            if new_q:
                log_trade(sym, "buy", new_q, new_px, "momentum",
                          None, [f"momentum top{top_k} rebalance {month}"],
                          intended_price=lp, order_class="momentum_sleeve")
                _ledger_mark(order_id, _fq, _fp, "entry", sym)
            if _fq < qty or not _fp:
                # A fill landing after the confirm window is logged at EOD as a
                # momentum lot — never left as an unlogged, unprotected position.
                _record_pending_entry(order_id, coid, sym, qty, bucket="momentum",
                                      order_class="momentum_sleeve",
                                      reasons=[f"momentum top{top_k} rebalance {month} (late fill)"],
                                      intended_price=lp, source="momentum")
        if _st == "filled" and _fq >= qty:
            confirmed += 1
        else:
            pending.append({"symbol": sym, "side": side, "order_id": order_id,
                            "status": _st, "filled_qty": _fq, "qty": qty})
        time.sleep(0.4)

    # Close the monthly gate ONLY when every order of the full book is CONFIRMED
    # filled (M1). An unfilled limit, a deferred order (budget / no quote) or a
    # withheld buy leaves the month open: compute_momentum_rebalance_orders diffs
    # current vs target, so the next session re-attempts only what is still off,
    # idempotently (deterministic client_order_id per symbol/side/day).
    complete = entries_allowed and not deferred and confirmed == len(orders)
    if not complete:
        log.warning(f"::warning::Momentum: rebalance {month} incomplete — {confirmed}/"
                    f"{len(orders)} confirmed filled, {len(deferred)} deferred, "
                    f"{len(pending)} pending, {skipped_entries} entries withheld; "
                    f"retrying the remaining diff next session.")
    now_iso = datetime.now(timezone.utc).isoformat()
    save_json(DATA_DIR / "momentum_state.json", {
        "last_rebalance_month": month if complete else mstate.get("last_rebalance_month"),
        "rebalance_incomplete": not complete,
        # first activation stamp — anchors the live-readiness track record.
        "activated_at": mstate.get("activated_at") or now_iso,
        "rebalance_count": int(mstate.get("rebalance_count", 0)) + 1,
        "as_of": now_iso,
        "targets": {s: round(w, 4) for s, w in targets.items()},
        "targets_month": month,
        "targets_frozen_at": (mstate.get("targets_frozen_at") if frozen else now_iso),
        "orders_placed": placed, "orders_confirmed": confirmed,
        "orders_deferred": deferred, "orders_pending": pending,
        "entries_allowed": bool(entries_allowed),
        "universe_size": universe_size,
        "vol_scale": round(vol_scale, 4),
        "book_vol": round(book_vol, 4) if book_vol else None,
        "deployed_pct": round(sum(targets.values()) * 100, 1),
        "risk_off": not targets})
    log.info(f"  Momentum rebalance {month}: {placed} placed, {confirmed} confirmed filled, "
             f"{len(targets)} target names.")
    return True


def _confirmed_equity(alpaca, account, positions, portfolio_state, last_equity,
                      before_action=False):
    """Corroborate a broker equity read (shared.equity_guard — the 2026-07-07
    $26K phantom-read incident). ``before_action=True`` ALWAYS values the book
    independently and is required immediately before any halt or liquidation.
    The reference is the equity WE last trusted (saved state), not a field of
    the same possibly-corrupt account snapshot."""
    from shared.equity_guard import confirm_equity

    def _px(sym):
        return float(((alpaca.get_latest_trade(sym) or {}).get("trade") or {}).get("p") or 0)

    ref = (portfolio_state.get("day_start_equity") or portfolio_state.get("equity")
           or last_equity)
    return confirm_equity(account, positions, reference_equity=ref, get_price=_px,
                          max_jump_pct=0.0 if before_action else 15.0)


def _is_kill_switch_halt(state):
    return bool(state.get("halted")) and (
        state.get("halt_kind") == "kill_switch"
        or str(state.get("halt_reason") or "").startswith("Kill switch"))


def _latch_kill_switch(portfolio_state, drawdown_pct, check, source="unknown"):
    """Latch the drawdown halt WITH its evidence (C1a) so a human reviewing the
    lockdown can see exactly which read tripped it — and so a later clear can
    be keyed to this one halt (``halt_set_at``).

    An EXISTING kill-switch halt is never re-stamped: its first evidence and its
    ``halt_set_at`` (the key a human clear names) are preserved; later breaches
    are appended as observations."""
    from risk_officer import drawdown_reference_equity
    evidence = {
        "equity": check.get("equity"), "cash": check.get("cash"),
        "equity_reads": check.get("equity_reads")
        or [check.get("equity"), check.get("independent_equity")],
        "reference_equity": check.get("reference_equity"),
        "peak_reference_equity": drawdown_reference_equity(portfolio_state),
        "drawdown_pct": round(drawdown_pct, 3),
        "independent_equity": check.get("independent_equity"),
        "disagreement_pct": check.get("disagreement_pct"),
        "confirmation": check.get("reason")}
    if _is_kill_switch_halt(portfolio_state):
        obs = list(portfolio_state.get("halt_observations") or [])
        obs.append({"at": datetime.now(timezone.utc).isoformat(), "source": source, **evidence})
        portfolio_state["halt_observations"] = obs[-50:]
        return False
    _stamp_halt(portfolio_state, kind="kill_switch",
                reason=f"Kill switch: {drawdown_pct:.2f}% drawdown", source=source,
                evidence=evidence)
    return True


def _breach_check(alpaca, portfolio_state, account):
    """Run verified_loss_read and shape it like an equity_guard check dict."""
    ok, v_eq, ev = verified_loss_read(alpaca, portfolio_state)
    return {"ok": ok, "equity": v_eq, "cash": float(account.get("cash") or 0),
            "equity_reads": ev.get("reads"),
            "reference_equity": portfolio_state.get("day_start_equity"),
            "independent_equity": ev.get("independent_equity"),
            "reason": ev.get("confirmation") if ok else ev.get("reason")}


def run_trading_session(alpaca: AlpacaClient):
    log.info("=" * 60)
    log.info("TRADING SESSION — Validating signals, executing orders")
    log.info("=" * 60)

    if not alpaca.is_market_open():
        log.warning("Market closed — skipping trading session")
        return

    account = alpaca.get_account()
    equity = float(account["equity"])
    cash = float(account["cash"])
    last_equity = float(account["last_equity"])

    portfolio_state = load_json(DATA_DIR / "portfolio_state.json")
    limits = load_risk_limits(CONFIG_DIR)
    session_date = et_session_date()
    roll_session_anchors(portfolio_state, session_date)

    # Never trade — and never latch a halt — on an uncorroborated equity read.
    _positions0 = alpaca.get_positions()
    eq_check = _confirmed_equity(alpaca, account, _positions0, portfolio_state, last_equity)
    if not eq_check["ok"]:
        log.error(f"::error::P1 equity read UNCONFIRMED — {eq_check['reason']}. "
                  f"Skipping this session; no halt latched.")
        return
    update_peak_equity(alpaca, portfolio_state, account, _positions0, last_equity)

    # Kill switch — drawdown from the CONFIRMED high-water mark (M5); the breach
    # must survive an independent valuation before it latches.
    drawdown_pct = kill_switch_drawdown_pct(portfolio_state, equity)
    if drawdown_pct >= limits["kill_switch_drawdown_pct"]:
        # Latch only on the SAME bar as the human clear: two consistent reads +
        # independent valuation + not the empty-book phantom (audit item 3).
        eq_check = _breach_check(alpaca, portfolio_state, account)
        if eq_check["ok"]:
            drawdown_pct = kill_switch_drawdown_pct(portfolio_state, eq_check["equity"])
        if not eq_check["ok"] or drawdown_pct < limits["kill_switch_drawdown_pct"]:
            log.error(f"::error::P1 kill-switch breach NOT verified — "
                      f"{eq_check['reason']}. No halt latched; skipping session.")
            return
        log.critical(f"KILL SWITCH: Drawdown {drawdown_pct:.2f}% — HALTING ALL TRADING")
        _latch_kill_switch(portfolio_state, drawdown_pct, eq_check, source="trading-session")
        save_json(DATA_DIR / "portfolio_state.json", portfolio_state)
        return

    # Weekly loss (hard limit: -8% -> halt 7 days). Previously enforced only for
    # the disabled active sleeve via risk_officer; the momentum/core allocators
    # bypassed it (audit 2026-10-03, H5). Corroborated before it latches, and the
    # halt EXPIRES (halt_until) — it can never become another permanent freeze.
    week_start = portfolio_state.get("week_start_equity") or last_equity
    weekly_pnl_pct = (equity - week_start) / week_start * 100 if week_start > 0 else 0
    # Never overwrite an equal-or-stronger halt: re-latching would push the
    # expiry out every session, and stamping over a kill switch would give a
    # permanent halt an expiry. Only an unhalted book or a 24h daily halt escalates.
    if weekly_pnl_pct <= -limits.get("max_weekly_loss_pct", 8.0) and (
            not portfolio_state.get("halted")
            or portfolio_state.get("halt_kind") == "daily_loss"):
        eq_check = _breach_check(alpaca, portfolio_state, account)
        if not eq_check["ok"]:
            log.error(f"::error::P1 weekly-loss breach NOT corroborated — "
                      f"{eq_check['reason']}. No halt latched; skipping session.")
            return
        log.critical(f"WEEKLY LOSS LIMIT: {weekly_pnl_pct:.2f}% — halting new trading 7 days")
        _stamp_halt(
            portfolio_state, kind="weekly_loss", reason=f"Weekly loss: {weekly_pnl_pct:.2f}%",
            source="trading-session",
            until=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            evidence={"equity": eq_check.get("equity"), "week_start_equity": week_start,
                      "weekly_pnl_pct": round(weekly_pnl_pct, 3),
                      "independent_equity": eq_check.get("independent_equity"),
                      "confirmation": eq_check.get("reason")})
        save_json(DATA_DIR / "portfolio_state.json", portfolio_state)
        return

    # Halt lifecycle: timed halts expire; a human-owned clear is honoured only on
    # a fresh cross-checked read (C1c); an evidence-less halt is flagged (C1d).
    _expire_halt_if_due(portfolio_state)
    maybe_apply_halt_clear(alpaca, portfolio_state, limits, source="trading-session")
    _warn_if_unverified_halt(portfolio_state)

    # ENTRY gates. None of these may stop a risk-REDUCING exit (H1): when any is
    # set the session still runs, in exits-only mode.
    entry_block = None
    day_start = portfolio_state.get("day_start_equity", last_equity)
    daily_pnl_pct = (equity - day_start) / day_start * 100 if day_start > 0 else 0
    if daily_pnl_pct <= -limits["max_daily_loss_pct"]:
        entry_block = f"daily loss limit {daily_pnl_pct:.2f}% — no new trades today"
    elif portfolio_state.get("halted"):
        entry_block = f"system halted: {portfolio_state.get('halt_reason')}"
    else:
        # Human strategy control (config/strategy_controls.json).
        from shared.strategy_controls import entries_enabled
        _ok, _why = entries_enabled("portfolio_1")
        if not _ok:
            entry_block = f"allocation quarantined: {_why}"
    if entry_block:
        log.warning(f"::warning::P1 new entries blocked — {entry_block}. "
                    f"Risk-reducing exits still run.")

    # Disaster floor BEFORE any allocator (H1): exits are never gated by entry
    # blocks or preflight, and must see each lot's own basis before a rebalance
    # add can dilute it.
    try:
        run_disaster_exits(alpaca, alpaca.get_positions(),
                           load_json(DATA_DIR / "strategy_params.json", {}), "trading-session")
    except Exception as e:
        log.error(f"::error::P1 pre-session disaster check failed: {e}")

    # Preflight self-check FIRST (H2) — fail CLOSED before ANY order if the sizing
    # math, self-learned params, account health, risk limits, or data freshness
    # are off (the 2026-06-01 class). Previously the momentum sleeve ran BEFORE
    # this and so bypassed it entirely.
    from analyst_v2 import load_adaptive_params
    from shared.preflight import run_preflight
    _sig_file = DATA_DIR / "signals.json"
    _signals = load_json(_sig_file) if _sig_file.exists() else {}
    _data_fresh = str(_signals.get("timestamp", "")).startswith(
        datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    pf_ok, pf = run_preflight(
        limits=limits, account=account, params=load_adaptive_params(),
        sizing_canary=True, crypto_canary=True, data_fresh=_data_fresh,
        portfolio_id="portfolio_1",
    )
    save_json(DATA_DIR / "preflight_report.json", pf)
    for _w in pf["warnings"]:
        log.warning(f"  Preflight: {_w}")
    if not pf_ok:
        for _f in pf["hard_failures"]:
            log.error(f"::error::PREFLIGHT FAILED (P1): {_f}")
        log.critical("Preflight failed — refusing to trade (fail-closed)")
        save_json(DATA_DIR / "portfolio_state.json", portfolio_state)
        return

    # ONE daily trade budget for every allocator this session (H2).
    budget = build_trade_budget(alpaca, limits, session_date)

    # Momentum sleeve (high-return PAPER strategy, 2026-07-04 research). When
    # enabled it is the PRIMARY allocator for P1 and REPLACES the passive-core +
    # active logic below. Reversible: strategy_params.momentum_sleeve_enabled=false.
    if run_momentum_sleeve(alpaca, equity, cash, portfolio_state, limits,
                           budget=budget, entries_allowed=entry_block is None):
        portfolio_state["trades_today"] = budget.used
        _sync_portfolio_state(alpaca, portfolio_state)
        return

    if entry_block:
        _sync_portfolio_state(alpaca, portfolio_state)
        return

    # Run risk officer validation
    from risk_officer import run_validation
    # Update portfolio state for risk officer
    positions = alpaca.get_positions()
    portfolio_state["equity"] = equity
    portfolio_state["day_start_equity"] = portfolio_state.get("day_start_equity", last_equity)
    portfolio_state["week_start_equity"] = portfolio_state.get("week_start_equity", last_equity)
    portfolio_state["trades_today"] = budget.used
    portfolio_state["total_exposure"] = sum(abs(float(p.get("market_value", 0))) for p in positions)
    portfolio_state["short_exposure"] = sum(
        abs(float(p.get("market_value", 0))) for p in positions if p.get("side") == "short"
    )
    portfolio_state["crypto_exposure"] = 0
    save_json(DATA_DIR / "portfolio_state.json", portfolio_state)

    # --- Passive index core (regime-aware) — the evidence-mandated allocation ----
    # core_satellite study: a passive broad-ETF core dominates the active multifactor
    # strategy out-of-sample by ~+2.16 Sharpe (-0.33 -> +1.83). Allocate core_weight x
    # equity across SPY/QQQ/IWM/DIA, each capped strictly UNDER the 12% ETF limit and
    # scaled down in bears. Runs BEFORE active execution so the core gets first call on
    # cash; gradual (active positions free cash as they close). core_weight=0 -> off.
    # Trade budget is shared with the active sleeve below so core buys COUNT against
    # the hardcoded max_trades_per_day (audit fix: core was bypassing the 12/day cap).
    trades_executed = 0
    max_trades = budget.entry_remaining      # this path opens risk: frozen -> 0
    _params = load_adaptive_params()
    # Fail-closed on stale data: only allocate the core when signals are fresh, so a
    # missing/old regime can't silently size a full-weight core (audit fix).
    if _params.get("core_weight") and _data_fresh:
        from portfolio_manager import compute_core_orders, core_regime
        # FIX: signals.json stores the regime under "market_regime" — the old
        # "regime" key always fell back to BULL, so bear de-risking never engaged.
        _regime = core_regime(_signals)
        _basket = _params.get("core_basket") or ["SPY", "QQQ", "IWM", "DIA"]
        _prices = {}
        for _s in _basket:
            try:
                _q = alpaca.get_latest_quote(_s).get("quote", {})
                _prices[_s] = float(_q.get("ap", 0) or 0) or float(_q.get("bp", 0) or 0)
            except Exception:
                pass
        # Core sub-budget so it never starves the active sleeve of the daily trade
        # cap (audit fix): keep at least half the budget for active + rotation.
        _core_budget = max(2, max_trades // 2)
        _core_placed = 0
        for _co in compute_core_orders(positions, equity, cash, _params, _regime, _prices, limits):
            if trades_executed >= max_trades or _core_placed >= _core_budget:
                break
            _sym = _co["symbol"]
            # Tradability gate (audit fix): never buy a non-tradable / inactive ETF.
            try:
                _asset = alpaca.get_asset(_sym)
            except Exception:
                _asset = None
            if not _asset or not _asset.get("tradable") or _asset.get("status") != "active":
                log.warning(f"  CORE: skip {_sym} — not tradable/active")
                continue
            try:
                _ask = _prices.get(_sym, 0)
                _lp = round(_ask * 1.001, 2) if _ask else None
                if not _lp:
                    # Limit orders only (L1): no live price -> no order this run.
                    log.warning(f"  CORE: skip {_sym} — no live quote (no market fallback)")
                    continue
                _r = alpaca.place_order(
                    symbol=_sym, qty=_co["qty"], side="buy",
                    order_type="limit", limit_price=_lp,
                    client_order_id=make_client_order_id("p1core", _sym, "buy"))
                trades_executed += 1
                _core_placed += 1
                log.info(f"  CORE: buy {_co['qty']} x {_sym} — {_co['reason']}")
                _st, _fq, _fp = confirm_fill(alpaca, _r.get("id"))
                if _fq > 0:
                    _px = _fp or _lp or _ask
                    cash -= _fq * _px
                    from performance_tracker import log_trade
                    # D9: attribute to the sleeve's real bucket — defensive core
                    # ETFs (TLT/GLD/SHY/BIL) were all logged as "core_equity",
                    # which would poison future by-bucket learning stats.
                    _bucket = ("defensive" if _co.get("asset_class") == "defensive"
                               else "core_equity")
                    log_trade(_sym, "buy", _fq, round(_px, 4), _bucket,
                              None, [_co["reason"]], intended_price=_lp, order_class="passive_core")
            except requests.HTTPError as _e:
                # Duplicate client_order_id (422) on a retried/double-fired run means
                # this core buy already exists — an idempotent skip, not a failure.
                if getattr(_e, "response", None) is not None and _e.response.status_code == 422:
                    trades_executed += 1
                    _core_placed += 1
                    log.info(f"  CORE: {_sym} already placed (idempotent skip)")
                else:
                    log.error(f"  Core buy failed for {_sym}: {_e}")
            except Exception as _e:
                log.error(f"  Core buy failed for {_sym}: {_e}")
        positions = alpaca.get_positions()  # refresh after core buys
        # FIX: re-sync exposure so the risk officer validates the active sleeve
        # AGAINST the core just deployed (was reading pre-core total_exposure ->
        # the combined book could breach the 160% gross cap).
        portfolio_state["total_exposure"] = sum(abs(float(p.get("market_value", 0))) for p in positions)
        save_json(DATA_DIR / "portfolio_state.json", portfolio_state)

    validated = run_validation(asset_lookup=_build_asset_lookup(alpaca))
    approved = validated.get("approved_orders", [])
    log.info(f"Validated: {validated['summary']['approved']} approved, {validated['summary']['rejected']} rejected")

    # --- Core-only mode (committee-approved risk reduction, 2026-06-18 audit) -----
    # The active multifactor satellite has a MEASURED negative realized edge
    # (profit factor 0.23, -$4,782 over 53 closes) and its own out-of-sample study
    # shows the diversified passive core DOMINATES the blend on BOTH return and
    # drawdown (core-only OOS Sharpe 1.08 / DD 16.4% vs deployed 0.59 / 16.9%).
    # active_entries_enabled=false -> the satellite opens NO new entries; the core
    # block above is the sole allocator and existing active positions wind down by
    # riding their stops via the monitor. Exits/sells are NEVER suppressed.
    from portfolio_manager import filter_active_entries, regime_gate_active_entries
    approved, _suppressed = filter_active_entries(approved, _params)
    if _suppressed:
        log.info(f"Core-only mode: suppressing {len(_suppressed)} active entry signal(s) "
                 f"({', '.join(o['symbol'] for o in _suppressed)}) — satellite winding down, "
                 f"existing positions ride their stops")
    # Regime brake (chief-expert rec #3): block new active LONGS when the short-
    # horizon market is adverse. Dormant while active entries are suppressed
    # above; active when the satellite is re-enabled.
    approved, _regime_blocked = regime_gate_active_entries(approved, _signals, _params)
    if _regime_blocked:
        log.info(f"Regime brake: blocked {len(_regime_blocked)} new long entry(ies) "
                 f"({', '.join(o['symbol'] for o in _regime_blocked)}) — adverse "
                 f"short-horizon regime, not buying high-beta into weakness")

    if not approved:
        log.info("No approved orders to execute")
        _sync_portfolio_state(alpaca, portfolio_state)
        return

    # trades_executed / max_trades are initialized BEFORE the passive-core block so
    # core + active orders share one daily budget (audit fix); do not reset here.
    placed_count = 0       # orders submitted to the broker (or idempotent dup)
    filled_count = 0       # orders confirmed filled this run
    skips = []             # [{symbol, reason}] for approved orders we did not place

    # --- Capital recycling (rotation) ----------------------------------------
    # If the book is cash-starved, exit the lowest-conviction HOLD names to fund
    # the highest-conviction approved BUYs. compute_rotation_plan is fail-safe:
    # it returns nothing unless genuinely starved (cash < min_cash_pct of equity).
    # Sells go in first so the buy loop below sees the freed cash this same run.
    rot_cfg = limits.get("rotation", {})
    rotated = []
    if rot_cfg.get("enabled", True) and approved:
        from portfolio_manager import compute_rotation_plan
        rotation = compute_rotation_plan(
            positions, validated, cash, equity,
            min_cash_pct=rot_cfg.get("min_cash_pct", 3.0),
            rotation_edge=rot_cfg.get("rotation_edge", 0.25),
            max_rotation_pct=rot_cfg.get("max_rotation_pct", 15.0),
            max_rotations=rot_cfg.get("max_rotations", 3),
        )
        for rot in rotation:
            if trades_executed >= max_trades:
                break
            rsym, rqty = rot["symbol"], rot["qty"]
            try:
                log.info(f"  ROTATE: selling {rqty} x {rsym} — {rot['reason']}")
                res = execute_exit(alpaca, rsym, rqty, reason="rotation",
                                   coid_prefix="p1", source="rotation")
                if res is None:
                    continue                    # unpriceable / idempotent dup
                trades_executed += 1            # counts against the daily trade budget
                if res["filled_qty"] > 0 and res["filled_price"]:
                    cash += res["filled_qty"] * res["filled_price"]
                    rotated.append(rsym)
                time.sleep(0.5)
            except Exception as e:
                log.error(f"  Rotation sell error for {rsym}: {e}")
        if rotated:
            log.info(f"Rotation freed cash by exiting {len(rotated)} HOLD name(s): {rotated}")

    for order in approved:
        if trades_executed >= max_trades:
            log.warning(f"Daily trade limit reached ({limits['max_trades_per_day']})")
            break

        symbol = order["symbol"]
        signal = order["signal"]
        qty = order.get("approved_qty", 0)
        price = order.get("price", 0)
        itype = get_instrument_type(symbol)

        if qty <= 0 or price <= 0:
            skips.append({"symbol": symbol, "reason": "non-positive qty/price", "benign": False})
            continue

        existing = alpaca.get_position(symbol)
        max_add_qty = None
        if existing and signal == "BUY":
            existing_val = abs(float(existing["market_value"]))
            existing_pct = existing_val / equity * 100
            max_pct = limits["max_single_position_pct"].get(itype, 8)
            if existing_pct >= max_pct * 0.85:
                log.info(f"  Already hold {existing_pct:.1f}% of {symbol}, skipping")
                skips.append({"symbol": symbol, "reason": f"already hold {existing_pct:.1f}%", "benign": True})
                continue
            # Cap the ADD so (existing + new) stays within the single-position cap.
            # risk_officer caps the NEW order to max_pct of equity but does NOT
            # subtract the existing holding, so one add to a ~6% name could land at
            # ~14% (≈2x the cap, observed live: AMZN 13.5%, GOOGL 10.4%). Enforce
            # the PROPOSED total here, where the live position is known.
            from shared.sizing import position_add_room_qty
            max_add_qty = position_add_room_qty(existing_val, price, equity, max_pct,
                                                fractional=(itype == "crypto"))
            if max_add_qty <= 0:
                log.info(f"  {symbol} at {existing_pct:.1f}% leaves no room under {max_pct}% cap, skipping")
                skips.append({"symbol": symbol, "reason": f"no room under {max_pct}% cap", "benign": True})
                continue
            if qty > max_add_qty:
                log.info(f"  Capping {symbol} add {qty}->{max_add_qty} to respect {max_pct}% cap "
                         f"(hold {existing_pct:.1f}%)")
                qty = max_add_qty
                order["approved_dollar_amount"] = qty * price  # keep cash check in sync

        dollar_amount = order.get("approved_dollar_amount", qty * price)
        if dollar_amount > cash * 0.95:
            # Crypto sizes fractionally; equities in whole shares.
            qty = round(cash * 0.90 / price, 6) if itype == "crypto" else int(cash * 0.90 / price)
            if max_add_qty is not None and qty > max_add_qty:
                qty = max_add_qty  # a cash-driven refill must not breach the position cap
            if qty <= 0:
                log.warning(f"  Insufficient cash for {symbol}")
                skips.append({"symbol": symbol, "reason": "insufficient cash", "benign": True})
                continue

        # Min-notional gate — never place a capital-starved stub (observed
        # 2026-06-02: 3 shares / $184 of XLE with $80 cash left). Skip cleanly
        # instead of consuming the last dollar on a meaningless position.
        from shared.sizing import meets_min_notional
        min_notional = limits.get("min_position_notional_usd", 500)
        if signal == "BUY" and not meets_min_notional(
                qty, price, floor_usd=min_notional, equity=equity, floor_pct=0.5):
            log.info(f"  {symbol} order ${qty * price:,.0f} below min notional "
                     f"(${min_notional}) — skipping stub")
            skips.append({"symbol": symbol, "reason": "below min notional", "benign": True})
            continue

        side = "buy" if signal == "BUY" else "sell"

        # Money-path re-check: borrow status changes daily, so re-confirm ETB
        # immediately before opening a short. Fail-closed — skip if not ETB.
        if signal == "SHORT" and itype != "crypto":
            from shared.alpaca_http import evaluate_asset_gate
            ok_short, short_reasons, _ = evaluate_asset_gate(
                alpaca.get_asset(symbol), "SHORT")
            if not ok_short:
                log.warning(f"  SHORT {symbol} skipped at execution: "
                            f"{'; '.join(short_reasons)}")
                skips.append({"symbol": symbol, "reason": "short not ETB at execution", "benign": True})
                continue

        coid = make_client_order_id("p1", symbol, side)
        try:
            if itype == "crypto":
                quote_price = price
                limit_price = round(quote_price * (1.002 if side == "buy" else 0.998), 2)
                result = alpaca.place_crypto_order(
                    symbol=symbol, qty=qty, side=side,
                    order_type="limit", limit_price=limit_price,
                    client_order_id=coid,
                )
            else:
                quote = alpaca.get_latest_quote(symbol)
                ask = float(quote.get("quote", {}).get("ap", 0))
                bid = float(quote.get("quote", {}).get("bp", 0))
                mid = (ask + bid) / 2 if bid > 0 and ask > 0 else price

                if side == "buy":
                    limit_price = round(mid * 1.0015, 2)
                else:
                    limit_price = round(mid * 0.9985, 2)

                result = alpaca.place_order(
                    symbol=symbol, qty=qty, side=side,
                    order_type="limit", limit_price=limit_price,
                    client_order_id=coid,
                )

            order_id = result.get("id")
            placed_count += 1
            # Confirm the fill before logging — never record a phantom entry.
            status, filled_qty, filled_price = confirm_fill(alpaca, order_id)
            entry_price = filled_price if filled_price else limit_price

            if filled_qty <= 0:
                log.info(f"  {side.upper()} {symbol}: order {status} (0 filled) "
                         f"— working limit @ ${limit_price:.2f}, not logged until filled")
                # Order still counts against the daily trade budget (it was placed).
                trades_executed += 1
                cash -= qty * limit_price
                time.sleep(0.5)
                continue

            filled_count += 1
            log.info(f"  {side.upper()} {filled_qty:g} x {symbol} @ ${entry_price:.2f} "
                     f"(${filled_qty * entry_price:,.0f}) — {status}")

            from performance_tracker import log_trade
            bucket = get_bucket_for_symbol(symbol)
            log_trade(
                symbol=symbol, side=side, qty=filled_qty, entry_price=entry_price,
                bucket=bucket, signal_score=order.get("confidence", 0),
                reasons=order.get("reasons", []),
                stop_loss=order.get("stop_loss"),
                take_profit=order.get("take_profit"),
                intended_price=limit_price,
                borrow_status=("etb" if signal == "SHORT" else None),
                order_class="simple",
            )
            trades_executed += 1
            cash -= filled_qty * entry_price
            time.sleep(0.5)

        except requests.HTTPError as e:
            resp = getattr(e, "response", None)
            # 422 with a duplicate client_order_id means this order was already
            # placed on a prior fire today — idempotent no-op, not an error.
            if resp is not None and resp.status_code == 422 and "client_order_id" in resp.text:
                log.info(f"  {symbol}: already placed today (idempotent skip)")
                placed_count += 1  # order exists at broker from a prior fire today
                continue
            log.error(f"  Order failed for {symbol}: {e}")
            if resp is not None:
                log.error(f"  Response: {resp.text}")
        except Exception as e:
            log.error(f"  Unexpected error for {symbol}: {e}")

    log.info(f"Trading session complete: {trades_executed} orders placed")

    # Execution-integrity audit — "approved>0 but placed==0" with no error is the
    # exact symptom that hid the 2026-06-01 incident. Persist it; shout on anomaly.
    from shared.integrity import execution_integrity, write_integrity_report
    integrity = execution_integrity(
        total_signals=validated["summary"]["total_signals"],
        approved=len(approved), placed=placed_count, filled=filled_count,
        halted=bool(portfolio_state.get("halted")), cash_available=cash > 100,
        skipped=skips, portfolio_id="portfolio_1",
    )
    write_integrity_report(str(DATA_DIR / "execution_integrity.json"), integrity)
    if integrity["anomalous"]:
        log.warning(f"::warning::EXECUTION ANOMALY (P1): {integrity['anomaly_reason']}")

    # Strategy conformance — record P1's mandate adherence for the watchdog.
    from shared.integrity import (bracket_conformance, strategy_conformance,
                                  write_conformance_report)
    conf = strategy_conformance(portfolio_id="portfolio_1", checks=[
        bracket_conformance(approved, stop_key="stop_loss", tp_key="take_profit"),
        {"name": "regime_applied",
         "ok": bool(_signals.get("market_regime")) and "regime_modifiers" in _signals,
         "detail": f"regime={_signals.get('market_regime')}"},
    ])
    write_conformance_report(str(DATA_DIR / "strategy_conformance.json"), conf)
    for _v in conf["violations"]:
        log.warning(f"::warning::CONFORMANCE (P1): {_v['name']} — {_v['detail']}")

    _sync_portfolio_state(alpaca, portfolio_state)


# ---------------------------------------------------------------------------
# MODE 3: INTRADAY MONITOR
# ---------------------------------------------------------------------------

# Regime severity ordering (least -> most bearish). Used to detect intraday
# DETERIORATION vs the morning regime (committee rec #5).
_REGIME_SEVERITY = ["STRONG_BULL", "BULL", "RECOVERY", "TRANSITIONAL",
                    "UNKNOWN", "CORRECTION", "BEAR", "STRONG_BEAR"]


def _regime_rank(regime):
    return (_REGIME_SEVERITY.index(regime) if regime in _REGIME_SEVERITY
            else _REGIME_SEVERITY.index("UNKNOWN"))


def refresh_intraday_regime(alpaca: AlpacaClient, portfolio_state: dict, signals_data: dict):
    """Recompute the SPY market regime intraday so the stored label stops lagging a
    midday pullback (committee rec #5). The morning regime in signals.json is the
    provenance for that day's signals; this writes a fresh, timestamped
    `current_regime` onto portfolio_state and warns when it has DETERIORATED vs the
    morning read. ADVISORY: updates the label only — it places no orders and does
    not alter the morning signals. Best-effort; never breaks the monitor.
    """
    try:
        from analyst_v2 import detect_regime, regime_allocation_modifier
        # Explicit start (CLAUDE.md bars rule): without one the feed returns a
        # single bar and the refresh never had enough history.
        _start = (datetime.now(timezone.utc) - timedelta(days=330)).strftime("%Y-%m-%d")
        resp = alpaca.get_stock_bars("SPY", timeframe="1Day", start=_start, limit=220)
        bars = resp.get("bars", []) if isinstance(resp, dict) else (resp or [])
        closes = [float(b["c"]) for b in bars if b.get("c")]
        if len(closes) < 50:
            log.info("  Intraday regime refresh: insufficient SPY history")
            return None
        regime = detect_regime(closes)
        morning = (signals_data or {}).get("market_regime", "UNKNOWN")
        portfolio_state["current_regime"] = regime
        portfolio_state["current_regime_at"] = datetime.now(timezone.utc).isoformat()
        portfolio_state["current_regime_modifiers"] = regime_allocation_modifier(regime)
        portfolio_state["morning_regime"] = morning
        deteriorated = _regime_rank(regime) > _regime_rank(morning)
        portfolio_state["regime_deteriorated_intraday"] = deteriorated
        if deteriorated:
            log.warning(f"  Regime DETERIORATED intraday: morning {morning} -> now {regime} "
                        f"(SPY ${closes[-1]:.2f}) — risk posture should lean defensive")
        else:
            log.info(f"  Intraday regime: {regime} (morning {morning}, SPY ${closes[-1]:.2f})")
        return regime
    except Exception as e:
        log.warning(f"  Intraday regime refresh skipped: {e}")
        return None


def run_intraday_monitor(alpaca: AlpacaClient):
    log.info("=" * 60)
    log.info("INTRADAY MONITOR — Checking P&L, stops, kill switch")
    log.info("=" * 60)

    if not alpaca.is_market_open():
        log.info("Market closed — skipping intraday monitor")
        return

    account = alpaca.get_account()
    equity = float(account["equity"])
    last_equity = float(account["last_equity"])
    positions = alpaca.get_positions()

    portfolio_state = load_json(DATA_DIR / "portfolio_state.json")
    limits = load_risk_limits(CONFIG_DIR)
    roll_session_anchors(portfolio_state, et_session_date())

    # C2: reconcile order state every cycle so partial/late fills, cancels and
    # rejections are never invisible between cron runs. Best-effort — never break
    # the monitor loop on a reconciliation hiccup.
    try:
        from shared.order_state import reconcile_and_persist, stale_working_orders, load_state
        all_orders = alpaca.get_orders(status="all")
        events = reconcile_and_persist(str(DATA_DIR / "order_state.json"), all_orders)
        for ev in events:
            log.info(f"  Order event: {ev['type']} {ev.get('symbol','')} "
                     f"{ev.get('order_id','')}")
        stale = stale_working_orders(load_state(str(DATA_DIR / "order_state.json")))
        for s in stale:
            log.warning(f"  Stale working order {s['order_id']} ({s['symbol']}) "
                        f"age {s['age_seconds']}s — review for repricing/cancel")
    except Exception as e:
        log.warning(f"  Order-state reconcile skipped: {e}")

    # Liquidation and halts act only on a corroborated equity read: a breach is
    # re-valued independently before anything fires. An uncorroborated breach
    # skips the drawdown/daily-loss action this cycle (stops below still run —
    # they are risk-reducing and price-based, not equity-based).
    drawdown_pct = kill_switch_drawdown_pct(portfolio_state, equity)   # from peak (M5)
    day_start = portfolio_state.get("day_start_equity", last_equity)
    daily_pnl_pct = (equity - day_start) / day_start * 100 if day_start > 0 else 0
    eq_check = {"ok": True}
    if (drawdown_pct >= limits["kill_switch_drawdown_pct"]
            or daily_pnl_pct <= -limits["max_daily_loss_pct"]):
        # A halt or LIQUIDATION acts only on a verified read: two consistent
        # account reads + independent valuation + not the empty-book phantom.
        eq_check = _breach_check(alpaca, portfolio_state, account)
        if not eq_check["ok"]:
            log.error(f"::error::P1 monitor loss breach NOT verified — "
                      f"{eq_check['reason']}. No liquidation/halt this cycle.")
        else:
            drawdown_pct = kill_switch_drawdown_pct(portfolio_state, eq_check["equity"])
            daily_pnl_pct = ((eq_check["equity"] - day_start) / day_start * 100
                             if day_start > 0 else 0)
    else:
        update_peak_equity(alpaca, portfolio_state, account, positions, last_equity)

    # Kill switch
    if eq_check["ok"] and drawdown_pct >= limits["kill_switch_drawdown_pct"]:
        log.critical(f"KILL SWITCH TRIGGERED: {drawdown_pct:.2f}% drawdown — LIQUIDATING ALL")
        try:
            alpaca.close_all_positions()
            alpaca.cancel_all_orders()
        except Exception as e:
            log.error(f"Liquidation error: {e}")
        _latch_kill_switch(portfolio_state, drawdown_pct, eq_check, source="intraday-monitor")
        save_json(DATA_DIR / "portfolio_state.json", portfolio_state)
        return

    # Daily loss — use day_start_equity from state for consistency
    # Latch only on an unhalted book: a daily halt must never overwrite (and so
    # put a 24h expiry on) a kill-switch or weekly halt, nor re-extend itself.
    if (eq_check["ok"] and daily_pnl_pct <= -limits["max_daily_loss_pct"]
            and not portfolio_state.get("halted")):
        log.warning(f"Daily loss limit breached: {daily_pnl_pct:.2f}% — halting for 24h")
        _stamp_halt(
            portfolio_state, kind="daily_loss", reason=f"Daily loss: {daily_pnl_pct:.2f}%",
            source="intraday-monitor",
            until=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            evidence={"equity": eq_check.get("equity", equity),
                      "day_start_equity": day_start,
                      "daily_pnl_pct": round(daily_pnl_pct, 3),
                      "independent_equity": eq_check.get("independent_equity"),
                      "confirmation": eq_check.get("reason")})
        save_json(DATA_DIR / "portfolio_state.json", portfolio_state)
        return

    # Halt lifecycle: timed halts expire; a human-owned clear is honoured only on
    # a fresh cross-checked read (C1c); an evidence-less halt is flagged (C1d).
    # Exits below run whether or not the book is halted (H1).
    _expire_halt_if_due(portfolio_state)
    maybe_apply_halt_clear(alpaca, portfolio_state, limits, source="intraday-monitor")
    _warn_if_unverified_halt(portfolio_state)

    # Stop-loss and take-profit checks. Pass the OPEN trade log so a held position
    # absent from today's signals still gets its persisted entry stop enforced
    # (otherwise it would be left unprotected — the -10.8% no-stop failure mode).
    signals_data = load_json(DATA_DIR / "signals.json", {})
    trade_log = load_json(DATA_DIR / "trade_log.json", [])
    open_trades = [t for t in trade_log if isinstance(t, dict) and t.get("status") == "open"]
    strategy_params = load_json(DATA_DIR / "strategy_params.json", {})
    from portfolio_manager import (active_sleeve_exit_triggers, check_stop_triggers,
                                    compute_stop_levels)
    triggers = check_stop_triggers(positions, signals_data, open_trades, strategy_params)
    # Active-sleeve hard max-loss + loser time-stop (chief-expert rec #2). Scoped
    # to active positions only (never the passive core). Merged with the stop
    # triggers, de-duped by symbol so we don't double-fire on one name this run.
    _ase = limits.get("active_sleeve_exits", {}) or {}
    _already = {t["symbol"] for t in triggers}
    for _t in active_sleeve_exit_triggers(
            compute_stop_levels(positions, signals_data, open_trades, strategy_params),
            open_trades,
            max_loss_pct=_ase.get("max_loss_pct", 4.0),
            time_stop_days=_ase.get("loser_time_stop_days", 4),
            active_entries_enabled=bool(strategy_params.get("active_entries_enabled"))):
        if _t["symbol"] not in _already:
            triggers.append(_t)
            _already.add(_t["symbol"])
    # Disaster floor for the STOP-EXEMPT rebalanced sleeves (H1): momentum /
    # core lots skip intraday stops, but never ride unbounded (CAT -28.5%).
    from portfolio_manager import schedule_managed_disaster_triggers
    for _t in schedule_managed_disaster_triggers(positions, open_trades, strategy_params,
                                                 sleeve_symbols=_sleeve_symbols(strategy_params)):
        if _t["symbol"] not in _already:
            triggers.append(_t)
            _already.add(_t["symbol"])

    for trigger in triggers:
        sym = trigger["symbol"]
        action = trigger["action"]
        log.warning(f"  TRIGGER: {action} for {sym} (P&L: {trigger['pnl_pct']:.1f}%)")

        try:
            pos = alpaca.get_position(sym)
            if not pos:
                continue
            qty = int(float(pos["qty"]))
            if qty <= 0:
                continue        # long exits only — never sell into (or grow) a short

            # Deterministic exit ids (shared.alpaca_http): a concurrent monitor /
            # guardian run re-issuing the same exit today gets an idempotent 422
            # instead of a second sell. Every exit is booked at its CONFIRMED
            # fill, FIFO across all open lots; an unfilled remainder is recorded
            # by order id for EOD settlement — never at the trigger price (H3).
            if action in ("STOP_LOSS_SELL", "HARD_STOP_SELL", "DISASTER_STOP_SELL"):
                # Stop-loss-class exits may be market orders (CLAUDE.md).
                _reason = {"STOP_LOSS_SELL": "stop_loss",
                           "HARD_STOP_SELL": "active_max_loss",
                           "DISASTER_STOP_SELL": "disaster_stop"}[action]
                if action == "DISASTER_STOP_SELL":
                    _record_disaster_exclusion(sym)
                res = execute_exit(alpaca, sym, qty, reason=_reason,
                                   coid_prefix="p1stop", market=True)
                if res:
                    log.warning(f"  {action}: sold {res['filled_qty']:g}/{qty} x {sym} "
                                f"@ {res['filled_price']} — {trigger.get('reason', _reason)}")

            elif action == "TIME_STOP_SELL":
                # Not a stop-loss: marketable limit off the live bid (L1).
                # Own id prefix: an unfilled time-stop limit must never 422-block
                # a later same-day stop-loss market exit on the same name.
                res = execute_exit(alpaca, sym, qty, reason="active_time_stop",
                                   coid_prefix="p1time")
                if res:
                    log.warning(f"  {action}: sold {res['filled_qty']:g}/{qty} x {sym} "
                                f"@ {res['filled_price']} — {trigger.get('reason')}")

            elif action == "TAKE_PROFIT_SELL":
                sell_qty = max(1, qty // 2)
                res = execute_exit(alpaca, sym, sell_qty, reason="take_profit",
                                   coid_prefix="p1tp")
                if res:
                    log.info(f"  TAKE PROFIT: sold {res['filled_qty']:g}/{sell_qty} of {qty} "
                             f"x {sym} @ {res['filled_price']}")

        except Exception as e:
            log.error(f"  Stop/TP order failed for {sym}: {e}")

    # Cap-maintenance trims (H1): entry-time caps don't catch a position that
    # DRIFTS past its asset-class cap as it appreciates (IWM/XLI breached 12%).
    # Trim the breach back to the cap — risk-REDUCING, marketable limit SELLs only.
    try:
        from portfolio_manager import compute_cap_trims
        cfg_limits = load_risk_limits(CONFIG_DIR, {})
        bucket_map = portfolio_state.get("positions", {})
        for trim in compute_cap_trims(positions, equity, cfg_limits, bucket_map):
            sym, tq = trim["symbol"], trim["trim_qty"]
            # `positions` was read before the stop exits above; re-read so a
            # name already sold this cycle is never sold again into a short.
            fresh = alpaca.get_position(sym)
            held = int(float(fresh["qty"])) if fresh else 0
            tq = min(int(tq), held)
            if tq <= 0:
                continue
            res = execute_exit(alpaca, sym, tq, reason=trim["reason"], coid_prefix="p1cap")
            if res:
                log.warning(f"  CAP TRIM: sold {res['filled_qty']:g}/{tq} {sym} "
                            f"({trim['weight_pct']}% > {trim['cap_pct']}% cap)")
    except Exception as e:
        log.warning(f"  Cap-maintenance trim skipped: {e}")

    # Portfolio health
    from portfolio_manager import portfolio_health_check
    health = portfolio_health_check(account, positions)
    if not eq_check["ok"]:
        # Health alerts derive from the same equity read; on an uncorroborated
        # read they would announce a phantom "KILL SWITCH" (log-only, but false).
        log.warning("  Health alerts suppressed: equity read not corroborated this cycle")
        health["alerts"] = []
    for alert in health.get("alerts", []):
        level = alert["level"]
        if level in ("CRITICAL", "EMERGENCY"):
            log.critical(f"  ALERT [{level}]: {alert['msg']}")
        elif level == "WARNING":
            log.warning(f"  ALERT [{level}]: {alert['msg']}")
        else:
            log.info(f"  ALERT [{level}]: {alert['msg']}")

    # Refresh the regime label intraday so it does not lag a midday pullback (rec #5).
    refresh_intraday_regime(alpaca, portfolio_state, signals_data)

    _sync_portfolio_state(alpaca, portfolio_state)
    log.info(f"Monitor: equity=${equity:,.2f}, daily P&L={daily_pnl_pct:+.2f}%, {len(positions)} positions, {len(triggers)} triggers")


# ---------------------------------------------------------------------------
# MODE 4: END-OF-DAY JOURNAL
# ---------------------------------------------------------------------------

def reconcile_positions(alpaca: AlpacaClient):
    """Read-only integrity audit: detect drift between the trade log and the
    broker's actual positions. Writes data/reconciliation_report.json. Places
    NO orders — surfaces issues for the journal/heartbeat to act on.

    Two drift classes:
      * orphan_open_trades  — trade_log says 'open' but no live position
                              (an exit that wasn't logged).
      * unlogged_positions  — a live position with no matching open trade
                              (an entry fill that wasn't logged, e.g. a limit
                              that filled after the confirmation window).
    """
    from shared.reconcile import (compute_drift, reconcile_log_to_broker,
                                  is_open_trade, order_classes_from_orders)
    from shared.accounting import realized_pnl

    positions = alpaca.get_positions()
    pos_syms = [p.get("symbol") for p in positions if p.get("symbol")]
    trade_log = load_json(DATA_DIR / "trade_log.json", [])

    # Sleeve attribution for reconstructed lots, read off the broker's own
    # client_order_id prefixes — a late-filled momentum order must stay a
    # momentum lot, never become an "active" lot that gets -4%/4-day stops.
    try:
        recent = alpaca._get(f"{alpaca.base_url}/v2/orders",
                             {"status": "closed", "limit": 500, "direction": "desc"})
        order_classes = order_classes_from_orders(recent, P1_ORDER_CLASS_BY_PREFIX)
    except Exception as e:
        log.warning(f"  Reconciliation: order attribution unavailable ({e})")
        order_classes = {}

    # Repair the audit trail to broker ground truth BEFORE auditing it: close
    # orphan lots, trim double-logged qty, log unlogged positions. Places NO
    # orders; recovers real net-of-fee P&L only where a true exit price exists,
    # otherwise marks 'closed_reconciled' (pnl=None) — never fabricates a result.
    repaired, recon_actions = reconcile_log_to_broker(
        trade_log, positions,
        pnl_fn=lambda side, qty, entry, ex: realized_pnl(side, qty, entry, ex)["net_pnl"],
        order_classes=order_classes,
    )
    if recon_actions:
        save_json(DATA_DIR / "trade_log.json", repaired)
        log.info(f"  Reconciliation backfill: {len(recon_actions)} corrective action(s): "
                 f"{[a['action'] + ':' + a['symbol'] for a in recon_actions]}")
        trade_log = repaired

    open_trades = [t for t in trade_log if is_open_trade(t) and t.get("symbol")]
    open_syms = [t.get("symbol") for t in open_trades]

    # Pass detailed records so qty + cost-basis drift (C6) is caught, not just
    # symbol presence — a partial fill or missed corporate action shows up here.
    report = compute_drift(pos_syms, open_syms, positions=positions,
                           open_trades=open_trades)
    report["reconcile_actions"] = recon_actions
    save_json(DATA_DIR / "reconciliation_report.json", report)
    if report["in_sync"]:
        log.info("  Reconciliation: trade log and broker positions in sync")
    else:
        if report["orphan_open_trades"]:
            log.warning(f"  Reconciliation: {len(report['orphan_open_trades'])} open trade(s) "
                        f"with no live position: {report['orphan_open_trades']}")
        if report["unlogged_positions"]:
            log.warning(f"  Reconciliation: {len(report['unlogged_positions'])} live position(s) "
                        f"not in trade log: {report['unlogged_positions']}")
        if report.get("qty_drift"):
            log.warning(f"  Reconciliation: quantity drift on "
                        f"{[d['symbol'] for d in report['qty_drift']]}")
        if report.get("cost_basis_drift"):
            log.warning(f"  Reconciliation: cost-basis drift on "
                        f"{[d['symbol'] for d in report['cost_basis_drift']]}")
    return report


def run_end_of_day(alpaca: AlpacaClient, force=None):
    log.info("=" * 60)
    log.info("END-OF-DAY JOURNAL — Performance, self-learning, adapt params")
    log.info("=" * 60)

    # Idempotency per ET trading session (M2): the staggered cron lines fire the
    # EOD up to 6x; only the first completed run of a session does the work.
    # Re-running would re-adapt params, re-roll day_start_equity, and append
    # duplicate journal entries. P1_EOD_FORCE=1 (manual dispatch) overrides.
    session_date = et_session_date()
    portfolio_state = load_json(DATA_DIR / "portfolio_state.json")
    if force is None:
        force = os.environ.get("P1_EOD_FORCE", "").strip() == "1"
    if portfolio_state.get("last_eod_session_date") == session_date and not force:
        log.info(f"EOD already completed for session {session_date} "
                 f"(at {portfolio_state.get('last_eod_completed_at')}) — skipping (idempotent).")
        return False
    roll_session_anchors(portfolio_state, session_date)

    account = alpaca.get_account()
    equity = float(account["equity"])
    positions = alpaca.get_positions()

    # Book late fills of exits that were still working at confirmation time, at
    # the REAL broker fill (H3), before any reconciliation reads the log.
    try:
        settle_pending_exits(alpaca)
    except Exception as e:
        log.warning(f"  Pending-exit settlement skipped: {e}")
    try:
        settle_pending_entries(alpaca, positions)
    except Exception as e:
        log.warning(f"  Pending-entry settlement skipped: {e}")

    # Close open trades that were filled
    trade_log = load_json(DATA_DIR / "trade_log.json", [])
    position_symbols = {p["symbol"] for p in positions}
    from performance_tracker import close_trade

    # Idempotent by order id (audit item 7): a symbol whose exit is still in
    # pending settlement is owned by that path (e.g. its poll failed this run),
    # and a sell order whose fill the ledger already booked is never re-used.
    _pending_syms = pending_exit_symbols()
    for trade in trade_log:
        if trade["status"] == "open" and trade["symbol"] not in position_symbols:
            if trade["symbol"] in _pending_syms:
                log.info(f"  Reconcile: {trade['symbol']} exit pending settlement — skipped")
                continue
            pos_data = alpaca.get_position(trade["symbol"])
            if pos_data is None:
                orders = alpaca.get_orders("closed")
                sell_orders = [o for o in orders if o["symbol"] == trade["symbol"] and o["side"] == "sell" and o["filled_qty"] != "0"]
                if sell_orders:
                    so = sell_orders[0]
                    if _ledger_booked(so.get("id"))[0] >= float(so.get("filled_qty") or 0):
                        log.info(f"  Reconcile: sell {so.get('id')} for {trade['symbol']} "
                                 f"already booked — left to reconcile_positions")
                        continue
                    exit_price = float(so.get("filled_avg_price", trade["entry_price"]))
                    close_trade(trade["id"], exit_price, reason="reconcile")
                    log.info(f"  Closed trade #{trade['id']} {trade['symbol']} @ ${exit_price:.2f}")

    # Read-only integrity audit: flag any drift between trade log and broker.
    reconcile_positions(alpaca)

    # Cross-portfolio aggregate exposure (committee rec #3) — advisory, read-only,
    # committed so the dashboard + heartbeat can surface the correlated stacking no
    # single book sees. P1's EOD owns this write (it commits root data/).
    try:
        from shared.cross_portfolio import cross_portfolio_report, load_books
        root = DATA_DIR.parent
        cfg = load_json(root / "config" / "risk_limits.json", {})
        xp = cfg.get("cross_portfolio", {})
        xp_report = cross_portfolio_report(
            load_books(str(root)),
            single_name_cap_pct=xp.get("single_name_cap_pct", 10.0),
            sector_cap_pct=xp.get("sector_cap_pct", 30.0),
            clusters=cfg.get("correlation_clusters"),
            max_cluster_pct=cfg.get("max_cluster_exposure_pct"),
        )
        save_json(DATA_DIR / "cross_portfolio_risk.json", xp_report)
        log.info(f"  Cross-portfolio: gross {xp_report['gross_exposure_pct']}% of total, "
                 f"clusters={xp_report.get('cluster_exposure_pct')}, ok={xp_report['ok']}")
    except Exception as e:
        log.warning(f"  Cross-portfolio report skipped: {e}")

    # Run self-learning
    from performance_tracker import adapt_parameters, generate_learning_report

    log.info("Running self-learning adaptation...")
    # Gate parameter changes on out-of-sample (walk-forward) validation using the
    # bars morning-research cached today — never tune on live noise.
    validate_with_bars = None
    try:
        from backtest.walk_forward import load_aligned_bars
        symbol_bars, spy_bars = load_aligned_bars(str(DATA_DIR))
        if symbol_bars and spy_bars:
            validate_with_bars = (symbol_bars, spy_bars)
            log.info(f"  Walk-forward gate active: {len(symbol_bars)} symbols, "
                     f"{len(spy_bars)} aligned bars")
        else:
            log.info("  Walk-forward gate inactive (insufficient cached bars)")
    except Exception as e:
        log.warning(f"  Walk-forward gate unavailable: {e}")

    adaptation = adapt_parameters(validate_with_bars=validate_with_bars)
    gate = adaptation.get("walk_forward_gate")
    if gate:
        log.info(f"  Walk-forward gate result: {gate}")
    wr_7d = adaptation['metrics_7d'].get('win_rate')
    wr_30d = adaptation['metrics_30d'].get('win_rate')
    log.info(f"  7d win rate: {wr_7d:.1%}" if wr_7d is not None else "  7d win rate: N/A (no trades)")
    log.info(f"  30d win rate: {wr_30d:.1%}" if wr_30d is not None else "  30d win rate: N/A (no trades)")
    log.info(f"  Position size mult: {adaptation['updated_params'].get('position_size_multiplier', 1.0):.2f}")

    report = generate_learning_report()
    for insight in report.get("insights", []):
        log.info(f"  INSIGHT: {insight}")

    # Write journal — dated by the ET SESSION date, not the runner's clock (M2).
    today = session_date
    day_start = portfolio_state.get("day_start_equity", float(account["last_equity"]))
    journal_entry = {
        "date": today,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "end-of-day",
        "account": {
            "equity": equity,
            "cash": float(account["cash"]),
            "portfolio_value": float(account["portfolio_value"]),
            "daily_pnl": equity - day_start,
            "daily_pnl_pct": round((equity - day_start) / day_start * 100, 3) if day_start > 0 else 0,
        },
        "positions": [
            {
                "symbol": p["symbol"],
                "qty": p["qty"],
                "market_value": p["market_value"],
                "unrealized_pl": p["unrealized_pl"],
                "unrealized_plpc": p["unrealized_plpc"],
            }
            for p in positions
        ],
        "learning": {
            "metrics_7d": adaptation["metrics_7d"],
            "metrics_30d": adaptation["metrics_30d"],
            "updated_params_snapshot": {
                "position_size_multiplier": adaptation["updated_params"].get("position_size_multiplier"),
                "confidence_buy_threshold": adaptation["updated_params"].get("confidence_buy_threshold"),
                "trailing_stop_atr_mult": adaptation["updated_params"].get("trailing_stop_atr_mult"),
            },
        },
        "insights": report.get("insights", []),
    }

    journal_path = JOURNAL_DIR / f"{today}.json"
    if journal_path.exists():
        existing = load_json(journal_path)
        if isinstance(existing, list):
            existing.append(journal_entry)
        else:
            existing = [existing, journal_entry]
        save_json(journal_path, existing)
    else:
        save_json(journal_path, [journal_entry])

    # Momentum sleeve live-readiness ledger (advisory, read-only). Scores the
    # sleeve's forward OOS paper track record vs the go-live gates so the go/no-go
    # is evidence-driven and visible on the dashboard. Fail-open — never blocks EOD.
    try:
        from momentum_readiness import build_and_save
        mr = build_and_save(data_dir=str(DATA_DIR), journal_dir=str(JOURNAL_DIR))
        log.info(f"  Momentum readiness: status={mr['status']} "
                 f"({mr.get('days_on_paper', 0)}d, gates_pass={mr.get('all_gates_pass')})")
    except Exception as e:
        log.warning(f"  Momentum readiness skipped: {e}")

    # Update portfolio state for next day. This close is tomorrow's day-start
    # and — if it is the last close of the ISO week — next week's week_start
    # (rolled by roll_session_anchors on the first run of the new week, M3).
    update_peak_equity(alpaca, portfolio_state, account, positions,
                       float(account.get("last_equity") or 0))
    portfolio_state["day_start_equity"] = equity
    portfolio_state["last_close_equity"] = equity
    portfolio_state["last_close_session_date"] = session_date
    portfolio_state["trades_today"] = 0
    portfolio_state["last_eod_session_date"] = session_date
    portfolio_state["last_eod_completed_at"] = datetime.now(timezone.utc).isoformat()
    _sync_portfolio_state(alpaca, portfolio_state)

    log.info(f"EOD complete: equity=${equity:,.2f}, {len(positions)} positions")
    return True


# ---------------------------------------------------------------------------
# MODE 5: WEEKLY REVIEW
# ---------------------------------------------------------------------------

def run_weekly_review(alpaca: AlpacaClient):
    log.info("=" * 60)
    log.info("WEEKLY REVIEW — Deep analysis, rebalancing, strategy tuning")
    log.info("=" * 60)

    account = alpaca.get_account()
    equity = float(account["equity"])
    positions = alpaca.get_positions()

    from performance_tracker import compute_metrics, compute_metrics_by_bucket, compute_metrics_by_symbol
    from portfolio_manager import compute_rebalance_orders

    metrics_all = compute_metrics()
    metrics_7d = compute_metrics(7)
    metrics_30d = compute_metrics(30)
    by_bucket = compute_metrics_by_bucket()
    by_symbol = compute_metrics_by_symbol()

    log.info(f"Overall: {metrics_all['total_trades']} trades, "
             f"{metrics_all['win_rate']:.1%} win rate, PF={metrics_all['profit_factor']:.2f}" 
             if metrics_all['win_rate'] is not None else 
             f"Overall: {metrics_all['total_trades']} trades, N/A win rate (no closed trades)")
    if metrics_30d['total_trades'] > 0:
        log.info(f"30d: {metrics_30d['total_trades']} trades, "
                 f"{metrics_30d['win_rate']:.1%} win rate" if metrics_30d['win_rate'] is not None else
                 f"30d: {metrics_30d['total_trades']} trades")

    for bucket, data in by_bucket.items():
        log.info(f"  {bucket}: {data['trades']} trades, {data['win_rate']:.1%} WR, ${data['total_pnl']:+,.2f}")

    # Rebalancing analysis
    signals_data = load_json(DATA_DIR / "signals.json", {})
    regime = signals_data.get("market_regime", "UNKNOWN")
    rebalance = compute_rebalance_orders(positions, equity, regime)

    for action in rebalance.get("rebalance_actions", []):
        log.info(f"  REBALANCE: {action['bucket']} {action['action']} "
                 f"{action['current_pct']:.1f}% -> {action['target_pct']:.1f}% (drift {action['drift_pct']:+.1f}%)")

    # Write weekly review
    week_num = datetime.now().strftime("%Y-W%W")
    review = {
        "week": week_num,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account": {
            "equity": equity,
            "cash": float(account["cash"]),
            "portfolio_value": float(account["portfolio_value"]),
        },
        "performance": {
            "overall": metrics_all,
            "last_7d": metrics_7d,
            "last_30d": metrics_30d,
            "by_bucket": by_bucket,
            "by_symbol": by_symbol,
        },
        "market_regime": regime,
        "rebalancing": rebalance,
        "positions": [
            {
                "symbol": p["symbol"],
                "qty": p["qty"],
                "market_value": p["market_value"],
                "unrealized_pl": p["unrealized_pl"],
                "unrealized_plpc": p["unrealized_plpc"],
                "bucket": get_bucket_for_symbol(p["symbol"]),
            }
            for p in positions
        ],
    }

    save_json(JOURNAL_DIR / f"weekly-{week_num}.json", review)
    log.info(f"Weekly review saved: weekly-{week_num}.json")


# ---------------------------------------------------------------------------
# SHARED HELPERS
# ---------------------------------------------------------------------------

def _sync_portfolio_state(alpaca: AlpacaClient, portfolio_state: dict):
    account = alpaca.get_account()
    positions = alpaca.get_positions()

    equity = float(account["equity"])
    cash = float(account["cash"])
    long_mv = sum(float(p.get("market_value", 0)) for p in positions if p.get("side") == "long")
    short_mv = sum(abs(float(p.get("market_value", 0))) for p in positions if p.get("side") == "short")

    portfolio_state["equity"] = equity
    portfolio_state["cash"] = cash
    portfolio_state["long_market_value"] = long_mv
    portfolio_state["short_exposure"] = short_mv
    portfolio_state["total_exposure"] = long_mv + short_mv
    portfolio_state["last_updated"] = datetime.now(timezone.utc).isoformat()

    pos_dict = {}
    for p in positions:
        sym = p["symbol"]
        pos_dict[sym] = {
            "qty": int(float(p["qty"])),
            "avg_price": float(p["avg_entry_price"]),
            "bucket": get_bucket_for_symbol(sym),
        }
    portfolio_state["positions"] = pos_dict

    day_start = portfolio_state.get("day_start_equity", float(account["last_equity"]))
    portfolio_state["day_pnl"] = round(equity - day_start, 2)
    portfolio_state["day_pnl_pct"] = round((equity - day_start) / day_start, 6) if day_start > 0 else 0

    week_start = portfolio_state.get("week_start_equity", day_start)
    portfolio_state["week_pnl"] = round(equity - week_start, 2)
    portfolio_state["week_pnl_pct"] = round((equity - week_start) / week_start, 6) if week_start > 0 else 0

    # Halt verification flag (C1d) travels with every state write so the
    # heartbeat/dashboard can show an UNVERIFIED HALT.
    annotate_halt_verification(portfolio_state)
    save_json(DATA_DIR / "portfolio_state.json", portfolio_state)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Portfolio 1 Autonomous Runner")
    parser.add_argument("mode", choices=[
        "morning-research", "trading-session", "intraday-monitor",
        "end-of-day-journal", "weekly-review",
    ])
    args = parser.parse_args()

    alpaca = AlpacaClient()

    # Quick health check
    try:
        acct = alpaca.get_account()
        log.info(f"Account {acct['account_number']}: equity=${float(acct['equity']):,.2f}, status={acct['status']}")
    except Exception as e:
        log.critical(f"Cannot connect to Alpaca: {e}")
        sys.exit(1)

    if args.mode == "morning-research":
        run_morning_research(alpaca)
    elif args.mode == "trading-session":
        run_trading_session(alpaca)
    elif args.mode == "intraday-monitor":
        run_intraday_monitor(alpaca)
    elif args.mode == "end-of-day-journal":
        run_end_of_day(alpaca)
    elif args.mode == "weekly-review":
        run_weekly_review(alpaca)


if __name__ == "__main__":
    # Belt-and-suspenders reproducibility: pin PYTHONHASHSEED for the EOD
    # self-learning run so its walk-forward gate_param_change decision is
    # bit-for-bit reproducible across invocations. Scoped to the EOD mode (peeked
    # from argv before re-exec) so the intraday money path's process is untouched.
    # Runs in __main__ only, so importing this module under pytest never re-execs.
    if (sys.argv[1:2] or [None])[0] == "end-of-day-journal":
        from shared.determinism import ensure_hash_seed_pinned

        ensure_hash_seed_pinned()
    main()
