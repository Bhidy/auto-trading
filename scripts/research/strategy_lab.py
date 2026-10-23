#!/usr/bin/env python3
"""Strategy lab — pre-registered evaluation of matf-v1 / secmom-v1 / crisis-core-v1.

Pure stdlib + repo backtest modules (T1-compatible; nothing here imports a heavy
dependency, so the engine could later run on the cloud path). Research lane only:
it reads the gitignored SIP research cache and writes
``data/strategy_lab_results.json`` (+ provenance). It places NO orders and touches
no live state.

Engine (weight-based, daily):
  * signal at the close of session t (allocator sees closes[0..t] only — the lists
    are truncated before the call) -> trade at the open of session t+1;
  * weekly (last session of ISO week) or monthly (last session of month) snapshots;
    book target = mean of the last ``tranches`` snapshots (missing = all cash);
  * no-trade band, sell-to-zero, >cap positions always traded, 12% close drift guard,
    max 12 orders per session (sells first, then |dw| desc; remainder queued);
  * per-side friction on traded notional; buys scaled down if cash would go negative
    (no leverage); uninvested cash earns 0.

Specs: docs/specs/{matf_v1,secmom_v1,crisis_core_v1}.json — read, never edited here.
"""
import argparse
import hashlib
import json
import math
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest import metrics as M  # noqa: E402
from backtest.allocators import ALLOCATORS, secmom_held  # noqa: E402
from backtest.cpcv import combinatorial_splits  # noqa: E402
from backtest.friction import load_friction  # noqa: E402
from shared.research_provenance import write_provenance  # noqa: E402

DATA_DIRS = [os.path.join(ROOT, "data", "research_cache", "adj10y_sip"),
             os.path.join(ROOT, "data", "research_cache", "adj10y_sip_ext")]
SPEC_FILES = {"matf-v1": "matf_v1.json", "secmom-v1": "secmom_v1.json", "crisis-core-v1": "crisis_core_v1.json"}
OUT_PATH = os.path.join(ROOT, "data", "strategy_lab_results.json")
INITIAL = 100000.0
CAP = 0.114
DRIFT_CAP = 0.12
MAX_ORDERS = 12
EPS = 1e-9


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_bars(symbols, dirs=None, calendar_symbol="SPY"):
    """Return (dates, opens, closes) aligned to ``calendar_symbol``'s sessions."""
    dirs = dirs or DATA_DIRS

    def _read(sym):
        for d in dirs:
            path = os.path.join(d, f"{sym}.json")
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f), path
        raise FileNotFoundError(f"no bars for {sym} in {dirs}")

    cal, _ = _read(calendar_symbol)
    dates = [b["t"][:10] for b in cal]
    pos = {d: i for i, d in enumerate(dates)}
    opens, closes, paths = {}, {}, {}
    for s in sorted(set(symbols) | {calendar_symbol}):
        bars, path = _read(s)
        paths[s] = path
        o, c = [None] * len(dates), [None] * len(dates)
        for b in bars:
            i = pos.get(b["t"][:10])
            if i is not None:
                o[i], c[i] = float(b["o"]), float(b["c"])
        opens[s], closes[s] = o, c
    return dates, opens, closes, paths


