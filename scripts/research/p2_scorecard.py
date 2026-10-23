#!/usr/bin/env python3
"""P2 satellite scorecard (OFFLINE research lane, measurement only, pure Python).

Scores the LIVE P2 copy-trade sleeve against the pre-registered acceptance test in
``docs/specs/p2_satellite.json``: per closed round trip, realized return vs a
beta-matched SPY return over the same holding window, then mean alpha, alpha
t-stat, profit factor, N and a Deflated Sharpe with an honest trial count.
Entries before / after the 2026-07-04 pipeline change are separate cohorts; only
the post cohort is gated (N >= 50, alpha t >= 2.0, PF >= 1.3, DSR >= 0.95).

Never imputes: lots with an open remainder or a slice closed without a recorded
pnl are excluded and counted; trades outside the cached SPY history are
unbenchmarkable and counted. Reads committed files only, places no orders.
"""
import argparse
import glob
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
from research.passive_core_eval import dsr_with_trial_count, load_dataset, moments, spec_hash  # noqa: E402

SPEC_PATH = os.path.join(ROOT, "docs", "specs", "p2_satellite.json")
TRADE_LOG = os.path.join(ROOT, "political-copy-bot", "data", "trade_log.json")
JOURNAL_DIR = os.path.join(ROOT, "political-copy-bot", "journal")
OUT_PATH = os.path.join(ROOT, "data", "p2_scorecard.json")
SPY_SOURCES = ["data/deep", "data"]
TRIAL_ARTIFACTS = ["p2_congress_copy_backtest.json", "p2_congress_technical_confirmation_backtest.json",
                   "p2_cluster_buy_backtest.json"]
LIVE_PIPELINE_VERSIONS = 2
BETA_MIN_R2 = 0.3


# ---------------------------------------------------------------------------
# Lots
# ---------------------------------------------------------------------------

def _is_sleeve(row):
    return ("benchmark_sleeve" in (row.get("source"), row.get("strategy"))
            or row.get("politician") == "BENCHMARK_SLEEVE")


def _slice_closed(row):
    return row.get("status") in ("closed", "closed_reconciled") or bool(row.get("exit_timestamp"))


def _slice_pnl(row):
    for k in ("realized_pnl", "pnl"):
        v = row.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def build_lots(trade_log):
    """Group BUY rows into lots by order_id (fallback symbol|date), in log order."""
    lots = {}
    for row in trade_log or []:
        if not isinstance(row, dict) or row.get("side") != "buy" or _is_sleeve(row):
            continue
        key = row.get("order_id") or f"{row.get('symbol')}|{row.get('date')}"
        lots.setdefault(key, []).append(row)
    return lots


def classify_lot(slices):
    """CLOSED | PARTIAL (some slices open) | OPEN | UNPRICED (closed, pnl missing)."""
    closed = [s for s in slices if _slice_closed(s)]
    if len(closed) < len(slices):
        return "PARTIAL" if closed else "OPEN"
    if any(_slice_pnl(s) is None for s in slices):
        return "UNPRICED"
    return "CLOSED"


# ---------------------------------------------------------------------------
# SPY benchmark + beta
# ---------------------------------------------------------------------------

def spy_close_map(root=ROOT, sources=None):
    ds = load_dataset(sources or SPY_SOURCES, ["SPY"], root=root)
    return dict(zip(ds["dates"], ds["closes"].get("SPY", []))), ds["files"]


def close_on_or_before(spy, dates_sorted, d):
    """SPY close on date d, or the last close before d. None if d is outside history."""
    if not dates_sorted or d < dates_sorted[0] or d > dates_sorted[-1]:
        return None
    lo, hi = 0, len(dates_sorted) - 1
    while lo < hi:                                  # rightmost date <= d
        mid = (lo + hi + 1) // 2
        if dates_sorted[mid] <= d:
            lo = mid
        else:
            hi = mid - 1
    return spy[dates_sorted[lo]]


