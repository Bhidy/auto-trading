"""Adoption of the workflow-validated optimization (wfbtwy38x):
1) the backtester is now REPRODUCIBLE across processes (the Challenger found
   hash-seed-dependent set ordering made absolute Sharpe numbers a lottery);
2) the live breakeven trigger is PARAMETERIZED so the validated 0.03->0.08
   change (stop killing winners) is realizable in production.
"""
import os
import subprocess
import sys

from portfolio_manager import compute_stop_levels

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Five symbols with IDENTICAL trajectories -> tied scores. If symbol selection
# were set-ordered (hash-randomized), different seeds would pick a different 2 of
# 5 and diverge. The deterministic fix (sorted symbols + ranked, tie-broken
# selection) must give the SAME equity curve under every seed.
_CODE = (
    "import sys; sys.path.insert(0, 'scripts')\n"
    "from backtest.multifactor import backtest_multifactor\n"
    "def bars(cl):\n"
    "    out=[]; prev=cl[0]\n"
    "    for c in cl:\n"
    "        out.append({'t':'','o':prev,'h':max(c,prev)*1.002,'l':min(c,prev)*0.998,'c':c,'v':1000000}); prev=c\n"
    "    return out\n"
    "n=240\n"
    "syms={'SPY':bars([400*(1.0006**i) for i in range(n)])}\n"
    "for nm in ['AAA','BBB','CCC','DDD','EEE']:\n"
    "    syms[nm]=bars([100*(1.001**i) for i in range(n)])\n"
    "r=backtest_multifactor(syms, syms['SPY'], max_positions=2, warmup=200)\n"
    "print(round(r['equity_curve'][-1], 6))\n"
)


def _run(seed):
    env = {**os.environ, "PYTHONHASHSEED": str(seed)}
    out = subprocess.run([sys.executable, "-c", _CODE], cwd=REPO_ROOT, env=env,
                         capture_output=True, text=True, timeout=90)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_backtest_reproducible_across_hashseeds():
    results = {_run(s) for s in (0, 1, 2, 13)}
    assert len(results) == 1, f"backtest non-deterministic across hash seeds: {results}"


# --- live breakeven parameterization -------------------------------------

def _pos(entry, current):
    return [{"symbol": "X", "avg_entry_price": entry, "current_price": current, "side": "long"}]


def test_default_breakeven_arms_at_3pct():
    # Legacy behavior: up >3% -> breakeven stop at entry*1.005.
    stops = compute_stop_levels(_pos(100.0, 105.0), {"signals": []})
    assert stops["X"]["stop_loss"] == 100.5


def test_adopted_8pct_trigger_does_not_kill_a_5pct_winner():
    # The validated change: with 0.08 trigger, a +5% winner is NOT breakeven-stopped
    # (the disposition-error fix — it gets room to run).
    stops = compute_stop_levels(_pos(100.0, 105.0), {"signals": []},
                                params={"breakeven_trigger_pct": 0.08})
    assert stops["X"]["stop_loss"] is None


def test_8pct_trigger_still_locks_at_9pct():
    stops = compute_stop_levels(_pos(100.0, 109.0), {"signals": []},
                                params={"breakeven_trigger_pct": 0.08})
    assert stops["X"]["stop_loss"] == 100.5
