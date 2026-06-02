"""P3 within-sector rotation — 2026-06-02 audit follow-up.

When a sector is at its 20% exposure cap, a strong new leader was hard-skipped
even when the book held a clear laggard in that sector. pick_sector_rotation_exit
picks the weakest holding to swap out IFF the incoming candidate beats it by the
RS edge — capturing the better idea without breaching the cap, and refusing to
churn between similar-strength names.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P3_SCRIPTS = os.path.join(REPO_ROOT, "event-driven-bot", "scripts")
for _p in (REPO_ROOT, P3_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from event_driven_bot import pick_sector_rotation_exit  # noqa: E402


def _h(symbol, qty, rs):
    return {"symbol": symbol, "qty": qty, "rs": rs}


def test_swaps_out_weakest_when_candidate_dominates():
    held = [_h("XOM", 3, 0.5), _h("EOG", 5, 9.3)]
    pick = pick_sector_rotation_exit(24.6, held, edge=10.0)   # VLO RS +24.6
    assert pick["symbol"] == "XOM"                            # weakest RS exits


def test_no_swap_when_edge_not_met():
    held = [_h("EOG", 5, 9.3)]
    assert pick_sector_rotation_exit(15.0, held, edge=10.0) is None   # 15-9.3 < 10


def test_exactly_at_edge_swaps():
    held = [_h("EOG", 5, 5.0)]
    assert pick_sector_rotation_exit(15.0, held, edge=10.0)["symbol"] == "EOG"   # 15-5 == 10


def test_swaps_out_a_dropped_out_holding():
    # A name that fell out of the screen carries -999 RS -> always the one to exit.
    held = [_h("HAL", 10, -999.0), _h("VLO", 2, 24.6)]
    assert pick_sector_rotation_exit(11.0, held, edge=10.0)["symbol"] == "HAL"


def test_empty_sector_returns_none():
    assert pick_sector_rotation_exit(50.0, [], edge=10.0) is None


def test_degenerate_candidate_rs_returns_none():
    held = [_h("XOM", 3, 0.5)]
    assert pick_sector_rotation_exit(None, held) is None
    assert pick_sector_rotation_exit("x", held) is None
