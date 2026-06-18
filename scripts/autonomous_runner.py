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

    def get_orders(self, status="open"):
        return self._get(f"{self.base_url}/v2/orders", {"status": status})

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
    limits = load_json(CONFIG_DIR / "risk_limits.json")

    # Kill switch check
    starting_equity = portfolio_state.get("starting_equity", 100000)
    drawdown_pct = (starting_equity - equity) / starting_equity * 100
    if drawdown_pct >= limits["kill_switch_drawdown_pct"]:
        log.critical(f"KILL SWITCH: Drawdown {drawdown_pct:.2f}% — HALTING ALL TRADING")
        portfolio_state["halted"] = True
        portfolio_state["halt_reason"] = f"Kill switch: {drawdown_pct:.2f}% drawdown"
        save_json(DATA_DIR / "portfolio_state.json", portfolio_state)
        return

    # Daily loss check — use day_start_equity from state for consistency with risk_officer
    day_start = portfolio_state.get("day_start_equity", last_equity)
    daily_pnl_pct = (equity - day_start) / day_start * 100 if day_start > 0 else 0
    if daily_pnl_pct <= -limits["max_daily_loss_pct"]:
        log.warning(f"Daily loss limit: {daily_pnl_pct:.2f}% — no new trades today")
        return

    if portfolio_state.get("halted"):
        log.warning(f"System halted: {portfolio_state.get('halt_reason')}")
        return

    # Preflight self-check — fail CLOSED before any order if the sizing math,
    # self-learned params, account health, risk limits, or data freshness are off
    # (the 2026-06-01 class). The canary alone would have caught that incident.
    from analyst_v2 import load_adaptive_params
    from shared.preflight import run_preflight
    _sig_file = DATA_DIR / "signals.json"
    _signals = load_json(_sig_file) if _sig_file.exists() else {}
    _data_fresh = _signals.get("timestamp", "").startswith(
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
        return

    # Run risk officer validation
    from risk_officer import run_validation
    # Update portfolio state for risk officer
    positions = alpaca.get_positions()
    portfolio_state["equity"] = equity
    portfolio_state["day_start_equity"] = portfolio_state.get("day_start_equity", last_equity)
    portfolio_state["week_start_equity"] = portfolio_state.get("week_start_equity", last_equity)
    portfolio_state["trades_today"] = len([
        t for t in load_json(DATA_DIR / "trade_log.json", [])
        if t.get("timestamp", "").startswith(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ])
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
    max_trades = limits["max_trades_per_day"] - portfolio_state["trades_today"]
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
        for _co in compute_core_orders(positions, equity, cash, _params, _regime, _prices, limits):
            if trades_executed >= max_trades:
                break
            try:
                _ask = _prices.get(_co["symbol"], 0)
                _lp = round(_ask * 1.001, 2) if _ask else None
                _r = alpaca.place_order(
                    symbol=_co["symbol"], qty=_co["qty"], side="buy",
                    order_type="limit" if _lp else "market", limit_price=_lp,
                    client_order_id=make_client_order_id("p1core", _co["symbol"], "buy"))
                trades_executed += 1
                log.info(f"  CORE: buy {_co['qty']} x {_co['symbol']} — {_co['reason']}")
                _st, _fq, _fp = confirm_fill(alpaca, _r.get("id"))
                if _fq > 0:
                    _px = _fp or _lp or _ask
                    cash -= _fq * _px
                    from performance_tracker import log_trade
                    log_trade(_co["symbol"], "buy", _fq, round(_px, 4), "core_equity",
                              None, [_co["reason"]], intended_price=_lp, order_class="passive_core")
            except Exception as _e:
                log.error(f"  Core buy failed for {_co['symbol']}: {_e}")
        positions = alpaca.get_positions()  # refresh after core buys
        # FIX: re-sync exposure so the risk officer validates the active sleeve
        # AGAINST the core just deployed (was reading pre-core total_exposure ->
        # the combined book could breach the 160% gross cap).
        portfolio_state["total_exposure"] = sum(abs(float(p.get("market_value", 0))) for p in positions)
        save_json(DATA_DIR / "portfolio_state.json", portfolio_state)

    validated = run_validation(asset_lookup=_build_asset_lookup(alpaca))
    approved = validated.get("approved_orders", [])
    log.info(f"Validated: {validated['summary']['approved']} approved, {validated['summary']['rejected']} rejected")

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
                quote = alpaca.get_latest_quote(rsym)
                bid = float(quote.get("quote", {}).get("bp", 0))
                limit_price = round(bid * 0.999, 2) if bid > 0 else None
                rcoid = make_client_order_id("p1", rsym, "sell")
                result = alpaca.place_order(
                    symbol=rsym, qty=rqty, side="sell",
                    order_type="limit" if limit_price else "market",
                    limit_price=limit_price, client_order_id=rcoid,
                )
                log.info(f"  ROTATE: selling {rqty} x {rsym} — {rot['reason']}")
                status, filled_qty, filled_price = confirm_fill(alpaca, result.get("id"))
                exit_px = filled_price or limit_price or 0
                if filled_qty > 0:
                    from performance_tracker import find_open_trade, close_trade
                    tr = find_open_trade(rsym)
                    if tr and exit_px > 0:
                        close_trade(tr["id"], exit_px)
                    cash += filled_qty * exit_px
                    rotated.append(rsym)
                trades_executed += 1  # counts against the daily trade budget
                time.sleep(0.5)
            except requests.HTTPError as e:
                resp = getattr(e, "response", None)
                if resp is not None and resp.status_code == 422 and "client_order_id" in resp.text:
                    log.info(f"  {rsym}: rotation already placed today (idempotent skip)")
                    continue
                log.error(f"  Rotation sell failed for {rsym}: {e}")
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
        resp = alpaca.get_stock_bars("SPY", timeframe="1Day", limit=220)
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
    limits = load_json(CONFIG_DIR / "risk_limits.json")

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

    # Kill switch
    starting_equity = portfolio_state.get("starting_equity", 100000)
    drawdown_pct = (starting_equity - equity) / starting_equity * 100
    if drawdown_pct >= limits["kill_switch_drawdown_pct"]:
        log.critical(f"KILL SWITCH TRIGGERED: {drawdown_pct:.2f}% drawdown — LIQUIDATING ALL")
        try:
            alpaca.close_all_positions()
            alpaca.cancel_all_orders()
        except Exception as e:
            log.error(f"Liquidation error: {e}")
        portfolio_state["halted"] = True
        portfolio_state["halt_reason"] = f"Kill switch at {drawdown_pct:.2f}%"
        save_json(DATA_DIR / "portfolio_state.json", portfolio_state)
        return

    # Daily loss — use day_start_equity from state for consistency
    day_start = portfolio_state.get("day_start_equity", last_equity)
    daily_pnl_pct = (equity - day_start) / day_start * 100 if day_start > 0 else 0
    if daily_pnl_pct <= -limits["max_daily_loss_pct"]:
        log.warning(f"Daily loss limit breached: {daily_pnl_pct:.2f}% — halting for 24h")
        portfolio_state["halted"] = True
        portfolio_state["halt_reason"] = f"Daily loss: {daily_pnl_pct:.2f}%"
        portfolio_state["halt_until"] = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        save_json(DATA_DIR / "portfolio_state.json", portfolio_state)
        return

    # Check halt expiry
    if portfolio_state.get("halted") and portfolio_state.get("halt_until"):
        halt_until = datetime.fromisoformat(portfolio_state["halt_until"])
        if datetime.now(timezone.utc) > halt_until:
            log.info("Halt period expired — resuming trading")
            portfolio_state["halted"] = False
            portfolio_state["halt_reason"] = None
            portfolio_state["halt_until"] = None

    # Stop-loss and take-profit checks. Pass the OPEN trade log so a held position
    # absent from today's signals still gets its persisted entry stop enforced
    # (otherwise it would be left unprotected — the -10.8% no-stop failure mode).
    signals_data = load_json(DATA_DIR / "signals.json", {})
    trade_log = load_json(DATA_DIR / "trade_log.json", [])
    open_trades = [t for t in trade_log if isinstance(t, dict) and t.get("status") == "open"]
    strategy_params = load_json(DATA_DIR / "strategy_params.json", {})
    from portfolio_manager import check_stop_triggers
    triggers = check_stop_triggers(positions, signals_data, open_trades, strategy_params)

    for trigger in triggers:
        sym = trigger["symbol"]
        action = trigger["action"]
        log.warning(f"  TRIGGER: {action} for {sym} (P&L: {trigger['pnl_pct']:.1f}%)")

        try:
            pos = alpaca.get_position(sym)
            if not pos:
                continue
            qty = int(float(pos["qty"]))

            if action == "STOP_LOSS_SELL":
                order_result = alpaca.place_order(symbol=sym, qty=qty, side="sell",
                                   order_type="market", time_in_force="day")
                log.warning(f"  STOP LOSS executed: sold {qty} x {sym}")
                from performance_tracker import find_open_trade, close_trade
                trade = find_open_trade(sym)
                if trade:
                    fill_price = float(order_result.get("filled_avg_price", 0) or trigger["current_price"])
                    if fill_price <= 0:
                        fill_price = trigger["current_price"]
                    close_trade(trade["id"], fill_price)

            elif action == "TAKE_PROFIT_SELL":
                sell_qty = max(1, qty // 2)
                quote = alpaca.get_latest_quote(sym)
                bid = float(quote.get("quote", {}).get("bp", 0))
                limit_price = round(bid * 0.999, 2) if bid > 0 else None
                order_result = alpaca.place_order(
                    symbol=sym, qty=sell_qty, side="sell",
                    order_type="limit" if limit_price else "market",
                    limit_price=limit_price,
                )
                log.info(f"  TAKE PROFIT: sold {sell_qty} of {qty} x {sym}")
                from performance_tracker import find_open_trade, close_trade
                trade = find_open_trade(sym)
                if trade:
                    fill_price = float(order_result.get("filled_avg_price", 0) or trigger["current_price"])
                    if fill_price <= 0:
                        fill_price = trigger["current_price"]
                    close_trade(trade["id"], fill_price)

        except Exception as e:
            log.error(f"  Stop/TP order failed for {sym}: {e}")

    # Cap-maintenance trims (H1): entry-time caps don't catch a position that
    # DRIFTS past its asset-class cap as it appreciates (IWM/XLI breached 12%).
    # Trim the breach back to the cap — risk-REDUCING, limit SELLs only.
    try:
        from performance_tracker import reduce_open_position
        from portfolio_manager import compute_cap_trims
        cfg_limits = load_json(CONFIG_DIR / "risk_limits.json", {})
        bucket_map = portfolio_state.get("positions", {})
        for trim in compute_cap_trims(positions, equity, cfg_limits, bucket_map):
            sym, tq = trim["symbol"], trim["trim_qty"]
            quote = alpaca.get_latest_quote(sym)
            bid = float(quote.get("quote", {}).get("bp", 0))
            limit_price = round(bid * 0.999, 2) if bid > 0 else None
            order_result = alpaca.place_order(
                symbol=sym, qty=tq, side="sell",
                order_type="limit" if limit_price else "market",
                limit_price=limit_price,
                client_order_id=make_client_order_id("p1cap", sym, "sell"))
            fill_price = float(order_result.get("filled_avg_price", 0) or limit_price or 0)
            if fill_price > 0:
                reduce_open_position(sym, tq, fill_price, reason=trim["reason"])
            log.warning(f"  CAP TRIM: sold {tq} {sym} "
                        f"({trim['weight_pct']}% > {trim['cap_pct']}% cap)")
    except Exception as e:
        log.warning(f"  Cap-maintenance trim skipped: {e}")

    # Portfolio health
    from portfolio_manager import portfolio_health_check
    health = portfolio_health_check(account, positions)
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
                                  is_open_trade)
    from shared.accounting import realized_pnl

    positions = alpaca.get_positions()
    pos_syms = [p.get("symbol") for p in positions if p.get("symbol")]
    trade_log = load_json(DATA_DIR / "trade_log.json", [])

    # Repair the audit trail to broker ground truth BEFORE auditing it: close
    # orphan lots, trim double-logged qty, log unlogged positions. Places NO
    # orders; recovers real net-of-fee P&L only where a true exit price exists,
    # otherwise marks 'closed_reconciled' (pnl=None) — never fabricates a result.
    repaired, recon_actions = reconcile_log_to_broker(
        trade_log, positions,
        pnl_fn=lambda side, qty, entry, ex: realized_pnl(side, qty, entry, ex)["net_pnl"],
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


def run_end_of_day(alpaca: AlpacaClient):
    log.info("=" * 60)
    log.info("END-OF-DAY JOURNAL — Performance, self-learning, adapt params")
    log.info("=" * 60)

    account = alpaca.get_account()
    equity = float(account["equity"])
    positions = alpaca.get_positions()

    # Close open trades that were filled
    trade_log = load_json(DATA_DIR / "trade_log.json", [])
    position_symbols = {p["symbol"] for p in positions}
    from performance_tracker import close_trade

    for trade in trade_log:
        if trade["status"] == "open" and trade["symbol"] not in position_symbols:
            pos_data = alpaca.get_position(trade["symbol"])
            if pos_data is None:
                orders = alpaca.get_orders("closed")
                sell_orders = [o for o in orders if o["symbol"] == trade["symbol"] and o["side"] == "sell" and o["filled_qty"] != "0"]
                if sell_orders:
                    exit_price = float(sell_orders[0].get("filled_avg_price", trade["entry_price"]))
                    close_trade(trade["id"], exit_price)
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

    # Write journal
    today = datetime.now().strftime("%Y-%m-%d")
    portfolio_state = load_json(DATA_DIR / "portfolio_state.json")
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

    # Update portfolio state for next day
    portfolio_state["day_start_equity"] = equity
    portfolio_state["trades_today"] = 0
    if datetime.now().weekday() == 0:
        portfolio_state["week_start_equity"] = equity
    _sync_portfolio_state(alpaca, portfolio_state)

    log.info(f"EOD complete: equity=${equity:,.2f}, {len(positions)} positions")


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
