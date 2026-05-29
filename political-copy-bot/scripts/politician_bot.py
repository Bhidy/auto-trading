#!/usr/bin/env python3
"""
Politician Copy Trading Bot — Production Autonomous Script
Copies trades from top-performing politicians via Capitol Trades data.
Executes via Alpaca paper trading API.
"""

import json
import sys
import time
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))
sys.path.insert(0, str(REPO_ROOT))
from mcp_client import call_mcp_tool
from shared.alpaca_http import confirm_fill, make_client_order_id, resilient_request

(BASE_DIR / "logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "logs" / f"bot_{datetime.now().strftime('%Y-%m-%d')}.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("politician_bot")


class AlpacaClient:
    def __init__(self, config_path: Path):
        with open(config_path) as f:
            cfg = json.load(f)
        self.api_key = cfg["api_key"]
        self.api_secret = cfg["api_secret"]
        self.base_url = cfg["base_url"]
        self.data_url = cfg["data_url"]
        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }

    def get(self, endpoint: str, params: dict = None, use_data_url: bool = False) -> dict:
        url = f"{self.data_url if use_data_url else self.base_url}{endpoint}"
        return resilient_request("GET", url, self.headers, params=params, logger=log)

    def post(self, endpoint: str, data: dict) -> dict:
        url = f"{self.base_url}{endpoint}"
        return resilient_request("POST", url, self.headers, json_body=data, logger=log)

    def delete(self, endpoint: str) -> dict:
        url = f"{self.base_url}{endpoint}"
        return resilient_request("DELETE", url, self.headers, logger=log)

    def get_account(self) -> dict:
        return self.get("/v2/account")

    def get_positions(self) -> list:
        return self.get("/v2/positions")

    def get_position(self, symbol: str) -> dict | None:
        try:
            return self.get(f"/v2/positions/{symbol}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def get_orders(self, status: str = "open") -> list:
        return self.get("/v2/orders", {"status": status})

    def get_latest_quote(self, symbol: str) -> dict:
        return self.get(f"/v2/stocks/{symbol}/quotes/latest", use_data_url=True)

    def get_latest_trade(self, symbol: str) -> dict:
        return self.get(f"/v2/stocks/{symbol}/trades/latest", use_data_url=True)

    def place_order(self, symbol: str, qty: int, side: str, order_type: str = "limit",
                    limit_price: float = None, time_in_force: str = "day",
                    client_order_id: str = None) -> dict:
        data = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        if limit_price and order_type == "limit":
            data["limit_price"] = str(round(limit_price, 2))
        if client_order_id:
            data["client_order_id"] = client_order_id
        return self.post("/v2/orders", data)

    def get_order(self, order_id: str) -> dict:
        return self.get(f"/v2/orders/{order_id}")

    def get_clock(self) -> dict:
        return self.get("/v2/clock")

    def is_market_open(self) -> bool:
        return self.get_clock().get("is_open", False)


class RiskManager:
    def __init__(self, config_path: Path, trade_log_path: Path):
        with open(config_path) as f:
            self.limits = json.load(f)
        self.trade_log_path = trade_log_path
        self.trade_log = self._load_trade_log()

    def _load_trade_log(self) -> list:
        if self.trade_log_path.exists():
            with open(self.trade_log_path) as f:
                return json.load(f)
        return []

    def _save_trade_log(self):
        with open(self.trade_log_path, "w") as f:
            json.dump(self.trade_log, f, indent=2, default=str)

    def check_daily_trade_count(self) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        today_trades = [t for t in self.trade_log if t.get("date", "").startswith(today)]
        if len(today_trades) >= self.limits["max_daily_trades"]:
            log.warning(f"Daily trade limit reached: {len(today_trades)}/{self.limits['max_daily_trades']}")
            return False
        return True

    def check_position_size(self, trade_value: float, equity: float) -> bool:
        max_pct = self.limits["max_single_position_pct"]
        if trade_value / equity * 100 > max_pct:
            log.warning(f"Position size {trade_value/equity*100:.1f}% exceeds max {max_pct}%")
            return False
        return True

    def check_portfolio_exposure(self, positions: list, equity: float) -> bool:
        total_value = sum(abs(float(p.get("market_value", 0))) for p in positions)
        exposure_pct = total_value / equity * 100
        if exposure_pct >= self.limits["max_portfolio_exposure_pct"]:
            log.warning(f"Portfolio exposure {exposure_pct:.1f}% at/above max {self.limits['max_portfolio_exposure_pct']}%")
            return False
        return True

    def check_daily_loss(self, account: dict) -> bool:
        equity = float(account.get("equity", 0))
        last_equity = float(account.get("last_equity", 0))
        if last_equity > 0:
            daily_change_pct = (equity - last_equity) / last_equity * 100
            if daily_change_pct <= -self.limits["max_daily_loss_pct"]:
                log.warning(f"Daily loss {daily_change_pct:.2f}% exceeds limit {self.limits['max_daily_loss_pct']}%")
                return False
        return True

    def check_kill_switch(self, account: dict, initial_capital: float = 100000) -> bool:
        equity = float(account.get("equity", 0))
        drawdown_pct = (initial_capital - equity) / initial_capital * 100
        if drawdown_pct >= self.limits["kill_switch_drawdown_pct"]:
            log.critical(f"KILL SWITCH: Drawdown {drawdown_pct:.2f}% >= {self.limits['kill_switch_drawdown_pct']}%")
            return False
        return True

    def check_duplicate_trade(self, symbol: str) -> bool:
        cooldown_hours = self.limits["duplicate_trade_cooldown_hours"]
        cutoff = datetime.now() - timedelta(hours=cooldown_hours)
        recent = [
            t for t in self.trade_log
            if t.get("symbol") == symbol
            and datetime.fromisoformat(t.get("timestamp", "2000-01-01")) > cutoff
        ]
        if recent:
            log.info(f"Duplicate trade cooldown: {symbol} traded within last {cooldown_hours}h")
            return False
        return True

    def get_trade_size(self, reported_size: str, equity: float) -> float:
        scaling = self.limits["trade_size_scaling"]
        base = scaling.get(reported_size, self.limits["min_trade_value_usd"])
        scaled = min(base, equity * self.limits["max_single_position_pct"] / 100)
        return max(self.limits["min_trade_value_usd"], min(scaled, self.limits["max_trade_value_usd"]))

    def log_trade(self, trade_record: dict):
        trade_record["timestamp"] = datetime.now().isoformat()
        trade_record["date"] = datetime.now().strftime("%Y-%m-%d")
        self.trade_log.append(trade_record)
        self._save_trade_log()

    def validate_ticker(self, ticker: str) -> str | None:
        if not ticker or ticker == "N/A":
            return None
        clean = ticker.split(":")[0].replace("/", ".")
        if len(clean) > 5 or not clean.isalpha():
            if not all(c.isalpha() or c == "." for c in clean):
                return None
        return clean


class PoliticianBot:
    def __init__(self):
        self.alpaca = AlpacaClient(BASE_DIR / "config" / "alpaca_config.json")
        self.risk = RiskManager(
            BASE_DIR / "config" / "risk_limits.json",
            BASE_DIR / "data" / "trade_log.json",
        )
        with open(BASE_DIR / "config" / "watchlist.json") as f:
            self.watchlist_cfg = json.load(f)
        self.processed_trades_path = BASE_DIR / "data" / "processed_trades.json"
        self.portfolio_state_path = BASE_DIR / "data" / "portfolio_state.json"
        self.processed_trades = self._load_processed()

    def _load_processed(self) -> set:
        if self.processed_trades_path.exists():
            with open(self.processed_trades_path) as f:
                return set(json.load(f))
        return set()

    def _save_processed(self):
        with open(self.processed_trades_path, "w") as f:
            json.dump(list(self.processed_trades), f, indent=2)

    def _trade_fingerprint(self, trade: dict) -> str:
        pol = trade.get("politician", {}).get("name", "")
        issuer = trade.get("issuer", {}).get("ticker", "")
        tx_type = trade.get("transaction", {}).get("type", "")
        size = trade.get("transaction", {}).get("size", "")
        date = trade.get("dates", {}).get("trade", "")
        return f"{pol}|{issuer}|{tx_type}|{size}|{date}"

    def _is_copyable_trade(self, trade: dict) -> bool:
        cfg = self.watchlist_cfg["copy_filters"]
        tx_type = (trade.get("transaction", {}).get("type", "") or "").upper()
        if tx_type not in [t.upper() for t in cfg["transaction_types"]]:
            return False
        issuer = trade.get("issuer", {}).get("name", "")
        ticker = trade.get("issuer", {}).get("ticker", "")
        if cfg.get("skip_private_investments") and ticker == "N/A" and not issuer.startswith("SPDR"):
            if any(kw in issuer.upper() for kw in ["LLC", "LP", "LTD", "TRUST", "FUND", "CITY OF", "COUNTY", "STATE OF", "AUTHORITY", "DISTRICT"]):
                return False
        if cfg.get("skip_municipal_bonds"):
            if any(kw in issuer.upper() for kw in ["CITY OF", "COUNTY", "STATE OF", "AUTHORITY", "DISTRICT"]):
                return False
        if cfg.get("skip_treasury_bills") and "TREASURY" in issuer.upper():
            return False
        return True

    def _is_sell_signal(self, trade: dict) -> bool:
        tx_type = (trade.get("transaction", {}).get("type", "") or "").upper()
        return tx_type == "SELL"

    def scan_politician_trades(self) -> list:
        primary = self.watchlist_cfg["primary_politician"]
        days = self.watchlist_cfg["check_intervals"]["primary_scan_days"]

        log.info(f"Scanning {primary} trades (last {days} days)...")
        all_new_trades = []

        try:
            buy_trades = call_mcp_tool("get_politician_trades", {
                "politician": primary, "type": ["BUY"], "days": days,
            })
            for t in buy_trades.get("trades", []):
                fp = self._trade_fingerprint(t)
                if fp not in self.processed_trades and self._is_copyable_trade(t):
                    t["_source"] = "primary"
                    t["_action"] = "BUY"
                    all_new_trades.append(t)
        except Exception as e:
            log.error(f"Error scanning {primary}: {e}")

        if self.watchlist_cfg.get("sell_logic", {}).get("copy_politician_sells"):
            try:
                sell_trades = call_mcp_tool("get_politician_trades", {
                    "politician": primary, "type": ["SELL"], "days": days,
                })
                for t in sell_trades.get("trades", []):
                    fp = self._trade_fingerprint(t)
                    if fp not in self.processed_trades:
                        ticker = self.risk.validate_ticker(t.get("issuer", {}).get("ticker", ""))
                        if ticker:
                            pos = self.alpaca.get_position(ticker)
                            if pos:
                                t["_source"] = "primary"
                                t["_action"] = "SELL"
                                all_new_trades.append(t)
            except Exception as e:
                log.error(f"Error scanning sells for {primary}: {e}")

        for backup in self.watchlist_cfg.get("backup_politicians", []):
            try:
                backup_trades = call_mcp_tool("get_politician_trades", {
                    "politician": backup, "type": ["BUY"], "days": days,
                })
                for t in backup_trades.get("trades", []):
                    fp = self._trade_fingerprint(t)
                    if fp not in self.processed_trades and self._is_copyable_trade(t):
                        t["_source"] = "backup"
                        t["_action"] = "BUY"
                        all_new_trades.append(t)
            except Exception as e:
                log.error(f"Error scanning {backup}: {e}")

        log.info(f"Found {len(all_new_trades)} new copyable trades")
        return all_new_trades

    def execute_trade(self, trade: dict) -> dict | None:
        ticker = self.risk.validate_ticker(trade.get("issuer", {}).get("ticker", ""))
        if not ticker:
            log.info(f"Skipping non-tradeable: {trade.get('issuer', {}).get('name', 'Unknown')}")
            return None

        action = trade.get("_action", "BUY")
        account = self.alpaca.get_account()
        equity = float(account["equity"])
        cash = float(account["cash"])

        if not self.risk.check_kill_switch(account):
            log.critical("Kill switch active — halting all trading")
            return None

        if not self.risk.check_daily_loss(account):
            log.warning("Daily loss limit hit — skipping")
            return None

        if not self.risk.check_daily_trade_count():
            return None

        if action == "BUY":
            return self._execute_buy(trade, ticker, equity, cash, account)
        elif action == "SELL":
            return self._execute_sell(trade, ticker)
        return None

    def _execute_buy(self, trade: dict, ticker: str, equity: float, cash: float, account: dict) -> dict | None:
        if not self.risk.check_duplicate_trade(ticker):
            return None

        positions = self.alpaca.get_positions()
        if not self.risk.check_portfolio_exposure(positions, equity):
            return None

        existing = self.alpaca.get_position(ticker)
        if existing:
            existing_pct = abs(float(existing["market_value"])) / equity * 100
            if existing_pct >= self.risk.limits["max_single_position_pct"] * 0.8:
                log.info(f"Already hold {existing_pct:.1f}% of {ticker}, skipping add")
                return None

        reported_size = trade.get("transaction", {}).get("size", "1K–15K")
        trade_value = self.risk.get_trade_size(reported_size, equity)

        if not self.risk.check_position_size(trade_value, equity):
            return None

        if trade_value > cash * 0.9:
            log.warning(f"Insufficient cash for {ticker}: need ${trade_value:.0f}, have ${cash:.0f}")
            trade_value = min(trade_value, cash * 0.8)
            if trade_value < self.risk.limits["min_trade_value_usd"]:
                return None

        try:
            quote = self.alpaca.get_latest_quote(ticker)
            ask_price = float(quote.get("quote", {}).get("ap", 0))
            bid_price = float(quote.get("quote", {}).get("bp", 0))
            if ask_price <= 0:
                trade_data = self.alpaca.get_latest_trade(ticker)
                ask_price = float(trade_data.get("trade", {}).get("p", 0))
                bid_price = ask_price
            if ask_price <= 0:
                log.error(f"Cannot get price for {ticker}")
                return None

            mid_price = (ask_price + bid_price) / 2 if bid_price > 0 else ask_price
            limit_price = round(mid_price * (1 + self.risk.limits["limit_offset_pct"] / 100), 2)
            qty = max(1, int(trade_value / limit_price))

            if qty * limit_price < self.risk.limits["min_trade_value_usd"]:
                log.info(f"Trade value too small for {ticker}: ${qty * limit_price:.0f}")
                return None

            log.info(f"BUYING {qty} x {ticker} @ limit ${limit_price:.2f} (${qty*limit_price:.0f})")

            coid = make_client_order_id("p2", ticker, "buy")
            order = self.alpaca.place_order(
                symbol=ticker, qty=qty, side="buy",
                order_type="limit", limit_price=limit_price,
                client_order_id=coid,
            )

            # Confirm the fill so the trade log records the real entry price.
            status, filled_qty, filled_price = confirm_fill(self.alpaca, order.get("id"))
            entry_price = filled_price if filled_price else limit_price

            trade_record = {
                "symbol": ticker,
                "side": "buy",
                "qty": qty,
                "limit_price": limit_price,
                "entry_price": round(entry_price, 4),
                "filled_qty": filled_qty,
                "estimated_value": round(qty * limit_price, 2),
                "order_id": order.get("id"),
                "order_status": status if status != "unknown" else order.get("status"),
                "politician": trade.get("politician", {}).get("name", ""),
                "politician_trade_size": reported_size,
                "source": trade.get("_source", ""),
                "reason": f"Copying {trade.get('politician', {}).get('name', '')} BUY of {trade.get('issuer', {}).get('name', '')}",
            }
            self.risk.log_trade(trade_record)
            return trade_record

        except requests.HTTPError as e:
            resp = getattr(e, "response", None)
            # Duplicate client_order_id (422) -> already placed today; idempotent skip.
            if resp is not None and resp.status_code == 422 and "client_order_id" in resp.text:
                log.info(f"{ticker}: already placed today (idempotent skip)")
                return None
            log.error(f"Order failed for {ticker}: {e}")
            if resp is not None:
                log.error(f"Response: {resp.text}")
            return None
        except Exception as e:
            log.error(f"Unexpected error for {ticker}: {e}")
            return None

    def _execute_sell(self, trade: dict, ticker: str) -> dict | None:
        pos = self.alpaca.get_position(ticker)
        if not pos:
            log.info(f"No position in {ticker} to sell")
            return None

        qty = int(float(pos.get("qty", 0)))
        if qty <= 0:
            return None

        sell_qty = max(1, qty // 2)

        try:
            quote = self.alpaca.get_latest_quote(ticker)
            bid_price = float(quote.get("quote", {}).get("bp", 0))
            if bid_price <= 0:
                trade_data = self.alpaca.get_latest_trade(ticker)
                bid_price = float(trade_data.get("trade", {}).get("p", 0))
            limit_price = round(bid_price * (1 - self.risk.limits["limit_offset_pct"] / 100), 2)

            log.info(f"SELLING {sell_qty} x {ticker} @ limit ${limit_price:.2f}")

            order = self.alpaca.place_order(
                symbol=ticker, qty=sell_qty, side="sell",
                order_type="limit", limit_price=limit_price,
            )

            trade_record = {
                "symbol": ticker,
                "side": "sell",
                "qty": sell_qty,
                "limit_price": limit_price,
                "order_id": order.get("id"),
                "order_status": order.get("status"),
                "politician": trade.get("politician", {}).get("name", ""),
                "source": trade.get("_source", ""),
                "reason": f"Copying {trade.get('politician', {}).get('name', '')} SELL of {trade.get('issuer', {}).get('name', '')}",
            }
            self.risk.log_trade(trade_record)
            return trade_record

        except Exception as e:
            log.error(f"Sell order failed for {ticker}: {e}")
            return None

    def _position_age_days(self, symbol: str):
        """Age (in days) of the oldest open buy for `symbol`, derived from the
        trade log. Returns None if no buy record exists (predates logging)."""
        buys = [t for t in self.risk.trade_log
                if t.get("symbol") == symbol and t.get("side") == "buy" and t.get("timestamp")]
        if not buys:
            return None
        earliest = None
        for t in buys:
            try:
                ts = datetime.fromisoformat(t["timestamp"])
            except (ValueError, TypeError):
                continue
            if earliest is None or ts < earliest:
                earliest = ts
        if earliest is None:
            return None
        return (datetime.now() - earliest).days

    def check_stops(self):
        sell_cfg = self.watchlist_cfg.get("sell_logic", {})
        trailing_stop_pct = sell_cfg.get("trailing_stop_pct", 8.0)
        take_profit_pct = sell_cfg.get("take_profit_pct", 25.0)
        max_hold_days = sell_cfg.get("max_hold_days", 180)

        positions = self.alpaca.get_positions()
        for pos in positions:
            symbol = pos.get("symbol", "")
            unrealized_plpc = float(pos.get("unrealized_plpc", 0)) * 100
            qty = int(float(pos.get("qty", 0)))
            age_days = self._position_age_days(symbol)

            if unrealized_plpc <= -trailing_stop_pct:
                log.warning(f"STOP LOSS triggered for {symbol}: {unrealized_plpc:.1f}% loss")
                try:
                    self.alpaca.place_order(symbol=symbol, qty=qty, side="sell",
                                            order_type="market", time_in_force="day")
                    self.risk.log_trade({
                        "symbol": symbol, "side": "sell", "qty": qty,
                        "reason": f"Stop loss at {unrealized_plpc:.1f}%",
                    })
                except Exception as e:
                    log.error(f"Stop loss order failed for {symbol}: {e}")

            elif age_days is not None and age_days >= max_hold_days:
                log.warning(f"MAX HOLD reached for {symbol}: held {age_days}d "
                            f">= {max_hold_days}d ({unrealized_plpc:+.1f}%) — exiting")
                try:
                    self.alpaca.place_order(symbol=symbol, qty=qty, side="sell",
                                            order_type="market", time_in_force="day")
                    self.risk.log_trade({
                        "symbol": symbol, "side": "sell", "qty": qty,
                        "reason": f"Max hold {age_days}d at {unrealized_plpc:+.1f}%",
                    })
                except Exception as e:
                    log.error(f"Max-hold exit failed for {symbol}: {e}")

            elif unrealized_plpc >= take_profit_pct:
                sell_qty = max(1, qty // 2)
                log.info(f"TAKE PROFIT for {symbol}: {unrealized_plpc:.1f}% gain, selling {sell_qty}")
                try:
                    quote = self.alpaca.get_latest_quote(symbol)
                    bid = float(quote.get("quote", {}).get("bp", 0))
                    limit_price = round(bid * 0.999, 2) if bid > 0 else None
                    self.alpaca.place_order(
                        symbol=symbol, qty=sell_qty, side="sell",
                        order_type="limit" if limit_price else "market",
                        limit_price=limit_price,
                    )
                    self.risk.log_trade({
                        "symbol": symbol, "side": "sell", "qty": sell_qty,
                        "reason": f"Take profit at {unrealized_plpc:.1f}%",
                    })
                except Exception as e:
                    log.error(f"Take profit order failed for {symbol}: {e}")

    def save_portfolio_state(self):
        account = self.alpaca.get_account()
        positions = self.alpaca.get_positions()
        orders = self.alpaca.get_orders("open")

        state = {
            "timestamp": datetime.now().isoformat(),
            "account": {
                "equity": account.get("equity"),
                "cash": account.get("cash"),
                "buying_power": account.get("buying_power"),
                "portfolio_value": account.get("portfolio_value"),
                "daily_pnl_pct": round(
                    (float(account["equity"]) - float(account["last_equity"]))
                    / float(account["last_equity"]) * 100, 2
                ) if float(account.get("last_equity", 0)) > 0 else 0,
            },
            "positions": [
                {
                    "symbol": p["symbol"],
                    "qty": p["qty"],
                    "avg_entry": p["avg_entry_price"],
                    "market_value": p["market_value"],
                    "unrealized_pl": p["unrealized_pl"],
                    "unrealized_plpc": p["unrealized_plpc"],
                }
                for p in positions
            ],
            "open_orders": len(orders),
            "total_positions": len(positions),
        }

        with open(self.portfolio_state_path, "w") as f:
            json.dump(state, f, indent=2)
        log.info(f"Portfolio: equity=${account['equity']}, cash=${account['cash']}, positions={len(positions)}")

    def write_journal(self, trades_executed: list):
        journal_dir = BASE_DIR / "journal"
        journal_dir.mkdir(exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        journal_path = journal_dir / f"{today}.json"

        account = self.alpaca.get_account()
        entry = {
            "date": today,
            "timestamp": datetime.now().isoformat(),
            "account_snapshot": {
                "equity": account.get("equity"),
                "cash": account.get("cash"),
                "portfolio_value": account.get("portfolio_value"),
            },
            "trades_executed": trades_executed,
            "trades_count": len(trades_executed),
        }

        if journal_path.exists():
            with open(journal_path) as f:
                existing = json.load(f)
            if isinstance(existing, list):
                existing.append(entry)
            else:
                existing = [existing, entry]
            with open(journal_path, "w") as f:
                json.dump(existing, f, indent=2)
        else:
            with open(journal_path, "w") as f:
                json.dump([entry], f, indent=2)

    def run_scan_and_trade(self):
        log.info("=" * 50)
        log.info("POLITICIAN COPY BOT — SCAN & TRADE CYCLE")
        log.info("=" * 50)

        account = self.alpaca.get_account()
        if not self.risk.check_kill_switch(account):
            log.critical("Kill switch active. Halting.")
            return

        clock = self.alpaca.get_clock()
        is_open = clock.get("is_open", False)
        log.info(f"Market open: {is_open}")

        if not is_open:
            log.info("Market closed — scanning and queuing for next open")
            new_trades = self.scan_politician_trades()
            for trade in new_trades:
                fp = self._trade_fingerprint(trade)
                self.processed_trades.add(fp)
            self._save_processed()
            log.info(f"Queued {len(new_trades)} trades for next market open")
            return

        new_trades = self.scan_politician_trades()
        executed = []

        for trade in new_trades:
            fp = self._trade_fingerprint(trade)
            result = self.execute_trade(trade)
            self.processed_trades.add(fp)
            if result:
                executed.append(result)
            time.sleep(1)

        self._save_processed()
        self.check_stops()
        self.save_portfolio_state()
        self.write_journal(executed)

        log.info(f"Cycle complete: {len(executed)} trades executed out of {len(new_trades)} signals")

    def run_monitor(self):
        log.info("MONITOR CYCLE — checking stops and portfolio health")
        if not self.alpaca.is_market_open():
            log.info("Market closed — skipping monitor")
            return
        account = self.alpaca.get_account()
        if not self.risk.check_kill_switch(account):
            log.critical("Kill switch active — liquidating if needed")
            return
        if not self.risk.check_daily_loss(account):
            log.warning("Daily loss limit — no new trades until tomorrow")
        self.check_stops()
        self.save_portfolio_state()

    def run_weekly_review(self):
        log.info("=" * 50)
        log.info("WEEKLY REVIEW")
        log.info("=" * 50)

        account = self.alpaca.get_account()
        positions = self.alpaca.get_positions()
        trade_log = self.risk.trade_log

        week_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        weekly_trades = [t for t in trade_log if t.get("date", "") >= week_start]

        buys = [t for t in weekly_trades if t.get("side") == "buy"]
        sells = [t for t in weekly_trades if t.get("side") == "sell"]

        review = {
            "week_ending": datetime.now().strftime("%Y-%m-%d"),
            "account": {
                "equity": account.get("equity"),
                "cash": account.get("cash"),
                "portfolio_value": account.get("portfolio_value"),
            },
            "weekly_activity": {
                "total_trades": len(weekly_trades),
                "buys": len(buys),
                "sells": len(sells),
                "buy_value": sum(t.get("estimated_value", 0) for t in buys),
            },
            "positions": [
                {
                    "symbol": p["symbol"],
                    "qty": p["qty"],
                    "unrealized_pl": p["unrealized_pl"],
                    "unrealized_plpc": p["unrealized_plpc"],
                }
                for p in positions
            ],
            "total_positions": len(positions),
        }

        week_num = datetime.now().strftime("%Y-W%W")
        review_path = BASE_DIR / "journal" / f"weekly-{week_num}.json"
        with open(review_path, "w") as f:
            json.dump(review, f, indent=2)

        log.info(f"Weekly review saved: {len(weekly_trades)} trades this week, {len(positions)} positions")

        try:
            stats = call_mcp_tool("get_politician_stats", {
                "politician": self.watchlist_cfg["primary_politician"], "days": 30,
            })
            log.info(f"Primary politician 30d: {stats.get('totalTrades', 0)} trades, ratio={stats.get('buySellRatio', 0)}")
        except Exception as e:
            log.error(f"Failed to refresh politician stats: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Politician Copy Trading Bot")
    parser.add_argument("mode", choices=["scan", "monitor", "weekly", "full"],
                        help="scan=scan+trade, monitor=check stops, weekly=weekly review, full=all")
    args = parser.parse_args()

    bot = PoliticianBot()

    if args.mode == "scan":
        bot.run_scan_and_trade()
    elif args.mode == "monitor":
        bot.run_monitor()
    elif args.mode == "weekly":
        bot.run_weekly_review()
    elif args.mode == "full":
        bot.run_scan_and_trade()
        bot.run_monitor()


if __name__ == "__main__":
    main()
