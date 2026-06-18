#!/usr/bin/env python3
"""
P3 BREAKOUT x FUNDAMENTAL CONVERGENCE — no-look-ahead backtest.

EXTENDS scripts/research/p3_breakout_backtest.py (imported, not copied) to test
ONE hypothesis: does requiring a breakout name to ALSO pass a point-in-time
fundamental-quality screen (SEC EDGAR, gated by FILED date) improve OOS
risk-adjusted results vs breakout-ALONE?

  breakout-ALONE  : exactly the committed faithful backtest (BASELINE thr=0.40).
  breakout+FUND   : same signal/sizing/risk, but an entry is ALSO required to
                    pass a fundamental gate (positive YoY revenue growth and/or
                    positive free cash flow and/or non-extreme leverage), using
                    only the most-recent 10-K whose FILED (effective) date <= the
                    signal bar date t  (strict no look-ahead).

NO LOOK-AHEAD (inherited + added):
  * signal computed on bars[0..t]; fill at open[t+1]; ATR bracket; friction
    >= 5bps+5bps EACH side (from scripts/backtest/friction.load_friction).
  * fundamentals are point-in-time: as_of(t) = the FY row with the greatest
    `effective` (=earliest 10-K filed date) that is <= t. A filing is NEVER
    visible before it was filed. If no filing is yet public for a symbol, the
    fundamental gate FAILS CLOSED (symbol not eligible under the +FUND variant).

OUT-OF-SAMPLE: reported per calendar year (entry-year) for both arms, plus the
deflated Sharpe across the variant grid (multiple-testing penalty).

OFFLINE research (T2). Places NO orders, commits nothing, imports nothing on the
trading path.
"""
import os
import sys
import json

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.backtest import metrics as M                # noqa: E402
from scripts.backtest.friction import load_friction      # noqa: E402

# Reuse the EXACT committed breakout engine + screen/score + reporting.
import p3_breakout_backtest as P3                         # noqa: E402

FUND_PATH = os.path.join(REPO, "data", "fundamentals_pit.json")


# ---------------------------------------------------------------------------
# Point-in-time fundamental lookup
# ---------------------------------------------------------------------------
def load_fundamentals():
    with open(FUND_PATH) as f:
        d = json.load(f)
    return d.get("fundamentals", {})


def fundamentals_asof(fund_rows, date_str):
    """Most-recent FY row with effective (filed) <= date_str, else None.

    Rows are sorted by effective; we scan for the latest one already public.
    """
    chosen = None
    for row in fund_rows:
        if row["effective"] <= date_str:
            chosen = row  # keep advancing to the latest public filing
        else:
            break
    return chosen


def fundamental_gate(row, mode):
    """Return True if the point-in-time fundamentals pass the screen `mode`.

    mode keys (combinable):
      'growth'   : YoY revenue growth > 0
      'fcf'      : free cash flow > 0
      'leverage' : debt/equity is known and <= LEV_CAP (non-extreme)
      'quality'  : composite quality_score >= Q_MIN
    A None row (no filing public yet) FAILS CLOSED.
    """
    if row is None:
        return False
    checks = mode["checks"]
    if "growth" in checks and not (row.get("revenue_growth") is not None
                                   and row["revenue_growth"] > mode.get("growth_min", 0.0)):
        return False
    if "fcf" in checks and not row.get("fcf_positive"):
        return False
    if "leverage" in checks:
        de = row.get("debt_to_equity")
        # unknown leverage -> fail closed under a leverage gate
        if de is None or de > mode.get("lev_cap", 4.0):
            return False
    if "quality" in checks and not (row.get("quality_score") is not None
                                    and row["quality_score"] >= mode.get("q_min", 0.0)):
        return False
    return True


