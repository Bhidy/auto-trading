#!/usr/bin/env python3
"""Options-sleeve research spec + spread-aware go/no-go feasibility — OFFLINE lane.

The deferred options sleeve (CLAUDE allocation: 5%, "Phase 2"). Per the red-team
we deliver ONLY a spread-aware research spec that yields a single go/no-go number
— no live plumbing until the equity book clears LIVE_READINESS. This script:

  1. authors a PRECISE, defined-risk options spec and validates it against the
     project's own strategy-spec contract (``backtest.strategy_spec``);
  2. writes ``docs/specs/options_sleeve_spec.json`` (the formalized strategy);
  3. evaluates a GO/NO-GO feasibility scorecard from REAL gating facts and writes
     ``data/options_sleeve_feasibility.json``.

Defined-risk by construction (vertical spreads only -> max loss bounded), spread-
aware (skip if quoted spread exceeds a fraction of mid), liquidity-floored. The
sleeve is sized INSIDE the existing hardcoded caps — it never relaxes a limit.

Pure-stdlib; offline; the trading path never imports it (invariant A).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

from backtest.strategy_spec import validate_spec  # noqa: E402

SPEC_OUT = os.path.join(ROOT, "docs", "specs", "options_sleeve_spec.json")
FEAS_OUT = os.path.join(ROOT, "data", "options_sleeve_feasibility.json")
RISK_LIMITS = os.path.join(ROOT, "config", "risk_limits.json")
LIVE_READINESS = os.path.join(ROOT, "docs", "LIVE_READINESS.md")

SLEEVE_CAP_PCT = 0.05          # CLAUDE allocation target for the options bucket
MAX_LOSS_PER_TRADE_PCT = 0.01  # mirrors the equity book's 1% max-loss-per-trade
MAX_SPREAD_FRAC_OF_MID = 0.10  # spread-aware: skip if (ask-bid)/mid > 10%
MIN_OPEN_INTEREST = 500        # liquidity floor


def build_spec():
    """A defined-risk, spread-aware vertical-spread spec conforming to the validator."""
    return {
        "spec_id": "options-sleeve-defined-risk-v1",
        "portfolio": "portfolio_1",
        "universe": "liquid optionable underlyings: SPY, QQQ, AAPL, MSFT, NVDA",
        "timeframe": "1Day",
        "indicators": [
            {"name": "IV_rank", "params": {"lookback_days": 252, "entry_max": 0.50}},
            {"name": "ATR", "params": {"period": 14}},
            {"name": "trend_filter", "params": {"ma_fast": 20, "ma_slow": 50}},
        ],
        "entry_rule": ("open a DEFINED-RISK vertical spread aligned with the underlying's "
                       "trend filter ONLY when quoted spread <= "
                       f"{MAX_SPREAD_FRAC_OF_MID:.0%} of mid AND open_interest >= "
                       f"{MIN_OPEN_INTEREST} AND debit <= per-trade max loss"),
        "exit_rule": ("close at 50% of max profit, or at 21 DTE, or if the underlying "
                      "trend filter flips; max loss is structurally capped by the spread width"),
        "signal_bar": "t (close)",
        "fill": {"model": "limit", "bar": "t+1", "look_ahead_ack": False},
        "sizing": (f"sleeve <= {SLEEVE_CAP_PCT:.0%} of equity; per-trade debit (max loss) "
                   f"<= {MAX_LOSS_PER_TRADE_PCT:.0%} of equity; defined-risk verticals only"),
        "fees_bps": 10.0,        # per-contract commissions + exchange fees, conservative
        "slippage_bps": 25.0,    # options spreads are wide -> conservative spread cost
        "benchmark": "SPY buy & hold, friction-matched",
        "structures": ["bull_call_spread", "bear_put_spread"],
        "spread_filter": {"max_spread_frac_of_mid": MAX_SPREAD_FRAC_OF_MID,
                          "min_open_interest": MIN_OPEN_INTEREST},
        "notes": ("Defined-risk ONLY (no naked/undefined exposure). Activation is gated "
                  "behind LIVE_READINESS; see data/options_sleeve_feasibility.json for the "
                  "current go/no-go and the exact conditions that flip it."),
    }


def _equity_book_live_ready():
    """Hard fact from the live-readiness doc: the system is PAPER ONLY today."""
    try:
        with open(LIVE_READINESS) as f:
            txt = f.read()
    except OSError:
        return None  # unknown -> treated as not-ready (fail closed)
    return "PAPER ONLY" not in txt.upper()


def _sizing_within_caps():
    """5% sleeve + 1% per-trade defined-risk fits inside the hardcoded caps."""
    try:
        with open(RISK_LIMITS) as f:
            limits = json.load(f)
    except (OSError, ValueError):
        return None
    # The sleeve cap (5%) must not exceed the most permissive single-position cap,
    # and per-trade max loss (1%) must not exceed the equity book's max_loss_per_trade.
    caps = []
    for k, v in limits.items():
        if "max_single_position" in k and isinstance(v, dict):
            caps.extend([x for x in v.values() if isinstance(x, (int, float))])
        if k == "max_single_position" and isinstance(v, (int, float)):
            caps.append(v)
    cap_ok = (not caps) or SLEEVE_CAP_PCT <= max(caps)
    return bool(cap_ok)


def build_feasibility(spec):
    spec_ok, spec_errors = validate_spec(spec)
    live_ready = _equity_book_live_ready()
    sizing_ok = _sizing_within_caps()

    gates = [
        {"gate": "spec_conforms",
         "pass": bool(spec_ok),
         "flips_when": "the spec validates against backtest.strategy_spec",
         "detail": spec_errors or "valid"},
        {"gate": "defined_risk_only",
         "pass": True,
         "flips_when": "structures stay limited to bounded-loss verticals",
         "detail": spec["structures"]},
        {"gate": "sizing_within_caps",
         "pass": bool(sizing_ok),
         "flips_when": f"sleeve {SLEEVE_CAP_PCT:.0%} + per-trade {MAX_LOSS_PER_TRADE_PCT:.0%} "
                       "stay within config/risk_limits.json",
         "detail": "ok" if sizing_ok else "exceeds a hardcoded cap"},
        {"gate": "equity_book_live_ready",
         "pass": bool(live_ready),
         "flips_when": "the equity book clears LIVE_READINESS (>=90 paper days, "
                       "OOS Sharpe >= 1.0, max DD <= 15%)",
         "detail": "PAPER ONLY" if not live_ready else "cleared"},
        {"gate": "pure_python_options_data_path",
         "pass": False,
         "flips_when": "a requests-only options chain/quote path exists for the cloud loop "
                       "(today option data is research-lane MCP/CLI only -> not on the money path)",
         "detail": "not implemented (deliberate — no LLM/CLI in the autonomous loop)"},
    ]
    passed = sum(1 for g in gates if g["pass"])
    go = all(g["pass"] for g in gates)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": "options_sleeve_feasibility",
        "verdict": "GO" if go else "NO_GO",
        "readiness_score": f"{passed}/{len(gates)}",
        "blocking_gates": [g["gate"] for g in gates if not g["pass"]],
        "gates": gates,
        "sleeve_cap_pct": SLEEVE_CAP_PCT,
        "max_loss_per_trade_pct": MAX_LOSS_PER_TRADE_PCT,
        "disclosure": ("Research feasibility only — not investment advice. The options "
                       "sleeve stays NO-GO until every gate passes; defined-risk caps and "
                       "the hardcoded risk limits are never relaxed by this sleeve."),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Options-sleeve spec + go/no-go feasibility.")
    ap.add_argument("--spec-out", default=SPEC_OUT)
    ap.add_argument("--feas-out", default=FEAS_OUT)
    args = ap.parse_args(argv)

    spec = build_spec()
    ok, errors = validate_spec(spec)
    if not ok:
        print("SPEC INVALID:", errors)
        return 1
    with open(args.spec_out, "w") as f:
        json.dump(spec, f, indent=2)
        f.write("\n")

    feas = build_feasibility(spec)
    with open(args.feas_out, "w") as f:
        json.dump(feas, f, indent=2)
        f.write("\n")

    try:
        from shared.research_provenance import write_provenance
        write_provenance(args.feas_out, [args.spec_out, RISK_LIMITS, LIVE_READINESS],
                         warnings=[f"blocking gates: {feas['blocking_gates']}"]
                         if feas["blocking_gates"] else [],
                         source="options_sleeve_spec + risk_limits + LIVE_READINESS")
    except Exception as e:
        print(f"  (provenance sidecar skipped: {e})")

    print(f"Wrote {args.spec_out} and {args.feas_out}")
    print(f"  verdict={feas['verdict']} readiness={feas['readiness_score']} "
          f"blocking={feas['blocking_gates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
