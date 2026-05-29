"""Execution-layer resilience tests: HTTP retry/backoff, order idempotency,
and fill confirmation. These guard the money path."""
import types

import requests

import autonomous_runner as ar


# --- Idempotency key --------------------------------------------------------

def test_client_order_id_is_deterministic_per_day():
    a = ar.make_client_order_id("p1", "AAPL", "buy")
    b = ar.make_client_order_id("p1", "AAPL", "buy")
    assert a == b
    assert a.startswith("p1-")
    assert "AAPL" in a and a.endswith("-buy")


def test_client_order_id_strips_slash_for_crypto():
    cid = ar.make_client_order_id("p1", "BTC/USD", "buy")
    assert "/" not in cid
    assert "BTCUSD" in cid


def test_client_order_id_differs_by_side_and_symbol():
    assert ar.make_client_order_id("p1", "AAPL", "buy") != ar.make_client_order_id("p1", "AAPL", "sell")
    assert ar.make_client_order_id("p1", "AAPL", "buy") != ar.make_client_order_id("p1", "MSFT", "buy")


# --- Retry / backoff --------------------------------------------------------

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


def _client():
    """An AlpacaClient without touching the config file."""
    c = ar.AlpacaClient.__new__(ar.AlpacaClient)
    c.headers = {"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}
    c.base_url = "https://paper-api.alpaca.markets"
    c.data_url = "https://data.alpaca.markets"
    return c


def test_client_request_delegates_to_shared_core(monkeypatch):
    # P1's AlpacaClient._request must route through the shared hardened core,
    # inheriting retry/backoff. (Exhaustive retry cases: test_shared_alpaca_http.)
    from shared import alpaca_http as http
    calls = {"n": 0}

    def fake(method, url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp(429, headers={"Retry-After": "0"})
        return _FakeResp(200, payload={"ok": True}, text='{"ok":true}')

    monkeypatch.setattr(http.time, "sleep", lambda *_: None)
    monkeypatch.setattr(http.requests, "request", fake)
    assert _client()._request("GET", "http://x") == {"ok": True}
    assert calls["n"] == 2  # retried via shared core


# --- Fill confirmation ------------------------------------------------------

def _fake_alpaca(order_states):
    """order_states: list of get_order() return dicts, returned in sequence."""
    seq = iter(order_states)
    fake = types.SimpleNamespace()
    fake.get_order = lambda _id: next(seq)
    return fake


def test_confirm_fill_returns_real_price_on_fill(monkeypatch):
    monkeypatch.setattr(ar.time, "sleep", lambda *_: None)
    alp = _fake_alpaca([
        {"status": "filled", "filled_qty": "10", "filled_avg_price": "501.23"},
    ])
    status, qty, price = ar.confirm_fill(alp, "oid", timeout=5)
    assert status == "filled"
    assert qty == 10
    assert price == 501.23


def test_confirm_fill_unfilled_returns_zero(monkeypatch):
    monkeypatch.setattr(ar.time, "sleep", lambda *_: None)
    # Always 'new' -> loop times out, returns 0 filled, no phantom price
    alp = types.SimpleNamespace(get_order=lambda _id: {"status": "new", "filled_qty": "0",
                                                       "filled_avg_price": None})
    status, qty, price = ar.confirm_fill(alp, "oid", timeout=0.01, poll=0.001)
    assert qty == 0
    assert price is None


def test_confirm_fill_handles_poll_error(monkeypatch):
    monkeypatch.setattr(ar.time, "sleep", lambda *_: None)

    def boom(_id):
        raise RuntimeError("api down")

    alp = types.SimpleNamespace(get_order=boom)
    status, qty, price = ar.confirm_fill(alp, "oid", timeout=5)
    assert qty == 0  # never logs a phantom fill on error
