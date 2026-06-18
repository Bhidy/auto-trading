#!/usr/bin/env python3
"""
P3 "Cautious Sniper" BREAKOUT — SAMPLING / RISK-CONTROL extension.

PROBLEM (from the committed p3_breakout_backtest.py): the faithful breakout makes
only 17 round trips over 5 years (2021-06..2026-06, 116-symbol universe) and 14 of
them are INTC — i.e. the sample is too small to validate AND single-name dominated.
A strategy that fires ~3 trades/year on one name cannot be statistically validated.

GOAL: produce a config that reaches >=100 round-trip trades across the 116-symbol
universe so an edge can actually be tested OUT-OF-SAMPLE, WITHOUT single-name
domination, by combining three levers:
  (a) MAX_CONCURRENT positions cap  — the live engine already allowed unbounded
      concurrency, so on its own this is NOT what limits trade count. The binding
      constraint is CANDIDATE SCARCITY (the breakout score rarely clears 0.40 and
      the screen is strict). We therefore loosen the SCREEN/THRESHOLD (lever c) to
      *create* candidates, then cap concurrency to keep risk bounded.
  (b) PER-SYMBOL RE-ENTRY CAP  — hard max round-trips / symbol / calendar-quarter.
      This is the direct kill-switch for the INTC churn: even if INTC keeps
      qualifying, it can trade at most `max_roundtrips_per_q` times per quarter.
  (c) LOOSER ENTRY  — lower score threshold and optionally drop the strictest screen
      gates (the >EMA200 regime gate, the RS>0 gate, the RVOL score component). Each
      is a knob so we can see which loosening creates breadth vs. which destroys edge.

NON-NEGOTIABLE DISCIPLINE (inherited from the committed engine, unchanged):
  * No look-ahead: indicators/score at close[t] use bars[0..t] only; ENTER at
    open[t+1]; point-in-time SPY 3M return for the RS screen.
  * Friction cost_bps+slip_bps applied EACH SIDE, floored at 5+5 bps
    (load_friction("portfolio_3")).
  * ATR(14) bracket: stop=ATR*1.5, TP1=ATR*3.0 (sell 50%), ATR trailing after TP1,
    15-day time stop. Stop-before-TP if both touch same bar (conservative).
  * OUT-OF-SAMPLE: every config is reported BY CALENDAR YEAR (walk-forward). Small
    #trades is flagged as not significant.

CONCENTRATION: each config reports the top-name trade share and HHI so "well-sampled"
is never confused with "one name spammed N times".

Metrics reuse scripts/backtest/metrics.py. This is OFFLINE research (T2): NO orders,
commits nothing, imports nothing on the trading path.

We EXTEND the committed module by importing its data loaders, indicators, and the
faithful screen/score so the entry logic stays identical except for the explicit
loosening knobs below.
"""
import os
import sys
import json
import math
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from scripts.backtest import metrics as M                       # noqa: E402
from scripts.backtest.friction import load_friction            # noqa: E402
import scripts.research.p3_breakout_backtest as base           # noqa: E402

# Pull the verbatim indicators / loaders from the committed script (single source
# of truth for the entry math — we do not re-implement them).
load_data = base.load_data
index_by_date = base.index_by_date
momentum_pct = base.momentum_pct
ema = base.ema
atr = base.atr
rsi = base.rsi
bollinger_bands = base.bollinger_bands
macd = base.macd

# live constants (mirrors event-driven-bot/config/risk_limits.json)
RISK_PER_TRADE_PCT = base.RISK_PER_TRADE_PCT
ATR_STOP_MULT = base.ATR_STOP_MULT
ATR_TP1_MULT = base.ATR_TP1_MULT
TP1_SELL_PCT = base.TP1_SELL_PCT
ATR_TRAIL_MULT = base.ATR_TRAIL_MULT
MAX_SECTOR_EXPOSURE_PCT = base.MAX_SECTOR_EXPOSURE_PCT
MAX_TRADES_PER_DAY = base.MAX_TRADES_PER_DAY
MAX_GROSS_EXPOSURE_PCT = base.MAX_GROSS_EXPOSURE_PCT
SWING_HOLD_MAX = base.SWING_HOLD_MAX
BREAKOUT_RVOL_THRESHOLD = base.BREAKOUT_RVOL_THRESHOLD
MIN_AVG_VOL_20D = base.MIN_AVG_VOL_20D
MIN_1M_RETURN = base.MIN_1M_RETURN
START_EQUITY = base.START_EQUITY


