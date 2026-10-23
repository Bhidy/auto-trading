#!/usr/bin/env python3
"""Passive-core evaluator (OFFLINE research lane, T1-compatible pure Python).

Runs the PRE-REGISTERED spec ``docs/specs/passive_core.json`` (8 ETFs, equal
weight at 11.4% each under the 12% ETF cap, monthly rebalance, 5 bps floor
friction) against SPY buy & hold on real cached daily bars, and scores it
against the acceptance criteria written in the spec BEFORE this ran:

  C1  mean per-window Sharpe(core) >= mean per-window Sharpe(SPY) - 0.15
  C2  full-span max drawdown(core) <= full-span max drawdown(SPY)
  C3  live tracking error <= 3%/yr over 60 days  -> PENDING_LIVE (not measurable offline)

Statistics are REUSED, not rebuilt: Sharpe/MaxDD/CAGR/PSR/DSR from
``backtest.metrics``, combinatorial splits from ``backtest.cpcv``, friction from
``backtest.friction``, lineage from ``shared.research_provenance``.

Never fabricates data: it reads only cached bar files, refuses (INSUFFICIENT_DATA)
when the aligned history yields fewer than ``min_windows`` windows, and refuses to
splice two sources whose overlapping closes disagree. Stdlib + repo modules only;
the trading path never imports it.
"""
import argparse
import glob
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest import metrics  # noqa: E402
from backtest.cpcv import combinatorial_splits, n_backtest_paths  # noqa: E402
from backtest.friction import load_friction  # noqa: E402

SPEC_PATH = os.path.join(ROOT, "docs", "specs", "passive_core.json")
OUT_PATH = os.path.join(ROOT, "data", "passive_core_validation.json")
BENCHMARK = "SPY"


# ---------------------------------------------------------------------------
# Spec + data loading
# ---------------------------------------------------------------------------

def spec_hash(spec):
    """sha256 of the canonical JSON of the spec — any edit voids prior results."""
    canon = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def load_spec(path=SPEC_PATH):
    with open(path) as f:
        return json.load(f)


def _bars_in_dir(directory, symbols):
    """{symbol: {date: bar}} for `symbols` from every bar-cache JSON in `directory`.

    Returns ({}, []) if the directory is absent. Second element = files that
    actually contributed bars (for provenance)."""
    out, used = {}, []
    if not os.path.isdir(directory):
        return out, used
    for f in sorted(glob.glob(os.path.join(directory, "*.json"))):
        try:
            with open(f) as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            continue
        bars_map = payload.get("bars") if isinstance(payload, dict) else None
        if not isinstance(bars_map, dict):
            continue
        hit = False
        for sym in symbols:
            bars = bars_map.get(sym)
            if isinstance(bars, list) and bars:
                dm = {b["t"][:10]: b for b in bars if isinstance(b, dict) and b.get("t") and b.get("c")}
                if dm:
                    out[sym] = dm
                    hit = True
        if hit:
            used.append(f)
    return out, used


def splice_sources(per_source, symbols, max_rel_diff=0.01):
    """Splice per-source {sym: {date: bar}} maps, earliest source first.

    The first source that has a symbol is its base; later sources only APPEND
    dates strictly after the base's last date. On overlapping dates the closes
    must agree within `max_rel_diff` (else the splice is refused for that symbol
    and only the base is kept — never silently mixing inconsistent feeds).
    Returns (merged {sym: {date: bar}}, splice_checks list).
    """
    merged, checks = {}, []
    for sym in symbols:
        base = None
        for idx, src in enumerate(per_source):
            dm = src.get(sym)
            if not dm:
                continue
            if base is None:
                base = dict(dm)
                continue
            overlap = sorted(set(base) & set(dm))
            diffs = [abs(dm[d]["c"] / base[d]["c"] - 1.0) for d in overlap if base[d]["c"]]
            worst = max(diffs) if diffs else None
            ok = bool(overlap) and worst is not None and worst <= max_rel_diff
            last = max(base)
            appended = 0
            if ok:
                for d in sorted(dm):
                    if d > last:
                        base[d] = dm[d]
                        appended += 1
            checks.append({"symbol": sym, "source_index": idx, "overlap_days": len(overlap),
                           "max_rel_close_diff": round(worst, 6) if worst is not None else None,
                           "accepted": ok, "appended_days": appended})
        if base:
            merged[sym] = base
    return merged, checks


