#!/usr/bin/env python3
"""Alpaca REST API client for Portfolio 3."""

import json
import requests
from pathlib import Path

CONFIG_PATH = Path("/Users/home/Documents/Auto Trading/event-driven-bot/config/alpaca_config.json")


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
        r = requests.get(url, headers=self.headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, url, data):
        r = requests.post(url, headers=self.headers, json=data, timeout=30)
        r.raise_for_status()
        return r.json()

    def _delete(self, url, params=None):
        r = requests.delete(url, headers=self.headers, params=params, timeout=30)
        if r.status_code == 204:
            return {}
        r.raise_for_status()
        return r.json()

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
                    take_profit=None, stop_loss=None):
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
        return self._post(f"{self.base_url}/v2/orders", data)

    def place_bracket_order(self, symbol, qty, side, take_profit_price, stop_loss_price):
        return self.place_order(
            symbol=symbol, qty=qty, side=side, order_type="market",
            time_in_force="day", order_class="bracket",
            take_profit={"limit_price": str(round(take_profit_price, 2))},
            stop_loss={"stop_price": str(round(stop_loss_price, 2))},
        )

    def cancel_all_orders(self):
        return self._delete(f"{self.base_url}/v2/orders")

    def close_all_positions(self):
        return self._delete(f"{self.base_url}/v2/positions")

    def close_position(self, symbol, qty=None):
        params = {}
        if qty:
            params["qty"] = str(qty)
        return self._delete(f"{self.base_url}/v2/positions/{symbol}", params)
