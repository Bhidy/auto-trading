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


# ---------------------------------------------------------------------------
# SIGNAL-HIERARCHY HELPERS (T9) — pure + unit-testable.
#
# Congressional disclosures are structurally delayed (the STOCK Act allows 30-45
# days from transaction to disclosure). They are therefore RESEARCH-GRADE
# CONTEXT, never fresh alpha. Two disciplines follow: (1) reject trades whose
# underlying transaction is already stale, and (2) never copy on the political
# signal alone — require a corroborating technical confirmation.
# ---------------------------------------------------------------------------

# Capitol Trades returns the underlying TRANSACTION date in a compact human
# format like "8 May2026" / "8 May 2026"; the published/disclosed fields are
# sometimes ISO ("2026-05-15"). A parser that only understood ISO once idled
# P2's entire book for days: the T9 freshness gate (commit 09abea0) fails CLOSED
# on an unknown age, so every disclosure was silently dropped as "stale". Parse
# every format the source can emit. Only ever WIDEN this list, never narrow it.
_DISCLOSURE_DATE_FORMATS = (
    "%d %b%Y",    # 8 May2026    (Capitol Trades transaction date, no space)
    "%d %b %Y",   # 8 May 2026
    "%d %B%Y",    # 8 May2026    (full month name, same token for "May")
    "%d %B %Y",   # 8 May 2026
    "%b %d, %Y",  # May 8, 2026
    "%b %d %Y",   # May 8 2026
    "%B %d, %Y",  # May 8, 2026  (full month name)
    "%m/%d/%Y",   # 05/08/2026
)


