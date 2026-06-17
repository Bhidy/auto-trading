#!/usr/bin/env python3
"""P2 (Capitol Shadow) disclosure-lag tuning study — OFFLINE research lane.

Formalizes the deferred P2 question: is there a profit-maximizing
``max_disclosure_age_days`` for copy-trading US-politician disclosures? Per the
red-team this is COMMITTEE-GATED and must clear PBO + deflated-Sharpe with a
hard N-floor; on thin, survivorship-biased disclosure history it is EXPECTED to
refuse to assert. This script builds the real machinery that produces that
honest verdict now and a real number the moment enough closed round-trips exist.

Emits a STATIC artifact (``data/p2_disclosure_lag_study.json``) the cloud path
may READ but never imports — invariant A. Pure-stdlib; reuses the project's own
deflated-Sharpe / PBO / friction implementations (no numpy/pandas).

Honesty policy (mirrors calibrate_friction):
  * Below ``--min-sample-n`` closed round-trips -> verdict REFUSE_TO_ASSERT.
  * Returns are NET of round-trip friction (entry + exit) read from the same
    ``data/fee_source.json`` the rest of the backtest stack uses — never a
    gross, friction-blind Sharpe.
  * The grid searches ``max_disclosure_age_days`` ONLY. Holding-period tuning is
    deliberately NOT searched: re-simulating a different holding period needs
    per-trade price paths (bar data), which closed round-trips do not carry —
    so claiming an optimized holding period would be fabricated. It is listed as
    a further data requirement instead.
  * DSR is fed PER-PERIOD Sharpes (its contract); the >= floor gate uses the
    ANNUALIZED Sharpe (the LIVE_READINESS bar is annualized). PBO is the
    overfitting / out-of-sample guard; the Sharpe floor is in-sample.
  * GO requires ALL of: PBO <= pbo_max, DSR >= dsr_min, best annualized Sharpe
    >= sharpe_min. Anything else is NO_GO. Failing closed is correct.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

from backtest.friction import load_friction  # noqa: E402
from backtest.metrics import (  # noqa: E402
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_ratio,
)

P2_LOG = os.path.join(ROOT, "political-copy-bot", "data", "trade_log.json")

# The single dimension the study can honestly search from closed round-trips.
AGE_GRID = [15, 30, 45, 60]        # max_disclosure_age_days
N_TIME_SLICES = 8                  # PBO needs >= 4 columns
GATE = {"pbo_max": 0.5, "dsr_min": 0.95, "sharpe_min": 1.0}


def _price(rec):
    for k in ("exit_price", "entry_price", "fill_price", "limit_price", "price"):
        v = rec.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def _age_days(rec):
    """Disclosure age in days if derivable, else None (the data gap we flag)."""
    v = rec.get("disclosure_age_days")
    if isinstance(v, (int, float)):
        return float(v)
    d, obs = rec.get("disclosure_date"), rec.get("date") or rec.get("timestamp")
    if d and obs:
        try:
            d0 = datetime.fromisoformat(str(d)[:10])
            d1 = datetime.fromisoformat(str(obs)[:10])
            return (d1 - d0).days
        except ValueError:
            return None
    return None


def reconstruct_round_trips(log):
    """FIFO-match BUY -> later SELL of the same symbol into realized round-trips."""
    if not isinstance(log, list):
        return []
    open_buys = {}
    trips = []
    for rec in log:
        if not isinstance(rec, dict):
            continue
        sym = rec.get("symbol")
        side = str(rec.get("side", "")).lower()
        px = _price(rec)
        if not sym or px is None:
            continue
        if side.startswith("b"):
            open_buys.setdefault(sym, []).append(rec)
        elif side.startswith("s") and open_buys.get(sym):
            entry = open_buys[sym].pop(0)
            epx = _price(entry)
            if not epx:
                continue
            trips.append({
                "symbol": sym,
                "ret": (px - epx) / epx,
                "entry_date": str(entry.get("date") or entry.get("timestamp") or ""),
                "disclosure_age_days": _age_days(entry),
            })
    return trips


def _slice_returns(rets, n_slices):
    """Split a chronological return list into n_slices mean-return buckets."""
    if len(rets) < n_slices:
        return None
    size = len(rets) / n_slices
    out = []
    for i in range(n_slices):
        lo, hi = int(i * size), int((i + 1) * size)
        chunk = rets[lo:hi] or rets[lo:lo + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def round_trip_friction(portfolio="portfolio_2"):
    """Net round-trip friction (entry + exit) as a return fraction, from fee_source."""
    cost_bps, slip_bps = load_friction(portfolio)
    return 2.0 * (cost_bps + slip_bps) / 10_000.0


def run_grid(round_trips, rt_friction):
    """Per-age Sharpe (net of friction), the PBO matrix, DSR, and the best age."""
    combos = []
    perf_matrix = []
    for age in AGE_GRID:
        rets = [t["ret"] - rt_friction for t in round_trips
                if t["disclosure_age_days"] is None or t["disclosure_age_days"] <= age]
        sr_ann = sharpe_ratio(rets) if len(rets) >= 2 else None              # annualized (reported + gate)
        sr_pp = sharpe_ratio(rets, periods_per_year=1) if len(rets) >= 2 else None  # per-period (DSR contract)
        row = _slice_returns(rets, N_TIME_SLICES)
        combos.append({"max_disclosure_age_days": age, "n": len(rets),
                       "sharpe_annualized": round(sr_ann, 4) if sr_ann is not None else None,
                       "sharpe_per_period": round(sr_pp, 6) if sr_pp is not None else None})
        if row is not None:
            perf_matrix.append(row)
    pp_sharpes = [c["sharpe_per_period"] for c in combos if c["sharpe_per_period"] is not None]
    n_obs = max((c["n"] for c in combos), default=0)
    pbo = probability_of_backtest_overfitting(perf_matrix) if len(perf_matrix) >= 2 else None
    dsr = deflated_sharpe_ratio(pp_sharpes, n_obs) if pp_sharpes and n_obs >= 2 else None
    best = max((c for c in combos if c["sharpe_annualized"] is not None),
               key=lambda c: c["sharpe_annualized"], default=None)
    return combos, pbo, dsr, best


def build_study(min_sample_n, log_path=P2_LOG):
    try:
        with open(log_path) as f:
            log = json.load(f)
    except (OSError, ValueError):
        log = []

    trips = reconstruct_round_trips(log)
    n = len(trips)
    rt_friction = round_trip_friction()
    result = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": "p2_disclosure_lag_tuning",
        "source": "political-copy-bot/data/trade_log.json (Alpaca PAPER)",
        "min_sample_n": min_sample_n,
        "n_round_trips": n,
        "round_trip_friction_pct": round(rt_friction * 100, 4),
        "search": {"max_disclosure_age_days": AGE_GRID},
        "holding_days": ("NOT searched — re-simulating a holding period requires per-trade "
                         "price paths (bar data) absent from closed round-trips; listed as a "
                         "further data requirement, never reported as optimized"),
        "gate_thresholds": GATE,
        "disclosure": ("Hypothetical/paper research only — not investment advice. "
                       "Politician-disclosure history is thin and survivorship-biased; "
                       "a positive in-sample age clears nothing until it passes PBO + "
                       "deflated-Sharpe with N >= min_sample_n. Returns are net of friction."),
    }

    if n < min_sample_n:
        result["verdict"] = "REFUSE_TO_ASSERT"
        result["reason"] = (
            f"{n} closed round-trips < N-floor {min_sample_n}. P2 currently logs "
            "ENTRIES ONLY — no exit price, realized P&L, or disclosure age — so no "
            "round-trip return series can be formed.")
        result["data_needed"] = [
            "closed round-trips (matched BUY->SELL) with entry_price + exit_price",
            "per-entry disclosure_date AND observed_date (to derive disclosure_age_days)",
            "per-trade bar data if holding-period tuning is later in scope",
            f"at least {min_sample_n} such round-trips before any tuning is trusted",
        ]
        return result

    combos, pbo, dsr, best = run_grid(trips, rt_friction)
    best_sr = best["sharpe_annualized"] if best else None
    passes = (pbo is not None and dsr is not None and best_sr is not None
              and pbo <= GATE["pbo_max"] and dsr >= GATE["dsr_min"]
              and best_sr >= GATE["sharpe_min"])
    result.update({
        "verdict": "GO" if passes else "NO_GO",
        "pbo": round(pbo, 4) if pbo is not None else None,
        "deflated_sharpe": round(dsr, 4) if dsr is not None else None,
        "best_combo": best,
        "combos": combos,
        "reason": ("cleared PBO + deflated-Sharpe + in-sample annualized Sharpe floor "
                   "(PBO is the overfitting / out-of-sample guard)"
                   if passes else "failed one or more gates -> fail closed (correct on thin data)"),
    })
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="P2 disclosure-lag tuning study (PBO/DSR-gated).")
    ap.add_argument("--min-sample-n", type=int, default=30)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "p2_disclosure_lag_study.json"))
    args = ap.parse_args(argv)

    study = build_study(args.min_sample_n)
    with open(args.out, "w") as f:
        json.dump(study, f, indent=2)
        f.write("\n")

    try:
        from shared.research_provenance import write_provenance
        warn = [] if study["verdict"] != "REFUSE_TO_ASSERT" else [study["reason"]]
        write_provenance(args.out, [P2_LOG], warnings=warn, source=study["source"])
    except Exception as e:
        print(f"  (provenance sidecar skipped: {e})")

    print(f"Wrote {args.out}")
    print(f"  verdict={study['verdict']} n_round_trips={study['n_round_trips']} "
          f"(floor {study['min_sample_n']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
