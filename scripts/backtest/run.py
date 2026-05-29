#!/usr/bin/env python3
"""
CLI runner for the backtest engine.

Reads daily bars from a JSON file and prints an institutional performance
report. Accepts either Alpaca's bar schema ({"bars": {"SYM": [{t,o,h,l,c,v}]}})
or a plain list of {o,h,l,c} objects — so it works against saved API output
with no embedded credentials.

Usage:
    python3 scripts/backtest/run.py --bars-file bars.json --symbol SPY
    python3 scripts/backtest/run.py --bars-file bars.json --cost-bps 5 --slippage-bps 5
"""
import argparse
import json
import sys

from engine import backtest_symbol


def _extract_bars(payload, symbol=None):
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and "bars" in payload:
        bars = payload["bars"]
        if isinstance(bars, dict):
            key = symbol or next(iter(bars))
            rows = bars[key]
        else:
            rows = bars
    else:
        raise ValueError("Unrecognized bars JSON shape")
    return [{"o": r.get("o", r["c"]), "h": r.get("h", r["c"]),
             "l": r.get("l", r["c"]), "c": r["c"], "v": r.get("v", 0)}
            for r in rows]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Backtest a symbol's daily bars.")
    ap.add_argument("--bars-file", required=True, help="Path to JSON bars.")
    ap.add_argument("--symbol", default=None, help="Symbol key (if multi-symbol file).")
    ap.add_argument("--starting-equity", type=float, default=100_000.0)
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--slippage-bps", type=float, default=5.0)
    args = ap.parse_args(argv)

    with open(args.bars_file) as f:
        payload = json.load(f)
    bars = _extract_bars(payload, args.symbol)
    if len(bars) < 60:
        print(f"Only {len(bars)} bars — need >= 60 for a meaningful backtest.")
        return 1

    res = backtest_symbol(bars, starting_equity=args.starting_equity,
                          cost_bps=args.cost_bps, slippage_bps=args.slippage_bps)
    sym = args.symbol or "symbol"
    print(f"\n=== Backtest: {sym} ({len(bars)} bars) ===")
    print(f"Entries: {res['num_entries']} | Closed trades: {len(res['trade_pnls'])}")
    print(json.dumps(res["metrics"], indent=2))
    bh = bars[-1]["c"] / bars[0]["c"] - 1
    print(f"Buy & hold benchmark: {bh:+.2%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
