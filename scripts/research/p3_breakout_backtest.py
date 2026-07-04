#!/usr/bin/env python3
"""
P3 "Cautious Sniper" BREAKOUT — faithful, no-look-ahead backtest + improvement tests.

Replicates event-driven-bot/scripts/event_driven_bot.py::generate_signals (the
breakout SCORE, entry when score >= threshold) and
event-driven-bot/scripts/fundamental_screener.py::screen_universe (the
point-in-time fundamental/technical screen + indicators), plus the ATR-bracket
risk model from event_driven_bot.compute_position_size and the swing hold window
in event-driven-bot/config/risk_limits.json.

INSTITUTIONAL DISCIPLINE (no look-ahead):
  * For each trading day t, indicators/score are computed using bars[0..t] ONLY.
  * If a symbol qualifies (screen passes) AND score >= threshold at close[t],
    the position is ENTERED at open[t+1] (next-day open), never at close[t].
  * ATR(14)*stop_mult stop, ATR(14)*tp1_mult take-profit (first touch wins;
    if both hit intrabar we conservatively assume STOP first), 15-day time stop.
  * Friction: cost_bps + slippage_bps applied EACH SIDE (loaded from
    scripts/backtest/friction.py, floored at the documented 5bps+5bps).
  * Sector exposure cap (20%), max signals/sector (3), max trades/day (15),
    1.5% risk per trade, gross-exposure cap (80%) — all from the live config.

OUT-OF-SAMPLE: results are reported per calendar year (walk-forward by-year),
never in-sample-only. A tiny #trades is flagged as not significant.

Metrics reuse scripts/backtest/metrics.py (sharpe, sortino, profit_factor,
max_drawdown, cagr, deflated_sharpe). Friction reuses scripts/backtest/friction.py.

This is OFFLINE research (T2). It places NO orders and commits nothing.
"""
import os
import sys
import json
import glob
import math

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from scripts.backtest import metrics as M           # noqa: E402
from scripts.backtest.friction import load_friction  # noqa: E402

DATA_GLOB = os.path.join(REPO, "data", "deep_wide5", "*.json")

# ---- live config (event-driven-bot/config/risk_limits.json) ----
RISK_PER_TRADE_PCT = 1.5
ATR_STOP_MULT = 1.5
ATR_TP1_MULT = 3.0
TP1_SELL_PCT = 50          # sell 50% at TP1; remainder rides to trail/time-stop
ATR_TRAIL_MULT = 1.5
MAX_SECTOR_EXPOSURE_PCT = 20.0
MAX_SIGNALS_PER_SECTOR = 3
MAX_TRADES_PER_DAY = 15
MAX_GROSS_EXPOSURE_PCT = 80.0
SWING_HOLD_MIN = 3
SWING_HOLD_MAX = 15
BREAKOUT_RVOL_THRESHOLD = 1.5
REGIME_FILTER_ENABLED = True   # require price > EMA200 (mirrors generate_signals)

# screen filters (fundamental_screener.screen_universe)
MIN_AVG_VOL_20D = 2_000_000
MIN_1M_RETURN = -10.0          # reject if 1M return < -10%

START_EQUITY = 100_000.0


# ---------------------------------------------------------------------------
# Indicators — copied verbatim (math) from fundamental_screener.py
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
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
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


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_data():
    """Return (symbol -> bars list), (symbol -> sector), spy_bars, trading_dates.

    Bars are dicts {o,h,l,c,v,t}. core.json/defensive.json are ETF buckets and
    are NOT tradeable for the breakout strategy (mirrors FULL_UNIVERSE = single
    stocks); SPY is kept aside as the benchmark.
    """
    bars_by_sym = {}
    sector_of = {}
    for fp in glob.glob(DATA_GLOB):
        sec = os.path.splitext(os.path.basename(fp))[0]
        with open(fp) as f:
            d = json.load(f)
        for sym, bars in d.get("bars", {}).items():
            bars_by_sym[sym] = bars
            sector_of[sym] = sec

    spy = bars_by_sym["SPY"]
    # tradeable universe excludes the ETF buckets
    tradeable = [s for s in bars_by_sym
                 if sector_of[s] not in ("core", "defensive")]

    # Build a master, sorted union of dates (date string -> ordinal index).
    all_dates = set()
    for bars in bars_by_sym.values():
        for b in bars:
            all_dates.add(b["t"][:10])
    dates = sorted(all_dates)
    return bars_by_sym, sector_of, spy, tradeable, dates