def score_lot(slices, spy, spy_dates, beta=1.0):
    """Per-lot record, or (None, reason) if it cannot be benchmarked."""
    entry_date = min(s.get("date") or "" for s in slices)
    cost = pnl = spy_w = 0.0
    basis_limit = False
    exit_dates = []
    for s in slices:
        qty = float(s.get("qty") or 0)
        px = s.get("entry_price")
        if not px:
            px, basis_limit = s.get("limit_price"), True
        if not qty or not px:
            return None, "missing_qty_or_basis"
        exit_d = (s.get("exit_timestamp") or "")[:10]
        p0 = close_on_or_before(spy, spy_dates, s.get("date") or entry_date)
        p1 = close_on_or_before(spy, spy_dates, exit_d)
        if p0 is None or p1 is None:
            return None, "outside_spy_history"
        c = qty * float(px)
        cost += c
        pnl += _slice_pnl(s)
        spy_w += c * (p1 / p0 - 1.0)
        exit_dates.append(exit_d)
    r = pnl / cost
    spy_r = spy_w / cost
    return {"symbol": slices[0].get("symbol"), "entry_date": entry_date, "exit_date": max(exit_dates),
            "n_slices": len(slices), "cost_basis": round(cost, 2), "pnl": round(pnl, 2),
            "return": round(r, 6), "spy_return": round(spy_r, 6), "alpha": round(r - beta * spy_r, 6),
            "basis_from_limit_price": basis_limit}, None


def book_beta(journal_dir, spy, spy_dates):
    """OLS beta of P2 book equity (last journal snapshot per day) vs SPY closes."""
    snaps = {}
    for f in sorted(glob.glob(os.path.join(journal_dir, "*.json"))):
        try:
            with open(f) as fh:
                entries = json.load(fh)
        except (OSError, ValueError):
            continue
        for e in entries if isinstance(entries, list) else [entries]:
            try:
                d, eq = e["date"], float(e["account_snapshot"]["equity"])
            except (KeyError, TypeError, ValueError):
                continue
            ts = e.get("timestamp") or ""
            if d not in snaps or ts >= snaps[d][0]:
                snaps[d] = (ts, eq)
    days = sorted(d for d in snaps if d in spy)
    xs, ys = [], []
    for d0, d1 in zip(days, days[1:]):
        e0, e1 = snaps[d0][1], snaps[d1][1]
        if e0 > 0:
            ys.append(e1 / e0 - 1.0)
            xs.append(spy[d1] / spy[d0] - 1.0)
    n = len(xs)
    if n < 20:
        return {"beta": None, "n_pairs": n, "reason": "fewer than 20 paired days"}
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    if vx <= 0:
        return {"beta": None, "n_pairs": n, "reason": "zero SPY variance"}
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vy = sum((y - my) ** 2 for y in ys)
    beta = cov / vx
    r2 = cov * cov / (vx * vy) if vy > 0 else 0.0
    reliable = r2 >= BETA_MIN_R2 and 0.0 < beta < 2.0
    return {"beta": round(beta, 4), "n_pairs": n, "r_squared": round(r2, 4),
            "reliable": reliable,
            "reliability_rule": f"r_squared >= {BETA_MIN_R2} and 0 < beta < 2; otherwise not used even as a sensitivity",
            "span": [days[0], days[-1]],
            "caveat": ("Intraday-timestamped snapshots vs SPY closes (asynchronous) and a book "
                       "blended with the benchmark ETF sleeve + cash: diagnostic only.")}


# ---------------------------------------------------------------------------
# Statistics + verdict
# ---------------------------------------------------------------------------

def honest_trial_count(data_dir):
    """Distinct P2 configurations in committed research + lag grid + live versions."""
    def count_overall(o):
        if isinstance(o, dict):
            return (1 if "overall" in o else 0) + sum(count_overall(v) for v in o.values())
        if isinstance(o, list):
            return sum(count_overall(v) for v in o)
        return 0

    parts = {}
    for name in TRIAL_ARTIFACTS:
        try:
            with open(os.path.join(data_dir, name)) as f:
                parts[name] = count_overall(json.load(f))
        except (OSError, ValueError):
            parts[name] = 0
    try:
        with open(os.path.join(data_dir, "p2_disclosure_lag_study.json")) as f:
            grid = (json.load(f).get("search") or {}).get("max_disclosure_age_days") or []
        parts["p2_disclosure_lag_study.json"] = len(grid)
    except (OSError, ValueError):
        parts["p2_disclosure_lag_study.json"] = 0
    parts["live_pipeline_versions"] = LIVE_PIPELINE_VERSIONS
    return max(1, sum(parts.values())), parts


