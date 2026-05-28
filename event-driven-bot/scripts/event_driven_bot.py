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
import math
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
from alpaca_client import AlpacaClient
from fundamental_screener import (
    screen_universe, save_watchlist, sma, ema, momentum_pct, rsi, atr,
    bollinger_bands, macd, SECTOR_MAP, FULL_UNIVERSE,
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

def generate_signals(watchlist_data: dict, alpaca: AlpacaClient) -> list:
    """Generate technical breakout signals from the fundamental watchlist."""
    universe = watchlist_data.get("universe", [])
    limits = load_json(CONFIG_DIR / "risk_limits.json")
    signals = []

    for stock in universe:
        sym = stock["symbol"]
        price = stock["price"]
        bb_upper = stock.get("bb_upper")
        bb_lower = stock.get("bb_lower")
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
            continue

        # Sector limit check
        sector_val = sector_exposure.get(sector, 0)
        if sector_val / equity * 100 >= limits["max_sector_exposure_pct"]:
            log.info(f"  Sector {sector} at limit ({sector_val/equity*100:.1f}%), skipping {sym}")
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
                continue

        shares, stop_price, tp1_price = compute_position_size(equity, price, atr_val, limits)
        if shares <= 0:
            continue

        trade_value = shares * price
        if trade_value > cash * 0.90:
            shares = int(cash * 0.85 / price)
            if shares <= 0:
                log.warning(f"  Insufficient cash for {sym}")
                continue
            trade_value = shares * price

        if trade_value > tranche_capital * 0.30:
            shares = int(tranche_capital * 0.25 / price)
            if shares <= 0:
                continue
            trade_value = shares * price

        try:
            log.info(f"  BUYING {shares} x {sym} @ ~${price:.2f} "
                     f"(${trade_value:,.0f}) stop=${stop_price:.2f} tp=${tp1_price:.2f}")

            order = alpaca.place_bracket_order(
                symbol=sym, qty=shares, side="buy",
                take_profit_price=tp1_price,
                stop_loss_price=stop_price,
            )

            trade_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "date": today,
                "symbol": sym,
                "side": "buy",
                "qty": shares,
                "entry_price": price,
                "stop_loss": stop_price,
                "take_profit_1": tp1_price,
                "atr": atr_val,
                "trade_value": round(trade_value, 2),
                "order_id": order.get("id"),
                "order_status": order.get("status"),
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
            log.error(f"  Order failed for {sym}: {e}")
            if hasattr(e, "response") and e.response is not None:
                log.error(f"  Response: {e.response.text}")
        except Exception as e:
            log.error(f"  Unexpected error for {sym}: {e}")

    save_json(DATA_DIR / "trade_log.json", trade_log)
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

    positions = alpaca.get_positions()
    for pos in positions:
        sym = pos["symbol"]
        pnl_pct = float(pos.get("unrealized_plpc", 0)) * 100
        qty = int(float(pos["qty"]))
        current = float(pos["current_price"])
        entry = float(pos["avg_entry_price"])

        if pnl_pct <= -10:
            log.warning(f"  {sym} down {pnl_pct:.1f}% — severe drawdown")
        elif pnl_pct >= 15:
            log.info(f"  {sym} up {pnl_pct:.1f}% — consider scaling out remainder")

    _sync_state(alpaca)
    log.info(f"Monitor: {len(positions)} positions, equity=${equity:,.2f}")


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
                log.info(f"Skipping execution — market closed")
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
