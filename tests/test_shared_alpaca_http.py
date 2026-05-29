"""Tests for the shared hardened broker core used by all 3 portfolios."""
import types

import pytest
import requests

from shared import alpaca_http as http


class _FakeResp:
    def __init__(self, status, payload=None, text="{}", headers=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code}")
            err.response = self
            raise err


HEADERS = {"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}


# --- resilient_request ------------------------------------------------------

def test_retries_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake(method, url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp(429, headers={"Retry-After": "0"})
        return _FakeResp(200, payload={"ok": True}, text='{"ok":true}')

    monkeypatch.setattr(http.time, "sleep", lambda *_: None)
    monkeypatch.setattr(http.requests, "request", fake)
    assert http.resilient_request("GET", "http://x", HEADERS) == {"ok": True}
    assert calls["n"] == 2


def test_5xx_exhausts_then_raises(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda *_: None)
    monkeypatch.setattr(http.requests, "request", lambda *a, **k: _FakeResp(503))
    with pytest.raises(requests.HTTPError):
        http.resilient_request("GET", "http://x", HEADERS)


def test_4xx_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake(method, url, **kw):
        calls["n"] += 1
        return _FakeResp(422, text="dupe client_order_id")

    monkeypatch.setattr(http.time, "sleep", lambda *_: None)
    monkeypatch.setattr(http.requests, "request", fake)
    with pytest.raises(requests.HTTPError):
        http.resilient_request("POST", "http://x", HEADERS, json_body={"a": 1})
    assert calls["n"] == 1


def test_network_error_retried(monkeypatch):
    calls = {"n": 0}

    def fake(method, url, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.ConnectionError("boom")
        return _FakeResp(200, payload={"ok": 1}, text='{"ok":1}')

    monkeypatch.setattr(http.time, "sleep", lambda *_: None)
    monkeypatch.setattr(http.requests, "request", fake)
    assert http.resilient_request("GET", "http://x", HEADERS) == {"ok": 1}
    assert calls["n"] == 3


def test_204_returns_empty(monkeypatch):
    monkeypatch.setattr(http.requests, "request", lambda *a, **k: _FakeResp(204, text=""))
    assert http.resilient_request("DELETE", "http://x", HEADERS) == {}


# --- make_client_order_id ---------------------------------------------------

def test_client_order_id_deterministic_and_safe():
    a = http.make_client_order_id("p2", "AAPL", "buy", day="20260529")
    b = http.make_client_order_id("p2", "AAPL", "buy", day="20260529")
    assert a == b == "p2-20260529-AAPL-buy"
    assert "/" not in http.make_client_order_id("p1", "BTC/USD", "buy", day="20260529")


def test_client_order_id_differs_by_portfolio_side_symbol():
    d = "20260529"
    ids = {
        http.make_client_order_id("p1", "AAPL", "buy", day=d),
        http.make_client_order_id("p2", "AAPL", "buy", day=d),
        http.make_client_order_id("p1", "AAPL", "sell", day=d),
        http.make_client_order_id("p1", "MSFT", "buy", day=d),
    }
    assert len(ids) == 4


# --- confirm_fill -----------------------------------------------------------

def test_confirm_fill_real_price():
    client = types.SimpleNamespace(
        get_order=lambda _id: {"status": "filled", "filled_qty": "10",
                               "filled_avg_price": "501.23"})
    status, qty, price = http.confirm_fill(client, "oid", timeout=5)
    assert (status, qty, price) == ("filled", 10.0, 501.23)


def test_confirm_fill_unfilled_no_phantom():
    client = types.SimpleNamespace(
        get_order=lambda _id: {"status": "new", "filled_qty": "0",
                               "filled_avg_price": None})
    status, qty, price = http.confirm_fill(client, "oid", timeout=0.01, poll=0.001)
    assert qty == 0.0 and price is None


def test_confirm_fill_no_order_id():
    client = types.SimpleNamespace(get_order=lambda _id: {})
    assert http.confirm_fill(client, None) == ("unknown", 0.0, None)


def test_confirm_fill_handles_poll_error():
    def boom(_id):
        raise RuntimeError("api down")
    client = types.SimpleNamespace(get_order=boom)
    _, qty, price = http.confirm_fill(client, "oid", timeout=5)
    assert qty == 0.0 and price is None
