#!/usr/bin/env python3
"""
Multi-Factor Event-Driven Trading Bot — Portfolio 3
Institutional-grade: Fundamental screening + Technical breakout + News sentiment.
ATR-based position sizing and risk management. 60/20/20 capital tranches.

Modes:
  weekly-screen    Fundamental universe screening (run weekly)
  morning-scan     Technical scan + signal generation
  trading-session  Execute breakout trades
  intraday-monitor Check stops, P&L, kill switch
  news-scan        Scan news for catalyst trades
  eod-journal      End-of-day logging and audit
  weekly-review    Deep weekly performance review
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
from alpaca_client import AlpacaClient, confirm_fill, make_client_order_id
from fundamental_screener import (
    screen_universe, save_watchlist, SECTOR_MAP,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / f"p3_{datetime.now().strftime('%Y-%m-%d')}.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("p3_event_driven")


def load_json(path, default=None):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# CATALYST-DECAY TIME STOP (T10) — pure + unit-testable.
#
# A news/event trade's edge is the catalyst surprise; once the market has
# digested it the position is just unmanaged risk. P3 therefore force-exits a
# catalyst trade after its short hold window, regardless of P&L. Core fundamental
# trades are NOT catalyst-decayed (they have a thesis with a longer horizon).
# ---------------------------------------------------------------------------

def is_catalyst_trade(trade):
    """A trade entered on a news/event catalyst (the event_driven tranche or a
    news-sourced signal), as opposed to a core fundamental/breakout position."""
    if not isinstance(trade, dict):
        return False
    if trade.get("tranche") == "event_driven":
        return True
    sig = str(trade.get("signal_type") or trade.get("signal") or "").upper()
    return "NEWS" in sig or "CATALYST" in sig


def sector_cap_breached(current_sector_value, trade_value, equity, max_sector_pct):
    """True if adding `trade_value` to a sector's CURRENT exposure would push the
    sector past its cap. Checks PROPOSED exposure (current + new order), not just
    current — a single tranche-sized entry must not be allowed to vault a sector
    far past the cap (P3 reached ~33% on a 20% cap because only `current` was
    checked). Mirrors risk_officer's proposed-exposure pattern (P1). Fails closed
    on non-positive equity. Pure + unit-tested."""
    if equity <= 0:
        return True
    proposed_pct = (current_sector_value + trade_value) / equity * 100
    return proposed_pct > max_sector_pct


def trade_age_days(trade, now=None):
    """Calendar days since entry, from the trade's timestamp (or date)."""
    now = now or datetime.now(timezone.utc)
    ts = trade.get("timestamp") or trade.get("date")
    if not ts:
        return None
    try:
        entered = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        try:
            entered = datetime.fromisoformat(str(ts)[:10]).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if entered.tzinfo is None:
        entered = entered.replace(tzinfo=timezone.utc)
    return (now - entered).days


def catalyst_decayed(trade, now=None, max_hold_days=1):
    """True when a catalyst trade has been held at least `max_hold_days` — its
    edge has decayed and it should be exited. Non-catalyst trades never decay
    here. Unknown age does NOT force an exit (avoid closing on bad data)."""
    if not is_catalyst_trade(trade):
        return False
    age = trade_age_days(trade, now=now)
    if age is None:
        return False
    return age >= max_hold_days


# ---------------------------------------------------------------------------
# POSITION SIZING (ATR-Based)
# ---------------------------------------------------------------------------

def compute_position_size(equity, price, atr_val, limits):
    max_risk = equity * limits["max_risk_per_trade_pct"] / 100
    stop_distance = atr_val * limits["atr_stop_multiplier"]
    if stop_distance <= 0:
        return 0, 0, 0
    shares = int(max_risk / stop_distance)
    stop_price = round(price - stop_distance, 2)
    tp1_price = round(price + atr_val * limits["atr_tp1_multiplier"], 2)
    return shares, stop_price, tp1_price


# ---------------------------------------------------------------------------
# TECHNICAL SIGNAL GENERATION
# ---------------------------------------------------------------------------

def diversify_by_sector(items: list, max_per_sector: int) -> list:
    """Cap the number of items per sector, preserving input order (which must be
    conviction-sorted, strongest first). Stops one hot sector from monopolising the
    candidate/signal queue and then being entirely rejected downstream by the 20%
    sector-exposure cap.

    Observed 2026-06-02: 8 of 13 P3 signals were Energy and 79% of the qualified
    watchlist was Energy+Tech; both sectors were already at cap, so the executor
    placed 0 of 13. Keeping the strongest N names per sector leaves the queue room
    for sectors that still have headroom. `max_per_sector` <= 0 disables (no-op)."""
    if not max_per_sector or max_per_sector <= 0:
        return list(items)
    seen, out = {}, []
    for it in items:
        sec = it.get("sector", "Unknown")
        if seen.get(sec, 0) >= max_per_sector:
            continue
        seen[sec] = seen.get(sec, 0) + 1
        out.append(it)
    return out


