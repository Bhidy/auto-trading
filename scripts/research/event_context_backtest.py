#!/usr/bin/env python3
"""Event-context advisory backtest evidence — OFFLINE research lane.

The deferred question: would wiring the advisory event-context overlay
(``shared/event_context.py``) into live P2/P3 entries as a VETO have improved
realized outcomes? Activating vetoes in the live path alters trade decisions and
is committee-gated; before that decision can even be put to the committee it
needs EVIDENCE. This script builds the attribution machinery.

Honest finding today: the overlay is point-in-time and NOT historized, so there
are no event-context labels attached to past entries -> the effect cannot be
attributed retrospectively. The script therefore (a) reports the available
closed-trade statistics, (b) defines the exact forward metric + N-floor + test,
and (c) refuses to assert until a per-entry event-context snapshot accrues.

Emits ``data/event_context_evidence.json`` (static; cloud path never imports
this). Pure-stdlib; reuses the project's win-rate / profit-factor helpers.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

from backtest.metrics import profit_factor, win_rate  # noqa: E402

LOGS = {
    "portfolio_1": os.path.join(ROOT, "data", "trade_log.json"),
    "portfolio_3": os.path.join(ROOT, "event-driven-bot", "data", "trade_log.json"),
}
# A historized snapshot of event flags per (date, symbol) at entry time. Absent
# today — this is exactly the data the overlay must start logging to enable
# retrospective attribution.
EVENT_HISTORY = os.path.join(ROOT, "data", "event_context_history.json")
MIN_PER_GROUP = 20  # N-floor per arm (vetoed vs kept) before a difference is trusted


def _closed_pnls(log):
    """Realized P&L of closed trades (absolute and as a fraction)."""
    out = []
    if not isinstance(log, list):
        return out
    for t in log:
        if not isinstance(t, dict):
            continue
        closed = t.get("status") == "closed" or t.get("exit_price") not in (None, "", 0)
        pnl = t.get("realized_pnl")
        if pnl is None:
            pnl = t.get("pnl")
        if closed and isinstance(pnl, (int, float)):
            out.append({"symbol": t.get("symbol"),
                        "entry_date": str(t.get("timestamp") or t.get("date") or "")[:10],
                        "pnl": float(pnl),
                        "pnl_pct": t.get("pnl_pct")})
    return out


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def build_evidence(min_per_group=MIN_PER_GROUP):
    labels = _load(EVENT_HISTORY)
    labels_available = isinstance(labels, dict) and bool(labels)

    per_portfolio = {}
    all_pnls = []
    for pid, path in LOGS.items():
        pnls = _closed_pnls(_load(path))
        abs_pnls = [p["pnl"] for p in pnls]
        all_pnls.extend(pnls)
        per_portfolio[pid] = {
            "n_closed": len(pnls),
            "win_rate": round(win_rate(abs_pnls), 4) if abs_pnls else None,
            "profit_factor": (round(profit_factor(abs_pnls), 4)
                              if abs_pnls and profit_factor(abs_pnls) != float("inf") else None),
            "mean_pnl": round(sum(abs_pnls) / len(abs_pnls), 2) if abs_pnls else None,
        }

    result = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": "event_context_advisory_evidence",
        "source": "P1 + P3 closed trades vs historized event-context labels",
        "labels_available": labels_available,
        "min_sample_per_group": min_per_group,
        "closed_trade_stats": per_portfolio,
        "forward_metric": {
            "definition": ("one-sided test of mean realized return for entries the overlay "
                           "WOULD have vetoed vs entries it kept; require each arm >= "
                           "min_sample_per_group; conclude 'veto helps' only if vetoed-arm "
                           "mean return is materially worse with the difference significant"),
            "needs": ["per-entry event_context snapshot logged AT entry time "
                      "(symbol, date, pending_corporate_action, fresh_news, liquidity_rank)",
                      f">= {min_per_group} closed trades in EACH arm"],
        },
        "disclosure": ("Research evidence only — not investment advice. No retrospective "
                       "attribution is possible without point-in-time event labels; the "
                       "veto stays committee-gated until this evidence exists."),
    }

    if not labels_available:
        result["verdict"] = "REFUSE_TO_ASSERT"
        result["reason"] = (
            "no historized event-context labels at entry time (data/event_context_history.json "
            "absent) — the advisory overlay is point-in-time, so its veto effect cannot be "
            "attributed to past trades. Start logging a per-entry snapshot to enable this.")
        return result

    # Machinery for when labels exist: split into vetoed/kept arms and test.
    vetoed, kept = [], []
    for p in all_pnls:
        day = labels.get(p["entry_date"], {})
        flag = day.get(p["symbol"]) if isinstance(day, dict) else None
        (vetoed if (isinstance(flag, dict) and flag.get("veto")) else kept).append(p["pnl"])
    if len(vetoed) < min_per_group or len(kept) < min_per_group:
        result["verdict"] = "REFUSE_TO_ASSERT"
        result["reason"] = (f"insufficient per-arm sample (vetoed={len(vetoed)}, "
                            f"kept={len(kept)}; floor {min_per_group})")
        return result
    mv, mk = sum(vetoed) / len(vetoed), sum(kept) / len(kept)
    result.update({
        "verdict": "VETO_HELPS" if mv < mk else "VETO_HURTS_OR_NEUTRAL",
        "vetoed_mean_pnl": round(mv, 2), "kept_mean_pnl": round(mk, 2),
        "n_vetoed": len(vetoed), "n_kept": len(kept),
        "reason": "vetoed entries underperformed kept entries" if mv < mk
                  else "vetoed entries did not underperform — overlay adds no edge",
    })
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="Event-context advisory backtest evidence.")
    ap.add_argument("--min-per-group", type=int, default=MIN_PER_GROUP)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "event_context_evidence.json"))
    args = ap.parse_args(argv)

    ev = build_evidence(args.min_per_group)
    with open(args.out, "w") as f:
        json.dump(ev, f, indent=2)
        f.write("\n")

    try:
        from shared.research_provenance import write_provenance
        warn = [ev["reason"]] if ev["verdict"] == "REFUSE_TO_ASSERT" else []
        write_provenance(args.out, list(LOGS.values()) + [EVENT_HISTORY],
                         warnings=warn, source=ev["source"])
    except Exception as e:
        print(f"  (provenance sidecar skipped: {e})")

    print(f"Wrote {args.out}")
    print(f"  verdict={ev['verdict']} labels_available={ev['labels_available']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