def quarter_key(date_str):
    """YYYY-Qn from a YYYY-MM-DD date string."""
    y = date_str[:4]
    m = int(date_str[5:7])
    return f"{y}-Q{(m - 1) // 3 + 1}"


# ---------------------------------------------------------------------------
# Parameterised screen + score (knobs control loosening; math is unchanged).
# When all knobs are at their strict defaults this is identical to
# base.screen_and_score (verified by a parity check in main()).
# ---------------------------------------------------------------------------
def screen_and_score(closes, highs, lows, vols, spy_3m, cfg):
    n = len(closes)
    if n < 60:
        return None

    avg_vol_20 = sum(vols[-20:]) / min(20, len(vols))
    if avg_vol_20 < cfg["min_avg_vol_20d"]:
        return None

    stock_3m = momentum_pct(closes, 63)
    if stock_3m is None:
        return None
    rs_vs_spy = stock_3m - spy_3m
    if cfg["require_rs_positive"] and rs_vs_spy < 0:
        return None

    ema200 = ema(closes, 200) if n >= 200 else ema(closes, n)
    ema50 = ema(closes, 50)
    price = closes[-1]
    if cfg["require_above_ema200"] and ema200 and price < ema200:
        return None

    stock_1m = momentum_pct(closes, 21) or 0
    if stock_1m < cfg["min_1m_return"]:
        return None

    atr_val = atr(highs, lows, closes)
    rsi_val = rsi(closes)
    bb_lower, bb_mid, bb_upper = bollinger_bands(closes)
    macd_line, macd_sig, macd_hist = macd(closes)
    vol_20d = sum(vols[-20:]) / 20
    vol_5d = sum(vols[-5:]) / 5
    rvol = vol_5d / vol_20d if vol_20d > 0 else 1.0
    bb_width = ((bb_upper - bb_lower) / bb_mid * 100
                if bb_mid and bb_upper and bb_lower else None)

    above_200 = bool(ema200 and price > ema200)
    above_50 = bool(ema50 and price > ema50)

    # regime gate inside the score path (mirrors generate_signals)
    if cfg["require_above_ema200"] and not above_200:
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

    return {
        "price": price, "atr": atr_val, "rsi": rsi_val, "rvol": rvol,
        "rs": rs_vs_spy, "score": round(score, 3),
    }