def pick_sector_rotation_exit(candidate_rs, held_in_sector, *, edge=10.0):
    """Pick the weakest current holding in a (capped) sector to exit so a stronger
    incoming candidate can take its place — a within-sector SWAP instead of a hard
    skip when the sector is at its 20% exposure cap.

    Returns the weakest holding dict ({symbol, qty, rs}) IFF the candidate beats it
    by at least `edge` relative-strength points; else None. `held_in_sector` lists
    the current holdings in that sector with their RS (a name that fell out of the
    screen carries a very low RS, so it is the natural one to rotate out of). Pure
    function — the edge gate prevents churning between similar-strength names."""
    if not held_in_sector:
        return None
    try:
        cand = float(candidate_rs)
    except (TypeError, ValueError):
        return None
    weakest = min(held_in_sector, key=lambda h: h.get("rs", float("-inf")))
    try:
        if cand - float(weakest.get("rs", 0)) >= float(edge):
            return weakest
    except (TypeError, ValueError):
        return None
    return None


def _finalize_rotation_exit(symbol, exit_price, *, reason=""):
    """Mark the open trade-log entry for `symbol` closed after a sector-rotation
    exit — records exit price + realized P&L so reconciliation stays in sync (the
    position is gone at the broker, so the log must reflect that, not orphan)."""
    trade_log = load_json(DATA_DIR / "trade_log.json", [])
    changed = False
    for t in trade_log:
        if t.get("symbol") == symbol and t.get("status") == "open":
            t["status"] = "closed"
            t["exit_reason"] = reason
            t["sector_rotation_exit"] = True
            try:
                exit_price = float(exit_price)
            except (TypeError, ValueError):
                exit_price = 0.0
            if exit_price > 0:
                t["exit_price"] = round(exit_price, 4)
                entry = float(t.get("entry_price", 0) or 0)
                qty = float(t.get("qty", 0) or 0)
                if entry > 0 and qty:
                    t["pnl"] = round((exit_price - entry) * qty, 2)
            changed = True
    if changed:
        save_json(DATA_DIR / "trade_log.json", trade_log)


def generate_signals(watchlist_data: dict, alpaca: AlpacaClient) -> list:
    """Generate technical breakout signals from the fundamental watchlist."""
    universe = watchlist_data.get("universe", [])
    limits = load_json(CONFIG_DIR / "risk_limits.json")
    signals = []

    for stock in universe:
        sym = stock["symbol"]
        price = stock["price"]
        bb_upper = stock.get("bb_upper")
        bb_width = stock.get("bb_width_pct")
        macd_line = stock.get("macd_line")
        macd_sig = stock.get("macd_signal")
        macd_hist = stock.get("macd_histogram")
        rsi_val = stock.get("rsi14")
        atr_val = stock.get("atr14")
        rvol = stock.get("rvol_5d", 1.0)
        above_200 = stock.get("above_ema200", False)
        above_50 = stock.get("above_ema50", False)
        rs = stock.get("rs_vs_spy_3m", 0)

        if not above_200 and limits.get("regime_filter_enabled"):
            continue

        score = 0.0
        reasons = []

        # Bollinger breakout
        if bb_upper and price >= bb_upper * 0.995:
            score += 0.30
            reasons.append(f"Breaking upper BB (${bb_upper:.2f})")

        # Bollinger squeeze (tight bands = pending explosion)
        if bb_width and bb_width < 5.0:
            score += 0.10
            reasons.append(f"BB squeeze ({bb_width:.1f}% width)")

        # MACD bullish crossover
        if macd_hist and macd_hist > 0 and macd_line and macd_sig:
            if macd_line > macd_sig:
                score += 0.20
                reasons.append("MACD bullish crossover")
                if macd_line < 0:
                    score += 0.10
                    reasons.append("MACD crossover below zero (structural reversal)")

        # Volume confirmation
        if rvol >= limits.get("breakout_rvol_threshold", 1.5):
            score += 0.15
            reasons.append(f"High RVOL ({rvol:.1f}x)")

        # Relative strength bonus
        if rs > 10:
            score += 0.15
            reasons.append(f"Strong RS vs SPY (+{rs:.1f}%)")
        elif rs > 5:
            score += 0.08

        # Trend alignment
        if above_200 and above_50:
            score += 0.10
            reasons.append("Above EMA50 & EMA200")

        # RSI sweet spot (not overbought)
        if rsi_val:
            if 40 <= rsi_val <= 65:
                score += 0.05
                reasons.append(f"RSI in sweet spot ({rsi_val:.0f})")
            elif rsi_val >= 80:
                score -= 0.15
                reasons.append(f"RSI overbought ({rsi_val:.0f})")

        if score < 0.40:
            continue

        signal = {
            "symbol": sym,
            "sector": stock.get("sector", "Unknown"),
            "signal": "BUY",
            "score": round(score, 3),
            "price": price,
            "atr": atr_val,
            "rs_vs_spy": rs,
            "rsi": rsi_val,
            "rvol": rvol,
            "reasons": reasons,
            "tranche": "core_swing",
        }
        signals.append(signal)

    signals.sort(key=lambda x: x["score"], reverse=True)

    # Spread the queue across sectors so a single hot sector (e.g. Energy on
    # 2026-06-02) can't fill it with names that the 20% exposure cap will reject
    # downstream, starving sectors that still have headroom.
    max_per_sector = limits.get("max_signals_per_sector", 0)
    if max_per_sector:
        before = len(signals)
        signals = diversify_by_sector(signals, max_per_sector)
        if len(signals) < before:
            log.info(f"Sector diversification: {before} -> {len(signals)} signals "
                     f"(cap {max_per_sector}/sector)")

    log.info(f"Generated {len(signals)} technical signals from {len(universe)} watchlist stocks")
    return signals


