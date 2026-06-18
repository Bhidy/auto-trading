"""Determinism guard for the self-learning walk-forward gate.

The EOD self-learning loop imports gate_param_change (scripts/backtest/walk_forward.py)
to approve/reject an adaptive parameter change out-of-sample. That decision MUST be
reproducible: the same params + bars must yield the same OOS Sharpe and the same
approval on every run, on every machine, regardless of PYTHONHASHSEED.

Historically it was NOT. The backtest scored symbols in hash-randomized dict/set
iteration order, so tied symbols (equal rs_score, or equal composite score at the
selection boundary) were ranked/bought in a process-dependent order -> the candidate
OOS Sharpe swung run-to-run (e.g. 1.40 / 1.59 / 1.64) and approvals could flip. The
fix removed every ordering dependence on the backtest path:
  * analyst_v2.rank_by_relative_strength sorts (-rs_score, symbol)  [self-deterministic]
  * backtest.multifactor sorts symbols/holdings + buys.sort((-score, symbol))
  * backtest.challenger sorts its universe/holdings

These tests fail-loud if any of that regresses. Pure-Python (cloud-path-safe).
The module is import-safe AND runnable as __main__ (the subprocess seed test
re-executes this file under two PYTHONHASHSEED values).
"""
import json
import os
import subprocess
import sys

