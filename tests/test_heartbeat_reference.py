"""The heartbeat must verify the right session-date even when GitHub Actions
delays a scheduled run past UTC midnight (the 02:00-UTC false-'STALE' alert)."""
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import heartbeat  # noqa: E402


def _utc(y, m, d, h):
    return datetime(y, m, d, h, 0, tzinfo=timezone.utc)


def test_on_time_evening_run_verifies_same_day():
    # Scheduled 22:30 / 23:30 UTC runs — unchanged behavior.
    assert heartbeat.reference_session_date(_utc(2026, 6, 1, 22)) == "2026-06-01"
    assert heartbeat.reference_session_date(_utc(2026, 6, 1, 23)) == "2026-06-01"


def test_delayed_post_midnight_run_verifies_previous_day():
    # The exact bug: a run delayed to 02:00 UTC Jun-2 must verify Jun-1's session,
    # not Jun-2 (whose session has not happened) — no more false STALE alert.
    assert heartbeat.reference_session_date(_utc(2026, 6, 2, 2)) == "2026-06-01"
    assert heartbeat.reference_session_date(_utc(2026, 5, 30, 1)) == "2026-05-29"


def test_boundary_at_21_utc():
    assert heartbeat.reference_session_date(_utc(2026, 6, 1, 21)) == "2026-06-01"   # post-close
    assert heartbeat.reference_session_date(_utc(2026, 6, 1, 20)) == "2026-05-31"   # pre-close