def is_snapshot(dates, t, schedule):
    if t + 1 >= len(dates):
        return False
    a, b = date.fromisoformat(dates[t]), date.fromisoformat(dates[t + 1])
    if schedule == "weekly":
        return a.isocalendar()[:2] != b.isocalendar()[:2]
    if schedule == "monthly":
        return (a.year, a.month) != (b.year, b.month)
    raise ValueError(schedule)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def run_backtest(dates, opens, closes, target_fn, params, *, schedule, tranches, band,
                 cost_bps_per_side, start_index, stateful_secmom=False, max_orders=MAX_ORDERS,
                 cap=CAP, drift_cap=DRIFT_CAP, initial=INITIAL):
    """Run one backtest. Returns a dict with the equity curve and diagnostics."""
    n = len(dates)
    syms = sorted(closes)
    c = cost_bps_per_side / 10000.0
    units = {s: 0.0 for s in syms}
    cash = initial
    last_close = {s: None for s in syms}
    for s in syms:  # last known close before the start (for valuing untradable names)
        for i in range(start_index - 1, -1, -1):
            if closes[s][i] is not None:
                last_close[s] = closes[s][i]
                break
    buffer, book = [], {}
    pending = False
    drift_flags = set()
    prev_held = []
    curve, curve_dates = [initial], [dates[start_index - 1]]
    tbill_w, cash_w = [], []
    turnover, n_orders, n_queue_days, drift_events = 0.0, 0, 0, 0
    max_post_trade_w, max_close_w = 0.0, 0.0
    snapshots = []

    for i in range(start_index, n):
        # ---------------- open of session i: trade ----------------
        snap_t = i - 1
        if is_snapshot(dates, snap_t, schedule):
            trunc = {s: closes[s][:snap_t + 1] for s in syms}
            p = dict(params)
            if stateful_secmom:
                p["prev_held"] = prev_held
            target = target_fn(trunc, snap_t, p)
            if stateful_secmom:
                prev_held = secmom_held(target, p)
            snapshots.append({"t": dates[snap_t], "w": {k: round(v, 6) for k, v in target.items()}})
            buffer.append(target)
            buffer = buffer[-tranches:]
            book = {}
            for vec in buffer:
                for s, w in vec.items():
                    book[s] = book.get(s, 0.0) + w / tranches
            pending = True

        px_open = {s: (opens[s][i] if opens[s][i] is not None else None) for s in syms}
        val = {s: units[s] * (px_open[s] if px_open[s] is not None else (last_close[s] or 0.0)) for s in syms}
        eq_open = cash + sum(val.values())
        orders = []
        was_rebalance = pending
        if pending or drift_flags:
            names = set(book) | {s for s in syms if units[s] > EPS} if pending else set(drift_flags)
            for s in names:
                if px_open[s] is None:
                    continue
                cur = val[s] / eq_open if eq_open > 0 else 0.0
                tgt = book.get(s, 0.0)
                if not pending:  # drift guard only
                    tgt = min(tgt, cap)
                d = tgt - cur
                if abs(d) < EPS:
                    continue
                if pending and abs(d) < band and not (tgt == 0.0 and cur > EPS) and not (cur > cap + EPS):
                    continue
                orders.append((s, tgt, d))
            if drift_flags and not pending:
                drift_events += 1
        if orders:
            orders.sort(key=lambda o: (0 if o[2] < 0 else 1, -abs(o[2]), o[0]))
            todo, rest = orders[:max_orders], orders[max_orders:]
            traded = 0.0
            for s, tgt, d in [o for o in todo if o[2] < 0]:
                q = min(units[s], -d * eq_open / px_open[s])
                if tgt == 0.0:
                    q = units[s]
                notional = q * px_open[s]
                units[s] -= q
                cash += notional * (1.0 - c)
                traded += notional
            buys = [o for o in todo if o[2] > 0]
            need = sum(d * eq_open for _, _, d in buys) * (1.0 + c)
            scale = 1.0 if need <= cash or need <= 0 else max(0.0, cash / need)
            for s, tgt, d in buys:
                notional = d * eq_open * scale
                units[s] += notional / px_open[s]
                cash -= notional * (1.0 + c)
                traded += notional
            cash = max(cash, 0.0) if cash > -1e-6 else cash
            n_orders += len(todo)
            turnover += traded / eq_open if eq_open > 0 else 0.0
            if rest and pending:
                n_queue_days += 1
            pending = bool(rest) and pending
            post = cash + sum(units[s] * (px_open[s] if px_open[s] is not None else (last_close[s] or 0.0)) for s in syms)
            for s in syms:
                if was_rebalance and units[s] > EPS and px_open[s] is not None and post > 0:
                    max_post_trade_w = max(max_post_trade_w, units[s] * px_open[s] / post)
        else:
            pending = False if pending else pending
        drift_flags = set()

        # ---------------- close of session i: value ----------------
        for s in syms:
            if closes[s][i] is not None:
                last_close[s] = closes[s][i]
        pos_val = {s: units[s] * (last_close[s] or 0.0) for s in syms}
        eq = cash + sum(pos_val.values())
        curve.append(eq)
        curve_dates.append(dates[i])
        if eq > 0:
            tb = sum(pos_val.get(s, 0.0) for s in ("BIL", "SHV", "SGOV", "USFR")) / eq
            tbill_w.append(tb)
            cash_w.append(cash / eq)
            for s in syms:
                w = pos_val[s] / eq
                if w > max_close_w:
                    max_close_w = w
                if w > drift_cap + EPS:
                    drift_flags.add(s)

    years = (len(curve) - 1) / 252.0
    return {
        "curve": curve, "dates": curve_dates,
        "turnover_one_way_per_year": round(turnover / 2.0 / years, 4) if years > 0 else None,
        "n_orders": n_orders, "orders_per_year": round(n_orders / years, 1) if years > 0 else None,
        "queued_sessions": n_queue_days, "drift_guard_events": drift_events,
        "max_post_trade_weight": round(max_post_trade_w, 5), "max_close_weight": round(max_close_w, 5),
        "avg_tbill_weight": round(sum(tbill_w) / len(tbill_w), 4) if tbill_w else None,
        "avg_cash_weight": round(sum(cash_w) / len(cash_w), 4) if cash_w else None,
        "n_snapshots": len(snapshots), "last_snapshot": snapshots[-1] if snapshots else None,
    }