# Make scripts/ importable both under pytest (conftest does this too) and when this
# file is run directly as a subprocess (python3 tests/test_walk_forward_determinism.py).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
for _p in (REPO_ROOT, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from analyst_v2 import load_adaptive_params, rank_by_relative_strength  # noqa: E402
from backtest.walk_forward import gate_param_change  # noqa: E402

# The candidate delta from the bug report (an exit/entry re-tune).
DELTA = {
    "breakeven_trigger_pct": 0.08,
    "trailing_stop_atr_mult": 3.2,
    "take_profit_atr_mult": 5,
    "time_stop_days": 0,
    "confidence_buy_threshold": 0.5,
}


def _bars(closes):
    bars, prev = [], closes[0]
    for c in closes:
        bars.append({"t": "", "o": prev, "h": max(c, prev) * 1.001,
                     "l": min(c, prev) * 0.999, "c": c, "v": 1_000_000})
        prev = c
    return bars


def _series(n=240):
    """Deterministic universe (pure-Python, no random/hash in generation) with
    real trend variety AND two exact-tie twins (AAA/AAB share an identical path),
    so both the relative-strength tiebreak and the cash-constrained selection
    tiebreak are exercised. Returns an ordered list of (symbol, bars)."""
    import math
    twin = [100 * (1.0016 ** i) for i in range(n)]          # AAA == AAB (exact tie)
    return [
        ("SPY", _bars([400 * (1.0008 ** i) for i in range(n)])),   # uptrend -> bull regime
        ("AAA", _bars(twin)),                                      # strong uptrend  ┐ exact
        ("AAB", _bars(list(twin))),                                # strong uptrend  ┘ tie
        ("CCC", _bars([100 * (1.0011 ** i) for i in range(n)])),   # strong uptrend
        ("DDD", _bars([100 * (1.0006 ** i) for i in range(n)])),   # mild uptrend
        ("EEE", _bars([100 * (1.0009 ** i) for i in range(n)])),   # uptrend
        ("FFF", _bars([100 * (0.9990 ** i) for i in range(n)])),   # downtrend
        ("GGG", _bars([100 + 9 * math.sin(i / 8.0) for i in range(n)])),  # choppy
        ("HHH", _bars([100 * (1.0004 ** i) for i in range(n)])),   # mild uptrend
    ]


def _dataset(order="sorted"):
    """Assemble the universe into a (symbol_bars, spy_bars) pair, controlling the
    dict INSERTION order so we can prove the gate is insertion-order invariant.
    order: 'sorted' | 'reversed' | 'hash' (hash = python set iteration order)."""
    pairs = _series()
    syms = [s for s, _ in pairs]
    if order == "sorted":
        keys = sorted(syms)
    elif order == "reversed":
        keys = sorted(syms, reverse=True)
    elif order == "hash":
        keys = list(set(syms))  # str-set iteration: hash-seed dependent insertion order
    else:
        raise ValueError(order)
    lut = dict(pairs)
    symbol_bars = {k: lut[k] for k in keys}
    return symbol_bars, lut["SPY"]


def _run_gate(order="sorted"):
    """Run the REAL gate the EOD loop uses; return the order-/seed-sensitive outputs."""
    symbol_bars, spy_bars = _dataset(order)
    baseline = load_adaptive_params()
    candidate = {**baseline, **DELTA}
    approved, detail = gate_param_change(baseline, candidate, symbol_bars, spy_bars)
    # Round the float to neutralize meaningless last-bit noise; the point is that
    # ordering must not change the *value*, not bit-exactness of IEEE addition.
    cand = detail.get("candidate_oos_sharpe")
    return {
        "approved": bool(approved),
        "candidate_oos_sharpe": round(cand, 6) if isinstance(cand, (int, float)) else cand,
        "current_oos_sharpe": detail.get("current_oos_sharpe"),
        "n_windows": detail.get("n_windows"),
    }


# --------------------------------------------------------------------------- #
# 1) Unit: the relative-strength ranking is self-deterministic (the root fix). #
#    RED before analyst_v2.rank_by_relative_strength got the (symbol) tiebreak. #
# --------------------------------------------------------------------------- #
def test_rank_by_relative_strength_insertion_order_invariant():
    twin = [{"c": 100 + i * 0.1} for i in range(130)]   # AAA == BBB -> exact rs_score tie
    other = [{"c": 50 + i * 0.1} for i in range(130)]

    fwd = rank_by_relative_strength({"AAA": list(twin), "BBB": list(twin), "ZZZ": other})
    rev = rank_by_relative_strength({"BBB": list(twin), "AAA": list(twin), "ZZZ": other})

    def view(ranked):
        return {r["symbol"]: (r["rank"], r["percentile"]) for r in ranked}

    # Confirm the tie actually exists (otherwise the test would be vacuous).
    rs = {r["symbol"]: r["rs_score"] for r in fwd}
    assert rs["AAA"] == rs["BBB"]
    # Same ranks/percentiles regardless of which tied symbol was inserted first.
    assert view(fwd) == view(rev)
    # And the tie is broken alphabetically (AAA outranks BBB), deterministically.
    assert view(fwd)["AAA"][0] < view(fwd)["BBB"][0]


# --------------------------------------------------------------------------- #
# 2) Integration: the full gate is invariant to input dict insertion order.    #
# --------------------------------------------------------------------------- #
def test_gate_param_change_insertion_order_invariant():
    base = _run_gate("sorted")
    # Not vacuous: the gate must actually have run a backtest (produced an OOS Sharpe).
    assert isinstance(base["candidate_oos_sharpe"], (int, float)), base
    assert base["n_windows"] and base["n_windows"] >= 2
    for order in ("reversed", "hash"):
        assert _run_gate(order) == base, f"gate differs for insertion order={order}"


# --------------------------------------------------------------------------- #
# 3) Cross-process: identical OOS Sharpe + approval under two PYTHONHASHSEEDs.  #
#    This is the exact reproduction from the bug report.                        #
# --------------------------------------------------------------------------- #
def _gate_under_seed(seed):
    env = {**os.environ, "PYTHONHASHSEED": str(seed)}
    proc = subprocess.run([sys.executable, os.path.abspath(__file__)],
                          env=env, cwd=REPO_ROOT, capture_output=True,
                          text=True, timeout=600)
    assert proc.returncode == 0, f"seed={seed} failed:\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_gate_param_change_hashseed_invariant():
    results = {seed: _gate_under_seed(seed) for seed in (0, 1, 2)}
    ref = results[0]
    assert isinstance(ref["candidate_oos_sharpe"], (int, float)), ref
    for seed, res in results.items():
        assert res == ref, f"PYTHONHASHSEED={seed} produced {res}, expected {ref}"


if __name__ == "__main__":
    # Subprocess entrypoint for test #3: emit one JSON line of the gate outputs.
    print(json.dumps(_run_gate("hash")))