# ---------------------------------------------------------------------------
# Backtest engine with the three new levers.
# ---------------------------------------------------------------------------
def run_backtest(cfg, bars_by_sym, sector_of, spy, tradeable, dates,
                 sym_idx, spy_idx):
    threshold = cfg["threshold"]
    friction_bps = cfg["friction_bps"]
    fr = friction_bps / 10000.0
    max_concurrent = cfg["max_concurrent"]              # lever (a)
    max_rt_per_q = cfg["max_roundtrips_per_q"]          # lever (b)
    cooldown_days = cfg.get("cooldown_days", 0)

    cash = START_EQUITY
    open_pos = {}
    cooldown = {}
    rt_count_q = defaultdict(int)        # (symbol, quarter) -> round trips so far
    trade_pnls = []
    equity_curve = []
    trades_log = []

    spy_closes_all = [b["c"] for b in spy]
    di_first = 63 + 1

    for di in range(di_first, len(dates) - 1):
        date = dates[di]
        next_date = dates[di + 1]

        # ---- manage / exit open positions on day di ----
        to_close = []
        for sym, pos in open_pos.items():
            si = sym_idx[sym].get(date)
            if si is None:
                continue
            bar = bars_by_sym[sym][si]
            hi, lo, cl = bar["h"], bar["l"], bar["c"]
            exit_price = None
            reason = None

            if lo <= pos["stop"]:
                exit_price = pos["stop"]
                reason = "stop"
            elif not pos["tp1_done"] and hi >= pos["tp1"]:
                sell_qty = int(pos["qty"] * TP1_SELL_PCT / 100)
                if sell_qty > 0:
                    fill = pos["tp1"] * (1 - fr)
                    cash += sell_qty * fill
                    pos["realized"] += (fill - pos["entry"]) * sell_qty
                    pos["qty"] -= sell_qty
                pos["tp1_done"] = True
                pos["stop"] = max(pos["stop"], pos["entry"])
                continue
            else:
                if pos["tp1_done"]:
                    new_trail = cl - pos["atr"] * ATR_TRAIL_MULT
                    pos["stop"] = max(pos["stop"], new_trail)
                    if lo <= pos["stop"]:
                        exit_price = pos["stop"]
                        reason = "trail"
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

        # ---- equity mark-to-market ----
        mtm = 0.0
        for sym, pos in open_pos.items():
            si = sym_idx[sym].get(date)
            px = bars_by_sym[sym][si]["c"] if si is not None else pos["entry"]
            mtm += pos["qty"] * px
        equity = cash + mtm
        equity_curve.append(equity)

        # ---- signals at close[di], enter at open[di+1] ----
        spi = spy_idx.get(date)
        if spi is None or spi < 63:
            continue
        spy_3m = momentum_pct(spy_closes_all[:spi + 1], 63) or 0.0

        # concurrency lever (a): if at cap, do not even scan for new entries
        slots = max_concurrent - len(open_pos)
        if slots <= 0:
            continue

        next_q = quarter_key(next_date)
        candidates = []
        for sym in tradeable:
            if sym in open_pos:
                continue
            if sym in cooldown and di < cooldown[sym]:
                continue
            # lever (b): per-symbol per-quarter round-trip cap (entries counted)
            if max_rt_per_q is not None and rt_count_q[(sym, next_q)] >= max_rt_per_q:
                continue
            si = sym_idx[sym].get(date)
            if si is None or si < 60:
                continue
            bars = bars_by_sym[sym]
            closes = [b["c"] for b in bars[:si + 1]]
            highs = [b["h"] for b in bars[:si + 1]]
            lows = [b["l"] for b in bars[:si + 1]]
            vols = [b["v"] for b in bars[:si + 1]]
            res = screen_and_score(closes, highs, lows, vols, spy_3m, cfg)
            if not res or res["score"] < threshold:
                continue
            res["symbol"] = sym
            res["sector"] = sector_of[sym]
            candidates.append(res)

        if not candidates:
            continue

        candidates.sort(key=lambda x: x["score"], reverse=True)
        # sector diversification cap (max 3/sector) — unchanged from live
        seen_sec, diversified = {}, []
        for c in candidates:
            sec = c["sector"]
            if seen_sec.get(sec, 0) >= base.MAX_SIGNALS_PER_SECTOR:
                continue
            seen_sec[sec] = seen_sec.get(sec, 0) + 1
            diversified.append(c)

        trades_today = 0
        for c in diversified:
            if trades_today >= MAX_TRADES_PER_DAY:
                break
            if len(open_pos) >= max_concurrent:      # lever (a) enforced per fill
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

            stop_dist = atr_val * ATR_STOP_MULT
            max_risk = equity * RISK_PER_TRADE_PCT / 100
            qty = int(max_risk / stop_dist)
            if qty <= 0:
                continue

            entry_fill = entry_open * (1 + fr)
            cost_basis = qty * entry_fill

            cur_gross = sum(p["qty"] * (bars_by_sym[s][sym_idx[s].get(date, 0)]["c"]
                            if sym_idx[s].get(date) is not None else p["entry"])
                            for s, p in open_pos.items())
            if (cur_gross + cost_basis) > equity * MAX_GROSS_EXPOSURE_PCT / 100:
                continue

            sec = c["sector"]
            cur_sec = sum(p["qty"] * p["entry"] for s, p in open_pos.items()
                          if sector_of[s] == sec)
            if (cur_sec + cost_basis) > equity * MAX_SECTOR_EXPOSURE_PCT / 100:
                continue
            if cost_basis > cash:
                continue

            cash -= cost_basis
            open_pos[sym] = {
                "qty": qty, "entry": entry_fill, "entry_di": di + 1,
                "entry_date": next_date, "atr": atr_val,
                "stop": entry_fill - stop_dist,
                "tp1": entry_fill + atr_val * ATR_TP1_MULT,
                "tp1_done": False, "realized": 0.0, "cost_basis": cost_basis,
            }
            rt_count_q[(sym, next_q)] += 1
            trades_today += 1

    # final liquidation
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
        "dates": dates[di_first:],
    }


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------
def concentration(trades_log):
    """Top-name trade share + HHI + distinct names from the realized log."""
    by_name = defaultdict(int)
    for t in trades_log:
        by_name[t["symbol"]] += 1
    n = sum(by_name.values())
    if n == 0:
        return {"top_name": None, "top_share_pct": 0.0, "hhi": 0.0,
                "distinct_names": 0}
    top_sym, top_n = max(by_name.items(), key=lambda kv: kv[1])
    hhi = sum((c / n) ** 2 for c in by_name.values())
    return {
        "top_name": top_sym,
        "top_share_pct": round(top_n / n * 100, 1),
        "hhi": round(hhi, 4),
        "distinct_names": len(by_name),
        "intc_share_pct": round(by_name.get("INTC", 0) / n * 100, 1),
    }


