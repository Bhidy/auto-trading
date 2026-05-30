#!/usr/bin/env python3
"""Alpaca REST API client for Portfolio 3.

Routes all broker calls through the shared hardened core (shared.alpaca_http)
for retry/backoff, order idempotency, and fill confirmation — identical to P1
and P2.
"""

import json
import logging
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# confirm_fill / make_client_order_id are re-exported for event_driven_bot.
from shared.alpaca_http import (  # noqa: E402,F401  (path set above; re-exported)
    confirm_fill,
    make_client_order_id,
    resilient_request,
)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "alpaca_config.json"
log = logging.getLogger("p3_alpaca")


class AlpacaClient:
    def __init__(self):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        self.api_key = cfg["api_key"]
        self.api_secret = cfg["api_secret"]
        self.base_url = cfg["base_url"]
        self.data_url = cfg["data_url"]
        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }

    def _get(self, url, params=None):
        return resilient_request("GET", url, self.headers, params=params, logger=log)

    def _post(self, url, data):
        return resilient_request("POST", url, self.headers, json_body=data, logger=log)

    def _delete(self, url, params=None):
        return resilient_request("DELETE", url, self.headers, params=params, logger=log)

    def get_account(self):
        return self._get(f"{self.base_url}/v2/account")

    def get_clock(self):
        return self._get(f"{self.base_url}/v2/clock")

    def is_market_open(self):
        return self.get_clock().get("is_open", False)

    def get_positions(self):
        return self._get(f"{self.base_url}/v2/positions")

    def get_position(self, symbol):
        try:
            return self._get(f"{self.base_url}/v2/positions/{symbol}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def get_orders(self, status="open"):
        return self._get(f"{self.base_url}/v2/orders", {"status": status})

    def get_stock_bars(self, symbol, timeframe="1Day", start=None, limit=220):
        params = {"timeframe": timeframe, "limit": limit, "feed": "sip"}
        if start:
            params["start"] = start
        return self._get(f"{self.data_url}/v2/stocks/{symbol}/bars", params)

    def get_stock_bars_multi(self, symbols, timeframe="1Day", start=None, limit=220):
        params = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "limit": limit,
            "feed": "sip",
        }
        if start:
            params["start"] = start
        return self._get(f"{self.data_url}/v2/stocks/bars", params)

    def get_latest_quote(self, symbol):
        return self._get(f"{self.data_url}/v2/stocks/{symbol}/quotes/latest")

    def get_latest_trade(self, symbol):
        return self._get(f"{self.data_url}/v2/stocks/{symbol}/trades/latest")

    def get_snapshot(self, symbol):
        return self._get(f"{self.data_url}/v2/stocks/{symbol}/snapshot", {"feed": "sip"})

    def get_snapshots(self, symbols):
        return self._get(f"{self.data_url}/v2/stocks/snapshots",
                         {"symbols": ",".join(symbols), "feed": "sip"})

    def get_most_active(self, top=50):
        return self._get(f"{self.data_url}/v1beta1/screener/stocks/most-actives",
                         {"top": top})

    def get_market_movers(self, top=20):
        return self._get(f"{self.data_url}/v1beta1/screener/stocks/movers",
                         {"top": top})

    def get_news(self, symbols=None, limit=50):
        params = {"limit": limit, "sort": "desc"}
        if symbols:
            params["symbols"] = ",".join(symbols)
        return self._get(f"{self.data_url}/v1beta1/news", params)

    def place_order(self, symbol, qty=None, notional=None, side="buy",
                    order_type="market", limit_price=None, stop_price=None,
                    time_in_force="day", trail_percent=None, order_class=None,
                    take_profit=None, stop_loss=None, client_order_id=None):
        data = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        if qty:
            data["qty"] = str(qty)
        if notional:
            data["notional"] = str(round(notional, 2))
        if limit_price and order_type in ("limit", "stop_limit"):
            data["limit_price"] = str(round(limit_price, 2))
        if stop_price and order_type in ("stop", "stop_limit"):
            data["stop_price"] = str(round(stop_price, 2))
        if trail_percent and order_type == "trailing_stop":
            data["trail_percent"] = str(round(trail_percent, 2))
        if order_class:
            data["order_class"] = order_class
        if take_profit:
            data["take_profit"] = take_profit
        if stop_loss:
            data["stop_loss"] = stop_loss
        if client_order_id:
            data["client_order_id"] = client_order_id
        return self._post(f"{self.base_url}/v2/orders", data)

    def place_bracket_order(self, symbol, qty, side, take_profit_price,
                            stop_loss_price, client_order_id=None):
        return self.place_order(
            symbol=symbol, qty=qty, side=side, order_type="market",
            time_in_force="day", order_class="bracket",
            take_profit={"limit_price": str(round(take_profit_price, 2))},
            stop_loss={"stop_price": str(round(stop_loss_price, 2))},
            client_order_id=client_order_id,
        )

    def get_order(self, order_id):
        return self._get(f"{self.base_url}/v2/orders/{order_id}")

    def cancel_all_orders(self):
        return self._delete(f"{self.base_url}/v2/orders")

    def cancel_order(self, order_id):
        return self._delete(f"{self.base_url}/v2/orders/{order_id}")

    def close_all_positions(self):
        return self._delete(f"{self.base_url}/v2/positions")

    def close_position(self, symbol, qty=None):
        params = {}
        if qty:
            params["qty"] = str(qty)
        return self._delete(f"{self.base_url}/v2/positions/{symbol}", params)
