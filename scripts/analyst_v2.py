#!/usr/bin/env python3
"""
Enhanced Analyst Engine v2 — Self-Learning Autonomous Trading Brain
Multi-timeframe, regime-aware, adaptive, with relative strength ranking.
"""
import json
import os
import math
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

# ---------------------------------------------------------------------------
# CORE INDICATOR COMPUTATION
# ---------------------------------------------------------------------------

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

def macd(closes, fast=12, slow=26, signal=9):
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    if fast_ema is None or slow_ema is None:
        return None, None, None
    macd_line = fast_ema - slow_ema
    if len(closes) < slow + signal:
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
    if len(macd_series) < signal:
        return macd_line, None, None
    sig = sum(macd_series[:signal]) / signal
    k_sig = 2 / (signal + 1)
    for v in macd_series[signal:]:
        sig = (v - sig) * k_sig + sig
    return macd_line, sig, macd_line - sig

def momentum(closes, days):
    if len(closes) < days + 1:
        return None
    return (closes[-1] - closes[-days]) / closes[-days] * 100

def volume_trend(volumes, period=20):
    if len(volumes) < period * 2:
        return None
    recent = sum(volumes[-period:]) / period
    prior = sum(volumes[-period*2:-period]) / period
    if prior == 0:
        return None
    return (recent - prior) / prior * 100

def average_true_range_pct(highs, lows, closes, period=14):
    a = atr(highs, lows, closes, period)
    if a is None or closes[-1] == 0:
        return None
    return a / closes[-1] * 100

# ---------------------------------------------------------------------------
# MARKET REGIME DETECTION
# ---------------------------------------------------------------------------

def detect_regime(spy_closes, vix_level=None):
    if not spy_closes or len(spy_closes) < 50:
        return "UNKNOWN"
    ma50 = sma(spy_closes, 50)
    ma200 = sma(spy_closes, 200) if len(spy_closes) >= 200 else sma(spy_closes, len(spy_closes))
    price = spy_closes[-1]
    mom_1m = momentum(spy_closes, 21)
    mom_3m = momentum(spy_closes, 63)
    r = rsi(spy_closes)

    if price > ma50 and price > ma200 and ma50 > ma200:
        if mom_1m and mom_1m > 3:
            return "STRONG_BULL"
        return "BULL"
    elif price > ma200 and price < ma50:
        return "CORRECTION"
    elif price < ma200 and price > ma50:
        return "RECOVERY"
    elif price < ma50 and price < ma200:
        if mom_1m and mom_1m < -5:
            return "STRONG_BEAR"
        return "BEAR"
    return "TRANSITIONAL"

def regime_allocation_modifier(regime):
    modifiers = {
        "STRONG_BULL":  {"equity_mult": 1.2, "defensive_mult": 0.6, "cash_target": 0.10},
        "BULL":         {"equity_mult": 1.0, "defensive_mult": 0.8, "cash_target": 0.15},
        "CORRECTION":   {"equity_mult": 0.7, "defensive_mult": 1.3, "cash_target": 0.25},
        "RECOVERY":     {"equity_mult": 0.8, "defensive_mult": 1.0, "cash_target": 0.20},
        "BEAR":         {"equity_mult": 0.5, "defensive_mult": 1.5, "cash_target": 0.35},
        "STRONG_BEAR":  {"equity_mult": 0.3, "defensive_mult": 1.8, "cash_target": 0.45},
        "TRANSITIONAL": {"equity_mult": 0.8, "defensive_mult": 1.0, "cash_target": 0.20},
        "UNKNOWN":      {"equity_mult": 0.7, "defensive_mult": 1.2, "cash_target": 0.25},
    }
    return modifiers.get(regime, modifiers["UNKNOWN"])

# ---------------------------------------------------------------------------
# RELATIVE STRENGTH RANKING
# ---------------------------------------------------------------------------

def rank_by_relative_strength(symbols_data):
    scores = []
    for sym, data in symbols_data.items():
        closes = [b["c"] for b in data]
        if len(closes) < 63:
            continue
        m1 = momentum(closes, 21) or 0
        m3 = momentum(closes, 63) or 0
        m6 = momentum(closes, 126) if len(closes) >= 127 else 0
        rs_score = m1 * 0.4 + m3 * 0.35 + (m6 or 0) * 0.25
        scores.append({"symbol": sym, "rs_score": round(rs_score, 2), "m1": round(m1, 2), "m3": round(m3, 2), "m6": round(m6, 2)})
    scores.sort(key=lambda x: x["rs_score"], reverse=True)
    for i, s in enumerate(scores):
        s["rank"] = i + 1
        s["percentile"] = round((1 - i / max(len(scores) - 1, 1)) * 100, 1)
    return scores

