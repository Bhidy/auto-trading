"""Heartbeat watchdog decision-logic tests."""
import heartbeat as hb


TODAY = "2026-05-29"


def test_all_fresh_no_alert():
    fresh = {
        "P1 Self Improving Brain": TODAY,
        "P2 Capitol Shadow": TODAY,
        "P3 Cautious Sniper": TODAY,
    }
    alert, summary = hb.assess(TODAY, fresh)
    assert alert is False
    assert "All 3" in summary


def test_one_stale_triggers_alert():
    fresh = {
        "P1 Self Improving Brain": TODAY,
        "P2 Capitol Shadow": "2026-05-28",  # yesterday -> stale
        "P3 Cautious Sniper": TODAY,
    }
    alert, summary = hb.assess(TODAY, fresh)
    assert alert is True
    assert "P2 Capitol Shadow" in summary
    assert "2026-05-28" in summary


def test_never_ran_triggers_alert():
    fresh = {
        "P1 Self Improving Brain": None,
        "P2 Capitol Shadow": TODAY,
        "P3 Cautious Sniper": TODAY,
    }
    alert, summary = hb.assess(TODAY, fresh)
    assert alert is True
    assert "never" in summary


def test_all_stale_triggers_alert():
    fresh = {k: "2026-05-20" for k in (
        "P1 Self Improving Brain", "P2 Capitol Shadow", "P3 Cautious Sniper")}
    alert, summary = hb.assess(TODAY, fresh)
    assert alert is True
    assert summary.count("-") >= 3  # multiple stale lines


def test_date_of_parses_iso():
    assert hb._date_of("2026-05-29T15:17:10.294980+00:00") == "2026-05-29"
    assert hb._date_of(None) is None
    assert hb._date_of("") is None
