#!/usr/bin/env python3
"""Signal-efficacy diagnostic (OFFLINE research lane) -> data/signal_efficacy.json.

Phase 3 / defect C1: the audit found P1's entry signal_score is ANTI-predictive
of outcome (Pearson ~-0.26). Fixing exits (Phase 0) and the learning loop
(Phase 1-2) reduces the loss; it cannot create alpha the ENTRY model lacks. This
script makes that edge measurable and trackable: it computes the
signal_score -> realized-return relationship from the trade log with a
significance test and an N-floor, and emits an honest verdict.

It is the GATE METRIC for any entry re-fit: a candidate factor-weight change is
only worth adopting if it flips this correlation from "no positive edge" to a
statistically significant POSITIVE one out-of-sample. Pure-stdlib; offline; the
trading path never imports it (invariant A).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

P1_LOG = os.path.join(ROOT, "data", "trade_log.json")
MIN_SAMPLE = 30
T_SIGNIFICANT = 2.0  # |t| > 2 ~ p < 0.05


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / ((vx ** 0.5) * (vy ** 0.5))


def _ranks(vals):
    """Average ranks (ties shared) for Spearman."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs, ys):
    return _pearson(_ranks(xs), _ranks(ys))


def _t_stat(r, n):
    if r is None or n < 3 or abs(r) >= 1.0:
        return None
    return r * ((n - 2) / (1.0 - r * r)) ** 0.5


def _tercile_table(pairs):
    """pairs sorted by score -> low/mid/high buckets with avg return + win rate."""
    pairs = sorted(pairs, key=lambda p: p[0])
    n = len(pairs)
    third = n // 3
    if third == 0:
        return []
    buckets = [("low", pairs[:third]), ("mid", pairs[third:2 * third]), ("high", pairs[2 * third:])]
    out = []
    for name, b in buckets:
        rets = [r for _, r in b]
        wins = sum(1 for r in rets if r > 0)
        out.append({"bucket": name, "n": len(b),
                    "avg_return_pct": round(sum(rets) / len(rets), 3) if rets else None,
                    "win_rate": round(wins / len(rets), 3) if rets else None})
    return out


def build_diagnostic(min_sample=MIN_SAMPLE, log_path=P1_LOG):
    try:
        with open(log_path) as f:
            log = json.load(f)
    except (OSError, ValueError):
        log = []

    pairs = []
    for t in log if isinstance(log, list) else []:
        if not isinstance(t, dict) or t.get("status") != "closed":
            continue
        score = t.get("signal_score")
        ret = t.get("pnl_pct")
        if isinstance(score, (int, float)) and isinstance(ret, (int, float)):
            pairs.append((float(score), float(ret)))

    n = len(pairs)
    result = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": "p1_signal_efficacy",
        "source": "data/trade_log.json closed trades (signal_score vs pnl_pct)",
        "n": n,
        "min_sample": min_sample,
        "disclosure": ("Hypothetical/paper research only — not investment advice. Measures "
                       "whether the entry score carries positive predictive information; it "
                       "is the gate metric an entry-model re-fit must improve out-of-sample."),
    }
    if n < min_sample:
        result["verdict"] = "INSUFFICIENT_DATA"
        result["reason"] = f"{n} scored closed trades < N-floor {min_sample}"
        return result

    xs = [s for s, _ in pairs]
    ys = [r for _, r in pairs]
    pr = _pearson(xs, ys)
    sr = _spearman(xs, ys)
    t = _t_stat(pr, n)
    significant = t is not None and abs(t) > T_SIGNIFICANT
    if not significant:
        verdict = "NO_EDGE"           # no evidence the score predicts outcome
    elif pr > 0:
        verdict = "POSITIVE_EDGE"     # the goal of a successful re-fit
    else:
        verdict = "NEGATIVE_EDGE"     # score is significantly anti-predictive
    result.update({
        "verdict": verdict,
        "pearson_r": round(pr, 4) if pr is not None else None,
        "spearman_r": round(sr, 4) if sr is not None else None,
        "t_stat": round(t, 3) if t is not None else None,
        "significant_at_5pct": significant,
        "terciles": _tercile_table(pairs),
        "reason": ("score carries no statistically significant predictive edge"
                   if verdict == "NO_EDGE" else
                   "score significantly predicts higher returns" if verdict == "POSITIVE_EDGE"
                   else "score significantly predicts LOWER returns (anti-predictive)"),
    })
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="P1 entry signal-efficacy diagnostic.")
    ap.add_argument("--min-sample", type=int, default=MIN_SAMPLE)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "signal_efficacy.json"))
    args = ap.parse_args(argv)

    diag = build_diagnostic(args.min_sample)
    with open(args.out, "w") as f:
        json.dump(diag, f, indent=2)
        f.write("\n")

    try:
        from shared.research_provenance import write_provenance
        warn = [diag["reason"]] if diag["verdict"] in ("NEGATIVE_EDGE", "NO_EDGE",
                                                        "INSUFFICIENT_DATA") else []
        write_provenance(args.out, [P1_LOG], warnings=warn, source=diag["source"])
    except Exception as e:
        print(f"  (provenance sidecar skipped: {e})")

    print(f"Wrote {args.out}")
    print(f"  verdict={diag['verdict']} n={diag['n']} "
          f"pearson_r={diag.get('pearson_r')} t={diag.get('t_stat')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
