"""P2 TRUE trailing stop (committee fix 2026-06-18).

The live P2 stop fired on `unrealized_plpc <= -X%` — a FIXED stop from entry,
despite the config name `trailing_stop_pct`. The backtest that justified widening
it modeled a TRAILING (peak-based) stop, so the validation didn't transfer. This
replaces it with a real trailing stop: exit when price has fallen `stop_pct`% from
the position's high-water mark, matching `current_price <= peak_price*(1-stop)`.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P2_SCRIPTS = os.path.join(REPO_ROOT, "political-copy-bot", "scripts")
for _p in (REPO_ROOT, P2_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from politician_bot import trailing_stop_triggered  # noqa: E402


def test_fresh_position_at_peak_does_not_trigger():
    assert trailing_stop_triggered(0.0, 0.0, 15.0) is False
    assert trailing_stop_triggered(5.0, 5.0, 15.0) is False   # new winner, peak==now


def test_winner_pullback_locks_in_gains_at_trail_from_peak():
    # Peak +20%: 15% trail => exit when price <= peak_price*0.85 (i.e. plpc ~ +2%).
    assert trailing_stop_triggered(1.0, 20.0, 15.0) is True    # 15%+ below the peak
    assert trailing_stop_triggered(5.0, 20.0, 15.0) is False   # only ~12.5% below peak -> hold


def test_pure_loser_floors_at_trail_pct_from_entry():
    # Never rose (peak ~ entry/0%): a 15% trail exits at -15% from entry, not before.
    assert trailing_stop_triggered(-15.0, 0.0, 15.0) is True
    assert trailing_stop_triggered(-10.0, 0.0, 15.0) is False


def test_disabled_when_stop_not_positive():
    assert trailing_stop_triggered(-50.0, 0.0, 0) is False
    assert trailing_stop_triggered(-50.0, 0.0, None) is False
