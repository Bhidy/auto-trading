#!/usr/bin/env python3
"""
Fetches 220-day historical bars from Alpaca API and saves to data/*.json.
Standalone fallback for when Claude Code scheduled tasks don't fire.
"""

import json
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path("/Users/home/Documents/Auto Trading")
CONFIG = BASE_DIR / "config" / "portfolios.json"
DATA_DIR = BASE_DIR / "data"

GROUPS = {
    "core_equity": ["SPY", "QQQ", "IWM", "DIA"],
    "aggressive_growth": ["NVDA", "TSLA", "META", "AMZN", "MSFT", "GOOGL", "AAPL"],
    "sector_momentum": ["XLK", "XLE", "XLF", "XLV", "XLY", "XLI"],
    "defensive": ["SHY", "BIL", "TLT", "GLD"],
}
CRYPTO = ["BTC/USD", "ETH/USD"]


def fetch_stock_bars(symbols, api_key, api_secret, days=220):
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    params = {
        "symbols": ",".join(symbols),
        "timeframe": "1Day",
        "start": start,
        "adjustment": "split",
        "limit": 10000,
        "sort": "asc",
    }
    r = requests.get("https://data.alpaca.markets/v2/stocks/bars", headers=headers, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_crypto_bars(symbols, api_key, api_secret, days=220):
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    params = {
        "symbols": ",".join(symbols),
        "timeframe": "1Day",
        "start": start,
        "limit": 10000,
        "sort": "asc",
    }
    r = requests.get("https://data.alpaca.markets/v1beta3/crypto/us/bars", headers=headers, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    with open(CONFIG) as f:
        cfg = json.load(f)
    p1 = cfg["portfolio_1"]
    api_key, api_secret = p1["api_key"], p1["api_secret"]

    for group, symbols in GROUPS.items():
        print(f"Fetching {group}: {symbols}")
        data = fetch_stock_bars(symbols, api_key, api_secret)
        with open(DATA_DIR / f"{group}.json", "w") as f:
            json.dump(data, f)
        print(f"  Saved {group}.json")

    print(f"Fetching crypto: {CRYPTO}")
    data = fetch_crypto_bars(CRYPTO, api_key, api_secret)
    with open(DATA_DIR / "crypto.json", "w") as f:
        json.dump(data, f)
    print("  Saved crypto.json")

    print("All bar data fetched successfully")


if __name__ == "__main__":
    main()