# ---------------------------------------------------------------------------
# Backtest engine with an optional fundamental gate on ENTRY.
# A monkeypatch-free reimplementation that calls P3's screen_and_score, so the
# breakout signal/score is byte-identical to the committed faithful backtest;
# only the entry-eligibility set differs (this is the experiment).
# ---------------------------------------------------------------------------
def run_backtest_fund(cfg, bars_by_sym, sector_of, spy, tradeable, dates,
                      sym_idx, spy_idx, fundamentals):
    threshold = cfg.get("threshold", 0.40)
    require_rvol = cfg.get("require_rvol", False)
    veto_rsi80 = cfg.get("veto_rsi80", False)
    cooldown_days = cfg.get("cooldown_days", 0)
    fund_mode = cfg.get("fund_mode")          # None => breakout-ALONE
    friction_bps = cfg["friction_bps"]
    fr = friction_bps / 10000.0

    cash = P3.START_EQUITY
    open_pos = {}
    cooldown = {}
    trade_pnls = []
    equity_curve = []
    trades_log = []
    # diagnostics: how many score-qualified candidates the fund gate rejected
    fund_rejected = 0
    fund_passed = 0

    spy_closes_all = [b["c"] for b in spy]
    di_first_tradeable = 63 + 1

    for di in range(di_first_tradeable, len(dates) - 1):
        date = dates[di]
        next_date = dates[di + 1]

        # ---- manage open positions (identical logic to P3.run_backtest) ----
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
                sell_qty = int(pos["qty"] * P3.TP1_SELL_PCT / 100)
                if sell_qty > 0:
                    fill = pos["tp1"] * (1 - fr)
                    cash += sell_qty * fill
                    realized = (fill - pos["entry"]) * sell_qty
                    pos["realized"] += realized
                    pos["qty"] -= sell_qty
                pos["tp1_done"] = True
                pos["stop"] = max(pos["stop"], pos["entry"])
                continue
            else:
                if pos["tp1_done"]:
                    new_trail = cl - pos["atr"] * P3.ATR_TRAIL_MULT
                    pos["stop"] = max(pos["stop"], new_trail)
                    if lo <= pos["stop"]:
                        exit_price = pos["stop"]
                        reason = "trail"
                held = di - pos["entry_di"]
                if exit_price is None and held >= P3.SWING_HOLD_MAX:
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
                    "ret_pct": (realized / pos["cost_basis"] * 100) if pos["cost_basis"] else 0.0,
                    "reason": reason, "year": int(pos["entry_date"][:4]),
                })
                if reason in ("stop", "trail") and cooldown_days > 0:
                    cooldown[sym] = di + cooldown_days
                to_close.append(sym)

        for sym in to_close:
            del open_pos[sym]

        mtm = 0.0
        for sym, pos in open_pos.items():
            si = sym_idx[sym].get(date)
            px = bars_by_sym[sym][si]["c"] if si is not None else pos["entry"]
            mtm += pos["qty"] * px
        equity = cash + mtm
        equity_curve.append(equity)

        spi = spy_idx.get(date)
        if spi is None or spi < 63:
            continue
        spy_3m = P3.momentum_pct(spy_closes_all[:spi + 1], 63) or 0.0

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
            res = P3.screen_and_score(closes, highs, lows, vols, spy_3m)
            if not res:
                continue
            if res["score"] < threshold:
                continue
            if require_rvol and res["rvol"] < P3.BREAKOUT_RVOL_THRESHOLD:
                continue
            if veto_rsi80 and res["rsi"] and res["rsi"] >= 80:
                continue

            # ---- FUNDAMENTAL GATE (point-in-time, the experiment) ----
            if fund_mode is not None:
                frow = fundamentals_asof(fundamentals.get(sym, []), date)
                if not fundamental_gate(frow, fund_mode):
                    fund_rejected += 1
                    continue
                fund_passed += 1

            res["symbol"] = sym
            res["sector"] = sector_of[sym]
            candidates.append(res)

        if not candidates:
            continue

        candidates.sort(key=lambda x: x["score"], reverse=True)
        seen_sec, diversified = {}, []
        for c in candidates:
            sec = c["sector"]
            if seen_sec.get(sec, 0) >= P3.MAX_SIGNALS_PER_SECTOR:
                continue
            seen_sec[sec] = seen_sec.get(sec, 0) + 1
            diversified.append(c)

        trades_today = 0
        for c in diversified:
            if trades_today >= P3.MAX_TRADES_PER_DAY:
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
            stop_dist = atr_val * P3.ATR_STOP_MULT
            max_risk = equity * P3.RISK_PER_TRADE_PCT / 100
            qty = int(max_risk / stop_dist)
            if qty <= 0:
                continue
            entry_fill = entry_open * (1 + fr)
            cost_basis = qty * entry_fill
            cur_gross = sum(p["qty"] * (bars_by_sym[s][sym_idx[s].get(date, 0)]["c"]
                            if sym_idx[s].get(date) is not None else p["entry"])
                            for s, p in open_pos.items())
            if (cur_gross + cost_basis) > equity * P3.MAX_GROSS_EXPOSURE_PCT / 100:
                continue
            sec = c["sector"]
            cur_sec = sum(p["qty"] * p["entry"] for s, p in open_pos.items()
                          if sector_of[s] == sec)
            if (cur_sec + cost_basis) > equity * P3.MAX_SECTOR_EXPOSURE_PCT / 100:
                continue
            if cost_basis > cash:
                continue
            cash -= cost_basis
            open_pos[sym] = {
                "qty": qty, "entry": entry_fill, "entry_di": di + 1,
                "entry_date": next_date, "atr": atr_val,
                "stop": entry_fill - stop_dist,
                "tp1": entry_fill + atr_val * P3.ATR_TP1_MULT,
                "tp1_done": False, "realized": 0.0, "cost_basis": cost_basis,
            }
            trades_today += 1

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
        "fund_rejected": fund_rejected,
        "fund_passed": fund_passed,
    }