# ---------------------------------------------------------------------------
# NEWS CATALYST SCANNER
# ---------------------------------------------------------------------------

POSITIVE_KEYWORDS = [
    "beats estimates", "raises guidance", "fda approval", "phase 3",
    "acquires", "merger", "acquisition", "upgraded", "buy rating",
    "record revenue", "beats expectations", "strong earnings",
    "strategic partnership", "contract win", "positive data",
    "outperform", "price target raised", "above consensus",
]

NEGATIVE_KEYWORDS = [
    "resigns", "investigation", "sec probe", "fraud", "downgrade",
    "misses estimates", "cuts guidance", "recall", "lawsuit",
    "layoffs", "bankruptcy", "default", "sell rating",
]

NOISE_KEYWORDS = [
    "top 10 stocks", "stocks to watch", "best stocks", "could soar",
    "you should buy", "hidden gem", "hot stock", "penny stock",
    "opinion", "editorial", "analysis says",
]


def scan_news(alpaca: AlpacaClient, watchlist_symbols: list) -> list:
    """Scan Alpaca news for catalyst events on watchlist stocks."""
    log.info("Scanning news for catalysts...")
    news_signals = []

    try:
        all_news = alpaca.get_news(limit=50)
        news_items = all_news.get("news", [])
    except Exception as e:
        log.error(f"News fetch failed: {e}")
        return []

    watchlist_set = set(watchlist_symbols)

    for item in news_items:
        headline = (item.get("headline", "") or "").lower()
        symbols = item.get("symbols", [])

        if any(noise in headline for noise in NOISE_KEYWORDS):
            continue

        matched_symbols = [s for s in symbols if s in watchlist_set]
        if not matched_symbols:
            continue

        sentiment = 0
        reasons = []
        for kw in POSITIVE_KEYWORDS:
            if kw in headline:
                sentiment += 1
                reasons.append(f"Positive: '{kw}'")
        for kw in NEGATIVE_KEYWORDS:
            if kw in headline:
                sentiment -= 1
                reasons.append(f"Negative: '{kw}'")

        if sentiment <= 0:
            continue

        for sym in matched_symbols:
            news_signals.append({
                "symbol": sym,
                "sector": SECTOR_MAP.get(sym, "Unknown"),
                "signal": "NEWS_BUY",
                "score": round(min(sentiment * 0.3, 1.0), 2),
                "headline": item.get("headline", ""),
                "source": item.get("source", ""),
                "created_at": item.get("created_at", ""),
                "reasons": reasons,
                "tranche": "event_driven",
            })

    log.info(f"Found {len(news_signals)} news catalyst signals")
    return news_signals


# ---------------------------------------------------------------------------
# ORDER EXECUTION
# ---------------------------------------------------------------------------