def cohort_stats(records, n_trials, min_n, book_beta_value=None):
    n = len(records)
    out = {"n": n}
    if n == 0:
        return out
    alphas = [r["alpha"] for r in records]
    rets = [r["return"] for r in records]
    out.update({
        "mean_return": round(sum(rets) / n, 6),
        "mean_spy_return": round(sum(r["spy_return"] for r in records) / n, 6),
        "mean_alpha": round(sum(alphas) / n, 6),
        "win_rate": round(sum(1 for r in rets if r > 0) / n, 4),
        "profit_factor": _pf(records),
        "profit_factor_no_losses": metrics.profit_factor([r["pnl"] for r in records]) == float("inf"),
        "total_pnl": round(sum(r["pnl"] for r in records), 2),
        "n_basis_from_limit_price": sum(1 for r in records if r["basis_from_limit_price"]),
    })
    sd = metrics._std(alphas)
    out["alpha_sd"] = round(sd, 6)
    out["alpha_t"] = round((sum(alphas) / n) / (sd / math.sqrt(n)), 4) if n >= 2 and sd > 0 else None
    if book_beta_value is not None and n >= 2:
        a2 = [r["return"] - book_beta_value * r["spy_return"] for r in records]
        sd2 = metrics._std(a2)
        out["sensitivity_book_beta"] = {
            "beta": book_beta_value, "mean_alpha": round(sum(a2) / n, 6),
            "alpha_t": round((sum(a2) / n) / (sd2 / math.sqrt(n)), 4) if sd2 > 0 else None}
    if n >= min_n and sd > 0:
        skew, kurt = moments(alphas)
        sr = (sum(alphas) / n) / sd
        out["dsr"] = round(dsr_with_trial_count(sr, n, n_trials, skew, kurt), 4)
    else:
        out["dsr"] = None
        out["dsr_reason"] = f"refused: N={n} < {min_n} (too few round trips for a DSR verdict)"
    return out


def _pf(records):
    pf = metrics.profit_factor([r["pnl"] for r in records])
    return None if pf == float("inf") else round(pf, 4)


def verdict(stats, acc):
    n = stats.get("n", 0)
    min_n = int(acc["min_n"])
    checks = {
        "n": {"value": n, "threshold": min_n, "result": "PASS" if n >= min_n else "INSUFFICIENT_N"},
        "alpha_t": {"value": stats.get("alpha_t"), "threshold": acc["alpha_t_min"]},
        "profit_factor": {"value": stats.get("profit_factor"), "threshold": acc["profit_factor_min"]},
        "dsr": {"value": stats.get("dsr"), "threshold": acc["dsr_min"]},
    }
    for k in ("alpha_t", "profit_factor", "dsr"):
        v = checks[k]["value"]
        if n < min_n:
            checks[k]["result"] = "INSUFFICIENT_N"
        elif k == "profit_factor" and stats.get("profit_factor_no_losses"):
            checks[k]["result"] = "PASS"                # wins and no losses: PF is +inf
        else:
            checks[k]["result"] = "PASS" if v is not None and v >= checks[k]["threshold"] else "FAIL"
    if n < min_n:
        status = "INSUFFICIENT_N"
    else:
        status = "PASS" if all(checks[k]["result"] == "PASS" for k in ("alpha_t", "profit_factor", "dsr")) else "FAIL"
    return status, checks


