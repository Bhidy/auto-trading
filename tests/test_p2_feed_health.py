"""P2 dark-feed alarm (2026-06 audit fix).

The Capitol Trades disclosure feed ran 100% rate-limited for ~3 weeks and NO
watchdog noticed, because a fully-failed scan returns 0 trades — identical to
"quiet markets". These tests prove (1) the feed-health classifier flags a fully
failed scan as 'dark', and (2) a dark feed becomes a conformance violation that
the heartbeat watchdog (assess_integrity) already turns into an alert.
"""
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P2_SCRIPTS = os.path.join(REPO_ROOT, "political-copy-bot", "scripts")
for _p in (REPO_ROOT, P2_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from politician_bot import disclosure_feed_status  # noqa: E402
from shared.integrity import strategy_conformance  # noqa: E402
from scripts.heartbeat import assess_integrity  # noqa: E402


def test_feed_status_classifies_dark_degraded_ok():
    assert disclosure_feed_status(14, 14) == "dark"     # the real 3-week outage
    assert disclosure_feed_status(14, 6) == "degraded"
    assert disclosure_feed_status(14, 0) == "ok"
    assert disclosure_feed_status(0, 0) == "ok"          # nothing attempted != dark


def test_dark_feed_is_a_conformance_violation():
    dark = disclosure_feed_status(14, 14) == "dark"
    conf = strategy_conformance(portfolio_id="portfolio_2", checks=[
        {"name": "disclosure_feed_reachable", "ok": not dark, "detail": "14/14 failed"},
    ])
    assert conf["conformant"] is False
    assert any(v["name"] == "disclosure_feed_reachable" for v in conf["violations"])


def test_heartbeat_alerts_on_dark_feed_conformance():
    # End-to-end: a today-dated P2 conformance report with a dark feed must trip
    # the heartbeat watchdog so a GitHub issue is opened (no more silent outage).
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conf = strategy_conformance(portfolio_id="portfolio_2", checks=[
        {"name": "disclosure_feed_reachable", "ok": False, "detail": "FEED DARK: 14/14 failed"},
    ])
    reports = {"P2 Capitol Shadow": {"integrity": None, "conformance": conf, "preflight": None}}
    alert, summary = assess_integrity(reports, today)
    assert alert is True
    assert "disclosure_feed_reachable" in summary