def execute_signals(alpaca: AlpacaClient, signals: list, tranche: str):
    """Execute approved signals with ATR-based position sizing and bracket orders."""
    limits = load_json(CONFIG_DIR / "risk_limits.json")
    account = alpaca.get_account()
    equity = float(account["equity"])
    cash = float(account["cash"])
    positions = alpaca.get_positions()

    # Preflight self-check — fail closed before sizing/placing any order.
    from shared.preflight import run_preflight
    pf_ok, pf = run_preflight(limits=limits, account=account, portfolio_id="portfolio_3")
    save_json(DATA_DIR / "preflight_report.json", pf)
    if not pf_ok:
        for _f in pf["hard_failures"]:
            log.error(f"::error::PREFLIGHT FAILED (P3): {_f}")
        return []

    tranche_pct = limits["capital_tranches"].get(tranche, 0.20)
    tranche_capital = equity * tranche_pct
    position_symbols = {p["symbol"] for p in positions}

    # Sector exposure tracking
    sector_exposure = {}
    for p in positions:
        sym = p["symbol"]
        sector = SECTOR_MAP.get(sym, "Unknown")
        sector_exposure[sector] = sector_exposure.get(sector, 0) + abs(float(p.get("market_value", 0)))

    trade_log = load_json(DATA_DIR / "trade_log.json", [])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    trades_today = len([t for t in trade_log if t.get("date", "").startswith(today)])

    executed = []
    placed_count = 0       # bracket orders submitted to the broker (or idempotent dup)
    filled_count = 0       # confirmed filled this run
    skips = []             # [{symbol, reason, benign}] for candidates we did not place

    # Within-sector rotation setup: RS for held names (a name that dropped out of
    # the screen carries a very low RS, so it's the first to be swapped out). The
    # swap is bounded per day so a noisy session can't churn the book.
    watchlist = load_json(DATA_DIR / "watchlist.json", {})
    rs_lookup = {w.get("symbol"): w.get("rs_vs_spy_3m", 0)
                 for w in (watchlist.get("universe", []) if isinstance(watchlist, dict) else [])}
    sector_rotation_enabled = limits.get("sector_rotation_enabled", True)
    max_sector_rotations = limits.get("max_sector_rotations_per_day", 2)
    sector_rotations = 0

    for signal in signals:
        if trades_today >= limits["max_trades_per_day"]:
            log.warning("Daily trade limit reached")
            break

        sym = signal["symbol"]
        price = signal.get("price", 0)
        atr_val = signal.get("atr")
        sector = signal.get("sector", "Unknown")

        if sym in position_symbols:
            log.info(f"  Already hold {sym}, skipping")
            skips.append({"symbol": sym, "reason": "already hold", "benign": True})
            continue

        # Sector limit check — if the sector is full, try a WITHIN-SECTOR swap
        # (exit the weakest holding in this sector when THIS candidate out-ranks it
        # by the RS edge) before giving up, so a strong new leader isn't hard-locked
        # out behind a sector laggard. Otherwise skip as before.
        sector_val = sector_exposure.get(sector, 0)
        if sector_val / equity * 100 >= limits["max_sector_exposure_pct"]:
            swapped = False
            if sector_rotation_enabled and sector_rotations < max_sector_rotations:
                held_in_sector = [
                    {"symbol": p["symbol"], "qty": int(float(p.get("qty", 0) or 0)),
                     "rs": rs_lookup.get(p["symbol"], -999.0)}
                    for p in positions
                    if SECTOR_MAP.get(p["symbol"], "Unknown") == sector
                ]
                exit_pick = pick_sector_rotation_exit(
                    signal.get("rs_vs_spy", 0), held_in_sector,
                    edge=limits.get("sector_rotation_rs_edge", 10.0))
                if exit_pick and exit_pick["qty"] > 0:
                    exit_sym = exit_pick["symbol"]
                    exit_pos = next((p for p in positions if p["symbol"] == exit_sym), None)
                    exit_val = abs(float(exit_pos.get("market_value", 0) or 0)) if exit_pos else 0
                    try:
                        for o in alpaca.get_orders(status="open"):
                            if o.get("symbol") == exit_sym and o.get("id"):
                                try:
                                    alpaca.cancel_order(o["id"])
                                except Exception as e:
                                    log.warning(f"    could not cancel {o.get('id')} for {exit_sym}: {e}")
                        close_res = alpaca.close_position(exit_sym)
                        _, _exit_qty, exit_price = confirm_fill(alpaca, close_res.get("id"))
                        _finalize_rotation_exit(exit_sym, exit_price or 0,
                                                reason=f"sector rotation -> {sym}")
                        # Free the room in-memory so the candidate can proceed.
                        sector_exposure[sector] = max(0.0, sector_val - exit_val)
                        cash += exit_val
                        positions = [p for p in positions if p["symbol"] != exit_sym]
                        position_symbols.discard(exit_sym)
                        sector_rotations += 1
                        swapped = True
                        log.info(f"  SECTOR ROTATE: exited {exit_sym} (RS {exit_pick['rs']:.1f}) "
                                 f"to make room for {sym} (RS {signal.get('rs_vs_spy', 0):.1f})")
                    except Exception as e:
                        log.error(f"  Sector rotation exit failed for {exit_sym}: {e}")
            if not swapped:
                log.info(f"  Sector {sector} at limit ({sector_val/equity*100:.1f}%), skipping {sym}")
                skips.append({"symbol": sym, "reason": f"sector {sector} at cap", "benign": True})
                continue

        try:
            live_trade = alpaca.get_latest_trade(sym)
            live_price = float(live_trade.get("trade", {}).get("p", 0))
            if live_price > 0:
                price = live_price
        except Exception:
            pass

        if not atr_val or atr_val <= 0:
            watchlist = load_json(DATA_DIR / "watchlist.json", [])
            match = next((w for w in watchlist if w.get("symbol") == sym), None)
            if match:
                atr_val = match.get("atr", 0)
            if not atr_val or atr_val <= 0:
                atr_val = price * 0.03 if price > 0 else 0
            if atr_val <= 0:
                log.info(f"  No ATR for {sym}, skipping")
                skips.append({"symbol": sym, "reason": "no ATR (cannot size)", "benign": True})
                continue

        shares, stop_price, tp1_price = compute_position_size(equity, price, atr_val, limits)
        if shares <= 0:
            skips.append({"symbol": sym, "reason": "sizing returned 0 shares", "benign": False})
            continue

        trade_value = shares * price
        if trade_value > cash * 0.90:
            shares = int(cash * 0.85 / price)
            if shares <= 0:
                log.warning(f"  Insufficient cash for {sym}")
                skips.append({"symbol": sym, "reason": "insufficient cash", "benign": True})
                continue
            trade_value = shares * price

        if trade_value > tranche_capital * 0.30:
            shares = int(tranche_capital * 0.25 / price)
            if shares <= 0:
                skips.append({"symbol": sym, "reason": "tranche capital exhausted", "benign": True})
                continue
            trade_value = shares * price

        # Enforce the sector cap on the PROPOSED exposure (current + THIS order),
        # not just current. The early >= check above only blocks adding to a
        # sector already at the cap; a single tranche-sized entry could still
        # vault a sector far past it (P3 reached ~33% on a 20% cap, holding 2
        # names per sector). This makes a 20% cap mean 20%, not 2x position size.
        current_sector_val = sector_exposure.get(sector, 0)
        if sector_cap_breached(current_sector_val, trade_value, equity,
                               limits["max_sector_exposure_pct"]):
            proposed_pct = (current_sector_val + trade_value) / equity * 100
            log.info(f"  Sector {sector} would reach {proposed_pct:.1f}% "
                     f"(cap {limits['max_sector_exposure_pct']}%), skipping {sym}")
            skips.append({"symbol": sym,
                          "reason": f"sector {sector} would breach cap", "benign": True})
            continue

        try:
            log.info(f"  BUYING {shares} x {sym} @ ~${price:.2f} "
                     f"(${trade_value:,.0f}) stop=${stop_price:.2f} tp=${tp1_price:.2f}")

            coid = make_client_order_id("p3", sym, "buy")
            order = alpaca.place_bracket_order(
                symbol=sym, qty=shares, side="buy",
                take_profit_price=tp1_price,
                stop_loss_price=stop_price,
                client_order_id=coid,
            )

            placed_count += 1
            # Confirm the fill so the trade log records the REAL entry price,
            # not the pre-trade quote.
            status, filled_qty, filled_price = confirm_fill(alpaca, order.get("id"))
            entry_price = filled_price if filled_price else price
            if filled_qty and float(filled_qty) > 0:
                filled_count += 1

            trade_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "date": today,
                "symbol": sym,
                "side": "buy",
                "qty": shares,
                "entry_price": round(entry_price, 4),
                "stop_loss": stop_price,
                "take_profit_1": tp1_price,
                "atr": atr_val,
                "trade_value": round(trade_value, 2),
                "order_id": order.get("id"),
                "order_status": status if status != "unknown" else order.get("status"),
                "filled_qty": filled_qty,
                "sector": sector,
                "tranche": tranche,
                "signal_score": signal["score"],
                "reasons": signal["reasons"],
                "signal_type": signal.get("signal", "BUY"),
                "status": "open",
            }
            trade_log.append(trade_record)
            executed.append(trade_record)

            position_symbols.add(sym)
            sector_exposure[sector] = sector_exposure.get(sector, 0) + trade_value
            cash -= trade_value
            trades_today += 1
            time.sleep(0.5)

        except requests.HTTPError as e:
            resp = getattr(e, "response", None)
            # Duplicate client_order_id (422) -> already placed today; idempotent skip.
            if resp is not None and resp.status_code == 422 and "client_order_id" in resp.text:
                log.info(f"  {sym}: already placed today (idempotent skip)")
                placed_count += 1  # order exists at broker from a prior fire today
                continue
            log.error(f"  Order failed for {sym}: {e}")
            if resp is not None:
                log.error(f"  Response: {resp.text}")
        except Exception as e:
            log.error(f"  Unexpected error for {sym}: {e}")

    save_json(DATA_DIR / "trade_log.json", trade_log)

    # Execution-integrity audit — same silent-no-op guard as P1 (2026-06-01).
    from shared.integrity import execution_integrity, write_integrity_report
    integrity = execution_integrity(
        total_signals=len(signals),
        approved=len(signals), placed=placed_count, filled=filled_count,
        halted=False, cash_available=cash > 100,
        skipped=skips, portfolio_id="portfolio_3",
    )
    write_integrity_report(str(DATA_DIR / "execution_integrity.json"), integrity)
    if integrity["anomalous"]:
        log.warning(f"::warning::EXECUTION ANOMALY (P3): {integrity['anomaly_reason']}")

    # Strategy conformance — P3 mandate: complete brackets + catalyst time-stop.
    from shared.integrity import (bracket_conformance, strategy_conformance,
                                  write_conformance_report)
    conf = strategy_conformance(portfolio_id="portfolio_3", checks=[
        bracket_conformance(executed, stop_key="stop_loss", tp_key="take_profit_1"),
        {"name": "catalyst_decay_configured",
         "ok": float(limits.get("catalyst_max_hold_days", 0)) > 0,
         "detail": f"catalyst_max_hold_days={limits.get('catalyst_max_hold_days')}"},
    ])
    write_conformance_report(str(DATA_DIR / "strategy_conformance.json"), conf)
    for _v in conf["violations"]:
        log.warning(f"::warning::CONFORMANCE (P3): {_v['name']} — {_v['detail']}")

    return executed


