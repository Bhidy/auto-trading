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
from backtest import metrics as _metrics  # noqa: E402


def auto_test_days(n_bars, warmup, target_windows=3, min_test=21, max_test=63):
    """Pick a test-window length so the available history yields ~target_windows
    out-of-sample windows. Fixes C4: a fixed test_days=63 on the standard ~220-bar
    cache produced only 1 window, so gate_param_change (floor 2) ALWAYS refused —
    the self-learning loop could never approve anything. Caps the WINDOW at a
    quarter (max_test) so abundant history buys MORE windows, not huge ones."""
    usable = n_bars - warmup - 1
    if usable < min_test:
        return min_test
    return max(min_test, min(max_test, usable // target_windows))


def walk_forward(symbol_bars, spy_bars, params, test_days=None, warmup=150,
                 max_positions=10, cost_bps=5.0, slippage_bps=5.0):
    """Roll consecutive out-of-sample windows of `test_days` and aggregate.

    Because params are FIXED (not fit on the train portion), every window is a
    genuine out-of-sample test of the param set's robustness across regimes.
    `test_days=None` (default) sizes the window adaptively via auto_test_days so
    the standard cache yields enough OOS windows to deflate honestly.
    Returns {windows: [...], aggregate: {mean_sharpe, mean_return,
    worst_drawdown, n_windows}}.
    """
    n = len(spy_bars)
    if test_days is None:
        test_days = auto_test_days(n, warmup)
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


def evaluate_overfitting_screens(cur_windows, cand_windows, *,
                                 challenger_sharpe=None, cand_sharpe=None,
                                 pbo_reject=0.5, dsr_reject=0.5,
                                 challenger_margin=0.10, extra_trial_sharpes=None):
    """Pure overfitting screens (V1/V2) applied on top of the OOS Sharpe test.

    Conservative by design: these VETO a clearly overfit / benchmark-losing
    candidate but do not demand statistical certainty the small self-learning
    sample can't provide — so the system stays fully automated and still adapts.

    Veto when (and only when computable):
      * PBO ≥ pbo_reject               — the in-sample winner fails out-of-sample.
      * Deflated Sharpe < dsr_reject   — best Sharpe no better than a coin flip
                                         after the multiple-testing haircut.
      * candidate clearly below the fixed challenger benchmark OOS.

    Returns {ok, reasons, pbo, deflated_sharpe, beats_challenger}.
    """
    reasons = []
    cand_sh = [w.get("sharpe", 0.0) for w in (cand_windows or [])]
    cur_sh = [w.get("sharpe", 0.0) for w in (cur_windows or [])]
    n_windows = len(cand_sh)

    # Deflated Sharpe across the candidate's OOS windows (windows ≈ trials),
    # augmented with the cumulative trial history (trial_ledger) so N reflects the
    # WHOLE search, not one run. More historical trials -> higher expected-max
    # hurdle -> stricter. Default (no history) reproduces the prior behavior.
    deflated = None
    if n_windows >= 2:
        trial_set = cand_sh + list(extra_trial_sharpes or [])
        deflated = _metrics.deflated_sharpe_ratio(trial_set, n_obs=n_windows)
        if deflated < dsr_reject:
            reasons.append(f"deflated Sharpe {deflated:.3f} < {dsr_reject} "
                           f"(not distinguishable from noise across "
                           f"{len(trial_set)} trials)")

    # PBO across the two configurations over the OOS windows.
    pbo = None
    if n_windows >= 4 and len(cur_sh) == n_windows:
        pbo = _metrics.probability_of_backtest_overfitting([cur_sh, cand_sh])
        if pbo is not None and pbo >= pbo_reject:
            reasons.append(f"PBO {pbo:.2f} ≥ {pbo_reject} (overfit)")

    # Challenger benchmark: candidate must not be clearly worse than buy-and-hold.
    beats_challenger = None
    if challenger_sharpe is not None and cand_sharpe is not None:
        beats_challenger = cand_sharpe >= challenger_sharpe - challenger_margin
        if not beats_challenger:
            reasons.append(f"candidate OOS Sharpe {cand_sharpe:.3f} below challenger "
                           f"{challenger_sharpe:.3f} (no edge over buy-and-hold)")

    return {
        "ok": len(reasons) == 0,
        "reasons": reasons,
        "pbo": pbo,
        "deflated_sharpe": deflated,
        "beats_challenger": beats_challenger,
    }


def gate_param_change(current_params, candidate_params, symbol_bars, spy_bars,
                      min_sharpe_margin=-0.05, extra_trial_sharpes=None,
                      min_oos_windows=2, **kw):
    """Return (approved: bool, detail: dict).

    Approves the candidate only if it passes ALL gates, fully automatically:
      1. aggregate OOS mean Sharpe ≥ current − margin (robustness vs status quo);
      2. overfitting screens (Deflated Sharpe + PBO) do not flag it as noise;
      3. it is not clearly worse than the fixed challenger benchmark OOS;
      4. the OOS sample is large enough to deflate honestly — a CHANGE with fewer
         than `min_oos_windows` windows is REFUSED on small N (committee rec #6).
         Small N is exactly where multiple-testing luck masquerades as skill, and
         below 2 windows the Deflated Sharpe cannot even be computed, so the change
         would otherwise ride on the raw Sharpe test alone.
    Fails closed on any error or insufficient data (an unvalidatable change is
    never applied).
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
    sharpe_ok = cand_sharpe >= cur_sharpe + min_sharpe_margin

    # The overfitting screens guard an actual CHANGE. Identical params are a
    # no-op (no new risk) and are approved on the Sharpe test alone — otherwise
    # the absolute screens could paradoxically reject "keep things as they are."
    is_change = current_params != candidate_params

    challenger_sharpe = None
    screens = {"ok": True, "reasons": [], "pbo": None,
               "deflated_sharpe": None, "beats_challenger": None}
    if is_change:
        # Fixed challenger benchmark (best-effort; never blocks on its own failure).
        try:
            from backtest.challenger import challenger_backtest
            warmup = kw.get("warmup", 150)
            ch = challenger_backtest(symbol_bars, spy_bars, warmup=warmup)
            challenger_sharpe = ch["metrics"]["sharpe"]
        except Exception:
            challenger_sharpe = None
        screens = evaluate_overfitting_screens(
            cur["windows"], cand["windows"],
            challenger_sharpe=challenger_sharpe, cand_sharpe=cand_sharpe,
            extra_trial_sharpes=extra_trial_sharpes)

    # Small-N refusal (committee rec #6): a real CHANGE needs enough out-of-sample
    # windows to deflate honestly. Below the floor, refuse and keep current params
    # (fail-closed) rather than approving on the raw Sharpe test alone.
    n_windows = cand["aggregate"]["n_windows"]
    small_n_refused = bool(is_change and n_windows < min_oos_windows)
    if small_n_refused:
        screens = {**screens, "ok": False,
                   "reasons": list(screens["reasons"]) + [
                       f"insufficient OOS windows (N={n_windows} < {min_oos_windows}) "
                       f"to deflate — refusing change on small sample (fail-closed)"]}

    approved = bool(sharpe_ok and screens["ok"])
    return approved, {
        "current_oos_sharpe": cur_sharpe,
        "candidate_oos_sharpe": cand_sharpe,
        "n_windows": n_windows,
        "min_oos_windows": min_oos_windows,
        "small_n_refused": small_n_refused,
        "sharpe_ok": sharpe_ok,
        "challenger_sharpe": challenger_sharpe,
        "pbo": screens["pbo"],
        "deflated_sharpe": screens["deflated_sharpe"],
        "beats_challenger": screens["beats_challenger"],
        "screen_reasons": screens["reasons"],
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