def main():
    bars_by_sym, sector_of, spy, tradeable, dates = P3.load_data()
    sym_idx = {s: P3.index_by_date(b) for s, b in bars_by_sym.items()}
    spy_idx = P3.index_by_date(spy)
    fundamentals = load_fundamentals()

    cost_bps, slip_bps = load_friction("portfolio_3")
    friction_one_side = cost_bps + slip_bps
    print(f"Universe: {len(tradeable)} stocks, {len(dates)} days "
          f"{dates[0]}..{dates[-1]} | fundamentals for "
          f"{len(fundamentals)} symbols")
    print(f"Friction (per side): {friction_one_side}bps  "
          f"(cost {cost_bps} + slip {slip_bps})\n")

    base_cfg = {"friction_bps": friction_one_side, "threshold": 0.40}

    # Fundamental gate variants (point-in-time, FILED-date no-look-ahead):
    GATE_GROWTH = {"checks": {"growth"}, "growth_min": 0.0}
    GATE_FCF = {"checks": {"fcf"}}
    GATE_GROWTH_FCF = {"checks": {"growth", "fcf"}, "growth_min": 0.0}
    GATE_GFL = {"checks": {"growth", "fcf", "leverage"},
                "growth_min": 0.0, "lev_cap": 4.0}
    GATE_QUALITY = {"checks": {"quality"}, "q_min": 0.0}

    variants = {
        "breakout-ALONE (BASELINE)": dict(base_cfg),
        "+FUND growth>0": {**base_cfg, "fund_mode": GATE_GROWTH},
        "+FUND fcf>0": {**base_cfg, "fund_mode": GATE_FCF},
        "+FUND growth>0 & fcf>0": {**base_cfg, "fund_mode": GATE_GROWTH_FCF},
        "+FUND growth&fcf&D/E<=4": {**base_cfg, "fund_mode": GATE_GFL},
        "+FUND quality>=0": {**base_cfg, "fund_mode": GATE_QUALITY},
    }

    results, reports = {}, {}
    for name, cfg in variants.items():
        res = run_backtest_fund(cfg, bars_by_sym, sector_of, spy, tradeable,
                                dates, sym_idx, spy_idx, fundamentals)
        results[name] = res
        reports[name] = P3.report(name, res)

    sub = results["breakout-ALONE (BASELINE)"]["dates"]
    bh = P3.spy_buy_hold(spy, sub, spy_idx, friction_one_side)

    # ---- print comparison ----
    print("=" * 120)
    hdr = (f"{'VARIANT':<30}{'Sharpe':>8}{'Sortino':>9}{'PF':>7}{'TotRet%':>9}"
           f"{'CAGR%':>8}{'MaxDD%':>8}{'Win%':>7}{'#Tr':>6}{'FundRej':>9}")
    print(hdr)
    print("-" * 120)
    for name in variants:
        r = reports[name]
        pf = r["pf"]
        pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
        wr = r["win_rate_pct"]
        wr_s = "-" if wr is None else f"{wr:.1f}"
        fr_rej = results[name].get("fund_rejected", 0)
        fr_s = "-" if "BASELINE" in name else str(fr_rej)
        print(f"{name:<30}{r['sharpe']:>8.2f}{r['sortino']:>9.2f}{pf_s:>7}"
              f"{r['total_return_pct']:>9.1f}{r['cagr_pct']:>8.1f}"
              f"{r['max_dd_pct']:>8.1f}{wr_s:>7}{r['num_trades']:>6}{fr_s:>9}")
    print("-" * 120)
    if bh:
        print(f"{'SPY BUY & HOLD (net)':<30}{bh['sharpe']:>8.2f}{'-':>9}{'-':>7}"
              f"{bh['total_return_pct']:>9.1f}{bh['cagr_pct']:>8.1f}"
              f"{bh['max_dd_pct']:>8.1f}{'-':>7}{'-':>6}{'-':>9}")
    print("=" * 120)

    # ---- by-year OOS: baseline vs best fundamental variant ----
    def yearly(res):
        return P3.by_year(res)

    print("\nBY-YEAR (entry-year) — net P&L / #trades / win%:")
    years = sorted({t["year"] for r in results.values() for t in r["trades_log"]})
    arms = ["breakout-ALONE (BASELINE)", "+FUND growth>0 & fcf>0",
            "+FUND growth&fcf&D/E<=4"]
    yb = {a: yearly(results[a]) for a in arms}
    print("  year " + "".join(f"{a.split(' (')[0]:>28}" for a in arms))
    for y in years:
        row = f"  {y} "
        for a in arms:
            b = yb[a].get(y)
            if b:
                wr = b["wins"] / b["n"] * 100 if b["n"] else 0
                cell = f"${b['pnl']:,.0f}/{b['n']}/{wr:.0f}%"
            else:
                cell = "-"
            row += f"{cell:>28}"
        print(row)

    # ---- alpha vs SPY for each arm ----
    print("\nTotal return vs SPY B&H:")
    for name in variants:
        a = reports[name]["total_return_pct"] - (bh["total_return_pct"] if bh else 0)
        print(f"  {name:<30} {reports[name]['total_return_pct']:>8.1f}%  "
              f"(alpha {a:+.1f}pp vs SPY {bh['total_return_pct']:.1f}%)")

    # ---- deflated Sharpe across the variant grid (multiple-testing) ----
    per_period = []
    for name in variants:
        rets = M.returns_from_equity(results[name]["equity_curve"])
        sd = M._std(rets)
        per_period.append((M._mean(rets) / sd) if sd else 0.0)
    n_obs = len(M.returns_from_equity(results["breakout-ALONE (BASELINE)"]["equity_curve"]))
    dsr = M.deflated_sharpe_ratio(per_period, n_obs)
    print(f"\nDeflated Sharpe (best of {len(variants)} variants, n_obs={n_obs}): "
          f"{dsr:.4f}  (>0.95 = significant after multiple-testing)")

    print("\n###JSON###")
    print(json.dumps({
        "friction_per_side_bps": friction_one_side,
        "universe": len(tradeable),
        "trading_days": len(dates),
        "date_range": [dates[0], dates[-1]],
        "fundamentals_symbols": len(fundamentals),
        "reports": reports,
        "fund_rejected": {n: results[n].get("fund_rejected", 0) for n in variants},
        "fund_passed": {n: results[n].get("fund_passed", 0) for n in variants},
        "spy_buy_hold": {k: v for k, v in bh.items() if k != "curve"} if bh else None,
        "by_year": {a: {str(y): {"trades": v["n"], "net_pnl": round(v["pnl"], 0),
                                 "win_pct": round(v["wins"]/v["n"]*100, 1) if v["n"] else 0}
                        for y, v in yb[a].items()} for a in arms},
        "deflated_sharpe_best_of_variants": round(dsr, 4),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