# ---------------------------------------------------------------------------
# INTRADAY MONITOR
# ---------------------------------------------------------------------------

def run_intraday_monitor(alpaca: AlpacaClient):
    log.info("=" * 60)
    log.info("INTRADAY MONITOR — P&L, stops, kill switch")
    log.info("=" * 60)

    if not alpaca.is_market_open():
        log.info("Market closed — skipping intraday monitor")
        return

    account = alpaca.get_account()
    equity = float(account["equity"])
    last_equity = float(account["last_equity"])
    limits = load_json(CONFIG_DIR / "risk_limits.json")

    daily_pnl_pct = (equity - last_equity) / last_equity * 100 if last_equity > 0 else 0
    log.info(f"Equity: ${equity:,.2f}, Daily P&L: {daily_pnl_pct:+.2f}%")

    # Kill switch
    if daily_pnl_pct <= -limits["kill_switch_daily_loss_pct"]:
        log.critical(f"KILL SWITCH: Daily loss {daily_pnl_pct:.2f}% >= {limits['kill_switch_daily_loss_pct']}%")
        log.critical("LIQUIDATING ALL POSITIONS AND HALTING")
        try:
            alpaca.cancel_all_orders()
            alpaca.close_all_positions()
        except Exception as e:
            log.error(f"Liquidation error: {e}")

        state = load_json(DATA_DIR / "bot_state.json")
        state["halted"] = True
        state["halt_reason"] = f"Kill switch: {daily_pnl_pct:.2f}% daily loss"
        state["halt_until"] = (datetime.now(timezone.utc) + timedelta(hours=limits["kill_switch_halt_hours"])).isoformat()
        save_json(DATA_DIR / "bot_state.json", state)
        return

    # Check halt expiry
    state = load_json(DATA_DIR / "bot_state.json")
    if state.get("halted") and state.get("halt_until"):
        halt_until = datetime.fromisoformat(state["halt_until"])
        if datetime.now(timezone.utc) > halt_until:
            log.info("Halt period expired — resuming")
            state["halted"] = False
            state["halt_reason"] = None
            state["halt_until"] = None
            save_json(DATA_DIR / "bot_state.json", state)

    # Per-position stop-loss and take-profit are enforced server-side by the
    # bracket (OCO) orders placed at entry (see run_trading_session →
    # place_bracket_order), so this loop is for portfolio-level reporting and
    # the kill switch above — not manual stop execution.
    positions = alpaca.get_positions()
    for pos in positions:
        sym = pos["symbol"]
        pnl_pct = float(pos.get("unrealized_plpc", 0)) * 100

        if pnl_pct <= -10:
            log.warning(f"  {sym} down {pnl_pct:.1f}% — severe drawdown")
        elif pnl_pct >= 15:
            log.info(f"  {sym} up {pnl_pct:.1f}% — consider scaling out remainder")

    # T10: catalyst-decay time stop. Force-exit news/event trades past their hold
    # window — the catalyst edge is gone and the position is now unmanaged risk.
    _enforce_catalyst_decay(alpaca, positions, limits)

    _sync_state(alpaca)
    log.info(f"Monitor: {len(positions)} positions, equity=${equity:,.2f}")


