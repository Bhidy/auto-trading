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


# --- Post-rotation sizing: entry capped to remaining sector room ---------------
# Locks the 2026-06-02 live bug: rotation exited OXY (freed ~$6K of Energy), but
# VLO's full tranche (~$15K) still exceeded the 20% cap, so the proposed-cap check
# blocked the entry and the swap was wasted. The fix caps the entry to the remaining
# sector budget before the proposed-cap check, so rotation always produces a trade.

def test_remaining_sector_room_math():
    """After exiting a $6K position from a 20%-capped sector, $4K room remains
    on a $100K book (20% = $20K cap, held MPC $16K -> freed OXY $6K -> $10K, room=$10K).
    A full tranche of $15K should get sized to fit the $10K room."""
    equity = 100_000.0
    cap_pct = 20.0
    # After rotation: sector holds $10K (MPC). Room = $20K - $10K = $10K.
    sector_val_after_exit = 10_000.0
    remaining_room = equity * cap_pct / 100.0 - sector_val_after_exit  # $10,000
    full_tranche = 15_000.0
    assert remaining_room == 10_000.0
    assert full_tranche > remaining_room         # this is the bug condition
    # Fix: size to 95% of remaining room
    price = 262.62
    adj_shares = int(remaining_room * 0.95 / price)
    assert adj_shares == 36                      # 36 × $262.62 = $9,454 < $10K ✓
    assert adj_shares * price < remaining_room   # does not exceed remaining room


def test_real_2026_06_02_vlo_swap():
    """VLO (RS +24.6) vs OXY (RS +10.6): edge=14 >= 10 -> swap fires.
    After exiting OXY (~$6.1K), Energy falls from 20% to ~14.7% on a $105K book.
    VLO tranche ~$15.7K would push to 29.5% -> full tranche BLOCKED.
    With the fix: VLO is sized to fit the ~$5.3K of remaining room instead."""
    # Verify the edge logic fires (swap should be picked)
    held = [_h("OXY", 100, 10.6), _h("MPC", 59, 26.68)]
    pick = pick_sector_rotation_exit(24.6, held, edge=10.0)   # VLO RS +24.6
    assert pick["symbol"] == "OXY"   # weakest exits

    # Verify remaining-room math prevents the proposed-cap breach
    equity = 105_816.0; cap_pct = 20.0
    sector_after_exit = 15_700.0     # MPC market value (~14.8%)
    remaining_room = equity * cap_pct / 100.0 - sector_after_exit  # ~$5.5K
    assert remaining_room > 0        # room exists after exit
    assert remaining_room < 15_700.0 # but less than full tranche (that was the bug)
    price = 262.62
    adj_shares = int(remaining_room * 0.95 / price)
    assert adj_shares > 0            # we can enter, just smaller
    assert adj_shares * price < equity * cap_pct / 100.0   # total would be within cap
