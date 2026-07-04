#!/usr/bin/env python3
"""Concentrated cross-sectional momentum selector — the reusable engine for a
high-return PAPER sleeve (audit 2026-07-04, high-return research).

WHY THIS EXISTS: the client asked for the highest-return strategy. A 5y backtest
(scripts/research/high_return_backtest.py) plus independent research converged on
concentrated cross-sectional momentum (hold the top-K highest 12-1-momentum
large-caps, monthly rebalance) as the strongest candidate. HONEST CAVEAT baked in
here so nobody over-sizes it: the 24% backtest CAGR is SURVIVORSHIP-INFLATED
(delisted names excluded); realistic live CAGR is ~12-16% with -40..-80% tail
drawdowns in a momentum crash. PAPER-ONLY until it earns a live track record.

This module is PURE (stdlib only) and is NOT imported by the autonomous trading
path — it is a ready-to-wire building block. Weights never breach a max-weight
cap, so output is always compatible with the hardcoded 8% single-name limit.
"""
import math


def momentum_score(closes, lookback=252, skip=21):
    """12-1 momentum: return from t-(lookback+skip) to t-skip (skip the most
    recent ~month to avoid short-term reversal). None if not enough history."""
    need = lookback + skip + 1
    if not closes or len(closes) < need:
        return None
    recent = closes[-1 - skip]
    past = closes[-1 - skip - lookback]
    if not past or past <= 0 or not recent or recent <= 0:
        return None
    return recent / past - 1.0


def market_trend_ok(market_closes, n=200):
    """Absolute-momentum gate: is the market above its n-day SMA? The research is
    clear this is a DRAWDOWN reducer (whipsaw-prone), not a return booster — so it
    is OPTIONAL and off by default in the selector. None-safe -> True (fail-open to
    'risk on' only when data is missing; callers can choose stricter)."""
    if not market_closes or len(market_closes) < n:
        return True
    sma = sum(market_closes[-n:]) / n
    return market_closes[-1] > sma


def select_top_momentum(closes_by_sym, k=13, max_weight=0.08, lookback=252,
                        skip=21, exclude=None, market_closes=None, use_trend=False,
                        sector_map=None, max_per_sector=None):
    """Equal-weight target for the top-K momentum names.

    Returns ``{symbol: weight}``. Guarantees every weight <= ``max_weight`` (so it
    can never breach the 8% single-name cap): the effective K is raised to at least
    ceil(1/max_weight) if the caller asks for fewer names. Ties broken by symbol.

    ``use_trend`` — gate on the market's 200-day trend. FAILS SAFE: if the trend
    can't be confirmed (market data missing/short), returns ``{}`` (cash), so a
    data glitch can never silently disable the crash filter (audit 2026-07-04).

    ``max_per_sector`` (with ``sector_map`` {sym: sector}) — caps how many names
    ONE sector can contribute, so the book can't go ~55% into a single industry
    (the semiconductor-bubble concentration the research flagged).
    """
    exclude = set(exclude or ())
    if use_trend:
        # fail SAFE: unconfirmable trend -> cash, never fail-open to risk-on.
        if not market_closes or len(market_closes) < 200 or not market_trend_ok(market_closes):
            return {}

    min_k = math.ceil(1.0 / max_weight)          # 8% cap -> >=13 names
    k = max(int(k), min_k)
    sector_map = sector_map or {}

    scored = []
    for sym, closes in closes_by_sym.items():
        if sym in exclude:
            continue
        m = momentum_score(closes, lookback, skip)
        if m is not None:
            scored.append((m, sym))
    if not scored:
        return {}
    scored.sort(key=lambda x: (-x[0], x[1]))     # momentum desc, symbol asc

    picks, sec_count = [], {}
    for _, sym in scored:
        if len(picks) >= k:
            break
        sec = sector_map.get(sym, sym)           # unknown sector -> its own bucket
        if max_per_sector and sec_count.get(sec, 0) >= max_per_sector:
            continue                             # sector full -> skip to next name
        picks.append(sym)
        sec_count[sec] = sec_count.get(sec, 0) + 1
    if not picks:
        return {}
    w = min(1.0 / len(picks), max_weight)        # never exceed the cap
    return {s: round(w, 6) for s in picks}