def _enforce_catalyst_decay(alpaca: AlpacaClient, positions: list, limits: dict):
    """Close any held catalyst trade whose edge has decayed. Cancels its working
    bracket legs first so the close doesn't conflict, then liquidates. Lets the
    EOD journal finalize the trade record (exit price from the fill)."""
    max_hold = limits.get("catalyst_max_hold_days")
    if max_hold is None:
        max_hold = (limits.get("event_hold_days", {}) or {}).get("max", 1)
    trade_log = load_json(DATA_DIR / "trade_log.json", [])
    held = {p.get("symbol") for p in positions}
    if not held:
        return
    try:
        open_orders = alpaca.get_orders(status="open")
    except Exception:
        open_orders = []

    for t in trade_log:
        if t.get("status") != "open":
            continue
        sym = t.get("symbol")
        if sym not in held or not catalyst_decayed(t, max_hold_days=max_hold):
            continue
        age = trade_age_days(t)
        log.info(f"  Catalyst-decay exit: {sym} held {age}d ≥ {max_hold}d — closing")
        for o in open_orders:
            if o.get("symbol") == sym and o.get("id"):
                try:
                    alpaca.cancel_order(o["id"])
                except Exception as e:
                    log.warning(f"    could not cancel order {o.get('id')} for {sym}: {e}")
        try:
            alpaca.close_position(sym)
            t["catalyst_decay_exit"] = True
        except Exception as e:
            log.error(f"    catalyst-decay close failed for {sym}: {e}")

    save_json(DATA_DIR / "trade_log.json", trade_log)


# ---------------------------------------------------------------------------
# EOD JOURNAL
# ---------------------------------------------------------------------------

