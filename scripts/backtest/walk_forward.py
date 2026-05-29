"""
Walk-forward validation + self-learning gate.

Purpose: stop the adaptive engine from tuning parameters on live noise. Before a
proposed parameter change is committed, it must prove itself OUT-OF-SAMPLE
across multiple rolling windows using the full multi-factor backtester.

  * walk_forward()      — evaluate a FIXED param set across consecutive OOS test
                          windows; aggregate Sharpe / return / worst drawdown.
  * gate_param_change() — return True only if a candidate param set is at least
                          as good OOS as the current one (within a margin).
                          Fails CLOSED: any error / insufficient data -> False
                          (never apply an unvalidated change).
  * load_aligned_bars() — load morning-research's cached bucket bars and align
                          them to SPY's date axis for backtesting.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.multifactor import backtest_multifactor  # noqa: E402


def walk_forward(symbol_bars, spy_bars, params, test_days=63, warmup=150,
                 max_positions=10, cost_bps=5.0, slippage_bps=5.0):
    """Roll consecutive out-of-sample windows of `test_days` and aggregate.

    Because params are FIXED (not fit on the train portion), every window is a
    genuine out-of-sample test of the param set's robustness across regimes.
    Returns {windows: [...], aggregate: {mean_sharpe, mean_return,
    worst_drawdown, n_windows}}.
    """
    n = len(spy_bars)
    windows = []
    start = warmup
    while start + test_days < n:
        end = start + test_days
        # Slice [0:end] but only measure the test portion via warmup=start.
        sub_spy = spy_bars[:end + 1]
        sub_syms = {s: b[:end + 1] for s, b in symbol_bars.items()}
        try:
            res = backtest_multifactor(
                sub_syms, sub_spy, params=params, max_positions=max_positions,
                cost_bps=cost_bps, slippage_bps=slippage_bps, warmup=start,
            )
            m = res["metrics"]
            windows.append({
                "start": start, "end": end,
                "sharpe": m["sharpe"], "total_return": m["total_return"],
                "max_drawdown": m["max_drawdown"],
            })
        except Exception:
            pass
        start += test_days

    if not windows:
        return {"windows": [], "aggregate": None}

    sharpes = [w["sharpe"] for w in windows]
    rets = [w["total_return"] for w in windows]
    dds = [w["max_drawdown"] for w in windows]
    return {
        "windows": windows,
        "aggregate": {
            "mean_sharpe": round(sum(sharpes) / len(sharpes), 3),
            "mean_return": round(sum(rets) / len(rets), 4),
            "worst_drawdown": round(max(dds), 4) if dds else 0.0,
            "n_windows": len(windows),
        },
    }


def gate_param_change(current_params, candidate_params, symbol_bars, spy_bars,
                      min_sharpe_margin=-0.05, **kw):
    """Return (approved: bool, detail: dict).

    Approves the candidate only if its aggregate OOS mean Sharpe is at least
    current's minus a small tolerance (so trivially-equal changes pass, but a
    materially worse candidate is rejected). Fails closed on any error or if
    there isn't enough aligned data to validate.
    """
    try:
        cur = walk_forward(symbol_bars, spy_bars, current_params, **kw)
        cand = walk_forward(symbol_bars, spy_bars, candidate_params, **kw)
    except Exception as e:
        return False, {"error": str(e)}

    if not cur["aggregate"] or not cand["aggregate"]:
        return False, {"reason": "insufficient data to validate"}

    cur_sharpe = cur["aggregate"]["mean_sharpe"]
    cand_sharpe = cand["aggregate"]["mean_sharpe"]
    approved = cand_sharpe >= cur_sharpe + min_sharpe_margin
    return approved, {
        "current_oos_sharpe": cur_sharpe,
        "candidate_oos_sharpe": cand_sharpe,
        "n_windows": cand["aggregate"]["n_windows"],
        "approved": approved,
    }


def load_aligned_bars(data_dir, buckets=None, benchmark="SPY", min_coverage=0.9):
    """Load morning-research cached bucket bars and align to the benchmark's
    date axis. Returns (symbol_bars, benchmark_bars) — both lists date-aligned —
    or (None, None) if insufficient.
    """
    import json
    import glob

    files = []
    if buckets:
        files = [os.path.join(data_dir, f"{b}.json") for b in buckets]
    else:
        # Bucket files are the per-bucket bar caches; exclude known state files.
        exclude = {"signals.json", "portfolio_state.json", "trade_log.json",
                   "strategy_params.json", "validated_orders.json",
                   "learning_report.json", "news_signals.json", "bot_state.json"}
        files = [f for f in glob.glob(os.path.join(data_dir, "*.json"))
                 if os.path.basename(f) not in exclude]

    by_symbol = {}
    for f in files:
        try:
            with open(f) as fh:
                payload = json.load(fh)
        except Exception:
            continue
        bars_map = payload.get("bars") if isinstance(payload, dict) else None
        if not isinstance(bars_map, dict):
            continue
        for sym, bars in bars_map.items():
            if isinstance(bars, list) and bars:
                by_symbol[sym] = bars

    if benchmark not in by_symbol:
        return None, None

    def date_map(bars):
        return {b.get("t", "")[:10]: b for b in bars if b.get("t")}

    spy_map = date_map(by_symbol[benchmark])
    spy_dates = sorted(spy_map.keys())
    if len(spy_dates) < 60:
        return None, None

    symbol_bars = {}
    for sym, bars in by_symbol.items():
        dm = date_map(bars)
        covered = [d for d in spy_dates if d in dm]
        if len(covered) >= int(len(spy_dates) * min_coverage):
            symbol_bars[sym] = dm

    if len(symbol_bars) < 3:
        return None, None

    # Common axis = SPY dates present in every retained symbol.
    common = [d for d in spy_dates if all(d in symbol_bars[s] for s in symbol_bars)]
    if len(common) < 60:
        return None, None

    aligned = {s: [symbol_bars[s][d] for d in common] for s in symbol_bars}
    spy_aligned = [spy_map[d] for d in common]
    return aligned, spy_aligned