def buy_and_hold(dates, opens, closes, sym, start_index, cost_bps_per_side, initial=INITIAL):
    c = cost_bps_per_side / 10000.0
    u = initial / (1.0 + c) / opens[sym][start_index]
    curve, cd = [initial], [dates[start_index - 1]]
    for i in range(start_index, len(dates)):
        curve.append(u * closes[sym][i])
        cd.append(dates[i])
    return {"curve": curve, "dates": cd}


# ---------------------------------------------------------------------------
# Statistics (thin wrappers over scripts/backtest/metrics.py)
# ---------------------------------------------------------------------------

def daily_returns(curve):
    return M.returns_from_equity(curve)


def hurdle_returns(dates, opens, closes, start_index, sym="BIL"):
    """BIL daily total returns aligned to curve returns (day 1 = open->close)."""
    out = [closes[sym][start_index] / opens[sym][start_index] - 1.0]
    for i in range(start_index + 1, len(dates)):
        out.append(closes[sym][i] / closes[sym][i - 1] - 1.0)
    return out


def moments(xs):
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / n)
    if sd == 0:
        return 0.0, 3.0
    skew = sum(((x - m) / sd) ** 3 for x in xs) / n
    kurt = sum(((x - m) / sd) ** 4 for x in xs) / n
    return skew, kurt


def per_period_sharpe(xs):
    sd = M._std(xs)
    return (M._mean(xs) / sd) if sd > 0 else 0.0


def expected_max_sharpe(trial_sharpes):
    """SR0 — identical null to metrics.deflated_sharpe_ratio (False Strategy Theorem)."""
    n = len(trial_sharpes)
    if n < 2:
        return 0.0
    mean = sum(trial_sharpes) / n
    var = sum((s - mean) ** 2 for s in trial_sharpes) / (n - 1)
    if var <= 0:
        return 0.0
    z1 = M.inverse_normal_cdf(1.0 - 1.0 / n)
    z2 = M.inverse_normal_cdf(1.0 - 1.0 / (n * math.e))
    g = M._EULER_MASCHERONI
    return math.sqrt(var) * ((1.0 - g) * z1 + g * z2)


def dsr_for(excess, trial_sharpes):
    sr = per_period_sharpe(excess)
    skew, kurt = moments(excess)
    return M.probabilistic_sharpe_ratio(sr, expected_max_sharpe(trial_sharpes), len(excess), skew, kurt)