def run(spec_path=SPEC_PATH, trade_log_path=TRADE_LOG, journal_dir=JOURNAL_DIR, out_path=OUT_PATH,
        root=ROOT, write=True):
    with open(spec_path) as f:
        spec = json.load(f)
    with open(trade_log_path) as f:
        trade_log = json.load(f)
    acc = spec["acceptance"]
    split = spec["cohorts"]["split_date"]
    beta = float(spec["beta_policy"]["gate_beta"])
    spy, spy_files = spy_close_map(root)
    spy_dates = sorted(spy)

    lots = build_lots(trade_log)
    counts = {"lots": len(lots), "CLOSED": 0, "PARTIAL": 0, "OPEN": 0, "UNPRICED": 0, "unbenchmarkable": 0}
    excluded, cohorts = [], {"pre": [], "post": []}
    for key, slices in lots.items():
        cls = classify_lot(slices)
        counts[cls] += 1
        entry_date = min(s.get("date") or "" for s in slices)
        if cls != "CLOSED":
            excluded.append({"lot": key, "symbol": slices[0].get("symbol"), "entry_date": entry_date,
                             "reason": cls})
            continue
        rec, why = score_lot(slices, spy, spy_dates, beta)
        if rec is None:
            counts["unbenchmarkable"] += 1
            excluded.append({"lot": key, "symbol": slices[0].get("symbol"), "entry_date": entry_date,
                             "reason": why})
            continue
        cohorts["post" if entry_date > split else "pre"].append(rec)

    n_trials, trial_parts = honest_trial_count(os.path.join(root, "data"))
    bb = book_beta(journal_dir, spy, spy_dates)
    min_n = int(acc["min_n"])
    sens_beta = bb.get("beta") if bb.get("reliable") else None
    stats = {k: cohort_stats(v, n_trials, min_n, sens_beta) for k, v in cohorts.items()}
    status, checks = verdict(stats["post"], acc)
    out = {
        "spec_id": spec["spec_id"], "spec_hash": spec_hash(spec),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "gated_cohort": "post",
        "acceptance": checks,
        "beta_used": beta,
        "book_beta_diagnostic": bb,
        "honest_trial_count": {"n_trials": n_trials, "derivation": trial_parts},
        "spy_history": [spy_dates[0], spy_dates[-1]] if spy_dates else None,
        "lot_counts": counts,
        "cohorts": {k: {"stats": stats[k], "round_trips": cohorts[k]} for k in cohorts},
        "excluded_lots": excluded,
        "caveats": [
            "Measurement only — no live parameter or order is changed by this artifact.",
            "Pre cohort lots use the old Capitol-Trades pipeline and some cost bases come from the "
            "submitted limit price (entry_price absent); informational, never gated.",
            "SPY window = close on entry date -> close on exit date (entries/exits are intraday).",
            "Survivorship/selection: only disclosures the pipeline captured; Senate filings not covered "
            "while Capitol Trades is WAF-blocked.",
            "Paper fills; live fills may differ.",
        ],
        "disclosure": "Hypothetical/paper research for internal model-risk use — not investment advice.",
    }
    if write:
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2)
            f.write("\n")
        try:
            from shared.research_provenance import write_provenance
            inputs = [spec_path, trade_log_path] + spy_files + [
                os.path.join(root, "data", n) for n in TRIAL_ARTIFACTS + ["p2_disclosure_lag_study.json"]]
            write_provenance(out_path, inputs, warnings=out["caveats"],
                             source="scripts/research/p2_scorecard.py", extra={"spec_hash": out["spec_hash"]})
        except OSError:
            pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="P2 satellite scorecard (measurement only).")
    ap.add_argument("--spec", default=SPEC_PATH)
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args(argv)
    out = run(args.spec, out_path=args.out)
    print(f"Wrote {args.out}  status={out['status']}  spec_hash={out['spec_hash'][:12]}")
    print(f"  lots={out['lot_counts']}  n_trials={out['honest_trial_count']['n_trials']}  "
          f"book_beta={out['book_beta_diagnostic'].get('beta')} "
          f"reliable={out['book_beta_diagnostic'].get('reliable')}")
    for k, c in out["cohorts"].items():
        print(f"  [{k}] {c['stats']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
