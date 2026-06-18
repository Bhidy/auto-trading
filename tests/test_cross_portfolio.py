"""Tests for the cross-portfolio aggregate-exposure monitor (committee rec #3)."""
import json

import heartbeat as hb
from shared.cross_portfolio import cross_portfolio_report, load_books

_CLUSTERS = {"mega_cap_tech_ai": ["AAPL", "NVDA", "QQQ", "XLK", "AMZN"]}


def _books():
    return [
        {"portfolio_id": "p1", "equity": 100_000, "positions": [
            {"symbol": "AAPL", "market_value": 9_000, "sector": None},
            {"symbol": "NVDA", "market_value": 8_000, "sector": None},
        ]},
        {"portfolio_id": "p2", "equity": 100_000, "positions": [
            {"symbol": "AAPL", "market_value": 6_000, "sector": None},
            {"symbol": "DIA", "market_value": 7_000, "sector": None},
        ]},
        {"portfolio_id": "p3", "equity": 100_000, "positions": [
            {"symbol": "QQQ", "market_value": 9_000, "sector": "Technology"},
        ]},
    ]


def test_report_flags_aggregate_single_name_breach():
    # AAPL: (9k+6k)/300k = 5% -> under 10%; raise the combined book to breach.
    books = _books()
    books[1]["positions"][0]["market_value"] = 30_000  # AAPL p2 -> 39k total = 13%
    rep = cross_portfolio_report(books, single_name_cap_pct=10.0, sector_cap_pct=30.0)
    assert "AAPL" in rep["single_name_breaches"]
    assert rep["ok"] is False


def test_report_flags_correlated_cluster_breach():
    # Cluster = AAPL(15k)+NVDA(8k)+QQQ(9k) = 32k / 300k = 10.67%.
    rep = cross_portfolio_report(_books(), clusters=_CLUSTERS, max_cluster_pct=10.0)
    assert "mega_cap_tech_ai" in rep["cluster_breaches"]
    assert rep["cluster_exposure_pct"]["mega_cap_tech_ai"] > 10.0
    assert rep["ok"] is False


def test_report_ok_when_within_caps():
    rep = cross_portfolio_report(_books(), single_name_cap_pct=10.0, sector_cap_pct=30.0,
                                 clusters=_CLUSTERS, max_cluster_pct=55.0)
    assert rep["single_name_breaches"] == []
    assert rep["cluster_breaches"] == []
    assert rep["ok"] is True


def test_report_handles_empty_books():
    rep = cross_portfolio_report([], clusters=_CLUSTERS, max_cluster_pct=55.0)
    assert rep["total_equity"] == 0.0
    assert rep["ok"] is True


def test_unknown_sector_never_trips_sector_breach():
    # P1/P2 carry no sector -> all value pools into "Unknown" (here 100% of book).
    # That metadata gap must NOT raise a false sector breach.
    books = [{"portfolio_id": "p1", "equity": 100_000, "positions": [
        {"symbol": "AAPL", "market_value": 50_000, "sector": None},
        {"symbol": "MSFT", "market_value": 40_000, "sector": None},
    ]}]
    rep = cross_portfolio_report(books, single_name_cap_pct=80.0, sector_cap_pct=30.0)
    assert rep["sector_breaches"] == []     # 'Unknown' excluded despite 90% weight
    assert rep["ok"] is True


def test_load_books_normalizes_three_schemas(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "political-copy-bot" / "data").mkdir(parents=True)
    (tmp_path / "event-driven-bot" / "data").mkdir(parents=True)
    # P1: positions dict with qty/avg_price
    (tmp_path / "data" / "portfolio_state.json").write_text(json.dumps({
        "equity": 99_000,
        "positions": {"NVDA": {"qty": 10, "avg_price": 200.0}},
    }))
    # P2: account.equity + positions list with market_value
    (tmp_path / "political-copy-bot" / "data" / "portfolio_state.json").write_text(json.dumps({
        "account": {"equity": "100163.32"},
        "positions": [{"symbol": "DIA", "qty": "13", "avg_entry": "512.5",
                       "market_value": "6640.46"}],
    }))
    # P3: bot_state equity + trade_log open trades (status-tagged, sector-tagged)
    (tmp_path / "event-driven-bot" / "data" / "bot_state.json").write_text(json.dumps({
        "equity": 105_000}))
    (tmp_path / "event-driven-bot" / "data" / "trade_log.json").write_text(json.dumps([
        {"symbol": "VLO", "qty": 10, "entry_price": 260.0, "sector": "Energy", "status": "open"},
        {"symbol": "CSCO", "qty": 5, "entry_price": 120.0, "sector": "Tech",
         "status": "closed_reconciled"},  # excluded (not open)
    ]))
    books = load_books(str(tmp_path))
    by_id = {b["portfolio_id"]: b for b in books}
    assert by_id["portfolio_1"]["positions"][0] == {
        "symbol": "NVDA", "market_value": 2_000.0, "sector": None}
    assert by_id["portfolio_2"]["equity"] == 100163.32
    assert by_id["portfolio_2"]["positions"][0]["market_value"] == 6640.46
    # P3 includes only the OPEN trade
    p3_syms = [p["symbol"] for p in by_id["portfolio_3"]["positions"]]
    assert p3_syms == ["VLO"]
    assert by_id["portfolio_3"]["positions"][0]["sector"] == "Energy"


# --- heartbeat surfacing ----------------------------------------------------

def test_heartbeat_assess_alerts_on_breach():
    report = {"single_name_breaches": ["AAPL"], "sector_breaches": [],
              "cluster_breaches": ["mega_cap_tech_ai"], "single_name_cap_pct": 10.0,
              "max_cluster_exposure_pct": 55.0, "gross_exposure_pct": 90.0}
    alert, summary = hb.assess_cross_portfolio(report)
    assert alert is True
    assert "AAPL" in summary and "mega_cap_tech_ai" in summary


def test_heartbeat_assess_clean_when_within_caps():
    report = {"single_name_breaches": [], "sector_breaches": [], "cluster_breaches": [],
              "gross_exposure_pct": 80.0}
    alert, summary = hb.assess_cross_portfolio(report)
    assert alert is False
    assert "within aggregate caps" in summary


def test_heartbeat_assess_missing_report_no_alert():
    alert, _summary = hb.assess_cross_portfolio(None)
    assert alert is False
