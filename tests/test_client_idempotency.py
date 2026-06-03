"""Verify P2 and P3 clients route orders through the shared hardened core and
thread the idempotency key (client_order_id) into the request body."""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P3_SCRIPTS = os.path.join(REPO_ROOT, "event-driven-bot", "scripts")
P2_SCRIPTS = os.path.join(REPO_ROOT, "political-copy-bot", "scripts")
for _p in (REPO_ROOT, P3_SCRIPTS, P2_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared import alpaca_http as http


class _FakeResp:
    status_code = 200
    text = '{"id":"o1","status":"accepted"}'
    headers = {}

    def json(self):
        return {"id": "o1", "status": "accepted"}

    def raise_for_status(self):
        pass


def _capture(monkeypatch):
    """Patch the shared HTTP layer to capture the outgoing request body."""
    captured = {}

    def fake(method, url, **kw):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kw.get("json")
        return _FakeResp()

    monkeypatch.setattr(http.time, "sleep", lambda *_: None)
    monkeypatch.setattr(http.requests, "request", fake)
    return captured


def test_p3_place_order_includes_client_order_id(monkeypatch):
    alpaca_client = pytest.importorskip("alpaca_client")
    captured = _capture(monkeypatch)

    c = alpaca_client.AlpacaClient.__new__(alpaca_client.AlpacaClient)
    c.headers = {"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}
    c.base_url = "https://paper-api.alpaca.markets"

    c.place_order(symbol="AAPL", qty=10, side="buy", order_type="market",
                  client_order_id="p3-20260529-AAPL-buy")
    assert captured["json"]["client_order_id"] == "p3-20260529-AAPL-buy"
    assert captured["method"] == "POST"


def test_p3_bracket_order_threads_client_order_id(monkeypatch):
    alpaca_client = pytest.importorskip("alpaca_client")
    captured = _capture(monkeypatch)

    c = alpaca_client.AlpacaClient.__new__(alpaca_client.AlpacaClient)
    c.headers = {"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}
    c.base_url = "https://paper-api.alpaca.markets"

    c.place_bracket_order(symbol="MSFT", qty=5, side="buy",
                          take_profit_price=110.0, stop_loss_price=90.0,
                          client_order_id="p3-20260529-MSFT-buy")
    body = captured["json"]
    assert body["client_order_id"] == "p3-20260529-MSFT-buy"
    assert body["order_class"] == "bracket"
    # GTC, not day: protective legs must persist across the whole multi-day hold.
    # A `day` bracket expired its stop/TP at the first close, leaving positions naked.
    assert body["time_in_force"] == "gtc"
    assert body["stop_loss"]["stop_price"] == "90.0"
    assert body["take_profit"]["limit_price"] == "110.0"


def test_p3_oco_rearm_is_gtc_and_well_formed(monkeypatch):
    alpaca_client = pytest.importorskip("alpaca_client")
    captured = _capture(monkeypatch)

    c = alpaca_client.AlpacaClient.__new__(alpaca_client.AlpacaClient)
    c.headers = {"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}
    c.base_url = "https://paper-api.alpaca.markets"

    c.place_oco_order(symbol="MSFT", qty=5, side="sell",
                      take_profit_price=120.0, stop_loss_price=95.0,
                      client_order_id="p3-rearm-20260603-MSFT-sell")
    body = captured["json"]
    assert body["order_class"] == "oco"
    assert body["time_in_force"] == "gtc"
    assert body["side"] == "sell"
    assert body["take_profit"]["limit_price"] == "120.0"
    assert body["stop_loss"]["stop_price"] == "95.0"
    # OCO carries the TP price in the take_profit leg, never a top-level limit_price.
    assert "limit_price" not in body
    assert body["client_order_id"] == "p3-rearm-20260603-MSFT-sell"


def test_p2_place_order_includes_client_order_id(monkeypatch):
    politician_bot = pytest.importorskip("politician_bot")
    captured = _capture(monkeypatch)

    c = politician_bot.AlpacaClient.__new__(politician_bot.AlpacaClient)
    c.headers = {"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}
    c.base_url = "https://paper-api.alpaca.markets"
    c.data_url = "https://data.alpaca.markets"

    c.place_order(symbol="T", qty=60, side="buy", order_type="limit",
                  limit_price=24.79, client_order_id="p2-20260529-T-buy")
    assert captured["json"]["client_order_id"] == "p2-20260529-T-buy"


def test_p2_client_routes_through_resilient_core(monkeypatch):
    # A transient 429 must be retried by the shared core when P2 calls the API.
    politician_bot = pytest.importorskip("politician_bot")
    calls = {"n": 0}

    def fake(method, url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            r = _FakeResp()
            r.status_code = 429
            r.headers = {"Retry-After": "0"}
            return r
        return _FakeResp()

    monkeypatch.setattr(http.time, "sleep", lambda *_: None)
    monkeypatch.setattr(http.requests, "request", fake)

    c = politician_bot.AlpacaClient.__new__(politician_bot.AlpacaClient)
    c.headers = {"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}
    c.base_url = "https://paper-api.alpaca.markets"
    c.data_url = "https://data.alpaca.markets"

    c.get_account()
    assert calls["n"] == 2  # retried once via shared core