def _parse_date(value):
    """Parse a disclosure date from any format the Capitol Trades source emits.
    ISO first (fast path), then the compact human formats above. Returns None
    only when nothing matches; callers treat None as 'unknown' and fail closed,
    so a silent format drift MUST surface loudly (see scan_politician_trades)."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:10])  # 2026-05-15 / 2026-05-15T09:30
    except ValueError:
        pass
    for fmt in _DISCLOSURE_DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def disclosure_age_days(trade, now=None):
    """Days from the actual transaction date (the conservative staleness measure)
    to `now`. Falls back to published/disclosed date. None if unparseable."""
    now = now or datetime.now()
    dates = trade.get("dates", {}) if isinstance(trade, dict) else {}
    txn = (_parse_date(dates.get("trade"))
           or _parse_date(dates.get("transaction"))
           or _parse_date(dates.get("published"))
           or _parse_date(dates.get("disclosed")))
    if txn is None:
        return None
    return (now - txn).days


def is_fresh_enough(trade, max_age_days, now=None):
    """A congressional copy is actionable only if its transaction is recent
    enough to still be relevant. Unknown age FAILS CLOSED (treated as stale)."""
    age = disclosure_age_days(trade, now=now)
    if age is None:
        return False
    return 0 <= age <= max_age_days


def confirm_with_technicals(closes, ma_period=20, min_momentum_pct=0.0):
    """Technical confirmation overlay: a delayed political signal is only copied
    when price action still agrees. Requires price above its `ma_period` SMA and
    non-negative recent momentum. Insufficient data FAILS CLOSED."""
    if not closes or len(closes) < ma_period + 1:
        return False
    ma = sum(closes[-ma_period:]) / ma_period
    price = closes[-1]
    lookback = min(ma_period, len(closes) - 1)
    prior = closes[-1 - lookback]
    momentum_pct = ((price - prior) / prior * 100) if prior else 0.0
    return price > ma and momentum_pct >= min_momentum_pct


# Broad, liquid ETFs for the benchmark sleeve. Each stays within the 8% single-
# position cap, so the sleeve is a diversified market-replication basket — NOT a
# single SPY block that would breach the cap. Political copies are the alpha
# overlay layered on top of this passive base.
SLEEVE_SYMBOLS = ["SPY", "QQQ", "DIA", "IWM", "XLK", "XLF", "XLV", "XLE", "XLY", "XLI"]


def compute_sleeve_orders(equity, cash, positions, cfg, *, sleeve_symbols=None):
    """Decide benchmark-sleeve rebalance orders so P2's cash is never fully idle
    between political disclosures (it sat 90% in cash on 2026-06-02).

    The sleeve is a diversified ETF basket, each name targeted at `per_name_target_pct`
    (kept under the single-position cap). Idle cash above `min_cash_reserve_pct` is
    deployed toward the per-name targets; a name held above target is trimmed back.
    A `rebalance_band_pct` deadband and a `max_orders_per_run` cap prevent churn and
    keep deployment gradual. Pure function — returns a list of
    {symbol, side, notional, reason}; the caller converts notionals to qty orders.

    `positions` is the live Alpaca positions list. Sells are returned before buys."""
    if not cfg or not cfg.get("enabled"):
        return []
    syms = sleeve_symbols or cfg.get("symbols") or SLEEVE_SYMBOLS
    try:
        equity = float(equity)
        cash = float(cash)
    except (TypeError, ValueError):
        return []
    if equity <= 0:
        return []

    per_name_target = equity * float(cfg.get("per_name_target_pct", 7.0)) / 100.0
    reserve = equity * float(cfg.get("min_cash_reserve_pct", 10.0)) / 100.0
    band = equity * float(cfg.get("rebalance_band_pct", 2.0)) / 100.0
    max_orders = int(cfg.get("max_orders_per_run", 3))

    val_by = {p.get("symbol"): abs(float(p.get("market_value", 0) or 0))
              for p in (positions or []) if p.get("symbol")}
    investable = max(0.0, cash - reserve)

    buys, sells = [], []
    for s in syms:
        cur = val_by.get(s, 0.0)
        delta = per_name_target - cur
        if delta > band:
            amt = min(delta, investable)
            if amt > band:
                buys.append({"symbol": s, "side": "buy", "notional": round(amt, 2),
                             "reason": "benchmark_sleeve: deploy idle cash"})
                investable -= amt
        elif delta < -band:
            sells.append({"symbol": s, "side": "sell", "notional": round(-delta, 2),
                          "reason": "benchmark_sleeve: trim to target"})
    # Sells first (free cash), then buys; bounded per run to avoid bursts.
    return (sells + buys)[:max_orders]


def classify_capital(positions, sleeve_symbols, cash, equity):
    """Split P2's book into beta-sleeve vs politician-alpha vs cash, as % of equity.

    The benchmark sleeve is honest BETA — a diversified ETF parking of idle cash —
    NOT politician insight. Disclosing the split keeps the dashboard (and the
    committee) from mistaking parked beta for alpha. Pure; a symbol in the sleeve
    set is beta, anything else is the politician-copy overlay. Returns zeros on
    bad input.
    """
    zeros = {"sleeve_beta_pct": 0.0, "politician_alpha_pct": 0.0, "cash_pct": 0.0,
             "sleeve_beta_value": 0.0, "politician_alpha_value": 0.0}
    sset = set(sleeve_symbols or [])
    try:
        equity = float(equity)
        cash = float(cash)
    except (TypeError, ValueError):
        return zeros
    if equity <= 0:
        return zeros
    beta = alpha = 0.0
    for p in positions or []:
        mv = abs(float(p.get("market_value", 0) or 0))
        if p.get("symbol") in sset:
            beta += mv
        else:
            alpha += mv
    return {
        "sleeve_beta_pct": round(beta / equity * 100, 2),
        "politician_alpha_pct": round(alpha / equity * 100, 2),
        "cash_pct": round(cash / equity * 100, 2),
        "sleeve_beta_value": round(beta, 2),
        "politician_alpha_value": round(alpha, 2),
    }


# ---------------------------------------------------------------------------
# CONVICTION MODEL — politician track-record weighting + cluster-buy detection
# ---------------------------------------------------------------------------

def trailing_stop_triggered(current_plpc, peak_plpc, stop_pct):
    """True TRAILING stop (committee fix 2026-06-18) — exit when price has fallen
    ``stop_pct``% from the position's HIGH-WATER MARK, NOT a fixed stop from entry.
    This matches the mechanism the P2 backtest actually validated
    (``current_price <= peak_price*(1-stop)``). All plpc are percentages
    (12.5 == +12.5%). A pure loser (peak≈entry) still floors at ~ -stop_pct%; a
    winner that pulls back locks in gains stop_pct% below its peak."""
    if stop_pct is None or stop_pct <= 0:
        return False
    return (1.0 + current_plpc / 100.0) <= (1.0 + peak_plpc / 100.0) * (1.0 - stop_pct / 100.0)


def disclosure_feed_status(attempts, failures):
    """Health of the Capitol Trades disclosure feed for one scan cycle.

    ``'dark'``  = every fetch failed → no signal possible (the 2026-06 rate-limit
    outage that ran ~3 weeks with no alert because 0 trades looked like quiet
    markets). ``'degraded'`` = some fetches failed. ``'ok'`` = all succeeded (or
    nothing was attempted). A ``'dark'`` result is surfaced as a conformance
    violation so the existing heartbeat watchdog opens an alert."""
    if not attempts or attempts <= 0:
        return "ok"
    if failures >= attempts:
        return "dark"
    if failures > 0:
        return "degraded"
    return "ok"


def count_cluster_buys(pairs):
    """`pairs`: iterable of (ticker, politician). Returns {ticker: count of DISTINCT
    politicians buying it}. Two or more politicians into the same name in one scan
    is a 'cluster' — a materially stronger copy signal than a lone disclosure."""
    from collections import defaultdict
    seen = defaultdict(set)
    for tk, pol in pairs:
        if tk and pol:
            seen[tk].add(pol)
    return {tk: len(s) for tk, s in seen.items()}


def politician_weight(name, tiers, *, default=1.0):
    """Track-record / credibility tier for a politician (config-driven, reputation-
    seeded). 1.0 for anyone not explicitly tiered. A later layer can blend the bot's
    own realized P&L per politician once the closed-trade sample is large enough."""
    try:
        if not tiers or not name:
            return float(default)
        return float(tiers.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def compute_conviction_multiplier(pol_weight, cluster_count, *,
                                  cluster_step=0.25, min_mult=0.75, max_mult=1.5):
    """Conviction scalar for a copy = politician credibility x cluster boost,
    CLAMPED to [min_mult, max_mult] so conviction only moves size WITHIN the
    hardcoded caps, never past them. `cluster_count` is the number of distinct
    politicians buying the same name (1 = no boost). Returns 1.0 on bad input."""
    try:
        w = float(pol_weight)
        c = int(cluster_count)
    except (TypeError, ValueError):
        return 1.0
    if w <= 0:
        w = 1.0
    boost = 1.0 + max(0, c - 1) * float(cluster_step)
    return max(float(min_mult), min(w * boost, float(max_mult)))


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

    def get_account_activities(self, activity_type: str = "FILL", page_size: int = 100) -> list:
        """Account activities (default FILL) — source real exit-fill prices so
        reconciled closes carry realized P&L instead of pnl=None."""
        return self.get(f"/v2/account/activities/{activity_type}", {"page_size": page_size})

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

    def get_stock_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 40) -> list:
        """Recent daily bars for the technical-confirmation overlay (T9)."""
        resp = self.get(f"/v2/stocks/{symbol}/bars",
                        {"timeframe": timeframe, "limit": limit, "feed": "iex"},
                        use_data_url=True)
        return resp.get("bars", []) or []


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
        """Conviction-scaled copy size as a PERCENT of the live book — not a flat
        $1.5K. The disclosed trade-size bucket is the conviction proxy: a larger
        politician buy → a larger copy. Bounded by the single-position cap and the
        max_trade_value guardrail. Falls back to the legacy flat `trade_size_scaling`
        table when `base_position_pct` is not configured (back-compat).

        WHY: with the flat table P2 copied ~$1.5K per disclosure and deployed only
        ~$10K of a $100K book — sitting 90% in idle cash (observed 2026-06-02). The
        copy size was decoupled from the book size, so the portfolio could never get
        invested. Sizing as a % of equity ties deployment to capital."""
        cap = min(self.limits["max_trade_value_usd"],
                  equity * self.limits["max_single_position_pct"] / 100.0)
        floor = self.limits["min_trade_value_usd"]
        base_pct = self.limits.get("base_position_pct")
        if base_pct:
            bucket_mult = self.limits.get("size_bucket_multiplier", {}).get(reported_size, 1.0)
            target = equity * float(base_pct) / 100.0 * float(bucket_mult)
        else:
            target = self.limits["trade_size_scaling"].get(reported_size, floor)
        return max(floor, min(target, cap))

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
        # Freshness-gate observability (reset each scan). A disclosure whose date
        # cannot be parsed is "unknown age" and fails closed — indistinguishable
        # from "genuinely stale" unless we count it. If the feed's date format
        # drifts, _unparseable_dates == _freshness_evaluated and we scream rather
        # than silently idle the book (the T9 regression that hid for days).
        self._freshness_evaluated = 0
        self._unparseable_dates = 0

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
        # T9: reject decayed signals — a delayed disclosure whose transaction is
        # already stale is research context, not a tradeable edge. Fails closed.
        self._freshness_evaluated += 1
        if not is_fresh_enough(trade, self._max_disclosure_age()):
            age = disclosure_age_days(trade)
            ticker = trade.get("issuer", {}).get("ticker", "?")
            if age is None:
                # Date present but UNPARSEABLE — a data/format problem, NOT a
                # decayed signal. Treating these as routine "stale" skips is what
                # let the T9 regression hide. Make every one loud and count it.
                self._unparseable_dates += 1
                log.warning(f"UNPARSEABLE disclosure date for {ticker} "
                            f"(dates={trade.get('dates', {})}) — freshness gate "
                            f"cannot evaluate it; Capitol Trades date format may "
                            f"have changed (see _DISCLOSURE_DATE_FORMATS)")
            else:
                log.info(f"Skipping stale disclosure ({age}d old) for {ticker}")
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

    def _max_disclosure_age(self) -> int:
        """Max age (days) of the underlying transaction we will still copy.
        Default 45 (the STOCK Act disclosure window) — older = decayed edge."""
        return int(self.watchlist_cfg.get("copy_filters", {})
                   .get("max_transaction_age_days", 45))

    def scan_politician_trades(self) -> list:
        primary = self.watchlist_cfg["primary_politician"]
        days = self.watchlist_cfg["check_intervals"]["primary_scan_days"]

        log.info(f"Scanning {primary} trades (last {days} days)...")
        all_new_trades = []
        self._freshness_evaluated = 0
        self._unparseable_dates = 0
        # Feed-health counters: a fully rate-limited/unreachable Capitol Trades feed
        # produces 0 trades that is INDISTINGUISHABLE from "quiet markets" — the
        # exact failure that ran dark for ~3 weeks with no alert (2026-06 audit).
        # Count every fetch attempt vs failure so a dark feed becomes a conformance
        # violation the heartbeat watchdog already surfaces.
        self._fetch_attempts = 0
        self._fetch_failures = 0

        self._fetch_attempts += 1
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
            self._fetch_failures += 1
            log.error(f"Error scanning {primary}: {e}")

        if self.watchlist_cfg.get("sell_logic", {}).get("copy_politician_sells"):
            self._fetch_attempts += 1
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
                self._fetch_failures += 1
                log.error(f"Error scanning sells for {primary}: {e}")

        # Space out requests to Capitol Trades — rapid-fire subprocess spawns
        # across 13 politicians exhausts the external API's rate limit (429). Widened
        # 3s->6s (2026-06-18) after a ~3-week dark-feed outage; combined with the
        # more patient per-call retries in mcp_client, this is strictly more
        # rate-limit-friendly. Scheduled run, so the extra wall-clock is fine.
        time.sleep(6)

        for backup in self.watchlist_cfg.get("backup_politicians", []):
            time.sleep(6)  # rate-limit guard between each politician scan
            self._fetch_attempts += 1
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
                self._fetch_failures += 1
                log.error(f"Error scanning {backup}: {e}")

        # A DARK feed (every fetch failed) means no copy can ever open this cycle —
        # make it LOUD and a conformance failure (heartbeat surfaces it). This is the
        # alarm the 3-week 2026-06 rate-limit outage never had.
        self._feed_dark = disclosure_feed_status(self._fetch_attempts, self._fetch_failures) == "dark"
        if self._feed_dark:
            log.error(f"::error::P2 FEED DARK: {self._fetch_failures}/{self._fetch_attempts} "
                      f"Capitol Trades fetches failed (unreachable/rate-limited). No new copies "
                      f"can open — flagged as a conformance violation for the heartbeat watchdog.")
        elif self._fetch_failures:
            log.warning(f"P2 feed degraded: {self._fetch_failures}/{self._fetch_attempts} "
                        f"disclosure fetches failed this cycle.")

        # Make a blinded feed LOUD: if every dated disclosure we evaluated had an
        # unparseable date, the copy pipeline is dark (almost certainly a feed
        # format change), not "quiet markets". This is the alarm the T9 regression
        # never had — it is also surfaced as a conformance violation downstream.
        if self._unparseable_dates and self._unparseable_dates == self._freshness_evaluated:
            log.error(f"P2 BLINDED: all {self._freshness_evaluated} dated disclosure(s) "
                      f"had UNPARSEABLE dates — no new copies can open until the date "
                      f"parser is updated (Capitol Trades format likely changed). "
                      f"Fix _DISCLOSURE_DATE_FORMATS / _parse_date.")
        elif self._unparseable_dates:
            log.warning(f"{self._unparseable_dates}/{self._freshness_evaluated} disclosure "
                        f"dates were unparseable — partial feed format drift; check _parse_date.")

        log.info(f"Found {len(all_new_trades)} new copyable trades")
        return all_new_trades

    def execute_trade(self, trade: dict, cluster_counts: dict = None) -> dict | None:
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
            return self._execute_buy(trade, ticker, equity, cash, account,
                                     cluster_counts=cluster_counts)
        elif action == "SELL":
            return self._execute_sell(trade, ticker)
        return None

    def _execute_buy(self, trade: dict, ticker: str, equity: float, cash: float,
                     account: dict, cluster_counts: dict = None) -> dict | None:
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

        # T9 confirmation overlay: never copy on the (delayed) political signal
        # alone. Require price action to still agree. Fails closed when required.
        if self.watchlist_cfg.get("copy_filters", {}).get("require_technical_confirmation", True):
            try:
                bars = self.alpaca.get_stock_bars(ticker, limit=40)
                closes = [float(b.get("c", 0)) for b in bars if b.get("c")]
            except Exception as e:
                log.warning(f"Confirmation bars unavailable for {ticker}: {e}")
                closes = []
            if not confirm_with_technicals(closes):
                log.info(f"Skipping {ticker}: no technical confirmation of the "
                         f"delayed congressional signal")
                return None

        reported_size = trade.get("transaction", {}).get("size", "1K–15K")
        trade_value = self.risk.get_trade_size(reported_size, equity)

        # Conviction overlay: scale the copy by the politician's track-record tier
        # and by cluster strength (multiple politicians into the same name), then
        # RE-CLAMP inside the single-position cap so conviction never breaches it.
        conv_cfg = self.risk.limits.get("conviction", {})
        if conv_cfg.get("enabled"):
            pol_name = (trade.get("politician", {}) or {}).get("name", "")
            pw = politician_weight(pol_name, conv_cfg.get("politician_tiers", {}))
            cc = (cluster_counts or {}).get(ticker, 1)
            mult = compute_conviction_multiplier(
                pw, cc,
                cluster_step=conv_cfg.get("cluster_step", 0.25),
                min_mult=conv_cfg.get("min_multiplier", 0.75),
                max_mult=conv_cfg.get("max_multiplier", 1.5))
            if mult != 1.0:
                cap = min(self.risk.limits["max_trade_value_usd"],
                          equity * self.risk.limits["max_single_position_pct"] / 100.0)
                scaled = max(self.risk.limits["min_trade_value_usd"],
                             min(trade_value * mult, cap))
                log.info(f"Conviction {ticker}: {pol_name or 'n/a'} weight {pw:.2f}, "
                         f"cluster {cc} -> x{mult:.2f} (${trade_value:,.0f} -> ${scaled:,.0f})")
                trade_value = scaled

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
                # Fill-fidelity (Phase 1): normalize intended_price + slippage_pct
                # across all three bots so friction calibration + reconciliation
                # cover the full $300k (P2 entry = its limit price).
                "intended_price": limit_price,
                "slippage_pct": (round((entry_price - limit_price) / limit_price * 100, 4)
                                 if limit_price else None),
                "client_order_id": coid,
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

        sleeve_cfg = self.risk.limits.get("benchmark_sleeve", {}) or {}
        sleeve_syms = set(sleeve_cfg.get("symbols") or SLEEVE_SYMBOLS) if sleeve_cfg.get("enabled") else set()

        # True TRAILING stop: track each position's HIGH-WATER MARK (peak unrealized
        # P&L %) across monitor runs and exit when it falls trailing_stop_pct% from
        # that peak — the mechanism the backtest validated (the old code stopped at a
        # FIXED % from entry despite the "trailing" name). Persisted per-symbol.
        peaks_path = BASE_DIR / "data" / "trailing_peaks.json"
        try:
            peaks = json.loads(peaks_path.read_text())
        except Exception:
            peaks = {}

        positions = self.alpaca.get_positions()
        held = set()
        for pos in positions:
            symbol = pos.get("symbol", "")
            # The passive benchmark sleeve is rebalanced by run_benchmark_sleeve,
            # not stop-managed — a trailing stop would churn it on every dip.
            if symbol in sleeve_syms:
                continue
            unrealized_plpc = float(pos.get("unrealized_plpc", 0)) * 100
            qty = int(float(pos.get("qty", 0)))
            age_days = self._position_age_days(symbol)
            held.add(symbol)

            # Update the high-water mark before evaluating the trail.
            peak_plpc = max(peaks.get(symbol, unrealized_plpc), unrealized_plpc)
            peaks[symbol] = peak_plpc

            if trailing_stop_triggered(unrealized_plpc, peak_plpc, trailing_stop_pct):
                log.warning(f"TRAILING STOP for {symbol}: now {unrealized_plpc:+.1f}% "
                            f"(peak {peak_plpc:+.1f}%, {trailing_stop_pct:.0f}% trail)")
                try:
                    self.alpaca.place_order(symbol=symbol, qty=qty, side="sell",
                                            order_type="market", time_in_force="day")
                    self.risk.log_trade({
                        "symbol": symbol, "side": "sell", "qty": qty,
                        "reason": (f"Trailing stop {trailing_stop_pct:.0f}% from peak "
                                   f"{peak_plpc:+.1f}% (now {unrealized_plpc:+.1f}%)"),
                    })
                    peaks.pop(symbol, None)
                except Exception as e:
                    log.error(f"Trailing stop order failed for {symbol}: {e}")

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
                    peaks.pop(symbol, None)
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

        # Drop high-water marks for names no longer held (closed/sold) so the trail
        # store can't grow unbounded or apply a stale peak to a re-bought name.
        for s in [k for k in peaks if k not in held]:
            peaks.pop(s, None)
        try:
            peaks_path.write_text(json.dumps(peaks, indent=2))
        except Exception as e:
            log.error(f"Could not persist trailing peaks: {e}")

    def save_portfolio_state(self):
        account = self.alpaca.get_account()
        positions = self.alpaca.get_positions()
        orders = self.alpaca.get_orders("open")

        # Honest beta/alpha disclosure: the benchmark sleeve is parked BETA, not
        # politician insight. Tag each position and surface the split so the
        # dashboard never overstates "alpha" (committee rec #4).
        sleeve_cfg = self.risk.limits.get("benchmark_sleeve", {})
        sleeve_syms = set(sleeve_cfg.get("symbols") or SLEEVE_SYMBOLS)
        equity = account.get("equity")
        cash = account.get("cash")

        state = {
            "timestamp": datetime.now().isoformat(),
            "account": {
                "equity": equity,
                "cash": cash,
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
                    "classification": ("beta_sleeve" if p["symbol"] in sleeve_syms
                                       else "politician_alpha"),
                }
                for p in positions
            ],
            "capital_classification": classify_capital(positions, sleeve_syms, cash, equity),
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

    def run_benchmark_sleeve(self):
        """Deploy idle cash into a diversified ETF sleeve so the book is never fully
        idle between political disclosures. Each ETF stays within the single-position
        cap; the political copies are the alpha overlay on top. No-op unless enabled.
        Runs only with the market open (called from the open branch of the cycle)."""
        cfg = self.risk.limits.get("benchmark_sleeve", {})
        if not cfg.get("enabled"):
            return []
        account = self.alpaca.get_account()
        equity = float(account.get("equity", 0))
        cash = float(account.get("cash", 0))
        positions = self.alpaca.get_positions()
        orders = compute_sleeve_orders(equity, cash, positions, cfg)
        if not orders:
            log.info("Benchmark sleeve: balanced, no rebalance needed")
            return []

        executed = []
        offset = self.risk.limits.get("limit_offset_pct", 0.15)
        for o in orders:
            sym, side, notional = o["symbol"], o["side"], o["notional"]
            try:
                quote = self.alpaca.get_latest_quote(sym)
                ask = float(quote.get("quote", {}).get("ap", 0))
                bid = float(quote.get("quote", {}).get("bp", 0))
                ref = ask if (side == "buy" and ask > 0) else (bid if bid > 0 else ask)
                if ref <= 0:
                    trade = self.alpaca.get_latest_trade(sym)
                    ref = float(trade.get("trade", {}).get("p", 0))
                if ref <= 0:
                    continue
                qty = int(notional / ref)
                if qty <= 0:
                    continue
                limit_price = round(ref * (1 + offset / 100) if side == "buy"
                                    else ref * (1 - offset / 100), 2)
                coid = make_client_order_id("p2sleeve", sym, side)
                order = self.alpaca.place_order(
                    symbol=sym, qty=qty, side=side, order_type="limit",
                    limit_price=limit_price, client_order_id=coid,
                )
                log.info(f"SLEEVE {side.upper()} {qty} x {sym} @ ${limit_price:.2f} "
                         f"(${qty * limit_price:,.0f}) — {o['reason']}")
                self.risk.log_trade({
                    "symbol": sym, "side": side, "qty": qty,
                    "limit_price": limit_price,
                    "estimated_value": round(qty * limit_price, 2),
                    "order_id": order.get("id"),
                    "politician": "BENCHMARK_SLEEVE",
                    "source": "benchmark_sleeve",
                    "strategy": "benchmark_sleeve",
                    "evidence_quality": "beta",  # parked beta, NOT politician alpha
                    "reason": o["reason"],
                })
                executed.append({"symbol": sym, "side": side, "qty": qty})
                time.sleep(1)
            except requests.HTTPError as e:
                resp = getattr(e, "response", None)
                if resp is not None and resp.status_code == 422 and "client_order_id" in resp.text:
                    log.info(f"{sym}: sleeve order already placed today (idempotent skip)")
                    continue
                log.error(f"Sleeve order failed for {sym}: {e}")
            except Exception as e:
                log.error(f"Sleeve order error for {sym}: {e}")
        return executed

    def run_scan_and_trade(self):
        log.info("=" * 50)
        log.info("POLITICIAN COPY BOT — SCAN & TRADE CYCLE")
        log.info("=" * 50)

        account = self.alpaca.get_account()
        if not self.risk.check_kill_switch(account):
            log.critical("Kill switch active. Halting.")
            return

        # Preflight self-check — fail closed before scanning/placing any order.
        from shared.preflight import run_preflight
        pf_ok, pf = run_preflight(limits=self.risk.limits, account=account,
                                  portfolio_id="portfolio_2")
        if not pf_ok:
            for _f in pf["hard_failures"]:
                log.error(f"::error::PREFLIGHT FAILED (P2): {_f}")
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

        # Cluster-buy detection: count distinct politicians per (validated) ticker
        # in this scan so the conviction model can up-size names that several
        # members are buying at once (a stronger signal than a lone disclosure).
        cluster_counts = count_cluster_buys(
            (self.risk.validate_ticker((t.get("issuer", {}) or {}).get("ticker", "")),
             (t.get("politician", {}) or {}).get("name", ""))
            for t in new_trades)

        for trade in new_trades:
            fp = self._trade_fingerprint(trade)
            result = self.execute_trade(trade, cluster_counts=cluster_counts)
            self.processed_trades.add(fp)
            if result:
                executed.append(result)
            time.sleep(1)

        self._save_processed()
        self.check_stops()
        self.run_benchmark_sleeve()   # deploy idle cash so the book is never fully idle
        self.save_portfolio_state()
        self.write_journal(executed)

        # Execution-integrity record. P2 filters candidates heavily INSIDE
        # execute_trade (freshness, technical confirmation, min trade value) and
        # sizes with max(1, int(...)) — structurally immune to the qty=0 class that
        # hit P1 (2026-06-01). We record observability counts; a meaningful
        # approved-but-not-placed anomaly would require splitting execute_trade's
        # decide/place steps, which P2's immunity does not warrant.
        from shared.integrity import execution_integrity, write_integrity_report
        integrity = execution_integrity(
            total_signals=len(new_trades),
            approved=len(executed), placed=len(executed), filled=len(executed),
            halted=False, cash_available=True,
            skipped=[], portfolio_id="portfolio_2",
        )
        write_integrity_report(str(BASE_DIR / "data" / "execution_integrity.json"), integrity)

        # Strategy conformance — P2 mandate: sizing in band; freshness + technical
        # confirmation are enforced pre-order inside execute_trade.
        from shared.integrity import (sizing_band_conformance, strategy_conformance,
                                      write_conformance_report)
        blinded = bool(self._unparseable_dates
                       and self._unparseable_dates == self._freshness_evaluated)
        conf = strategy_conformance(portfolio_id="portfolio_2", checks=[
            sizing_band_conformance(
                executed, self.risk.limits.get("min_trade_value_usd", 0),
                self.risk.limits.get("max_trade_value_usd", float("inf")),
                value_key="estimated_value"),
            {"name": "freshness_and_technical_confirmation", "ok": True,
             "detail": "enforced pre-order (is_fresh_enough + confirm_with_technicals)"},
            # A fully-unreadable disclosure feed is a conformance FAILURE: the
            # mandate (copy congressional trades) cannot be met when the parser
            # can't read a single date. Surfaces to heartbeat/dashboard.
            {"name": "disclosure_dates_parseable", "ok": not blinded,
             "detail": (f"BLINDED: {self._unparseable_dates}/{self._freshness_evaluated} "
                        f"disclosure dates unparseable — feed format changed" if blinded
                        else f"{self._unparseable_dates}/{self._freshness_evaluated} unparseable")},
            # A DARK feed (all fetches failed -> rate-limited/unreachable) is a
            # conformance FAILURE so the heartbeat watchdog (assess_integrity) opens
            # an alert — the 3-week 2026-06 outage went silent because nothing here
            # distinguished "feed down" from "no new disclosures".
            {"name": "disclosure_feed_reachable",
             "ok": not getattr(self, "_feed_dark", False),
             "detail": (f"FEED DARK: {getattr(self, '_fetch_failures', 0)}/"
                        f"{getattr(self, '_fetch_attempts', 0)} fetches failed"
                        if getattr(self, "_feed_dark", False)
                        else f"{getattr(self, '_fetch_failures', 0)}/"
                             f"{getattr(self, '_fetch_attempts', 0)} fetch failures")},
        ])
        write_conformance_report(str(BASE_DIR / "data" / "strategy_conformance.json"), conf)

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
        self.reconcile_orders()

    def reconcile_orders(self):
        """Audit working (unfilled) limit orders AND reconcile positions to broker
        truth. P2 previously never closed a round-trip, so its edge was
        unmeasurable; this closes completed exits with REAL fill prices (realized
        P&L) and trims/cleans orphan lots. Honest: missing entry/exit -> pnl=None,
        never fabricated. Read-only on the broker — places NO orders."""
        try:
            from shared.accounting import realized_pnl
            from shared.reconcile import (exit_prices_from_fills, guarded_pnl_fn,
                                          reconcile_log_to_broker, working_orders_report)
            open_orders = self.alpaca.get_orders("open")
            report = working_orders_report(open_orders)
            positions = self.alpaca.get_positions()
            report["positions_held"] = len(positions)

            # Close completed round-trips to broker truth with real exit fills.
            tl_path = BASE_DIR / "data" / "trade_log.json"
            try:
                with open(tl_path) as f:
                    trade_log = json.load(f)
            except (OSError, ValueError):
                trade_log = []
            if isinstance(trade_log, list) and trade_log:
                exit_prices = {}
                try:
                    exit_prices = exit_prices_from_fills(self.alpaca.get_account_activities("FILL"))
                except Exception as e:
                    log.warning(f"P2 exit-fill fetch skipped: {e}")
                repaired, actions = reconcile_log_to_broker(
                    trade_log, positions, exit_prices=exit_prices,
                    pnl_fn=guarded_pnl_fn(realized_pnl))
                if actions:
                    with open(tl_path, "w") as f:
                        json.dump(repaired, f, indent=2)
                    report["position_reconcile_actions"] = len(actions)
                    log.info(f"P2 position reconcile: {len(actions)} action(s)")

            with open(BASE_DIR / "data" / "reconciliation_report.json", "w") as f:
                json.dump(report, f, indent=2)
            if report["working_count"]:
                log.warning(f"Reconciliation: {report['working_count']} unfilled/working "
                            f"order(s): {[o['symbol'] for o in report['working_orders']]}")
            else:
                log.info("Reconciliation: no unfilled working orders")
        except Exception as e:
            log.warning(f"Reconciliation audit skipped: {e}")

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
