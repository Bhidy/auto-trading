#!/usr/bin/env python3
"""Research top politicians for copy trading."""

import json
import sys
sys.path.insert(0, "/Users/home/Documents/Auto Trading/political-copy-bot/scripts")
from mcp_client import call_mcp_tool


def research():
    print("=" * 60)
    print("POLITICIAN COPY TRADING RESEARCH")
    print("=" * 60)

    # 1. Get buy momentum assets (30, 90, 365 days)
    for days in [30, 90, 365]:
        print(f"\n--- Buy Momentum Assets ({days}d) ---")
        try:
            result = call_mcp_tool("get_buy_momentum_assets", {"limit": 15, "days": days})
            for a in result.get("assets", []):
                print(f"  #{a['rank']} {a['issuer']} ({a['ticker']}) buys={a['buys']} sells={a['sells']} ratio={a['buySellRatio']}")
        except Exception as e:
            print(f"  Error: {e}")

    # 2. Check specific active politicians
    politicians = [
        "Michael McCaul",
        "Tommy Tuberville",
        "Marjorie Taylor Greene",
        "Nancy Pelosi",
        "Dan Crenshaw",
        "Josh Gottheimer",
        "Mark Green",
        "John Curtis",
    ]

    print("\n" + "=" * 60)
    print("POLITICIAN STATS (365 days)")
    print("=" * 60)

    stats_list = []
    for pol in politicians:
        print(f"\n--- {pol} ---")
        try:
            result = call_mcp_tool("get_politician_stats", {"politician": pol, "days": 365})
            total = result.get("totalTrades", 0)
            buys = result.get("buys", 0)
            sells = result.get("sells", 0)
            ratio = result.get("buySellRatio", 0)
            print(f"  Total trades: {total}, Buys: {buys}, Sells: {sells}, Ratio: {ratio}")
            top_assets = result.get("mostTradedAssets", [])[:5]
            for a in top_assets:
                print(f"    -> {a['issuer']} ({a['ticker']}): {a['transactionCount']} trades")
            stats_list.append({"politician": pol, "total": total, "buys": buys, "sells": sells, "ratio": ratio, "top_assets": top_assets})
        except Exception as e:
            print(f"  Error: {e}")

    # 3. Get recent BUY trades from top politicians
    print("\n" + "=" * 60)
    print("RECENT BUY TRADES (30 days)")
    print("=" * 60)

    for pol in politicians[:4]:
        print(f"\n--- {pol} recent BUYs ---")
        try:
            result = call_mcp_tool("get_politician_trades", {
                "politician": pol, "type": ["BUY"], "days": 30
            })
            for t in result.get("trades", [])[:8]:
                print(f"  {t['issuer']['name']} ({t['issuer']['ticker']}) - {t['transaction']['type']} {t['transaction']['size']}")
        except Exception as e:
            print(f"  Error: {e}")

    # 4. Party momentum
    print("\n" + "=" * 60)
    print("PARTY BUY MOMENTUM (90 days)")
    print("=" * 60)
    try:
        result = call_mcp_tool("get_party_buy_momentum", {"limit": 10, "days": 90})
        print("\nConsensus (both parties buying):")
        for a in result.get("consensus", []):
            print(f"  #{a['rank']} {a['issuer']} ({a['ticker']}) Dem net={a['democrats']['netBuys']} Rep net={a['republicans']['netBuys']}")
        print("\nRepublican favorites:")
        for a in result.get("republicanFavorites", []):
            print(f"  #{a['rank']} {a['issuer']} ({a['ticker']}) net buys={a['republicans']['netBuys']}")
        print("\nDemocrat favorites:")
        for a in result.get("democratFavorites", []):
            print(f"  #{a['rank']} {a['issuer']} ({a['ticker']}) net buys={a['democrats']['netBuys']}")
    except Exception as e:
        print(f"  Error: {e}")

    # Save raw data
    with open("/Users/home/Documents/Auto Trading/political-copy-bot/data/research_results.json", "w") as f:
        json.dump({"stats": stats_list}, f, indent=2)
    print("\n\nResearch saved to data/research_results.json")


if __name__ == "__main__":
    research()