def align(merged, symbols):
    """Common date axis where EVERY symbol has a bar. Returns (dates, closes, opens, dropped)."""
    if any(s not in merged for s in symbols):
        return [], {}, {}, 0
    union = set().union(*(set(merged[s]) for s in symbols))
    dates = sorted(d for d in union if all(d in merged[s] for s in symbols))
    closes = {s: [float(merged[s][d]["c"]) for d in dates] for s in symbols}
    opens = {s: [float(merged[s][d].get("o") or merged[s][d]["c"]) for d in dates] for s in symbols}
    return dates, closes, opens, len(union) - len(dates)


def clip_span(merged, start=None, end=None):
    """Restrict every symbol's {date: bar} map to start <= date <= end (inclusive, ISO dates)."""
    if not start and not end:
        return merged
    lo, hi = start or "0000-00-00", end or "9999-99-99"
    return {s: {d: b for d, b in dm.items() if lo <= d <= hi} for s, dm in merged.items()}


def load_dataset(sources, symbols, max_rel_diff=0.01, root=ROOT, start=None, end=None):
    """Load + splice + (optionally) clip to [start, end] + align. Without start/end
    this is exactly the v1 behaviour."""
    per_source, files = [], []
    for src in sources:
        bars, used = _bars_in_dir(os.path.join(root, src), symbols)
        per_source.append(bars)
        files += used
    merged, checks = splice_sources(per_source, symbols, max_rel_diff)
    merged = clip_span(merged, start, end)
    dates, closes, opens, dropped = align(merged, symbols)
    return {"dates": dates, "closes": closes, "opens": opens, "dropped_dates": dropped,
            "splice_checks": checks, "files": files,
            "sources_present": [s for s, b in zip(sources, per_source) if b]}


# ---------------------------------------------------------------------------
# Simulation (pure)
# ---------------------------------------------------------------------------

def simulate_core(dates, closes, opens, symbols, target_weight, max_weight, cost_frac, initial=1.0):
    """Equal-weight core with monthly rebalance + cap drift guard.

    Returns dict(equity=[initial, close_0, close_1, ...], turnover, costs,
    n_rebalances, n_cap_trims, max_post_trade_weight, max_close_weight).
    Rebalance on bar 0 and on the first bar of each calendar month, at the OPEN.
    A symbol whose CLOSE weight exceeds max_weight is trimmed to target at the
    NEXT open (decision at close t, execution at open t+1 — no look-ahead); at that
    trade event any other symbol above the cap at the same open is trimmed too, so
    no weight exceeds max_weight immediately after a trade. Between trades, close
    weights can drift above the cap for one bar (reported as max_close_weight).
    """
    n = len(dates)
    hold = {s: 0.0 for s in symbols}
    cash = float(initial)
    equity = [float(initial)]
    turnover = costs = 0.0
    n_reb = n_trim = 0
    max_post = max_close = 0.0
    pending_trim = set()

    for t in range(n):
        month_start = t == 0 or dates[t][:7] != dates[t - 1][:7]
        value = cash + sum(hold[s] * opens[s][t] for s in symbols)
        if month_start:
            to_trade = list(symbols)
        elif pending_trim:
            # Trade event: trim the close-breach names AND any name above the cap at
            # this open (sized at the open we trade at), so no post-trade weight > cap.
            over_at_open = {s for s in symbols if value > 0 and hold[s] * opens[s][t] / value > max_weight}
            to_trade = sorted(pending_trim | over_at_open)
        else:
            to_trade = []
        if to_trade:
            for s in to_trade:
                px = opens[s][t]
                trade_val = target_weight * value - hold[s] * px
                fee = abs(trade_val) * cost_frac
                hold[s] += trade_val / px
                cash -= trade_val + fee
                turnover += abs(trade_val)
                costs += fee
            if month_start:
                n_reb += 1
            else:
                n_trim += len(to_trade)
            post_val = cash + sum(hold[s] * opens[s][t] for s in symbols)
            if post_val > 0:
                max_post = max(max_post, max(hold[s] * opens[s][t] / post_val for s in symbols))
        pending_trim = set()

        eq = cash + sum(hold[s] * closes[s][t] for s in symbols)
        equity.append(eq)
        if eq > 0:
            for s in symbols:
                w = hold[s] * closes[s][t] / eq
                max_close = max(max_close, w)
                if w > max_weight:
                    pending_trim.add(s)

    return {"equity": equity, "turnover": turnover, "costs": costs, "n_rebalances": n_reb,
            "n_cap_trims": n_trim, "max_post_trade_weight": max_post, "max_close_weight": max_close}