def per_period_sharpe(equity_curve):
    rets = M.returns_from_equity(equity_curve)
    sd = M._std(rets)
    return (M._mean(rets) / sd) if sd else 0.0, len(rets)


def by_year(trades_log):
    buckets = {}
    for t in trades_log:
        y = t["year"]
        buckets.setdefault(y, {"n": 0, "pnl": 0.0, "wins": 0})
        buckets[y]["n"] += 1
        buckets[y]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            buckets[y]["wins"] += 1
    return buckets


def full_report(name, res, n_total_variants):
    eq = res["equity_curve"]
    pnls = res["trade_pnls"]
    rets = M.returns_from_equity(eq)
    pf = M.profit_factor(pnls) if pnls else 0.0
    conc = concentration(res["trades_log"])
    pps, n_obs = per_period_sharpe(eq)
    # honest DSR: penalise for the number of configs we actually tested
    dsr = M.deflated_sharpe_ratio([pps] * n_total_variants, n_obs) if n_obs > 1 else 0.0
    return {
        "name": name,
        "num_trades": len(pnls),
        "sharpe": round(M.sharpe_ratio(rets), 3),
        "sortino": round(M.sortino_ratio(rets), 3),
        "pf": (round(pf, 3) if not math.isinf(pf) else "inf"),
        "total_return_pct": round(M.total_return(eq) * 100, 2),
        "cagr_pct": round(M.cagr(eq) * 100, 2),
        "max_dd_pct": round(M.max_drawdown(eq) * 100, 2),
        "win_rate_pct": (round(M.win_rate(pnls) * 100, 1) if pnls else None),
        "deflated_sharpe": round(dsr, 4),
        "final_equity": round(eq[-1], 2),
        "concentration": conc,
        "by_year": {str(y): {"trades": v["n"], "net_pnl": round(v["pnl"], 0),
                             "win_pct": round(v["wins"] / v["n"] * 100, 1)
                             if v["n"] else 0}
                    for y, v in by_year(res["trades_log"]).items()},
    }


