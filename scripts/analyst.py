#!/usr/bin/env python3
"""
Senior Chief Quantitative Trading Analyst Engine
Computes technical indicators and generates trade signals per the Master Blueprint.
"""
import json
import sys
import os
from datetime import datetime, timezone

def load_bars(filepath):
    with open(filepath) as f:
        data = json.load(f)
    return data.get("bars", data)

def compute_sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def compute_ema(closes, period):
    if len(closes) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def compute_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        true_ranges.append(tr)
    atr = sum(true_ranges[:period]) / period
    for i in range(period, len(true_ranges)):
        atr = (atr * (period - 1) + true_ranges[i]) / period
    return atr

def compute_momentum(closes, days):
    if len(closes) < days:
        return None
    return (closes[-1] - closes[-days]) / closes[-days] * 100

def analyze_symbol(bars, symbol, instrument_type="stock"):
    if not bars or len(bars) < 50:
        return {"symbol": symbol, "signal": "INSUFFICIENT_DATA", "reason": f"Only {len(bars)} bars available"}

    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    volumes = [b["v"] for b in bars]

    current_price = closes[-1]
    ma50 = compute_sma(closes, 50)
    ma200 = compute_sma(closes, 200) if len(closes) >= 200 else compute_sma(closes, len(closes))
    rsi = compute_rsi(closes)
    atr = compute_atr(highs, lows, closes)
    mom_3m = compute_momentum(closes, 63)
    mom_6m = compute_momentum(closes, 126) if len(closes) >= 126 else compute_momentum(closes, len(closes) - 1)
    avg_volume = sum(volumes[-20:]) / min(20, len(volumes))

    indicators = {
        "price": round(current_price, 4),
        "ma50": round(ma50, 4) if ma50 else None,
        "ma200": round(ma200, 4) if ma200 else None,
        "rsi14": round(rsi, 2) if rsi else None,
        "atr14": round(atr, 4) if atr else None,
        "momentum_3m_pct": round(mom_3m, 2) if mom_3m else None,
        "momentum_6m_pct": round(mom_6m, 2) if mom_6m else None,
        "avg_volume_20d": round(avg_volume, 0),
    }

    signal = "HOLD"
    confidence = 0.0
    reasons = []

    if ma50 and ma200:
        price_above_ma50 = current_price > ma50
        price_above_ma200 = current_price > ma200

        # LONG ENTRY
        if price_above_ma50 and price_above_ma200:
            confidence += 0.25
            reasons.append("Price above MA50 and MA200")
            if mom_3m and mom_3m > 0:
                confidence += 0.20
                reasons.append(f"3M momentum positive ({mom_3m:.1f}%)")
            if mom_6m and mom_6m > 0:
                confidence += 0.15
                reasons.append(f"6M momentum positive ({mom_6m:.1f}%)")
            if rsi and rsi < 75:
                confidence += 0.15
                reasons.append(f"RSI not overbought ({rsi:.1f})")
            elif rsi and rsi >= 75:
                confidence -= 0.20
                reasons.append(f"RSI overbought ({rsi:.1f}) - caution")
            if rsi and 30 < rsi < 50:
                confidence += 0.10
                reasons.append("RSI in buy zone")

            if confidence >= 0.50:
                signal = "BUY"
            elif confidence >= 0.30:
                signal = "HOLD"

        # SHORT ENTRY
        elif not price_above_ma50 and not price_above_ma200:
            confidence += 0.25
            reasons.append("Price below MA50 and MA200")
            if mom_3m and mom_3m < 0:
                confidence += 0.20
                reasons.append(f"3M momentum negative ({mom_3m:.1f}%)")
            if mom_6m and mom_6m < 0:
                confidence += 0.15
                reasons.append(f"6M momentum negative ({mom_6m:.1f}%)")
            if rsi and rsi > 30:
                confidence += 0.10
                reasons.append(f"RSI not oversold ({rsi:.1f})")

            if confidence >= 0.50 and instrument_type == "stock":
                signal = "SHORT"
            elif confidence >= 0.30:
                signal = "HOLD"

        # MIXED SIGNALS
        else:
            reasons.append("Mixed trend signals (MA50/MA200 divergence)")
            if mom_3m and mom_3m > 5:
                confidence += 0.15
                signal = "BUY"
                reasons.append("Short-term momentum recovering")
            elif mom_3m and mom_3m < -5:
                confidence += 0.15
                signal = "HOLD"
                reasons.append("Short-term momentum declining")

    target_risk_pct = 1.0
    position_size_pct = None
    if atr and current_price > 0:
        atr_pct = atr / current_price
        if atr_pct > 0:
            position_size_pct = round(min(target_risk_pct / (atr_pct * 100), 12.0), 2)

    return {
        "symbol": symbol,
        "instrument_type": instrument_type,
        "signal": signal,
        "confidence": round(confidence, 2),
        "reasons": reasons,
        "indicators": indicators,
        "suggested_position_size_pct": position_size_pct,
    }

def main():
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    results = {"timestamp": datetime.now(timezone.utc).isoformat(), "signals": []}

    bar_files = {
        "core_equity.json": {"type": "etf", "symbols": ["SPY", "QQQ", "IWM", "DIA"]},
        "aggressive_growth.json": {"type": "stock", "symbols": ["NVDA", "TSLA", "META", "AMZN", "MSFT", "GOOGL", "AAPL"]},
        "sector_momentum.json": {"type": "etf", "symbols": ["XLK", "XLE", "XLF", "XLV", "XLY", "XLI"]},
        "crypto.json": {"type": "crypto", "symbols": ["BTC/USD", "ETH/USD"]},
        "defensive.json": {"type": "etf", "symbols": ["SHY", "BIL", "TLT", "GLD"]},
    }

    for filename, info in bar_files.items():
        filepath = os.path.join(data_dir, filename)
        if not os.path.exists(filepath):
            continue
        bars_data = load_bars(filepath)
        for symbol in info["symbols"]:
            bars = bars_data.get(symbol, [])
            result = analyze_symbol(bars, symbol, info["type"])
            results["signals"].append(result)

    output_path = os.path.join(data_dir, "signals.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