def simulate_buy_hold(closes, opens, cost_frac, initial=1.0):
    """100% buy & hold from bar-0 open, entry friction charged once."""
    shares = initial / (opens[0] * (1.0 + cost_frac))
    return [float(initial)] + [shares * c for c in closes]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def moments(xs):
    """(skew, kurtosis) — kurtosis NOT excess (normal = 3). Pure stdlib."""
    n = len(xs)
    if n < 3:
        return 0.0, 3.0
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / n
    if var <= 0:
        return 0.0, 3.0
    sd = math.sqrt(var)
    skew = sum(((x - m) / sd) ** 3 for x in xs) / n
    kurt = sum(((x - m) / sd) ** 4 for x in xs) / n
    return skew, kurt


def window_bounds(n_bars, window_bars):
    """Non-overlapping windows aligned to the END of the series: [(a, b), ...]."""
    k = n_bars // window_bars
    offset = n_bars - k * window_bars
    return [(offset + j * window_bars, offset + (j + 1) * window_bars) for j in range(k)]


def _window_stats(equity, a, b):
    eq = equity[a:b + 1]                         # equity[i] = value BEFORE bar i's close
    rets = metrics.returns_from_equity(eq)
    return {"sharpe": round(metrics.sharpe_ratio(rets), 4),
            "max_drawdown": round(metrics.max_drawdown(eq), 4),
            "cagr": round(metrics.cagr(eq), 4),
            "total_return": round(metrics.total_return(eq), 4)}


def _full_stats(equity):
    rets = metrics.returns_from_equity(equity)
    return {"sharpe": round(metrics.sharpe_ratio(rets), 4),
            "max_drawdown": round(metrics.max_drawdown(equity), 4),
            "cagr": round(metrics.cagr(equity), 4),
            "total_return": round(metrics.total_return(equity), 4),
            "annual_volatility": round(metrics.annualized_volatility(rets), 4)}


def cpcv_distribution(core_rets, spy_rets, cfg):
    """Sharpe of core / SPY / difference on every CPCV test set (dispersion check)."""
    n = len(core_rets)
    ng, nt = int(cfg.get("n_groups", 6)), int(cfg.get("n_test_groups", 2))
    if n < ng * 10:
        return {"status": "INSUFFICIENT_DATA", "n_obs": n}
    core_s, spy_s, diff = [], [], []
    for sp in combinatorial_splits(n, ng, nt, label_horizon=cfg.get("label_horizon", 0),
                                   embargo_pct=cfg.get("embargo_pct", 0.0)):
        c = metrics.sharpe_ratio([core_rets[i] for i in sp["test_idx"]])
        s = metrics.sharpe_ratio([spy_rets[i] for i in sp["test_idx"]])
        core_s.append(c)
        spy_s.append(s)
        diff.append(c - s)

    def dist(xs):
        xs = sorted(xs)
        mid = len(xs) // 2
        med = xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2
        return {"min": round(xs[0], 4), "median": round(med, 4), "max": round(xs[-1], 4)}

    return {"n_splits": len(diff), "n_paths": n_backtest_paths(ng, nt),
            "core_sharpe": dist(core_s), "spy_sharpe": dist(spy_s), "diff_sharpe": dist(diff),
            "frac_core_sharpe_gt_0": round(sum(1 for x in core_s if x > 0) / len(core_s), 4),
            "frac_diff_ge_minus_0_15": round(sum(1 for x in diff if x >= -0.15) / len(diff), 4),
            "note": ("Zero fitted parameters, so there is no training set: CPCV here is a "
                     "combinatorial subsample-robustness check of the same path, not independent "
                     "OOS paths. Informational; not an acceptance criterion.")}


