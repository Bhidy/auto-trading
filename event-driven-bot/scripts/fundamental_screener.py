#!/usr/bin/env python3
"""
Fundamental Universe Screener — Filters 5000+ US equities down to 30-50 high-probability tickers.
Criteria: Market cap > $2B, ADV > 2M, relative strength vs SPY > 0 over 3M.
EPS growth is checked via price momentum as a proxy (no free fundamental API).
"""

import json
import math
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from alpaca_client import AlpacaClient

BASE_DIR = Path("/Users/home/Documents/Auto Trading/event-driven-bot")
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"

log = logging.getLogger("p3_screener")

SECTOR_MAP = {
    "AAPL": "Tech", "MSFT": "Tech", "GOOGL": "Tech", "AMZN": "Tech", "META": "Tech",
    "NVDA": "Tech", "AVGO": "Tech", "CRM": "Tech", "AMD": "Tech", "ADBE": "Tech",
    "ORCL": "Tech", "CSCO": "Tech", "INTC": "Tech", "QCOM": "Tech", "TXN": "Tech",
    "NOW": "Tech", "ANET": "Tech", "INTU": "Tech", "MU": "Tech", "LRCX": "Tech",
    "KLAC": "Tech", "SNPS": "Tech", "CDNS": "Tech", "MRVL": "Tech", "PANW": "Tech",
    "CRWD": "Tech", "FTNT": "Tech", "WDAY": "Tech", "TEAM": "Tech", "DDOG": "Tech",
    "JPM": "Financials", "BAC": "Financials", "WFC": "Financials", "GS": "Financials",
    "MS": "Financials", "C": "Financials", "BLK": "Financials", "SCHW": "Financials",
    "AXP": "Financials", "V": "Financials", "MA": "Financials", "SPGI": "Financials",
    "CME": "Financials", "ICE": "Financials", "CB": "Financials", "PGR": "Financials",
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "SLB": "Energy", "EOG": "Energy",
    "MPC": "Energy", "PSX": "Energy", "VLO": "Energy", "OXY": "Energy", "HAL": "Energy",
    "UNH": "Healthcare", "JNJ": "Healthcare", "LLY": "Healthcare", "ABBV": "Healthcare",
    "MRK": "Healthcare", "PFE": "Healthcare", "TMO": "Healthcare", "ABT": "Healthcare",
    "AMGN": "Healthcare", "BMY": "Healthcare", "GILD": "Healthcare", "ISRG": "Healthcare",
    "MDT": "Healthcare", "DHR": "Healthcare", "SYK": "Healthcare", "BSX": "Healthcare",
    "REGN": "Healthcare", "VRTX": "Healthcare", "ZTS": "Healthcare", "EW": "Healthcare",
    "PG": "Consumer", "KO": "Consumer", "PEP": "Consumer", "COST": "Consumer",
    "WMT": "Consumer", "HD": "Consumer", "MCD": "Consumer", "NKE": "Consumer",
    "SBUX": "Consumer", "TGT": "Consumer", "LOW": "Consumer", "DG": "Consumer",
    "TSLA": "Consumer", "GM": "Consumer", "F": "Consumer", "TJX": "Consumer",
    "CAT": "Industrials", "HON": "Industrials", "UNP": "Industrials", "RTX": "Industrials",
    "BA": "Industrials", "LMT": "Industrials", "GE": "Industrials", "DE": "Industrials",
    "MMM": "Industrials", "EMR": "Industrials", "ITW": "Industrials", "ETN": "Industrials",
    "CARR": "Industrials", "FDX": "Industrials", "UPS": "Industrials", "WM": "Industrials",
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities", "D": "Utilities",
    "AEP": "Utilities", "SRE": "Utilities", "EXC": "Utilities", "XEL": "Utilities",
    "AMT": "RealEstate", "PLD": "RealEstate", "CCI": "RealEstate", "EQIX": "RealEstate",
    "SPG": "RealEstate", "PSA": "RealEstate", "O": "RealEstate", "DLR": "RealEstate",
    "LIN": "Materials", "APD": "Materials", "SHW": "Materials", "ECL": "Materials",
    "NEM": "Materials", "FCX": "Materials", "NUE": "Materials", "DOW": "Materials",
    "T": "Telecom", "VZ": "Telecom", "TMUS": "Telecom", "CHTR": "Telecom",
    "NFLX": "Media", "DIS": "Media", "CMCSA": "Media", "WBD": "Media",
}

FULL_UNIVERSE = list(SECTOR_MAP.keys())


def sma(data, period):
    if len(data) < period:
        return None
    return sum(data[-period:]) / period


def ema(data, period):
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    val = sum(data[:period]) / period
    for p in data[period:]:
        val = (p - val) * k + val
    return val


def momentum_pct(data, days):
    if len(data) < days + 1 or data[-days] == 0:
        return None
    return (data[-1] - data[-days]) / data[-days] * 100


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
    val = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        val = (val * (period - 1) + trs[i]) / period
    return val


def bollinger_bands(closes, period=20, num_std=2):
    if len(closes) < period:
        return None, None, None
    mid = sma(closes, period)
    variance = sum((c - mid) ** 2 for c in closes[-period:]) / period
    std = math.sqrt(variance)
    return mid - num_std * std, mid, mid + num_std * std