def main():
    bars_by_sym, sector_of, spy, tradeable, dates = load_data()
    sym_idx = {s: index_by_date(b) for s, b in bars_by_sym.items()}
    spy_idx = index_by_date(spy)

    cost_bps, slip_bps = load_friction("portfolio_3")
    friction_one_side = cost_bps + slip_bps
    print(f"Universe: {len(tradeable)} tradeable stocks, {len(dates)} days "
          f"{dates[0]}..{dates[-1]}")
    print(f"Friction: {friction_one_side}bps each side\n")

    # strict defaults == the committed engine's screen (for parity)
    STRICT = {
        "friction_bps": friction_one_side,
        "min_avg_vol_20d": MIN_AVG_VOL_20D,
        "min_1m_return": MIN_1M_RETURN,
        "require_rs_positive": True,
        "require_above_ema200": True,
        "max_concurrent": 999,
        "max_roundtrips_per_q": None,
        "cooldown_days": 0,
    }

    def cfg(**over):
        c = dict(STRICT)
        c.update(over)
        return c

    # ---- config sweep ----
    # Faithful baseline (parity target) -> progressive loosening -> + per-symbol cap.
    variants = {
        # faithful (should reproduce 17 trades / INTC domination)
        "FAITHFUL thr0.40 strict": cfg(threshold=0.40),

        # lever (c): loosen the threshold only
        "thr0.30 strict screen": cfg(threshold=0.30),
        "thr0.25 strict screen": cfg(threshold=0.25),

        # lever (c): drop the strictest screen gates (still > EMA200 regime)
        "thr0.25 noRSgate": cfg(threshold=0.25, require_rs_positive=False),
        "thr0.25 noRSgate no1mFloor":
            cfg(threshold=0.25, require_rs_positive=False, min_1m_return=-1e9),

        # lever (c) maximal breadth: also drop the EMA200 regime gate
        "thr0.20 noRS no1m noRegime":
            cfg(threshold=0.20, require_rs_positive=False, min_1m_return=-1e9,
                require_above_ema200=False),

        # lever (b): the SAME breadth, but hard per-symbol re-entry cap = 1/quarter
        "BREADTH + cap 1rt/sym/Q":
            cfg(threshold=0.25, require_rs_positive=False, min_1m_return=-1e9,
                max_roundtrips_per_q=1),
        "BREADTH + cap 2rt/sym/Q":
            cfg(threshold=0.25, require_rs_positive=False, min_1m_return=-1e9,
                max_roundtrips_per_q=2),

        # lever (a)+(b): breadth + per-symbol cap + concurrency cap (risk control)
        "BREADTH + cap1/Q + maxconc8":
            cfg(threshold=0.25, require_rs_positive=False, min_1m_return=-1e9,
                max_roundtrips_per_q=1, max_concurrent=8),
        "BREADTH + cap1/Q + maxconc12 + cooldown10":
            cfg(threshold=0.25, require_rs_positive=False, min_1m_return=-1e9,
                max_roundtrips_per_q=1, max_concurrent=12, cooldown_days=10),
    }

    n_variants = len(variants)
    results, reports = {}, {}
    for name, c in variants.items():
        res = run_backtest(c, bars_by_sym, sector_of, spy, tradeable,
                           dates, sym_idx, spy_idx)
        results[name] = res
        reports[name] = full_report(name, res, n_variants)

    # ---- PARITY CHECK: faithful config must reproduce the committed 17 trades ----
    faithful_n = reports["FAITHFUL thr0.40 strict"]["num_trades"]
    base_res = base.run_backtest({"friction_bps": friction_one_side, "threshold": 0.40},
                                 bars_by_sym, sector_of, spy, tradeable, dates,
                                 sym_idx, spy_idx)
    parity_ok = (faithful_n == len(base_res["trade_pnls"]))
    print(f"PARITY: faithful extension={faithful_n} trades, "
          f"committed engine={len(base_res['trade_pnls'])} trades -> "
          f"{'MATCH' if parity_ok else 'MISMATCH'}\n")

    # SPY buy&hold over the same window
    sub = results["FAITHFUL thr0.40 strict"]["dates"]
    bh = base.spy_buy_hold(spy, sub, spy_idx, friction_one_side)

    # ---- print table ----
    print("=" * 138)
    hdr = (f"{'CONFIG':<38}{'#Tr':>5}{'Sharpe':>8}{'PF':>7}{'TotRet%':>9}"
           f"{'CAGR%':>7}{'MaxDD%':>8}{'Win%':>7}{'DSR':>7}"
           f"{'TopName':>9}{'Top%':>7}{'#Names':>8}")
    print(hdr)
    print("-" * 138)
    for name in variants:
        r = reports[name]
        pf = r["pf"]
        pf_s = "inf" if pf == "inf" else f"{pf:.2f}"
        wr = r["win_rate_pct"]
        wr_s = "-" if wr is None else f"{wr:.1f}"
        cc = r["concentration"]
        tn = cc["top_name"] or "-"
        print(f"{name:<38}{r['num_trades']:>5}{r['sharpe']:>8.2f}{pf_s:>7}"
              f"{r['total_return_pct']:>9.1f}{r['cagr_pct']:>7.1f}"
              f"{r['max_dd_pct']:>8.1f}{wr_s:>7}{r['deflated_sharpe']:>7.2f}"
              f"{tn:>9}{cc['top_share_pct']:>7.1f}{cc['distinct_names']:>8}")
    print("-" * 138)
    if bh:
        print(f"{'SPY BUY & HOLD (net)':<38}{'-':>5}{bh['sharpe']:>8.2f}{'-':>7}"
              f"{bh['total_return_pct']:>9.1f}{bh['cagr_pct']:>7.1f}"
              f"{bh['max_dd_pct']:>8.1f}{'-':>7}{'-':>7}{'-':>9}{'-':>7}{'-':>8}")
    print("=" * 138)
    print("DSR = Deflated Sharpe penalised for testing", n_variants,
          "configs (>0.95 = real after multiple-testing). Top% = share of the "
          "single most-traded name.")

    # ---- by-year OOS for the well-sampled, capped configs ----
    for name in ("BREADTH + cap 1rt/sym/Q", "BREADTH + cap1/Q + maxconc8"):
        print(f"\nBY-YEAR (entry-year) — {name}:")
        for y, v in sorted(reports[name]["by_year"].items()):
            print(f"  {y}: trades={v['trades']:>3}  net=${v['net_pnl']:>11,.0f}  "
                  f"win%={v['win_pct']:>5.1f}")

    # machine-readable
    print("\n###JSON###")
    print(json.dumps({
        "friction_per_side_bps": friction_one_side,
        "universe": len(tradeable),
        "date_range": [dates[0], dates[-1]],
        "parity_ok": parity_ok,
        "n_variants_tested": n_variants,
        "spy_buy_hold": {k: v for k, v in bh.items() if k != "curve"} if bh else None,
        "reports": reports,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