def run_eod_journal(alpaca: AlpacaClient):
    log.info("=" * 60)
    log.info("END-OF-DAY JOURNAL & AUDIT")
    log.info("=" * 60)

    account = alpaca.get_account()
    equity = float(account["equity"])
    last_equity = float(account["last_equity"])
    positions = alpaca.get_positions()
    trade_log = load_json(DATA_DIR / "trade_log.json", [])

    # Read-only integrity audit: flag drift between trade log and broker.
    from shared.reconcile import compute_drift
    recon = compute_drift(
        [p.get("symbol") for p in positions if p.get("symbol")],
        [t.get("symbol") for t in trade_log
         if t.get("status") == "open" and t.get("symbol")],
    )
    save_json(DATA_DIR / "reconciliation_report.json", recon)
    if recon["in_sync"]:
        log.info("  Reconciliation: trade log and broker positions in sync")
    else:
        if recon["orphan_open_trades"]:
            log.warning(f"  Reconciliation: open trades with no position: {recon['orphan_open_trades']}")
        if recon["unlogged_positions"]:
            log.warning(f"  Reconciliation: positions not in trade log: {recon['unlogged_positions']}")

    today = datetime.now().strftime("%Y-%m-%d")
    today_trades = [t for t in trade_log if t.get("date", "").startswith(today)]

    total_exposure = sum(abs(float(p.get("market_value", 0))) for p in positions)
    daily_pnl = equity - last_equity

    closed_today = [t for t in today_trades if t.get("status") == "closed"]
    wins = [t for t in closed_today if (t.get("pnl", 0) or 0) > 0]
    win_rate = len(wins) / len(closed_today) * 100 if closed_today else 0

    # Sector breakdown
    sector_exposure = {}
    for p in positions:
        sector = SECTOR_MAP.get(p["symbol"], "Unknown")
        sector_exposure[sector] = sector_exposure.get(sector, 0) + abs(float(p.get("market_value", 0)))

    journal_entry = {
        "date": today,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "audit": {
            "equity": equity,
            "cash": float(account["cash"]),
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": round(daily_pnl / last_equity * 100, 3) if last_equity > 0 else 0,
            "total_open_exposure": round(total_exposure, 2),
            "exposure_pct": round(total_exposure / equity * 100, 1),
            "position_count": len(positions),
            "trades_today": len(today_trades),
            "closed_today": len(closed_today),
            "win_rate_today": round(win_rate, 1),
            "sector_exposure": {k: round(v, 2) for k, v in sector_exposure.items()},
        },
        "positions": [
            {
                "symbol": p["symbol"],
                "qty": p["qty"],
                "entry": p["avg_entry_price"],
                "current": p["current_price"],
                "market_value": p["market_value"],
                "unrealized_pl": p["unrealized_pl"],
                "pnl_pct": round(float(p.get("unrealized_plpc", 0)) * 100, 2),
                "sector": SECTOR_MAP.get(p["symbol"], "Unknown"),
            }
            for p in positions
        ],
        "trades": [
            {
                "symbol": t["symbol"],
                "side": t["side"],
                "qty": t["qty"],
                "signal_type": t.get("signal_type", ""),
                "tranche": t.get("tranche", ""),
                "score": t.get("signal_score", 0),
                "reasons": t.get("reasons", [])[:3],
            }
            for t in today_trades
        ],
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

    _sync_state(alpaca)

    log.info(f"EOD: equity=${equity:,.2f}, P&L=${daily_pnl:+,.2f} ({daily_pnl/last_equity*100:+.2f}%), "
             f"{len(positions)} positions, {len(today_trades)} trades today")


# ---------------------------------------------------------------------------
# WEEKLY REVIEW
# ---------------------------------------------------------------------------

def run_weekly_review(alpaca: AlpacaClient):
    log.info("=" * 60)
    log.info("WEEKLY REVIEW")
    log.info("=" * 60)

    account = alpaca.get_account()
    equity = float(account["equity"])
    positions = alpaca.get_positions()
    trade_log = load_json(DATA_DIR / "trade_log.json", [])

    week_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    weekly_trades = [t for t in trade_log if t.get("date", "") >= week_start]
    closed = [t for t in weekly_trades if t.get("status") == "closed"]
    wins = [t for t in closed if (t.get("pnl", 0) or 0) > 0]

    by_tranche = {}
    for t in weekly_trades:
        tr = t.get("tranche", "unknown")
        by_tranche.setdefault(tr, []).append(t)

    review = {
        "week_ending": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account": {
            "equity": equity,
            "cash": float(account["cash"]),
            "initial_capital": 100000,
            "total_return_pct": round((equity - 100000) / 100000 * 100, 3),
        },
        "weekly_performance": {
            "total_trades": len(weekly_trades),
            "closed": len(closed),
            "wins": len(wins),
            "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        },
        "by_tranche": {
            tr: {"trades": len(trades), "buys": len([t for t in trades if t["side"] == "buy"])}
            for tr, trades in by_tranche.items()
        },
        "positions": len(positions),
    }

    week_num = datetime.now().strftime("%Y-W%W")
    save_json(JOURNAL_DIR / f"weekly-{week_num}.json", review)
    log.info(f"Weekly: {len(weekly_trades)} trades, {len(positions)} positions, equity=${equity:,.2f}")

    # Re-run fundamental screen for next week
    log.info("Running weekly fundamental screen...")
    start = (datetime.now(timezone.utc) - timedelta(days=330)).strftime("%Y-%m-%d")
    spy_resp = alpaca.get_stock_bars("SPY", start=start, limit=220)
    spy_bars = spy_resp.get("bars", [])
    qualified = screen_universe(alpaca, spy_bars)
    save_watchlist(qualified)
    log.info(f"New watchlist: {len(qualified)} stocks qualified")


# ---------------------------------------------------------------------------
# STATE SYNC
# ---------------------------------------------------------------------------

def _sync_state(alpaca: AlpacaClient):
    account = alpaca.get_account()
    positions = alpaca.get_positions()
    equity = float(account["equity"])

    state = load_json(DATA_DIR / "bot_state.json")
    state["equity"] = equity
    state["cash"] = float(account["cash"])
    state["positions"] = len(positions)
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    state.setdefault("starting_equity", 100000)
    state.setdefault("halted", False)
    save_json(DATA_DIR / "bot_state.json", state)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Portfolio 3 — Multi-Factor Event-Driven Bot")
    parser.add_argument("mode", choices=[
        "weekly-screen", "morning-scan", "trading-session",
        "intraday-monitor", "news-scan", "eod-journal", "weekly-review",
    ])
    args = parser.parse_args()

    alpaca = AlpacaClient()

    try:
        acct = alpaca.get_account()
        log.info(f"Account {acct['account_number']}: equity=${float(acct['equity']):,.2f}, status={acct['status']}")
    except Exception as e:
        log.critical(f"Cannot connect to Alpaca: {e}")
        sys.exit(1)

    # Check halt state
    state = load_json(DATA_DIR / "bot_state.json")
    if state.get("halted") and args.mode not in ("intraday-monitor", "eod-journal"):
        halt_until = state.get("halt_until", "")
        if halt_until:
            ht = datetime.fromisoformat(halt_until)
            if datetime.now(timezone.utc) < ht:
                log.warning(f"System halted until {halt_until}. Only monitor/journal allowed.")
                return
            else:
                state["halted"] = False
                state["halt_reason"] = None
                state["halt_until"] = None
                save_json(DATA_DIR / "bot_state.json", state)

    if args.mode == "weekly-screen":
        log.info("=" * 60)
        log.info("WEEKLY FUNDAMENTAL SCREEN")
        log.info("=" * 60)
        start = (datetime.now(timezone.utc) - timedelta(days=330)).strftime("%Y-%m-%d")
        spy_resp = alpaca.get_stock_bars("SPY", start=start, limit=220)
        spy_bars = spy_resp.get("bars", [])
        qualified = screen_universe(alpaca, spy_bars)
        result = save_watchlist(qualified)
        log.info(f"Watchlist: {result['qualified']} stocks qualified")
        for q in qualified[:15]:
            log.info(f"  {q['symbol']:6s} {q['sector']:12s} RS={q['rs_vs_spy_3m']:+.1f} "
                     f"3M={q['return_3m']:+.1f}% RSI={q['rsi14']} ATR%={q['atr_pct']}")

    elif args.mode == "morning-scan":
        log.info("=" * 60)
        log.info("MORNING TECHNICAL SCAN")
        log.info("=" * 60)
        watchlist = load_json(DATA_DIR / "watchlist.json")
        if not watchlist.get("universe"):
            log.warning("No watchlist found — running fundamental screen first")
            start = (datetime.now(timezone.utc) - timedelta(days=330)).strftime("%Y-%m-%d")
            spy_resp = alpaca.get_stock_bars("SPY", start=start, limit=220)
            spy_bars = spy_resp.get("bars", [])
            qualified = screen_universe(alpaca, spy_bars)
            watchlist = save_watchlist(qualified)

        signals = generate_signals(watchlist, alpaca)
        save_json(DATA_DIR / "signals.json", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_signals": len(signals),
            "signals": signals,
        })
        for s in signals[:10]:
            log.info(f"  {s['symbol']:6s} score={s['score']:.3f} "
                     f"ATR={s['atr']:.2f} RS={s['rs_vs_spy']:+.1f} | {'; '.join(s['reasons'][:2])}")

    elif args.mode == "trading-session":
        log.info("=" * 60)
        log.info("TRADING SESSION — Executing signals")
        log.info("=" * 60)
        if not alpaca.is_market_open():
            log.warning("Market closed — skipping trading session")
            return
        signals_data = load_json(DATA_DIR / "signals.json")
        signals = signals_data.get("signals", [])
        if not signals:
            log.info("No signals to execute")
            _sync_state(alpaca)
            return

        # Core swing trades (top signals)
        swing_signals = [s for s in signals if s.get("tranche") == "core_swing"][:8]
        if swing_signals:
            log.info(f"Executing {len(swing_signals)} core swing signals...")
            executed = execute_signals(alpaca, swing_signals, "core_swing")
            log.info(f"Executed {len(executed)} swing trades")

        _sync_state(alpaca)

    elif args.mode == "news-scan":
        log.info("=" * 60)
        log.info("NEWS CATALYST SCAN")
        log.info("=" * 60)
        if not alpaca.is_market_open():
            log.warning("Market closed — scanning news but skipping execution")
        watchlist = load_json(DATA_DIR / "watchlist.json")
        watchlist_symbols = [s["symbol"] for s in watchlist.get("universe", [])]

        if not watchlist_symbols:
            log.warning("No watchlist — skipping news scan")
            return

        news_signals = scan_news(alpaca, watchlist_symbols)
        if news_signals:
            save_json(DATA_DIR / "news_signals.json", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "signals": news_signals,
            })
            if alpaca.is_market_open():
                log.info(f"Executing {len(news_signals)} news-driven signals...")
                executed = execute_signals(alpaca, news_signals, "event_driven")
                log.info(f"Executed {len(executed)} event-driven trades")
            else:
                log.info("Skipping execution — market closed")
        else:
            log.info("No actionable news catalysts found")

    elif args.mode == "intraday-monitor":
        run_intraday_monitor(alpaca)

    elif args.mode == "eod-journal":
        run_eod_journal(alpaca)

    elif args.mode == "weekly-review":
        run_weekly_review(alpaca)


if __name__ == "__main__":
    main()