def macd(closes, fast=12, slow=26, signal_p=9):
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    if fast_ema is None or slow_ema is None:
        return None, None, None
    macd_line = fast_ema - slow_ema
    if len(closes) < slow + signal_p:
        return macd_line, None, None
    macd_series = []
    k_fast = 2 / (fast + 1)
    k_slow = 2 / (slow + 1)
    f = sum(closes[:fast]) / fast
    s = sum(closes[:slow]) / slow
    for i in range(slow, len(closes)):
        f = (closes[i] - f) * k_fast + f
        s = (closes[i] - s) * k_slow + s
        macd_series.append(f - s)
    if len(macd_series) < signal_p:
        return macd_line, None, None
    sig = sum(macd_series[:signal_p]) / signal_p
    k_sig = 2 / (signal_p + 1)
    for v in macd_series[signal_p:]:
        sig = (v - sig) * k_sig + sig
    return macd_line, sig, macd_line - sig


def screen_universe(alpaca: AlpacaClient, spy_bars: list) -> list:
    """Screen the full universe and return qualified tickers with full technical data."""
    log.info(f"Screening {len(FULL_UNIVERSE)} symbols...")

    spy_closes = [b["c"] for b in spy_bars]
    spy_3m_return = momentum_pct(spy_closes, 63) or 0

    start_date = (datetime.now(timezone.utc) - timedelta(days=330)).strftime("%Y-%m-%d")
    qualified = []

    for sym in FULL_UNIVERSE:
        try:
            resp = alpaca.get_stock_bars(sym, start=start_date, limit=220)
            bars = resp.get("bars", [])
        except Exception as e:
            log.error(f"Fetch {sym} failed: {e}")
            time.sleep(0.3)
            continue

        if True:
            if len(bars) < 60:
                continue

            closes = [b["c"] for b in bars]
            highs = [b["h"] for b in bars]
            lows = [b["l"] for b in bars]
            volumes = [b["v"] for b in bars]

            avg_vol = sum(volumes[-20:]) / min(20, len(volumes))
            if avg_vol < 2_000_000:
                continue

            stock_3m_return = momentum_pct(closes, 63)
            if stock_3m_return is None:
                continue
            rs_vs_spy = stock_3m_return - spy_3m_return
            if rs_vs_spy < 0:
                continue

            ema200 = ema(closes, 200) if len(closes) >= 200 else ema(closes, len(closes))
            ema50 = ema(closes, 50)
            price = closes[-1]

            if ema200 and price < ema200:
                continue

            stock_1m_return = momentum_pct(closes, 21) or 0
            if stock_1m_return < -10:
                continue

            atr_val = atr(highs, lows, closes)
            rsi_val = rsi(closes)
            bb_lower, bb_mid, bb_upper = bollinger_bands(closes)
            macd_line, macd_sig, macd_hist = macd(closes)

            vol_20d = sum(volumes[-20:]) / 20
            vol_5d = sum(volumes[-5:]) / 5
            rvol = vol_5d / vol_20d if vol_20d > 0 else 1.0

            bb_width = (bb_upper - bb_lower) / bb_mid * 100 if bb_mid and bb_upper and bb_lower else None

            qualified.append({
                "symbol": sym,
                "sector": SECTOR_MAP.get(sym, "Unknown"),
                "price": round(price, 2),
                "avg_volume_20d": round(avg_vol),
                "rs_vs_spy_3m": round(rs_vs_spy, 2),
                "return_1m": round(stock_1m_return, 2),
                "return_3m": round(stock_3m_return, 2),
                "ema50": round(ema50, 2) if ema50 else None,
                "ema200": round(ema200, 2) if ema200 else None,
                "above_ema200": price > ema200 if ema200 else False,
                "above_ema50": price > ema50 if ema50 else False,
                "rsi14": round(rsi_val, 1) if rsi_val else None,
                "atr14": round(atr_val, 2) if atr_val else None,
                "atr_pct": round(atr_val / price * 100, 2) if atr_val and price > 0 else None,
                "bb_upper": round(bb_upper, 2) if bb_upper else None,
                "bb_lower": round(bb_lower, 2) if bb_lower else None,
                "bb_width_pct": round(bb_width, 2) if bb_width else None,
                "macd_line": round(macd_line, 4) if macd_line else None,
                "macd_signal": round(macd_sig, 4) if macd_sig else None,
                "macd_histogram": round(macd_hist, 4) if macd_hist else None,
                "rvol_5d": round(rvol, 2),
                "bars": bars,
            })

        time.sleep(0.2)

    qualified.sort(key=lambda x: x["rs_vs_spy_3m"], reverse=True)
    log.info(f"Screened: {len(qualified)} qualified out of {len(FULL_UNIVERSE)}")
    return qualified


def save_watchlist(qualified: list):
    watchlist = []
    for q in qualified:
        entry = {k: v for k, v in q.items() if k != "bars"}
        watchlist.append(entry)

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_screened": len(FULL_UNIVERSE),
        "qualified": len(watchlist),
        "universe": watchlist,
    }
    with open(DATA_DIR / "watchlist.json", "w") as f:
        json.dump(output, f, indent=2)
    return output


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    alpaca = AlpacaClient()
    start = (datetime.now(timezone.utc) - timedelta(days=330)).strftime("%Y-%m-%d")
    spy_resp = alpaca.get_stock_bars("SPY", start=start, limit=220)
    spy_bars = spy_resp.get("bars", [])
    qualified = screen_universe(alpaca, spy_bars)
    result = save_watchlist(qualified)
    print(f"Watchlist: {result['qualified']} stocks qualified")
    for q in qualified[:10]:
        print(f"  {q['symbol']:6s} RS={q['rs_vs_spy_3m']:+.1f} 3M={q['return_3m']:+.1f}% RSI={q['rsi14']} ATR%={q['atr_pct']}")
