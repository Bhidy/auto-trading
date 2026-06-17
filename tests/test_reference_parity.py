"""Reference-parity + no-look-ahead fixture for the backtest engine (Phase 3).

This is the SCOPED-DOWN differential check the red-team approved (one CI fixture,
NOT a 6-action harness). It guards the two failure modes an independent reference
would catch:

  1. No look-ahead: a position/equity decision at bar t must depend ONLY on bars
     up to t. We verify this directly: mutating a FUTURE close must not change the
     equity-curve prefix before it. (A leak would change the past.)
  2. Metric-convention parity: the engine's reported metrics must match an
     INDEPENDENT recomputation from the equity curve using the documented
     conventions (sample N-1 stddev, 252-day annualization, drawdown as a positive
     fraction). Catches annualization / N-vs-N-1 / sign drift.

When the Alpaca CLI is available in the research lane, the SAME formalized rule is
additionally diffed against the skill's deterministic run.py — that runs OFFLINE
(it needs the CLI/network), so it is not part of CI. This fixture is the always-on
core. See docs/ALPACA_TOOLING.md.
"""
import math
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest.engine import backtest_symbol  # noqa: E402

# Deterministic trending series (no RNG): a rising ramp with a mild oscillation so
# the composite score crosses the buy threshold and round-trips fire.
def _series(n=260):
    bars = []
    for i in range(n):
        base = 100.0 + i * 0.5 + 6.0 * math.sin(i / 9.0)
        bars.append({"o": base, "h": base + 1.0, "l": base - 1.0, "c": base})
    return bars


PARAMS = {"ma_fast": 20, "ma_slow": 50, "confidence_buy_threshold": 0.40,
          "confidence_exit_threshold": 0.0, "rsi_oversold": 35, "rsi_overbought": 70}


# --- independent metric recomputation (mirrors scripts/backtest/metrics.py) ----

def _ind_total_return(eq):
    return eq[-1] / eq[0] - 1.0


def _ind_sharpe(eq, periods=252):
    rets = [eq[i] / eq[i - 1] - 1.0 for i in range(1, len(eq)) if eq[i - 1]]
    if len(rets) < 2:
        return 0.0
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)  # sample N-1
    sd = math.sqrt(var)
    return 0.0 if sd == 0 else (m / sd) * math.sqrt(periods)


def _ind_max_dd(eq):
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def test_no_look_ahead_future_change_does_not_alter_past():
    bars = _series()
    base = backtest_symbol(bars, PARAMS)["equity_curve"]

    k = 200
    shocked = [dict(b) for b in bars]
    shocked[k]["c"] = shocked[k]["c"] * 1.5   # large FUTURE shock at bar k
    shocked[k]["h"] = shocked[k]["c"] + 1.0
    shocked_curve = backtest_symbol(shocked, PARAMS)["equity_curve"]

    # The prefix before the shocked bar's mark must be byte-identical — otherwise a
    # decision used data it could not have seen (look-ahead).
    assert base[:k] == shocked_curve[:k], "future bar changed the equity-curve prefix (look-ahead!)"
    # And the shock MUST eventually move the curve (the fixture actually exercises it).
    assert base[-1] != shocked_curve[-1]


def test_metrics_match_independent_recomputation():
    res = backtest_symbol(_series(), PARAMS)
    eq = res["equity_curve"]
    m = res["metrics"]

    assert abs(m["total_return"] - _ind_total_return(eq)) < 1e-3
    assert abs(m["sharpe"] - _ind_sharpe(eq)) < 1e-2
    assert abs(m["max_drawdown"] - _ind_max_dd(eq)) < 1e-3
    # Drawdown convention: a positive fraction (0.18 == -18%), never negative.
    assert m["max_drawdown"] >= 0.0


def test_engine_actually_trades_on_the_fixture():
    # Guards against a degenerate fixture that would make the above vacuous.
    res = backtest_symbol(_series(), PARAMS)
    assert res["num_entries"] >= 1
