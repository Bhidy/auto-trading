"""P3 sector-cap enforcement (2026-06-02 audit).

The configured sector cap is 20%, but execute_signals only blocked adding to a
sector ALREADY at the cap — it never checked whether the incoming (tranche-sized,
~15-18%) position would PUSH the sector over. So P3 held two ~15% names per
sector and reached ~33% Tech / ~29% Energy on a 20% cap. These tests lock the
fix: the cap is enforced on PROPOSED exposure (current + this order), matching
P1's risk_officer pattern, so a 20% cap means 20% — not ~2x the position size.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P3_SCRIPTS = os.path.join(REPO_ROOT, "event-driven-bot", "scripts")
for _p in (REPO_ROOT, P3_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from event_driven_bot import sector_cap_breached  # noqa: E402

EQUITY = 100_000.0
CAP = 20.0


def test_first_position_under_cap_is_allowed():
    # Empty sector + a 15% position = 15% proposed, within the 20% cap.
    assert sector_cap_breached(0, 15_000, EQUITY, CAP) is False


def test_second_same_sector_position_that_breaches_is_blocked():
    # THE REGRESSION: sector already at 15%, a second ~15% entry would take it to
    # 30% — must be blocked. The old `current >= cap` check let this through
    # (15% < 20%), which is how P3 reached ~33% in a sector.
    assert sector_cap_breached(15_000, 15_000, EQUITY, CAP) is True


def test_exactly_at_cap_is_allowed():
    # Proposed == cap is fine (mirrors risk_officer's strict `>` comparison).
    assert sector_cap_breached(5_000, 15_000, EQUITY, CAP) is False  # -> 20.0%


def test_just_over_cap_is_blocked():
    assert sector_cap_breached(5_000, 15_010, EQUITY, CAP) is True  # -> 20.01%


def test_real_p3_live_scenario_is_now_blocked():
    # P3 on 2026-06-02 held Tech ~14.6% (~$14,600) at cost; a second comparable
    # tech name would push Tech to ~29% — exactly what must now be refused.
    assert sector_cap_breached(14_600, 14_600, EQUITY, CAP) is True


def test_fails_closed_on_nonpositive_equity():
    assert sector_cap_breached(0, 1_000, 0, CAP) is True
    assert sector_cap_breached(0, 1_000, -5, CAP) is True