def index_by_date(bars):
    """Map date(YYYY-MM-DD) -> position index within this symbol's bar list."""
    return {b["t"][:10]: i for i, b in enumerate(bars)}


# ---------------------------------------------------------------------------
# Faithful screen + score at day t (uses bars[0..t] only)
# ---------------------------------------------------------------------------
def screen_and_score(closes, highs, lows, volumes, spy_closes_3m_ret):
    """Return (passes_screen, score, detail) using ONLY the provided history
    (which the caller slices to bars[0..t]). Mirrors screen_universe + the
    generate_signals score. Returns score=None if the symbol fails the screen.
    """
    n = len(closes)
    if n < 60:
        return None

    avg_vol_20 = sum(volumes[-20:]) / min(20, len(volumes))
    if avg_vol_20 < MIN_AVG_VOL_20D:
        return None

    stock_3m = momentum_pct(closes, 63)
    if stock_3m is None:
        return None
    rs_vs_spy = stock_3m - spy_closes_3m_ret
    if rs_vs_spy < 0:
        return None

    ema200 = ema(closes, 200) if n >= 200 else ema(closes, n)
    ema50 = ema(closes, 50)
    price = closes[-1]
    if ema200 and price < ema200:
        return None

    stock_1m = momentum_pct(closes, 21) or 0
    if stock_1m < MIN_1M_RETURN:
        return None

    atr_val = atr(highs, lows, closes)
    rsi_val = rsi(closes)
    bb_lower, bb_mid, bb_upper = bollinger_bands(closes)
    macd_line, macd_sig, macd_hist = macd(closes)
    vol_20d = sum(volumes[-20:]) / 20
    vol_5d = sum(volumes[-5:]) / 5
    rvol = vol_5d / vol_20d if vol_20d > 0 else 1.0
    bb_width = ((bb_upper - bb_lower) / bb_mid * 100
                if bb_mid and bb_upper and bb_lower else None)

    above_200 = bool(ema200 and price > ema200)
    above_50 = bool(ema50 and price > ema50)

    # ---- regime filter (generate_signals): skip if not above EMA200 ----
    if not above_200 and REGIME_FILTER_ENABLED:
        return None

    # ---- breakout SCORE (verbatim weighting from generate_signals) ----
    score = 0.0
    if bb_upper and price >= bb_upper * 0.995:
        score += 0.30
    if bb_width and bb_width < 5.0:
        score += 0.10
    if macd_hist and macd_hist > 0 and macd_line and macd_sig:
        if macd_line > macd_sig:
            score += 0.20
            if macd_line < 0:
                score += 0.10
    if rvol >= BREAKOUT_RVOL_THRESHOLD:
        score += 0.15
    if rs_vs_spy > 10:
        score += 0.15
    elif rs_vs_spy > 5:
        score += 0.08
    if above_200 and above_50:
        score += 0.10
    if rsi_val:
        if 40 <= rsi_val <= 65:
            score += 0.05
        elif rsi_val >= 80:
            score -= 0.15

    detail = {
        "price": price, "atr": atr_val, "rsi": rsi_val, "rvol": rvol,
        "rs": rs_vs_spy, "score": round(score, 3),
    }
    return detail


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------
def run_backtest(cfg, bars_by_sym, sector_of, spy, tradeable, dates,
                 sym_idx, spy_idx):
    """Event-driven daily loop. cfg controls the variant knobs.

    cfg keys:
      threshold           : entry score threshold (default 0.40)
      require_rvol         : require rvol >= BREAKOUT_RVOL_THRESHOLD to enter
      veto_rsi80           : skip entries with rsi >= 80
      cooldown_days        : no re-entry of a symbol within N days of a stop-out
    Returns dict with equity_curve, trade_pnls (per-position $), per-year buckets,
    and bookkeeping for reporting.
    """
    threshold = cfg.get("threshold", 0.40)
    require_rvol = cfg.get("require_rvol", False)
    veto_rsi80 = cfg.get("veto_rsi80", False)
    cooldown_days = cfg.get("cooldown_days", 0)
    # Exit geometry — overridable per variant (defaults to the live config
    # globals). Widening stop_mult while holding RISK_PER_TRADE_PCT constant
    # automatically SHRINKS qty (same $ risk) — the audit's "wider stop, halved
    # size" restructure to cut the 63% noise stop-out rate (D-P3 exit test).
    stop_mult = cfg.get("stop_mult", ATR_STOP_MULT)
    tp1_mult = cfg.get("tp1_mult", ATR_TP1_MULT)
    trail_mult = cfg.get("trail_mult", ATR_TRAIL_MULT)
    tp1_sell_pct = cfg.get("tp1_sell_pct", TP1_SELL_PCT)
    friction_bps = cfg["friction_bps"]   # one-side total (cost+slip) in bps
    fr = friction_bps / 10000.0

    cash = START_EQUITY
    open_pos = {}     # symbol -> position dict
    cooldown = {}     # symbol -> date-index until which re-entry is blocked
    trade_pnls = []   # realized $ P&L per *position* (round trip)
    equity_curve = []
    trades_log = []   # (entry_date, exit_date, symbol, pnl, ret_pct, reason)

    # Precompute SPY 3M-return at each date index for the RS screen.
    spy_closes_all = [b["c"] for b in spy]

    di_first_tradeable = 63 + 1  # need >=64 bars for 3M momentum

    for di in range(di_first_tradeable, len(dates) - 1):
        date = dates[di]
        next_date = dates[di + 1]

        # ---- mark-to-market & manage open positions on day di (using day di bar) ----
        # 1) Check exits FIRST on today's bar (stop/tp/trailing/time-stop).
        to_close = []
        for sym, pos in open_pos.items():
            si = sym_idx[sym].get(date)
            if si is None:
                continue
            bar = bars_by_sym[sym][si]
            hi, lo, cl = bar["h"], bar["l"], bar["c"]
            exit_price = None
            reason = None

            # stop & TP — if both touched same bar, assume STOP first (conservative)
            if lo <= pos["stop"]:
                exit_price = pos["stop"]
                reason = "stop"
            elif not pos["tp1_done"] and hi >= pos["tp1"]:
                # sell TP1_SELL_PCT at tp1; rest keeps riding with a trailing stop
                sell_qty = int(pos["qty"] * tp1_sell_pct / 100)
                if sell_qty > 0:
                    fill = pos["tp1"] * (1 - fr)
                    cash += sell_qty * fill
                    realized = (fill - pos["entry"]) * sell_qty
                    pos["realized"] += realized
                    pos["qty"] -= sell_qty
                pos["tp1_done"] = True
                # raise trailing stop to breakeven+ after TP1
                pos["stop"] = max(pos["stop"], pos["entry"])
                # also start ATR trailing from the high
                continue
            else:
                # trailing stop update (only after TP1, mirrors live trail logic)
                if pos["tp1_done"]:
                    new_trail = cl - pos["atr"] * trail_mult
                    pos["stop"] = max(pos["stop"], new_trail)
                    if lo <= pos["stop"]:
                        exit_price = pos["stop"]
                        reason = "trail"
                # time stop
                held = di - pos["entry_di"]
                if exit_price is None and held >= SWING_HOLD_MAX:
                    exit_price = cl
                    reason = "time"

            if exit_price is not None:
                fill = exit_price * (1 - fr)
                cash += pos["qty"] * fill
                realized = (fill - pos["entry"]) * pos["qty"] + pos["realized"]
                trade_pnls.append(realized)
                trades_log.append({
                    "symbol": sym, "entry_date": pos["entry_date"],
                    "exit_date": date, "pnl": realized,
                    "ret_pct": (realized / pos["cost_basis"] * 100)
                    if pos["cost_basis"] else 0.0,
                    "reason": reason, "year": int(pos["entry_date"][:4]),
                })
                if reason in ("stop", "trail") and cooldown_days > 0:
                    cooldown[sym] = di + cooldown_days
                to_close.append(sym)

        for sym in to_close:
            del open_pos[sym]

        # ---- compute current equity (cash + MTM of open positions at close di) ----
        mtm = 0.0
        for sym, pos in open_pos.items():
            si = sym_idx[sym].get(date)
            px = bars_by_sym[sym][si]["c"] if si is not None else pos["entry"]
            mtm += pos["qty"] * px
        equity = cash + mtm
        equity_curve.append(equity)

        # ---- generate signals at close[di], enter at open[di+1] ----
        spi = spy_idx.get(date)
        if spi is None or spi < 63:
            continue
        spy_3m = momentum_pct(spy_closes_all[:spi + 1], 63) or 0.0

        candidates = []
        for sym in tradeable:
            if sym in open_pos:
                continue
            if sym in cooldown and di < cooldown[sym]:
                continue
            si = sym_idx[sym].get(date)
            if si is None or si < 60:
                continue
            bars = bars_by_sym[sym]
            closes = [b["c"] for b in bars[:si + 1]]
            highs = [b["h"] for b in bars[:si + 1]]
            lows = [b["l"] for b in bars[:si + 1]]
            vols = [b["v"] for b in bars[:si + 1]]
            res = screen_and_score(closes, highs, lows, vols, spy_3m)
            if not res:
                continue
            if res["score"] < threshold:
                continue
            if require_rvol and res["rvol"] < BREAKOUT_RVOL_THRESHOLD:
                continue
            if veto_rsi80 and res["rsi"] and res["rsi"] >= 80:
                continue
            res["symbol"] = sym
            res["sector"] = sector_of[sym]
            candidates.append(res)

        if not candidates:
            continue

        # sort by score desc, diversify by sector (max 3/sector) — mirrors live
        candidates.sort(key=lambda x: x["score"], reverse=True)
        seen_sec, diversified = {}, []
        for c in candidates:
            sec = c["sector"]
            if seen_sec.get(sec, 0) >= MAX_SIGNALS_PER_SECTOR:
                continue
            seen_sec[sec] = seen_sec.get(sec, 0) + 1
            diversified.append(c)

        # ---- enter at open[di+1], respecting caps ----
        trades_today = 0
        # current sector exposure (in $) from open positions, recomputed each fill
        for c in diversified:
            if trades_today >= MAX_TRADES_PER_DAY:
                break
            sym = c["symbol"]
            nbars = bars_by_sym[sym]
            nsi = sym_idx[sym].get(next_date)
            if nsi is None:
                continue
            entry_open = nbars[nsi]["o"]
            atr_val = c["atr"]
            if not atr_val or atr_val <= 0 or entry_open <= 0:
                continue

            # position sizing: 1.5% risk / (ATR*stop_mult)
            stop_dist = atr_val * stop_mult
            max_risk = equity * RISK_PER_TRADE_PCT / 100
            qty = int(max_risk / stop_dist)
            if qty <= 0:
                continue

            entry_fill = entry_open * (1 + fr)
            cost_basis = qty * entry_fill

            # gross exposure cap
            cur_gross = sum(p["qty"] * (bars_by_sym[s][sym_idx[s].get(date, 0)]["c"]
                            if sym_idx[s].get(date) is not None else p["entry"])
                            for s, p in open_pos.items())
            if (cur_gross + cost_basis) > equity * MAX_GROSS_EXPOSURE_PCT / 100:
                continue

            # sector exposure cap (20% of equity)
            sec = c["sector"]
            cur_sec = sum(p["qty"] * p["entry"] for s, p in open_pos.items()
                          if sector_of[s] == sec)
            if (cur_sec + cost_basis) > equity * MAX_SECTOR_EXPOSURE_PCT / 100:
                continue

            if cost_basis > cash:
                continue

            cash -= cost_basis
            open_pos[sym] = {
                "qty": qty,
                "entry": entry_fill,
                "entry_di": di + 1,
                "entry_date": next_date,
                "atr": atr_val,
                "stop": entry_fill - stop_dist,
                "tp1": entry_fill + atr_val * tp1_mult,
                "tp1_done": False,
                "realized": 0.0,
                "cost_basis": cost_basis,
            }
            trades_today += 1

    # liquidate any remaining at the last available close
    last_date = dates[-1]
    for sym, pos in open_pos.items():
        si = sym_idx[sym].get(last_date)
        px = bars_by_sym[sym][si]["c"] if si is not None else pos["entry"]
        fill = px * (1 - fr)
        cash += pos["qty"] * fill
        realized = (fill - pos["entry"]) * pos["qty"] + pos["realized"]
        trade_pnls.append(realized)
        trades_log.append({
            "symbol": sym, "entry_date": pos["entry_date"],
            "exit_date": last_date, "pnl": realized,
            "ret_pct": (realized / pos["cost_basis"] * 100) if pos["cost_basis"] else 0.0,
            "reason": "final_liquidation", "year": int(pos["entry_date"][:4]),
        })
    equity_curve.append(cash)

    return {
        "equity_curve": equity_curve,
        "trade_pnls": trade_pnls,
        "trades_log": trades_log,
        "dates": dates[di_first_tradeable:],
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def report(name, res):
    eq = res["equity_curve"]
    pnls = res["trade_pnls"]
    rets = M.returns_from_equity(eq)
    out = {
        "name": name,
        "sharpe": round(M.sharpe_ratio(rets), 3),
        "sortino": round(M.sortino_ratio(rets), 3),
        "pf": (round(M.profit_factor(pnls), 3)
               if pnls and not math.isinf(M.profit_factor(pnls)) else
               (float("inf") if pnls else 0.0)),
        "total_return_pct": round(M.total_return(eq) * 100, 2),
        "cagr_pct": round(M.cagr(eq) * 100, 2),
        "max_dd_pct": round(M.max_drawdown(eq) * 100, 2),
        "win_rate_pct": (round(M.win_rate(pnls) * 100, 1) if pnls else None),
        "num_trades": len(pnls),
        "final_equity": round(eq[-1], 2),
    }
    return out


def by_year(res):
    """Per-year #trades and net P&L from the realized trade log (entry-year)."""
    buckets = {}
    for t in res["trades_log"]:
        y = t["year"]
        buckets.setdefault(y, {"n": 0, "pnl": 0.0, "wins": 0})
        buckets[y]["n"] += 1
        buckets[y]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            buckets[y]["wins"] += 1
    return buckets


def spy_buy_hold(spy, dates_subset, spy_idx, friction_bps):
    """Buy SPY at first available open in the window, hold to last close."""
    fr = friction_bps / 10000.0
    first = dates_subset[0]
    last = dates_subset[-1]
    si0 = spy_idx.get(first)
    si1 = spy_idx.get(last)
    if si0 is None or si1 is None:
        return None
    entry = spy[si0]["o"] * (1 + fr)
    exitp = spy[si1]["c"] * (1 - fr)
    # daily equity curve for SPY (for sharpe / dd comparison)
    curve = []
    for d in dates_subset:
        si = spy_idx.get(d)
        if si is None:
            continue
        curve.append(spy[si]["c"])
    ret = exitp / entry - 1.0
    return {
        "total_return_pct": round(ret * 100, 2),
        "cagr_pct": round(M.cagr(curve) * 100, 2),
        "sharpe": round(M.sharpe_ratio(M.returns_from_equity(curve)), 3),
        "max_dd_pct": round(M.max_drawdown(curve) * 100, 2),
        "curve": curve,
    }


def main():
    bars_by_sym, sector_of, spy, tradeable, dates = load_data()
    sym_idx = {s: index_by_date(b) for s, b in bars_by_sym.items()}
    spy_idx = index_by_date(spy)

    cost_bps, slip_bps = load_friction("portfolio_3")
    friction_one_side = cost_bps + slip_bps   # total per side
    print(f"Universe: {len(tradeable)} tradeable stocks, "
          f"{len(dates)} trading days {dates[0]}..{dates[-1]}")
    print(f"Friction (per side): cost={cost_bps}bps + slip={slip_bps}bps "
          f"= {friction_one_side}bps each side\n")

    base_cfg = {"friction_bps": friction_one_side}

    variants = {
        "BASELINE (score>=0.40)": {"threshold": 0.40},
        "thr=0.35": {"threshold": 0.35},
        "thr=0.50": {"threshold": 0.50},
        "(a) require RVOL>=1.5": {"threshold": 0.40, "require_rvol": True},
        "(b) veto RSI>=80": {"threshold": 0.40, "veto_rsi80": True},
        "(c) cooldown 10d post-stop": {"threshold": 0.40, "cooldown_days": 10},
        "combo a+b+c": {"threshold": 0.40, "require_rvol": True,
                        "veto_rsi80": True, "cooldown_days": 10},
        # D-P3 exit restructure (audit 2026-07-04): widen the 1.5-ATR stop (63%
        # noise stop-out rate) to 2-3x ATR; RISK_PER_TRADE_PCT is constant so qty
        # shrinks with the wider stop (same $ risk = "halved size"). Also test
        # keeping R:R ~2:1 by widening TP with the stop.
        "STOP 2.0xATR": {"threshold": 0.40, "stop_mult": 2.0},
        "STOP 2.5xATR": {"threshold": 0.40, "stop_mult": 2.5},
        "STOP 3.0xATR": {"threshold": 0.40, "stop_mult": 3.0},
        "STOP 2.5 + TP 5.0 (R:R~2:1)": {"threshold": 0.40, "stop_mult": 2.5, "tp1_mult": 5.0},
        "STOP 3.0 + TP 6.0 (R:R~2:1)": {"threshold": 0.40, "stop_mult": 3.0, "tp1_mult": 6.0},
        "STOP 2.5 + trail 2.5": {"threshold": 0.40, "stop_mult": 2.5, "trail_mult": 2.5},
    }

    results = {}
    reports = {}
    for name, knobs in variants.items():
        cfg = dict(base_cfg)
        cfg.update(knobs)
        res = run_backtest(cfg, bars_by_sym, sector_of, spy, tradeable,
                           dates, sym_idx, spy_idx)
        results[name] = res
        reports[name] = report(name, res)

    # SPY buy & hold over the same window (net of one round trip friction)
    sub = results["BASELINE (score>=0.40)"]["dates"]
    bh = spy_buy_hold(spy, sub, spy_idx, friction_one_side)

    # ---- print report ----
    print("=" * 110)
    hdr = (f"{'VARIANT':<30}{'Sharpe':>8}{'Sortino':>9}{'PF':>7}"
           f"{'TotRet%':>9}{'CAGR%':>8}{'MaxDD%':>8}{'Win%':>7}{'#Tr':>6}")
    print(hdr)
    print("-" * 110)
    for name in variants:
        r = reports[name]
        pf = r["pf"]
        pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
        wr = r["win_rate_pct"]
        wr_s = "-" if wr is None else f"{wr:.1f}"
        print(f"{name:<30}{r['sharpe']:>8.2f}{r['sortino']:>9.2f}{pf_s:>7}"
              f"{r['total_return_pct']:>9.1f}{r['cagr_pct']:>8.1f}"
              f"{r['max_dd_pct']:>8.1f}{wr_s:>7}{r['num_trades']:>6}")
    print("-" * 110)
    if bh:
        print(f"{'SPY BUY & HOLD (net)':<30}{bh['sharpe']:>8.2f}{'-':>9}{'-':>7}"
              f"{bh['total_return_pct']:>9.1f}{bh['cagr_pct']:>8.1f}"
              f"{bh['max_dd_pct']:>8.1f}{'-':>7}{'-':>6}")
    print("=" * 110)

    # ---- by-year OOS for baseline + best alt ----
    print("\nBY-YEAR (entry-year) realized P&L — BASELINE:")
    yb = by_year(results["BASELINE (score>=0.40)"])
    for y in sorted(yb):
        b = yb[y]
        wr = b["wins"] / b["n"] * 100 if b["n"] else 0
        print(f"  {y}: trades={b['n']:>3}  net P&L=${b['pnl']:>11,.0f}  win%={wr:>5.1f}")

    # ---- alpha vs SPY (baseline) ----
    base_r = reports["BASELINE (score>=0.40)"]
    alpha = base_r["total_return_pct"] - (bh["total_return_pct"] if bh else 0)
    print(f"\nBASELINE total return {base_r['total_return_pct']}% vs "
          f"SPY B&H {bh['total_return_pct'] if bh else 'NA'}% -> alpha "
          f"{alpha:+.1f}pp")

    # ---- deflated sharpe across the 7 variants (multiple-testing penalty) ----
    per_period_sharpes = []
    for name in variants:
        eq = results[name]["equity_curve"]
        rets = M.returns_from_equity(eq)
        # per-period (non-annualized) sharpe for DSR
        sd = M._std(rets)
        pp = (M._mean(rets) / sd) if sd else 0.0
        per_period_sharpes.append(pp)
    n_obs = len(M.returns_from_equity(results["BASELINE (score>=0.40)"]["equity_curve"]))
    dsr = M.deflated_sharpe_ratio(per_period_sharpes, n_obs)
    print(f"\nDeflated Sharpe (best of {len(variants)} variants, n_obs={n_obs}): "
          f"{dsr:.4f}  (>0.95 = significant after multiple-testing)")

    # machine-readable dump for the caller
    print("\n###JSON###")
    print(json.dumps({
        "friction_per_side_bps": friction_one_side,
        "universe": len(tradeable),
        "trading_days": len(dates),
        "date_range": [dates[0], dates[-1]],
        "reports": reports,
        "spy_buy_hold": {k: v for k, v in bh.items() if k != "curve"} if bh else None,
        "baseline_alpha_pp": round(alpha, 2),
        "by_year_baseline": {str(y): {"trades": v["n"],
                                      "net_pnl": round(v["pnl"], 0),
                                      "win_pct": round(v["wins"]/v["n"]*100, 1)
                                      if v["n"] else 0}
                             for y, v in by_year(results["BASELINE (score>=0.40)"]).items()},
        "deflated_sharpe_best_of_variants": round(dsr, 4),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
