"""P3 sector diversification of the signal queue — 2026-06-02 audit.

The screener qualifies on absolute relative-strength momentum with no sector
awareness, so it floods the candidate list with whatever sector is hottest. On
2026-06-02, 8 of 13 P3 signals were Energy and 79% of the qualified watchlist was
Energy+Tech; both were already at the 20% exposure cap, so the executor placed 0
of 13. diversify_by_sector caps the strongest N names per sector so the queue
leaves room for sectors that still have headroom. These tests lock that contract.
"""
import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P3_SCRIPTS = os.path.join(REPO_ROOT, "event-driven-bot", "scripts")
for _p in (REPO_ROOT, P3_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from event_driven_bot import diversify_by_sector  # noqa: E402


def _sig(sym, sector, score):
    return {"symbol": sym, "sector": sector, "score": score}


def test_caps_per_sector_keeping_strongest_in_order():
    items = [_sig("VLO", "Energy", 0.80), _sig("EOG", "Energy", 0.73),
             _sig("XOM", "Energy", 0.65), _sig("HAL", "Energy", 0.50),
             _sig("CSCO", "Tech", 0.60), _sig("WMT", "Consumer", 0.65)]
    out = diversify_by_sector(items, 2)
    assert [s["symbol"] for s in out] == ["VLO", "EOG", "CSCO", "WMT"]
    assert sum(1 for s in out if s["sector"] == "Energy") == 2


def test_zero_or_none_disables():
    items = [_sig("A", "Energy", 0.8), _sig("B", "Energy", 0.7)]
    assert diversify_by_sector(items, 0) == items
    assert diversify_by_sector(items, None) == items


def test_unknown_sector_is_capped_like_any_other():
    items = [_sig("A", "Unknown", 0.9), _sig("B", "Unknown", 0.8), _sig("C", "Unknown", 0.7)]
    assert [s["symbol"] for s in diversify_by_sector(items, 2)] == ["A", "B"]


def test_under_cap_passes_through_untouched():
    items = [_sig("A", "Energy", 0.8), _sig("B", "Tech", 0.7)]
    assert diversify_by_sector(items, 3) == items


def test_real_2026_06_02_signal_mix():
    # 8 Energy + 4 Tech + 1 Consumer. Cap 3 -> 3 Energy + 3 Tech + 1 Consumer = 7,
    # so non-Energy sectors finally get a look instead of an all-Energy queue.
    items = ([_sig(f"E{i}", "Energy", 0.80 - i * 0.05) for i in range(8)]
             + [_sig(f"T{i}", "Tech", 0.60 - i * 0.05) for i in range(4)]
             + [_sig("WMT", "Consumer", 0.65)])
    out = diversify_by_sector(items, 3)
    counts = Counter(s["sector"] for s in out)
    assert counts["Energy"] == 3 and counts["Tech"] == 3 and counts["Consumer"] == 1
    assert len(out) == 7