def dsr_with_trial_count(sr, n_obs, n_trials, skew=0.0, kurtosis=3.0):
    """Deflated Sharpe when only the TRIAL COUNT is known (not each trial's Sharpe).

    N <= 1: plain ``metrics.deflated_sharpe_ratio([sr])`` (== PSR vs 0).
    N > 1: benchmark = expected max Sharpe of N zero-skill trials under the null,
    whose per-period Sharpe estimates have variance ~ 1/(n_obs-1) (Bailey & Lopez de
    Prado, False Strategy Theorem), then ``metrics.probabilistic_sharpe_ratio``.
    """
    if n_obs < 2:
        return 0.0
    if n_trials <= 1:
        return metrics.deflated_sharpe_ratio([sr], n_obs, skew, kurtosis)
    gamma = 0.5772156649015329
    z1 = metrics.inverse_normal_cdf(1.0 - 1.0 / n_trials)
    z2 = metrics.inverse_normal_cdf(1.0 - 1.0 / (n_trials * math.e))
    sr0 = math.sqrt(1.0 / (n_obs - 1)) * ((1.0 - gamma) * z1 + gamma * z2)
    return metrics.probabilistic_sharpe_ratio(sr, sr0, n_obs, skew, kurtosis)


def psr_dsr(core_rets, spy_rets, n_trials):
    n = len(core_rets)
    sd = metrics._std(core_rets)
    sr = metrics._mean(core_rets) / sd if sd else 0.0
    sd_b = metrics._std(spy_rets)
    sr_spy = metrics._mean(spy_rets) / sd_b if sd_b else 0.0
    skew, kurt = moments(core_rets)
    return {"n_obs": n, "per_period_sharpe": round(sr, 5), "skew": round(skew, 4),
            "kurtosis": round(kurt, 4), "n_trials": n_trials,
            "psr_vs_0": round(metrics.probabilistic_sharpe_ratio(sr, 0.0, n, skew, kurt), 4),
            "dsr": round(dsr_with_trial_count(sr, n, n_trials, skew, kurt), 4),
            "psr_vs_spy_observed_sharpe": round(
                metrics.probabilistic_sharpe_ratio(sr, sr_spy, n, skew, kurt), 4),
            "note": ("DSR with N=1 equals PSR vs 0 (no fitted parameters). psr_vs_spy treats SPY's "
                     "observed Sharpe as a fixed benchmark (ignores its own sampling error).")}