# ---------------------------------------------------------------------------
# ADAPTIVE PARAMETERS (SELF-LEARNING)
# ---------------------------------------------------------------------------

def load_adaptive_params():
    path = os.path.join(DATA_DIR, "strategy_params.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {
        "rsi_overbought": 75,
        "rsi_oversold": 30,
        "rsi_buy_zone_upper": 50,
        "momentum_threshold": 0,
        "confidence_buy_threshold": 0.50,
        "confidence_short_threshold": 0.50,
        "position_size_multiplier": 1.0,
        "ma_fast": 50,
        "ma_slow": 200,
        "atr_risk_target_pct": 1.0,
        "trailing_stop_atr_mult": 2.5,
        "take_profit_atr_mult": 4.0,
        "regime_weight": 0.15,
        "rs_weight": 0.10,
        "volume_weight": 0.05,
        "macd_weight": 0.10,
        "bb_weight": 0.05,
        "win_rate_7d": 0.5,
        "win_rate_30d": 0.5,
        "avg_win_loss_ratio": 1.0,
        "last_updated": None
    }

def save_adaptive_params(params):
    params["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(os.path.join(DATA_DIR, "strategy_params.json"), "w") as f:
        json.dump(params, f, indent=2)

# ---------------------------------------------------------------------------
# ENHANCED SIGNAL GENERATION
# ---------------------------------------------------------------------------

def analyze_symbol_v2(bars, symbol, instrument_type, regime, rs_data, params):
    if not bars or len(bars) < 50:
        return {"symbol": symbol, "signal": "INSUFFICIENT_DATA", "reason": f"Only {len(bars)} bars"}

    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    volumes = [b["v"] for b in bars]

    price = closes[-1]
    ma_fast = sma(closes, params["ma_fast"])
    ma_slow = sma(closes, params["ma_slow"]) if len(closes) >= params["ma_slow"] else sma(closes, len(closes))
    rsi_val = rsi(closes)
    atr_val = atr(highs, lows, closes)
    atr_pct = average_true_range_pct(highs, lows, closes)
    mom_1m = momentum(closes, 21)
    mom_3m = momentum(closes, 63)
    mom_6m = momentum(closes, 126) if len(closes) >= 127 else None
    macd_line, macd_sig, macd_hist = macd(closes)
    bb_lower, bb_mid, bb_upper = bollinger_bands(closes)
    vol_trend = volume_trend(volumes)

    indicators = {
        "price": round(price, 4),
        "ma_fast": round(ma_fast, 4) if ma_fast else None,
        "ma_slow": round(ma_slow, 4) if ma_slow else None,
        "rsi14": round(rsi_val, 2) if rsi_val else None,
        "atr14": round(atr_val, 4) if atr_val else None,
        "atr_pct": round(atr_pct, 2) if atr_pct else None,
        "momentum_1m": round(mom_1m, 2) if mom_1m else None,
        "momentum_3m": round(mom_3m, 2) if mom_3m else None,
        "momentum_6m": round(mom_6m, 2) if mom_6m else None,
        "macd": round(macd_line, 4) if macd_line else None,
        "macd_signal": round(macd_sig, 4) if macd_sig else None,
        "macd_histogram": round(macd_hist, 4) if macd_hist else None,
        "bb_lower": round(bb_lower, 4) if bb_lower else None,
        "bb_upper": round(bb_upper, 4) if bb_upper else None,
        "volume_trend_pct": round(vol_trend, 2) if vol_trend else None,
        "avg_volume_20d": round(sum(volumes[-20:]) / min(20, len(volumes)), 0),
    }

    # --- MULTI-FACTOR SCORING ---
    score = 0.0
    reasons = []

    # 1) TREND (weight: 0.30)
    if ma_fast and ma_slow:
        if price > ma_fast and price > ma_slow:
            score += 0.30
            reasons.append(f"Uptrend: price above MA{params['ma_fast']} & MA{params['ma_slow']}")
        elif price < ma_fast and price < ma_slow:
            score -= 0.30
            reasons.append("Downtrend: price below both MAs")
        else:
            reasons.append("Mixed trend")

    # 2) MOMENTUM (weight: 0.25)
    mom_score = 0
    if mom_1m and mom_1m > 0: mom_score += 0.08
    if mom_3m and mom_3m > params["momentum_threshold"]: mom_score += 0.10
    if mom_6m and mom_6m > params["momentum_threshold"]: mom_score += 0.07
    if mom_1m and mom_1m < 0: mom_score -= 0.08
    if mom_3m and mom_3m < -params["momentum_threshold"]: mom_score -= 0.10
    if mom_6m and mom_6m is not None and mom_6m < -params["momentum_threshold"]: mom_score -= 0.07
    score += mom_score
    if mom_score > 0:
        reasons.append(f"Positive momentum (1M:{mom_1m:.1f}% 3M:{mom_3m:.1f}%)")
    elif mom_score < 0:
        reasons.append(f"Negative momentum (1M:{mom_1m:.1f}% 3M:{mom_3m:.1f}%)")

    # 3) RSI (weight: 0.15)
    if rsi_val:
        if rsi_val >= params["rsi_overbought"]:
            score -= 0.15
            reasons.append(f"RSI overbought ({rsi_val:.0f})")
        elif rsi_val <= params["rsi_oversold"]:
            score += 0.10
            reasons.append(f"RSI oversold ({rsi_val:.0f}) — potential bounce")
        elif rsi_val < params["rsi_buy_zone_upper"]:
            score += 0.10
            reasons.append(f"RSI in buy zone ({rsi_val:.0f})")
        else:
            score += 0.05
            reasons.append(f"RSI neutral ({rsi_val:.0f})")

    # 4) MACD (weight: 0.10)
    if macd_hist is not None:
        if macd_hist > 0 and macd_line and macd_line > 0:
            score += params["macd_weight"]
            reasons.append("MACD bullish")
        elif macd_hist < 0 and macd_line and macd_line < 0:
            score -= params["macd_weight"]
            reasons.append("MACD bearish")

    # 5) BOLLINGER BANDS (weight: 0.05)
    if bb_lower and bb_upper:
        if price < bb_lower:
            score += params["bb_weight"]
            reasons.append("Price below lower Bollinger Band — mean reversion opportunity")
        elif price > bb_upper:
            score -= params["bb_weight"]
            reasons.append("Price above upper Bollinger Band — stretched")

    # 6) VOLUME CONFIRMATION (weight: 0.05)
    if vol_trend is not None:
        if vol_trend > 20 and score > 0:
            score += params["volume_weight"]
            reasons.append(f"Volume surging +{vol_trend:.0f}% — confirms trend")
        elif vol_trend < -20 and score > 0:
            score -= 0.03
            reasons.append(f"Volume declining {vol_trend:.0f}% — weak confirmation")

    # 7) REGIME MODIFIER (weight: 0.15)
    regime_mod = regime_allocation_modifier(regime)
    if score > 0:
        score *= regime_mod["equity_mult"]
        if regime_mod["equity_mult"] != 1.0:
            reasons.append(f"Regime ({regime}) adjusting score x{regime_mod['equity_mult']}")
    elif score < 0:
        if regime in ("BEAR", "STRONG_BEAR"):
            score *= 1.2
            reasons.append("Bear regime amplifying short signal")

    # 8) RELATIVE STRENGTH BONUS (weight: 0.10)
    rs_entry = next((r for r in rs_data if r["symbol"] == symbol), None)
    if rs_entry:
        if rs_entry["percentile"] >= 80:
            score += params["rs_weight"]
            reasons.append(f"Top {100-rs_entry['percentile']:.0f}% relative strength (rank #{rs_entry['rank']})")
        elif rs_entry["percentile"] <= 20:
            score -= params["rs_weight"] * 0.5
            reasons.append(f"Bottom {rs_entry['percentile']:.0f}% relative strength")
        indicators["rs_rank"] = rs_entry["rank"]
        indicators["rs_percentile"] = rs_entry["percentile"]

    # 9) ADAPTIVE LEARNING ADJUSTMENT
    if params["win_rate_30d"] > 0.55:
        score *= 1.05
    elif params["win_rate_30d"] < 0.40:
        score *= 0.90

    # --- SIGNAL DETERMINATION ---
    signal = "HOLD"
    if score >= params["confidence_buy_threshold"]:
        signal = "BUY"
    elif score <= -params["confidence_short_threshold"] and instrument_type == "stock":
        signal = "SHORT"
    elif score <= -params["confidence_short_threshold"] and instrument_type != "stock":
        signal = "HOLD"

    # --- POSITION SIZING (Volatility-Adjusted) ---
    position_size_pct = None
    stop_loss_price = None
    take_profit_price = None
    trailing_stop_pct = None

    if atr_val and price > 0:
        risk_per_share = atr_val * params["trailing_stop_atr_mult"]
        risk_pct = risk_per_share / price
        if risk_pct > 0:
            raw_size = params["atr_risk_target_pct"] / (risk_pct * 100)
            position_size_pct = round(min(raw_size * params["position_size_multiplier"], 12.0), 2)

        if signal == "BUY":
            stop_loss_price = round(price - atr_val * params["trailing_stop_atr_mult"], 2)
            take_profit_price = round(price + atr_val * params["take_profit_atr_mult"], 2)
            trailing_stop_pct = round(atr_val * params["trailing_stop_atr_mult"] / price * 100, 2)
        elif signal == "SHORT":
            stop_loss_price = round(price + atr_val * params["trailing_stop_atr_mult"], 2)
            take_profit_price = round(price - atr_val * params["take_profit_atr_mult"], 2)
            trailing_stop_pct = round(atr_val * params["trailing_stop_atr_mult"] / price * 100, 2)

    return {
        "symbol": symbol,
        "instrument_type": instrument_type,
        "signal": signal,
        "score": round(score, 3),
        "reasons": reasons,
        "indicators": indicators,
        "risk_management": {
            "suggested_position_pct": position_size_pct,
            "stop_loss": stop_loss_price,
            "take_profit": take_profit_price,
            "trailing_stop_pct": trailing_stop_pct,
        },
    }

# ---------------------------------------------------------------------------
# MAIN ANALYSIS PIPELINE
# ---------------------------------------------------------------------------

def load_bars_file(filepath):
    with open(filepath) as f:
        data = json.load(f)
    return data.get("bars", data)

def run_full_analysis():
    params = load_adaptive_params()

    bar_files = {
        "core_equity.json":      ("etf",    ["SPY", "QQQ", "IWM", "DIA"]),
        "aggressive_growth.json":("stock",  ["NVDA", "TSLA", "META", "AMZN", "MSFT", "GOOGL", "AAPL"]),
        "sector_momentum.json":  ("etf",    ["XLK", "XLE", "XLF", "XLV", "XLY", "XLI"]),
        "crypto.json":           ("crypto", ["BTC/USD", "ETH/USD"]),
        "defensive.json":        ("etf",    ["SHY", "BIL", "TLT", "GLD"]),
    }

    all_bars = {}
    for fname, (itype, syms) in bar_files.items():
        fpath = os.path.join(DATA_DIR, fname)
        if not os.path.exists(fpath):
            continue
        data = load_bars_file(fpath)
        for s in syms:
            if s in data:
                all_bars[s] = data[s]

    # Detect market regime from SPY
    spy_closes = [b["c"] for b in all_bars.get("SPY", [])]
    regime = detect_regime(spy_closes)

    # Rank all symbols by relative strength
    rs_data = rank_by_relative_strength(all_bars)

    # Analyze each symbol
    signals = []
    for fname, (itype, syms) in bar_files.items():
        for s in syms:
            if s in all_bars:
                result = analyze_symbol_v2(all_bars[s], s, itype, regime, rs_data, params)
                signals.append(result)

    # Sort by absolute score descending (strongest signals first)
    signals.sort(key=lambda x: abs(x.get("score", 0)), reverse=True)

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market_regime": regime,
        "regime_modifiers": regime_allocation_modifier(regime),
        "relative_strength_ranking": rs_data,
        "adaptive_params": {
            "win_rate_30d": params["win_rate_30d"],
            "position_size_multiplier": params["position_size_multiplier"],
            "rsi_overbought": params["rsi_overbought"],
        },
        "signals": signals,
    }

    with open(os.path.join(DATA_DIR, "signals.json"), "w") as f:
        json.dump(output, f, indent=2)

    return output

if __name__ == "__main__":
    result = run_full_analysis()
    print(json.dumps(result, indent=2))