def max_dd_dates(curve, dates):
    peak, peak_i, best = curve[0], 0, (0.0, 0, 0)
    for i, v in enumerate(curve):
        if v > peak:
            peak, peak_i = v, i
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > best[0]:
            best = (dd, peak_i, i)
    dd, pi, ti = best
    rec = None
    for j in range(ti, len(curve)):
        if curve[j] >= curve[pi]:
            rec = dates[j]
            break
    return {"max_drawdown": round(dd, 4), "peak": dates[pi], "trough": dates[ti], "recovered": rec}


def calendar_returns(curve, dates):
    last = {}
    for v, d in zip(curve, dates):
        last[d[:4]] = v
    out, prev = {}, None
    years = sorted(last)
    for y in years:
        if prev is not None:
            out[y] = round(last[y] / last[prev] - 1.0, 4)
        prev = y
    first_year = years[0]
    if len(years) > 1 and dates[0][:4] == first_year:
        out[first_year + "_partial"] = round(last[first_year] / curve[0] - 1.0, 4)
    return out


def monthly_returns(curve, dates):
    last, order = {}, []
    for v, d in zip(curve, dates):
        k = d[:7]
        if k not in last:
            order.append(k)
        last[k] = v
    out, prev = {}, curve[0]
    for k in order:
        out[k] = last[k] / prev - 1.0
        prev = last[k]
    return out


def window_slice(run, start_date):
    i = next(k for k, d in enumerate(run["dates"]) if d >= start_date)
    i = max(i - 1, 0)
    return {"curve": run["curve"][i:], "dates": run["dates"][i:]}