def evaluate_dataset(ds, spec, cost_frac):
    """Run the spec on one aligned dataset. Pure given `ds`."""
    ev = spec["evaluation"]
    symbols = spec["symbols"]
    dates = ds["dates"]
    wb, min_w = int(ev["window_bars"]), int(ev["min_windows"])
    bounds = window_bounds(len(dates), wb)
    base = {"n_bars": len(dates), "data_span": [dates[0], dates[-1]] if dates else None,
            "dropped_dates": ds.get("dropped_dates", 0), "n_windows": len(bounds)}
    if len(bounds) < min_w:
        base.update({"status": "INSUFFICIENT_DATA",
                     "reason": f"{len(dates)} aligned bars -> {len(bounds)} windows of {wb} < {min_w} required"})
        return base

    core = simulate_core(dates, ds["closes"], ds["opens"], symbols,
                         float(spec["target_weight"]), float(spec["max_weight"]), cost_frac)
    spy_eq = simulate_buy_hold(ds["closes"][BENCHMARK], ds["opens"][BENCHMARK], cost_frac)
    core_eq = core["equity"]

    windows = []
    for (a, b) in bounds:
        windows.append({"start": dates[a], "end": dates[b - 1],
                        "core": _window_stats(core_eq, a, b), "spy": _window_stats(spy_eq, a, b)})
    mean_core = sum(w["core"]["sharpe"] for w in windows) / len(windows)
    mean_spy = sum(w["spy"]["sharpe"] for w in windows) / len(windows)
    full_core, full_spy = _full_stats(core_eq), _full_stats(spy_eq)

    acc = spec["acceptance"]
    c1_thr = float(acc["C1_sharpe_vs_spy"]["threshold"])
    c1_val = mean_core - mean_spy
    core_rets = metrics.returns_from_equity(core_eq)
    spy_rets = metrics.returns_from_equity(spy_eq)

    base.update({
        "status": "EVALUATED",
        "windows": windows,
        "summary": {
            "mean_window_sharpe_core": round(mean_core, 4),
            "mean_window_sharpe_spy": round(mean_spy, 4),
            "windows_core_sharpe_ge_spy_minus_0_15": sum(
                1 for w in windows if w["core"]["sharpe"] >= w["spy"]["sharpe"] + c1_thr),
            "windows_core_dd_le_spy_dd": sum(
                1 for w in windows if w["core"]["max_drawdown"] <= w["spy"]["max_drawdown"]),
            "full_span_core": full_core, "full_span_spy": full_spy,
            "implementation": {
                "n_rebalances": core["n_rebalances"], "n_cap_trims": core["n_cap_trims"],
                "max_post_trade_weight": round(core["max_post_trade_weight"], 5),
                "max_close_weight_before_trim": round(core["max_close_weight"], 5),
                "turnover_x_initial": round(core["turnover"], 4),
                "costs_x_initial": round(core["costs"], 6)},
        },
        "cpcv": cpcv_distribution(core_rets, spy_rets, ev.get("cpcv", {})),
        "psr_dsr": psr_dsr(core_rets, spy_rets, int(spec.get("n_trials", 1))),
        "criteria": {
            "C1_sharpe_vs_spy": {"value": round(c1_val, 4), "threshold": c1_thr,
                                 "result": "PASS" if c1_val >= c1_thr else "FAIL"},
            "C2_drawdown_vs_spy": {"core_mdd": full_core["max_drawdown"], "spy_mdd": full_spy["max_drawdown"],
                                   "result": ("PASS" if full_core["max_drawdown"] <= full_spy["max_drawdown"]
                                              else "FAIL")},
        },
    })
    return base


def combine_acceptance(dataset_results, spec):
    """Robustness rule: a criterion PASSes only if it passes on every EVALUATED dataset."""
    evaluated = [r for r in dataset_results.values() if r.get("status") == "EVALUATED"]
    out = {}
    for key in ("C1_sharpe_vs_spy", "C2_drawdown_vs_spy"):
        if not evaluated:
            out[key] = "INSUFFICIENT_DATA"
        elif all(r["criteria"][key]["result"] == "PASS" for r in evaluated):
            out[key] = "PASS"
        else:
            out[key] = "FAIL"
    out["C3_live_tracking_error"] = spec["acceptance"]["C3_live_tracking_error"].get(
        "status_until_measured", "PENDING_LIVE")
    if "FAIL" in out.values():
        overall = "FAIL"
    elif "INSUFFICIENT_DATA" in out.values():
        overall = "INSUFFICIENT_DATA"
    elif all(v == "PASS" for v in out.values()):
        overall = "PASS"
    else:
        overall = "PASS_BACKTEST_PENDING_LIVE"
    out["overall"] = overall
    return out


