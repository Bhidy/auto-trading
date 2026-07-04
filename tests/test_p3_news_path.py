"""P3 news/event-tranche execution path (audit 2026-07-04, defect D1).

The 20% event_driven tranche never executed a trade: news signals carry no
``atr``, and the sizing fallback iterated the watchlist artifact — a DICT
({"timestamp", "total_screened", "qualified", "universe"}) — as if it were a
list of rows, raising ``AttributeError: 'str' object has no attribute 'get'``
on every attempt. The workflow's ``|| true`` masked the crash. These tests pin
the fixed lookup helper and the scan_news price/atr enrichment so the tranche
can never be silently disabled by an artifact-shape change again.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P3_SCRIPTS = os.path.join(REPO_ROOT, "event-driven-bot", "scripts")
for _p in (REPO_ROOT, P3_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from event_driven_bot import scan_news, watchlist_atr_lookup  # noqa: E402

DICT_ARTIFACT = {
    "timestamp": "2026-07-01T14:00:00+00:00",
    "total_screened": 500,
    "qualified": 34,
    "universe": [
        {"symbol": "DDOG", "sector": "Tech", "price": 150.25, "atr14": 5.2},
        {"symbol": "JPM", "sector": "Financials", "price": 334.4, "atr14": 4.1},
    ],
}


def test_atr_lookup_handles_dict_artifact():
    # The exact production shape that used to crash the news path.
    assert watchlist_atr_lookup(DICT_ARTIFACT, "DDOG") == 5.2


def test_atr_lookup_handles_legacy_list_and_atr_key():
    rows = [{"symbol": "MU", "atr": 3.7}]
    assert watchlist_atr_lookup(rows, "MU") == 3.7


def test_atr_lookup_missing_symbol_and_junk_are_zero():
    assert watchlist_atr_lookup(DICT_ARTIFACT, "NOPE") == 0.0
    assert watchlist_atr_lookup({}, "DDOG") == 0.0
    assert watchlist_atr_lookup(None, "DDOG") == 0.0
    assert watchlist_atr_lookup({"universe": ["DDOG", 42]}, "DDOG") == 0.0
    assert watchlist_atr_lookup({"universe": [{"symbol": "X", "atr14": "bad"}]}, "X") == 0.0


class _StubAlpaca:
    """get_news stub — one positive-catalyst headline on a universe name."""

    def __init__(self, news):
        self._news = news

    def get_news(self, limit=50):
        return {"news": self._news}


def test_scan_news_enriches_signals_with_price_and_atr():
    alpaca = _StubAlpaca([
        {
            "headline": "Datadog acquires Adaptive ML in strategic partnership",
            "symbols": ["DDOG", "ZZZZ"],
            "source": "benzinga",
            "created_at": "2026-07-01T14:03:19Z",
        }
    ])
    signals = scan_news(alpaca, DICT_ARTIFACT["universe"])
    assert len(signals) == 1
    sig = signals[0]
    assert sig["symbol"] == "DDOG"
    assert sig["signal"] == "NEWS_BUY"
    # The D1 fix: execution can size this signal without re-reading the artifact.
    assert sig["price"] == 150.25
    assert sig["atr"] == 5.2


def test_scan_news_tolerates_bare_symbol_strings():
    alpaca = _StubAlpaca([
        {
            "headline": "JPMorgan beats estimates with record revenue",
            "symbols": ["JPM"],
            "source": "benzinga",
            "created_at": "2026-07-01T14:03:19Z",
        }
    ])
    signals = scan_news(alpaca, ["JPM"])
    assert len(signals) == 1
    # No screen row available -> zeros, so execution falls back to live quote
    # and the (now shape-safe) watchlist ATR lookup.
    assert signals[0]["price"] == 0
    assert signals[0]["atr"] == 0