def cpcv_sharpes(excess):
    out = []
    for sp in combinatorial_splits(len(excess), n_groups=6, n_test_groups=2, label_horizon=0, embargo_pct=0.01):
        xs = [excess[i] for i in sp["test_idx"]]
        out.append(M.sharpe_ratio(xs))
    out.sort()
    k = len(out)
    return {"n_paths": k, "min": round(out[0], 3), "p25": round(out[k // 4], 3), "median": round(out[k // 2], 3),
            "p75": round(out[(3 * k) // 4], 3), "max": round(out[-1], 3),
            "frac_positive": round(sum(1 for x in out if x > 0) / k, 3)}


def risk_replay(curve):
    rets = daily_returns(curve)
    roll5 = [curve[i] / curve[i - 5] - 1.0 for i in range(5, len(curve))]
    mdd = M.max_drawdown(curve)
    return {"worst_day": round(min(rets), 4), "days_le_minus_4pct": sum(1 for r in rets if r <= -0.04),
            "worst_5d": round(min(roll5), 4), "rolling_5d_le_minus_8pct": sum(1 for r in roll5 if r <= -0.08),
            "max_drawdown": round(mdd, 4), "kill_switch_18pct_breached": mdd >= 0.18,
            "daily_loss_4pct_breached": any(r <= -0.04 for r in rets)}


def evaluate(run, hurdle):
    curve, dates = run["curve"], run["dates"]
    rets = daily_returns(curve)
    excess = [r - h for r, h in zip(rets, hurdle)]
    months = monthly_returns(curve, dates)
    worst_m = min(months.items(), key=lambda kv: kv[1])
    out = {
        "start": dates[1], "end": dates[-1], "n_days": len(rets),
        "cagr": round(M.cagr(curve), 4), "vol": round(M.annualized_volatility(rets), 4),
        "sharpe_excess": round(M.sharpe_ratio(excess), 3), "sharpe_raw_rf0": round(M.sharpe_ratio(rets), 3),
        "sortino": round(M.sortino_ratio(rets), 3), "calmar": round(M.calmar_ratio(curve), 3),
        "total_return": round(M.total_return(curve), 4),
        "drawdown": max_dd_dates(curve, dates), "calendar": calendar_returns(curve, dates),
        "worst_month": {"month": worst_m[0], "return": round(worst_m[1], 4)},
        "risk_replay": risk_replay(curve),
        "_excess": excess,
    }
    for k in ("turnover_one_way_per_year", "orders_per_year", "n_orders", "queued_sessions", "drift_guard_events",
              "max_post_trade_weight", "max_close_weight", "avg_tbill_weight", "avg_cash_weight", "last_snapshot"):
        if k in run:
            out[k] = run[k]
    if "avg_tbill_weight" in run and run["avg_tbill_weight"] is not None:
        out["avg_time_in_tbills_or_cash"] = round(run["avg_tbill_weight"] + run["avg_cash_weight"], 4)
    return out


def blend(runs, weights):
    curve = [sum(w * r["curve"][i] for r, w in zip(runs, weights)) for i in range(len(runs[0]["curve"]))]
    return {"curve": curve, "dates": runs[0]["dates"]}


# ---------------------------------------------------------------------------
# Lab
# ---------------------------------------------------------------------------

def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_specs():
    specs = {}
    for sid, fn in SPEC_FILES.items():
        path = os.path.join(ROOT, "docs", "specs", fn)
        with open(path) as f:
            specs[sid] = (json.load(f), path)
    return specs


def eval_start_index(dates, spec):
    want = spec["data"]["eval_start"][:10]
    return next(i for i, d in enumerate(dates) if d >= want)


def run_spec(sid, spec, data, params_override, cost_bps):
    dates, opens, closes = data
    params = dict(spec["params"])
    params.update(params_override or {})
    reb = spec["rebalance"]
    start = eval_start_index(dates, spec)
    symbols = set(spec["symbols"]) | {"BIL"}
    sub_c = {s: closes[s] for s in symbols}
    sub_o = {s: opens[s] for s in symbols}
    if sid != "secmom-v1" and "risky" in spec:
        params.setdefault("risky", spec["risky"])
    if sid == "secmom-v1":
        params.setdefault("risky", spec["risky"])
    return run_backtest(dates, sub_o, sub_c, ALLOCATORS[sid], params, schedule=reb["frequency"],
                        tranches=params.get("tranches", reb.get("tranches", 1)), band=params.get("band", reb["band"]),
                        cost_bps_per_side=cost_bps, start_index=start, stateful_secmom=(sid == "secmom-v1"))


def verdict(ev, spy, dsr, neigh_sharpes, stress_sharpe):
    s = ev["sharpe_excess"]
    c = {
        "C1_max_drawdown_le_12pct": ev["drawdown"]["max_drawdown"] <= 0.12,
        "C2_calmar_ge_spy": ev["calmar"] >= spy["calmar"],
        "C3_sharpe_ge_0.5_and_dsr_ge_0.95": s >= 0.5 and dsr >= 0.95,
        "C4_2022_ge_spy_plus_8pp": ev["calendar"].get("2022", -9) >= spy["calendar"]["2022"] + 0.08,
        "C5_neighbourhood_dsharpe_lt_0.25": all(abs(x - s) < 0.25 for x in neigh_sharpes) if neigh_sharpes else None,
        "C6_stress_20bps_sharpe_ge_0.4": stress_sharpe >= 0.4,
    }
    out = {k: ("PASS" if v else ("N/A" if v is None else "FAIL")) for k, v in c.items()}
    out["overall"] = "PASS" if all(v == "PASS" for v in out.values()) else "FAIL"
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args(argv)

    specs = load_specs()
    all_syms = set()
    for spec, _ in specs.values():
        all_syms |= set(spec["symbols"])
    all_syms |= {"SPY", "BIL"}
    dates, opens, closes, paths = load_bars(sorted(all_syms))
    data = (dates, opens, closes)
    cost, slip = load_friction("portfolio_1")
    base_bps = cost + slip
    stress_bps = specs["matf-v1"][0]["friction_stress"]["total_bps_per_side"]

    trials = []  # (trial_id, per-period excess sharpe)
    results = {}
    runs_main, runs_stress, runs_neigh = {}, {}, {}

    start = eval_start_index(dates, specs["matf-v1"][0])
    hurdle = hurdle_returns(dates, opens, closes, start)
    spy_run = buy_and_hold(dates, opens, closes, "SPY", start, base_bps)
    spy = evaluate(spy_run, hurdle)

    for sid, (spec, _) in specs.items():
        print(f"[{sid}] main", flush=True)
        runs_main[sid] = run_spec(sid, spec, data, None, base_bps)
        runs_stress[sid] = run_spec(sid, spec, data, None, stress_bps)
        runs_neigh[sid] = {}
        for v in spec["neighbourhood_variants"]:
            print(f"[{sid}] {v['id']}", flush=True)
            runs_neigh[sid][v["id"]] = run_spec(sid, spec, data, v["params"], base_bps)

    evals = {}
    for sid in specs:
        evals[sid] = {"main": evaluate(runs_main[sid], hurdle), "stress": evaluate(runs_stress[sid], hurdle),
                      "neighbours": {k: evaluate(r, hurdle) for k, r in runs_neigh[sid].items()}}
        trials.append((f"{sid}:main", per_period_sharpe(evals[sid]["main"]["_excess"])))
        trials.append((f"{sid}:stress20", per_period_sharpe(evals[sid]["stress"]["_excess"])))
        for k, e in evals[sid]["neighbours"].items():
            trials.append((f"{sid}:{k}", per_period_sharpe(e["_excess"])))

    combos = specs["matf-v1"][0]["registered_combinations"]
    combo_evals = {}
    for key in ("COMBO_A", "COMBO_B"):
        cdef = combos[key]
        comps, w = cdef["components"], cdef["weights"]
        main = evaluate(blend([runs_main[s] for s in comps], w), hurdle)
        stress = evaluate(blend([runs_stress[s] for s in comps], w), hurdle)
        neigh = {}
        for j, s in enumerate(comps):
            for vid, vr in runs_neigh[s].items():
                rs = [vr if k == j else runs_main[c] for k, c in enumerate(comps)]
                neigh[f"{s}:{vid}"] = evaluate(blend(rs, w), hurdle)
        combo_evals[cdef["id"]] = {"main": main, "stress": stress, "neighbours": neigh, "components": comps, "weights": w}
        trials.append((f"{cdef['id']}:main", per_period_sharpe(main["_excess"])))
        trials.append((f"{cdef['id']}:stress20", per_period_sharpe(stress["_excess"])))

    trial_sharpes = [s for _, s in trials]
    n_registered = specs["matf-v1"][0]["trial_plan"]["lab_total_trials"]
    assert len(trials) == n_registered, f"ran {len(trials)} trials, registered {n_registered}"
    # Transparency: N incl. the 2 passive-core-ew8 looks (their excess Sharpes are not on this span,
    # so they are represented by the lab's mean Sharpe — documented approximation).
    mean_sr = sum(trial_sharpes) / len(trial_sharpes)
    trial_sharpes_40 = trial_sharpes + [mean_sr, mean_sr]

    def _pack(name, ev_block):
        main = ev_block["main"]
        dsr = dsr_for(main["_excess"], trial_sharpes)
        dsr40 = dsr_for(main["_excess"], trial_sharpes_40)
        neigh_s = {k: e["sharpe_excess"] for k, e in ev_block["neighbours"].items()}
        v = verdict(main, spy, dsr, list(neigh_s.values()), ev_block["stress"]["sharpe_excess"])
        m = {k: val for k, val in main.items() if k != "_excess"}
        m["dsr_N38"] = round(dsr, 4)
        m["dsr_N40_incl_passive_core"] = round(dsr40, 4)
        m["psr_vs_0"] = round(M.probabilistic_sharpe_ratio(per_period_sharpe(main["_excess"]), 0.0, len(main["_excess"]),
                                                           *moments(main["_excess"])), 4)
        m["cpcv_sharpe"] = cpcv_sharpes(main["_excess"])
        return {
            "main": m,
            "stress_20bps": {k: ev_block["stress"][k] for k in ("sharpe_excess", "cagr", "calmar")} |
            {"max_drawdown": ev_block["stress"]["drawdown"]["max_drawdown"]},
            "neighbourhood": {k: {"sharpe_excess": e["sharpe_excess"], "d_sharpe": round(e["sharpe_excess"] - main["sharpe_excess"], 3),
                                  "max_drawdown": e["drawdown"]["max_drawdown"], "cagr": e["cagr"]}
                              for k, e in ev_block["neighbours"].items()},
            "max_abs_d_sharpe": round(max((abs(x - main["sharpe_excess"]) for x in neigh_s.values()), default=0.0), 3),
            "acceptance": v,
        }

    for sid, (spec, path) in specs.items():
        results[sid] = _pack(sid, evals[sid])
        results[sid]["spec_sha256"] = _sha(path)
        results[sid]["spec_path"] = os.path.relpath(path, ROOT)
    for cid, ev in combo_evals.items():
        results[cid] = _pack(cid, ev)
        results[cid]["components"] = ev["components"]
        results[cid]["weights"] = ev["weights"]

    # S3 sub-period with all three MF funds listed (information only)
    s3_sub = window_slice(runs_main["crisis-core-v1"], "2022-03-08")
    spy_sub = window_slice(spy_run, "2022-03-08")
    sub_h = hurdle[len(hurdle) - (len(s3_sub["curve"]) - 1):]
    results["crisis-core-v1"]["subperiod_2022-03-08_all_mf_listed"] = {
        "s3": {k: v for k, v in evaluate(s3_sub, sub_h).items() if k in ("cagr", "vol", "sharpe_excess", "calmar", "calendar")}
        | {"max_drawdown": evaluate(s3_sub, sub_h)["drawdown"]["max_drawdown"]},
        "spy": {k: v for k, v in evaluate(spy_sub, sub_h).items() if k in ("cagr", "vol", "sharpe_excess", "calmar", "calendar")}
        | {"max_drawdown": evaluate(spy_sub, sub_h)["drawdown"]["max_drawdown"]},
    }

    spy_out = {k: v for k, v in spy.items() if k != "_excess"}
    spy_out["cpcv_sharpe"] = cpcv_sharpes(spy["_excess"])
    out = {
        "generated_by": "scripts/research/strategy_lab.py",
        "label": "SIMULATION — research lane, not investment advice, PAPER ONLY",
        "data": {"dirs": [os.path.relpath(d, ROOT) for d in DATA_DIRS], "feed": "sip", "adjustment": "all",
                 "calendar_sessions": len(dates), "eval_start": dates[start], "eval_end": dates[-1]},
        "friction_bps_per_side": {"base": base_bps, "stress": stress_bps, "source": "scripts/backtest/friction.load_friction"},
        "trial_count": {"lab_N": len(trials), "registered_N": n_registered, "N_incl_passive_core": len(trial_sharpes_40),
                        "trials": [{"id": k, "per_period_excess_sharpe": round(s, 5),
                                    "annualized": round(s * math.sqrt(252), 3)} for k, s in trials],
                        "sr0_per_period_N38": round(expected_max_sharpe(trial_sharpes), 5),
                        "sr0_annualized_N38": round(expected_max_sharpe(trial_sharpes) * math.sqrt(252), 3),
                        "unpooled_ledgers": {"data/trial_ledger.json": "60 P1 self-learning knob trials",
                                             "data/p2_scorecard.json": "34 P2 trials"}},
        "benchmark_spy": spy_out,
        "results": results,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    inputs = sorted(set(paths.values())) + [p for _, p in specs.values()]
    write_provenance(args.out, inputs, source="scripts/research/strategy_lab.py",
                     warnings=["In-sample confirmation test (specs written knowing 2016-2026).",
                               "S3 holds no managed futures before 2019-05-08; all three MF ETFs only from 2022-03-08.",
                               "Uninvested cash above T-bill basket capacity earns 0%."],
                     extra={"spec_sha256": {sid: _sha(p) for sid, (_, p) in specs.items()}})
    for sid in list(specs) + list(combo_evals):
        r = results[sid]["main"]
        print(f"{sid:22s} CAGR {r['cagr']:.2%} Sh {r['sharpe_excess']:.2f} MDD {r['drawdown']['max_drawdown']:.2%} "
              f"Calmar {r['calmar']:.2f} DSR {r['dsr_N38']:.3f} -> {results[sid]['acceptance']['overall']}")
    print(f"SPY                    CAGR {spy['cagr']:.2%} Sh {spy['sharpe_excess']:.2f} "
          f"MDD {spy['drawdown']['max_drawdown']:.2%} Calmar {spy['calmar']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