def run(spec_path=SPEC_PATH, out_path=OUT_PATH, root=ROOT, write=True, bars_dir=None):
    """Evaluate a spec. ``bars_dir`` (repo-relative) overrides every dataset's sources
    with that single directory (e.g. a total-return cache); spans still come from the
    spec's per-dataset ``start``/``end``. Default (None) is the v1 behaviour."""
    spec = load_spec(spec_path)
    cost_bps, slip_bps = load_friction("portfolio_1", data_dir=os.path.join(root, "data"))
    cost_frac = (cost_bps + slip_bps) / 10_000.0
    ev = spec["evaluation"]
    results, files = {}, []
    for d in ev["datasets"]:
        sources = [bars_dir] if bars_dir else d["sources"]
        ds = load_dataset(sources, spec["symbols"], float(ev.get("splice_max_rel_close_diff", 0.01)), root,
                          start=d.get("start"), end=d.get("end"))
        files += ds["files"]
        if not ds["dates"]:
            results[d["id"]] = {"status": "NOT_AVAILABLE" if not d.get("required") else "INSUFFICIENT_DATA",
                                "sources_present": ds["sources_present"]}
            continue
        r = evaluate_dataset(ds, spec, cost_frac)
        r["sources_present"] = ds["sources_present"]
        r["splice_checks"] = ds["splice_checks"]
        results[d["id"]] = r

    acceptance = combine_acceptance(results, spec)
    caveats = list(spec.get("known_biases", [])) + [
        spec.get("prior_knowledge_disclosure", ""),
        spec.get("deliberate_second_test", ""),
        "Regime coverage: the mid-2023-onward span is a predominantly rising-equity regime; "
        "only the 2021-06-onward span includes the 2022 joint bond+equity drawdown.",
        "Survivorship: the universe is 8 large, long-lived ETFs chosen today; no delisting risk modeled.",
        "Backtest is simulation (hypothetical, paper) — not live performance.",
    ]
    out = {
        "spec_id": spec["spec_id"], "spec_hash": spec_hash(spec),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "friction_bps_per_side": {"cost": cost_bps, "slippage": slip_bps},
        "bar_adjustment": ev.get("bar_adjustment", "split (price-only)"),
        "bars_dir_override": bars_dir,
        "data_span": {k: v.get("data_span") for k, v in results.items()},
        "datasets": results,
        "acceptance": acceptance,
        "caveats": [c for c in caveats if c],
        "disclosure": "Hypothetical/paper research for internal model-risk use — not investment advice.",
    }
    if write:
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2)
            f.write("\n")
        try:
            from shared.research_provenance import write_provenance
            write_provenance(out_path, [spec_path] + sorted(set(files)), warnings=out["caveats"],
                             source="scripts/research/passive_core_eval.py",
                             extra={"spec_hash": out["spec_hash"]})
        except OSError:
            pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evaluate the pre-registered passive core spec.")
    ap.add_argument("--spec", default=SPEC_PATH)
    ap.add_argument("--out", default=OUT_PATH)
    ap.add_argument("--bars-dir", default=None,
                    help="repo-relative bar-cache dir overriding every dataset's sources "
                         "(e.g. data/research_cache/adj_bars for total-return bars)")
    args = ap.parse_args(argv)
    out = run(args.spec, args.out, bars_dir=args.bars_dir)
    print(f"Wrote {args.out}  spec_hash={out['spec_hash'][:12]}")
    for k, r in out["datasets"].items():
        if r.get("status") != "EVALUATED":
            print(f"  [{k}] {r.get('status')} {r.get('reason', '')}")
            continue
        s = r["summary"]
        print(f"  [{k}] span={r['data_span']} bars={r['n_bars']} windows={r['n_windows']} "
              f"meanSharpe core={s['mean_window_sharpe_core']} spy={s['mean_window_sharpe_spy']} "
              f"MDD core={s['full_span_core']['max_drawdown']} spy={s['full_span_spy']['max_drawdown']} "
              f"C1={r['criteria']['C1_sharpe_vs_spy']['result']} C2={r['criteria']['C2_drawdown_vs_spy']['result']}")
    print(f"  acceptance: {out['acceptance']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
