# Autonomous Trading System — Master Instructions

## Role
Senior Chief Quantitative Trading Analyst managing a $300,000 paper portfolio (3 portfolios × $100K) on Alpaca with a 60% Risky autonomous profile. Fully autonomous — zero manual intervention required.

## AI Agent Mandate — Non-Negotiable Quality Standards
Every AI model agent working on this project MUST operate under the following standards. These are not guidelines — they are the floor.

### Identity & Quality Bar
- **Title**: Senior Chief Expert — operate at the level of a Principal Engineer / Managing Director at the world's largest fintech institution (e.g., Goldman Sachs, Morgan Stanley, Bloomberg, BlackRock, Stripe, Plaid)
- **Output Standard**: World-class production code and designs. Nothing below institutional-grade. If a Goldman Sachs client-facing dashboard wouldn't ship it, neither do we.
- **Design Discipline**: Ultra-premium, highest-quality UI/UX. No generic AI-template patterns. No lazy defaults. Every pixel must feel intentional, every interaction must feel polished.
- **Code Quality**: Zero tolerance for commented-out code, placeholder logic, hardcoded credentials, untested edge cases, or incomplete implementations.

### Branding Compliance (Mandatory)
- Every visual component, dashboard panel, HTML page, CSS rule, and SVG icon MUST respect the **RiseWealth Brand Kit** (see Branding section below).
- **Primary identity**: `"Auto Trading."` — `"Auto"` in `--ink` + `"Trading."` in `--teal`, italic, DM Serif Display. Period always present.
- **Color palette**: Warm browns and oranges ONLY (`--teal` = `#E55A1F`). No cold blues, greens as primary, or grays beyond the muted token.
- **Typography**: DM Serif Display (display/money), Manrope (UI), IBM Plex Mono / JetBrains Mono (data/codes/IDs), IBM Plex Sans Arabic (RTL).
- **Component reference**: Cards at `0.85rem` radius with `1px solid var(--line)` + subtle hover glow. Buttons pill-shaped (`999px`). Tags uppercase, `0.68rem`.
- **Theme**: Support both light (`--page: #FFF7F0`) and dark (`--page: #0E0805`) modes.

### Execution Principles
1. **Understand before changing** — Read surrounding code, existing patterns, and project conventions before writing a single line.
2. **Solve the root problem** — Don't patch symptoms. Fix the architecture if needed.
3. **Test before shipping** — Verify changes work. Never deploy untested code.
4. **Preserve existing quality** — If something is already premium, don't degrade it.
5. **Document decisions** — Every trade decision, design choice, and architectural change must have a logged reason.

### Brand Voice Reference
- **System Name**: Auto Trading (by RiseWealth)
- **Dashboard**: `https://autotradingportfolios.vercel.app`
- **Brand Kit Location**: `docs/branding/RiseWealth Brand Kit.html`
- **Design Tokens File**: `docs/branding/risewealth-tokens.css`

---

# SYSTEM ARCHITECTURE — Production Cloud Deployment

## Overview: Three-Tier Cloud Automation

The entire system runs **100% on cloud** — zero local PC dependency:

```
GitHub Actions (CI/CD)           Vercel (Dashboard)
├── 9 scheduled workflows        ├── Express API (serverless)
│   ├── P1: Self Improving       │   ├── Live Alpaca API proxy
│   ├── P2: Capitol Shadow       │   ├── Static data file serving
│   └── P3: Cautious Sniper      │   └── Real-time portfolio dashboard
├── Alpaca API (trade execution) └── Auto-deploys on every git push
└── Git commits state after run
         ↓
    git push to GitHub
         ↓
    Vercel auto-deploys dashboard
```

## Three Independent Portfolios

| ID | Label | Account | Strategy | Directory |
|----|-------|---------|----------|-----------|
| `portfolio_1` | Self Improving Brain | PA3HULQQ8OOH | Multi-factor quant + regime detection + self-learning | `scripts/` (root) |
| `portfolio_2` | Capitol Shadow | PA38R564MIS7 | Copy-trade US politicians via MCP Capitol Trades | `political-copy-bot/` |
| `portfolio_3` | Cautious Sniper | PA3M3WI7C58W | Fundamental screen + technical breakout + news sentiment | `event-driven-bot/` |

**Each portfolio is ISOLATED**: separate directories, separate Alpaca accounts, separate GitHub Actions workflows, separate concurrency groups, separate git commit targets.

## GitHub Actions Workflow Architecture

### Critical: Concurrency Groups (PER PORTFOLIO — NOT shared!)
All 9 trading/monitor/EOD/weekly workflows use isolated concurrency groups (`p1-trading`, `p1-monitor`, `p2-trading`, etc.). This ensures P1, P2, and P3 can ALL run in parallel without blocking each other. (There are now **14 workflows total** — the 9 trading ones plus `ci`, `codeql`, `heartbeat`, `market-data`, `smoke-test`; see the ENTERPRISE HARDENING section.)

### Workflows by Portfolio

**P1 — Self Improving Brain (4 workflows)**:
| File | Schedule (ET) | Purpose |
|------|--------------|---------|
| `p1-trading.yml` | 9:45 AM M-F | Morning research → trading session → commit |
| `p1-monitor.yml` | Every 30 min 10:30AM-3:30PM | P&L check, stop enforcement, kill switch |
| `p1-eod.yml` | 4:15 PM M-F | End-of-day journal, self-learning, adapt params |
| `p1-weekly.yml` | Friday 4:30 PM | Weekly review, rebalancing analysis |

**P2 — Capitol Shadow (2 workflows)**:
| File | Schedule (ET) | Purpose |
|------|--------------|---------|
| `p2-trading.yml` | 10:15 AM + 3:45 PM | Scan politician trades → copy-trade → commit |
| `p2-monitor.yml` | Hourly 10:30AM-3:30PM | Check stops, portfolio health |

**P3 — Cautious Sniper (3 workflows)**:
| File | Schedule (ET) | Purpose |
|------|--------------|---------|
| `p3-trading.yml` | 9:50 AM M-F | Mon: weekly screen, daily: morning-scan → trading-session → news-scan |
| `p3-monitor.yml` | Hourly 11AM-3PM | P&L, kill switch, halt check |
| `p3-eod.yml` | 4:20 PM M-F | End-of-day journal & audit |

### Workflow Pattern (All 9)
Every workflow follows this pattern:
1. `actions/checkout@v4` — clone repo
2. `setup-python@v5` — Python 3.13
3. `pip install -r requirements.txt` — single dependency: `requests`
4. **Create Alpaca config from GitHub Secrets** — `P1_API_KEY`, `P2_API_KEY`, etc.
5. **Check market open** — Alpaca clock API → `steps.market.outputs.is_open`
6. Run the Python script with correct `PYTHONPATH`
7. **Sync data to dashboard** — `cp data/*.json dashboard/data/` etc. (so Vercel deploys latest state)
8. **Commit state** — `git add` all data dirs + `dashboard/data/` with `-f` flag, 3 retry push

### Defense-in-Depth: Market-Open Guards
Every trading/monitor code path has DOUBLE protection:
- **Workflow level**: `if: steps.market.outputs.is_open == 'true'`
- **Python level**: `if not alpaca.is_market_open(): return` inside each function

This applies to: P1 trading-session, P1 intraday-monitor, P2 scan-and-trade, P2 monitor, P3 trading-session, P3 intraday-monitor, P3 news-scan.

---

# ⭐ ENTERPRISE HARDENING & SYSTEM OF RECORD (2026-05) — READ BEFORE EDITING

> This section documents the hardening layered on top of the original system. A
> future AI/engineer **must understand these invariants before changing the
> money path, the chart, the data layer, or the workflows.** Breaking any of
> these silently regresses correctness or reliability.

## 14 GitHub Actions workflows (was 9)
Trading/monitor/EOD/weekly (9, per CLAUDE above) **plus**:
| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | push/PR to engine code | **Quality gate**: ruff + pytest must pass. |
| `codeql.yml` | push/PR + weekly | Security static analysis. |
| `heartbeat.yml` | 22:30 & 23:30 UTC M-F | Watchdog: alerts (GitHub issue / Slack) if any portfolio went stale. |
| `market-data.yml` | 21:30 & 22:30 UTC M-F + dispatch | Mirrors daily bars → Supabase. `dispatch days=730` = full backfill. |
| `smoke-test.yml` | push to `dashboard/**` | Polls prod health post-deploy. **No VERCEL_TOKEN** (Vercel git-integration auto-deploys). |

**Scheduled-trading reliability:** all trading/EOD crons use MULTIPLE staggered cron lines covering BOTH EDT and EST UTC offsets, with an idempotency dedup gate (P1/P3 check today's `signals.json` date). A single cron line is a known-fragile pattern — never reduce to one.

## Unified Alpaca client — `shared/alpaca_http.py` (SINGLE SOURCE OF TRUTH)
All three bots' broker calls route through this module. **Do not duplicate or bypass it.**
- `resilient_request()` — retries 429/5xx + network errors (exp backoff + jitter, honors Retry-After). 4xx (except 429) raise immediately.
- `make_client_order_id(prefix,symbol,side)` — deterministic per-portfolio/symbol/side/day key. **Every order MUST send `client_order_id`** so a retried/duplicate run can't double-place; a 422 duplicate is an idempotent skip (not an error).
- `confirm_fill(client,order_id)` — logs trades at the REAL `filled_avg_price`/`filled_qty`, never a phantom limit price.
- Consumers: P1 `scripts/autonomous_runner.py`, P2 `political-copy-bot/scripts/politician_bot.py` (`AlpacaClient`), P3 `event-driven-bot/scripts/alpaca_client.py` (re-exports the helpers for `event_driven_bot.py`). Each adds repo-root to `sys.path` then imports `shared.alpaca_http`.

## Tests + CI gate — `tests/` (RUN BEFORE SHIPPING ENGINE CHANGES)
- `python3 -m pytest tests/` (80+ tests) and `python3 -m ruff check scripts/ shared/ event-driven-bot/scripts/ political-copy-bot/scripts/`.
- Config in `pyproject.toml`; dev deps in `requirements-dev.txt`. CI gate (`ci.yml`) runs both on every push — it must stay green. Covers: risk_officer (incl. the INSUFFICIENT_DATA regression), execution resilience/idempotency/fill, indicators, backtest metrics+engine, walk-forward gate, reconciliation, heartbeat.

## Backtester + walk-forward-gated self-learning — `scripts/backtest/`
- `metrics.py` — Sharpe/Sortino/Calmar/CAGR/max-drawdown (pure; also used on the live equity curve).
- `multifactor.py` — point-in-time, **no-look-ahead** portfolio backtest that reuses the REAL `analyst_v2` scoring (regime, relative strength, composite). Signal at close t → execute at open t+1; cost+slippage modeled.
- `walk_forward.py` — `gate_param_change()` approves a self-learning param change only if its out-of-sample mean Sharpe ≥ current's (fails CLOSED). `load_aligned_bars()` reads morning-research's cached `data/{bucket}.json` bars.
- Wired into `performance_tracker.adapt_parameters(validate_with_bars=...)`: in EOD it loads cached bars and **reverts any knob change that fails OOS validation**. P1 only — P2/P3 have no self-learning loop. **Never let self-learning tune on live noise without this gate.**

## Reconciliation (read-only integrity audit) — `shared/reconcile.py`
- `compute_drift(positions, open_trades)` → orphan open trades / unlogged positions. Used by P1 (`autonomous_runner.reconcile_positions`, EOD) and P3 (`run_eod_journal`).
- `working_orders_report(open_orders)` → unfilled-limit surface; P2 monitor uses it (P2 is the only limit-entry portfolio; P3 uses bracket MARKET orders that fill instantly).
- Writes `data/reconciliation_report.json` (+ per-portfolio). **Read-only — places NO orders.**

## Supabase = SYSTEM OF RECORD — see `memory/reference_supabase.md`
- Project `auto-trading-prod`, ref `iqbnjzzrwcwxnipwposk`, URL `https://iqbnjzzrwcwxnipwposk.supabase.co`.
- Tables (public, **RLS on: anon SELECT-only, service_role writes**): `portfolio_equity_history` (portfolio_id,date,equity,cash,pnl,pnl_pct,positions_count), `market_daily_history` (symbol,date,open/high/low/close_price,volume). Both PK on (id,date) for merge-upserts.
- **Credential map:** GitHub secrets `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` (WRITE path — `save_to_supabase.py`, `collect_market_history.py`). Vercel env `SUPABASE_URL` + `SUPABASE_ANON_KEY` (READ path — `dashboard/server.js`). The running system does NOT depend on any personal access token.
- **Manage via the Management API** (`https://api.supabase.com/v1/...`) with a PAT from supabase.com/dashboard/account/tokens — NOT the browser. `POST /v1/projects/{ref}/database/query` runs SQL.
- Writers: `scripts/save_to_supabase.py` (daily equity snapshot per portfolio, in p1-eod/p2-trading/p3-eod) and `scripts/collect_market_history.py` (full chart-universe daily bars, in `market-data.yml`). Backfilled to ~2y × 37 symbols.
- **Honesty rule:** the dashboard shows ONLY real data. `dashboard/server.js` `realEquityBackfill()` uses real Supabase history; the old synthetic `generateStrategyBackfill` was DELETED. **Never reintroduce fabricated equity/price data.**

## Market-Pulse chart (world-class candlesticks) — `dashboard/public/assets/market-pulse.js`
- `renderWorkspaceChart` + `drawCandleChart` = a **self-contained canvas candlestick renderer** (wicks+bodies, volume strip, crosshair+OHLC tooltip, HiDPI). **Do NOT revert to a Chart.js `type:'bar'` approach** — that caused the flat-columns-from-$0 bug.
- Period→data mapping (free IEX tier): `1D`=5Min, `1W`=1Hour, `1M`/`3M`/`6M`/`1Y`=1Day (one candle/day). **Every non-1D request MUST send an explicit `start` date** — without it Alpaca IEX returns a SINGLE bar (the empty-period bug). Periods are exactly 1D/1W/1M/3M/6M/1Y (no 5D).
- Backend `/api/market/bars/:symbol` (`server.js`): `defaultBarsStart()` guarantees a start is always present; `sort=desc`+`.reverse()` returns the most-recent N bars chronologically. Free IEX gives years of daily history when `start` is set.
- Live updates: REST polling (20s for 1D/1W). **WebSocket is intentionally not used** — Vercel serverless can't hold a persistent connection and IEX free data is 15-min delayed, so polling is equivalent. True streaming would need a separate always-on worker.

## Dashboard security — `dashboard/server.js`
- All POST/mutation endpoints (`/order`, `/close`, `/positions/close-all`) require `DASHBOARD_ACCESS_TOKEN` (Bearer or `x-access-token`). **Unset → 503 (fail-closed); anonymous trade execution is impossible.** Reads stay public for the showcase.
- `helmet` headers, CORS locked to `DASHBOARD_ALLOWED_ORIGINS`, per-IP rate limit (`DASHBOARD_RATE_LIMIT`, default 120/min).
- `node_modules` is gitignored and **untracked** (Vercel runs `npm install`). Do not re-commit it.

## Live-readiness gate — `docs/LIVE_READINESS.md`
System is **PAPER ONLY**. The doc defines the engineering + strategy + ops gates (90d paper, OOS Sharpe ≥ 1.0, max DD ≤ 15%, etc.) and fractional go-live procedure. Do not deploy real capital until all gates are signed off.

## Still open (deliberate, not bugs)
Full sole-source migration (retire git-JSON state in favor of Supabase); P2/P3 active fill-backfill (currently read-only audits); time-on-paper to meet live-readiness gates.

## Quant research standards & the dependency-tiering law (2026-06)
Institutional quant-validation/portfolio-construction standards live in the **`portfolio-optimizer`
skill** (`.claude/skills/portfolio-optimizer/SKILL.md`); the evaluation of the external "Institutional
Blueprint" against this system is `docs/QUANT_BLUEPRINT_EVALUATION.md`. **Before adding any quant
module, obey the dependency-tiering law:**
- **T0/T1 (on the cloud path):** stdlib / pure-Python ONLY. The backtest+metrics stack is pure-Python
  by design (hand-rolled `_mean`/`_std`/`normal_cdf`) so it runs in the `requests`-only runtime.
  Deflated Sharpe / PSR / PBO already live here (`scripts/backtest/metrics.py`) — use, don't rebuild.
- **T2 (offline research only):** `numpy`/`pandas`/`scipy`/`sklearn`/`statsmodels`/boosting allowed,
  but they **NEVER import on the trading path**. They emit **static artifacts** (e.g. HRP weights,
  frac-diff `d`, regime labels, calibrated probabilities) committed for the cloud path to *read* —
  exactly how the walk-forward gate already feeds `data/strategy_params.json`.
- New risk math (VaR/CVaR/HRP/meta-label sizing) is **advisory inside the hardcoded caps** in
  `config/risk_limits.json` — it never relaxes a limit. DSR/VaR on live P&L is invalid until the
  sample is large enough (refuse on small N). Microstructure/tick/order-book/RL items are out of
  scope — the data and runtime do not support them.

---

# TRADING SYSTEM ARCHITECTURE

## Architecture (Three-Tier Triad)
- **Tier 1 — Analyst (`scripts/analyst_v2.py`)**: Multi-factor signal engine with regime detection, relative strength ranking, MACD, Bollinger Bands, and adaptive self-learning parameters
- **Tier 2 — Risk Officer (`scripts/risk_officer.py`)**: Validates signals against hardcoded limits; portfolio manager (`scripts/portfolio_manager.py`) handles stops and rebalancing
- **Tier 3 — Executor**: Places limit orders via Alpaca REST API (autonomous_runner.py AlpacaClient)

## Self-Learning System
- **Performance Tracker** (`scripts/performance_tracker.py`): Logs every trade, computes win rates per symbol/bucket/timeframe
- **Adaptive Parameters** (`data/strategy_params.json`): Auto-tunes RSI thresholds, stop distances, position sizing, and confidence thresholds based on rolling performance
- **Learning Loop**: End-of-day journal feeds outcomes → performance tracker computes metrics → adaptive engine adjusts parameters → next day's signals are better calibrated
- **None-safe metrics**: When zero closed trades exist, `compute_metrics()` returns `None` (not `0.5`) for win_rate — prevents self-learning from poisoning on empty data

## Enhanced Strategy: Multi-Factor Scoring
Each symbol gets a composite score from:
| Factor | Weight | Indicators |
|--------|--------|------------|
| Trend | 0.30 | Price vs MA50/MA200 |
| Momentum | 0.25 | 1M, 3M, 6M returns |
| RSI | 0.15 | Overbought/oversold/buy zone |
| MACD | 0.10 | Line, signal, histogram |
| Bollinger Bands | 0.05 | Mean reversion at extremes |
| Volume | 0.05 | 20-day volume trend |
| Market Regime | 0.15 | STRONG_BULL to STRONG_BEAR multiplier |
| Relative Strength | 0.10 | Cross-asset percentile ranking |

**Signal thresholds** (adaptive):
- BUY: score >= confidence_buy_threshold (starts at 0.50)
- SHORT: score <= -confidence_short_threshold (starts at -0.50)
- HOLD: everything in between

## Market Regime Detection
Regime detected from SPY: STRONG_BULL → BULL → CORRECTION → RECOVERY → BEAR → STRONG_BEAR
- Bull regimes: equity allocation x1.0–1.2, defensive x0.6–0.8
- Bear regimes: equity allocation x0.3–0.5, defensive x1.5–1.8, higher cash target

## Risk Management (ATR-Based)
- **Trailing stop**: entry - (ATR × trailing_stop_atr_mult), tightens as profit grows
- **Breakeven stop**: once up 3%+, stop moves to entry + 0.5%
- **Take profit**: entry + (ATR × take_profit_atr_mult) → sell 50%
- **Position sizing**: max_loss_per_trade = equity × 1%, shares = max_loss / (ATR × stop_mult)
- **Daily loss check**: uses `day_start_equity` from portfolio_state (consistent with risk_officer)
- **Fill price accuracy**: stop-loss/TP close_trade() uses `filled_avg_price` from order response, not current_price

## Hardcoded Safety Limits (Non-Negotiable)
- Max daily loss: 4% → halt 24h
- Max weekly loss: 8% → halt 7 days
- Kill switch drawdown: 18% → liquidate all, system lockdown
- Max single position: 12% ETF, 8% stock, 1% penny, 5% crypto
- Max crypto exposure: 10%
- Max trades/day: 12
- Max gross exposure: 160%
- Max short exposure: 25%

## Allocation Targets
| Bucket | Target | Symbols |
|--------|--------|---------|
| Core Equity | 20% | SPY, QQQ, IWM, DIA |
| Aggressive Growth | 25% | NVDA, TSLA, META, AMZN, MSFT, GOOGL, AAPL |
| Sector Momentum | 15% | XLK, XLE, XLF, XLV, XLY, XLI |
| Crypto | 10% | BTC/USD, ETH/USD |
| Penny Lab | 5% | Exchange-listed $1-$5, paper only |
| Defensive/Cash | 20% | SHY, BIL, TLT, GLD |
| Options | 5% | Phase 2 |

## Automated Routines (Scheduled Tasks)
| Routine | Schedule (ET) | Purpose |
|---------|--------------|---------|
| `morning-research` | 9:45 AM M-F | Pull 220-day bars, compute indicators, detect regime, generate signals |
| `trading-session` | 10:00 AM M-F | Validate signals, execute limit orders, log trades |
| `intraday-monitor` | Every 30 min 10AM-4PM M-F | Check P&L, enforce stops, trigger kill switch if needed |
| `end-of-day-journal` | 4:15 PM M-F | Log performance, run self-learning, adapt parameters, plan next day |
| `weekly-review` | 4:30 PM Fridays | Deep analysis, rebalancing assessment, strategy tuning |

## Key Files
- `config/risk_limits.json` — hardcoded guardrails (NEVER modify programmatically)
- `config/watchlist.json` — target symbols by bucket
- `scripts/analyst_v2.py` — enhanced multi-factor signal engine
- `scripts/autonomous_runner.py` — P1 orchestrator (dispatches all modes)
- `scripts/risk_officer.py` — trade validation engine
- `scripts/performance_tracker.py` — self-learning and trade logging
- `scripts/portfolio_manager.py` — stop management, rebalancing, health checks
- `scripts/fetch_bars.py` — standalone bar fetcher (local cron fallback only)
- `data/signals.json` — latest analysis output
- `data/strategy_params.json` — adaptive parameters (auto-tuned)
- `data/portfolio_state.json` — current portfolio state
- `data/trade_log.json` — complete trade history with outcomes
- `data/learning_report.json` — latest performance metrics
- `data/validated_orders.json` — risk-validated orders ready for execution
- `journal/YYYY-MM-DD.json` — daily trade journals
- `journal/weekly-YYYY-WNN.json` — weekly review reports

## Decision Framework
1. Check market status (`get_clock`) and account health (`get_account_info`)
2. Pull 220-day historical bars for all watchlist symbols
3. Run `analyst_v2.py`: compute indicators, detect regime, rank relative strength, score signals
4. Run `risk_officer.py`: validate against hardcoded limits
5. Run `portfolio_manager.py`: check stops, compute rebalancing needs
6. Execute approved orders via Alpaca REST API (limit orders only)
7. Log every trade to `trade_log.json` with full reasoning, stop_loss, take_profit
8. Update `portfolio_state.json` with new state
9. End-of-day: run `performance_tracker.py` to adapt parameters

---

# DASHBOARD ARCHITECTURE (Vercel Production)

## Deployment Pipeline
```
GitHub Actions commits state JSON → git push → GitHub
    → Vercel detects repo push → auto-builds from dashboard/ directory
    → Data files already present (synced by Actions before commit, NOT by build.sh)
    → Express serverless API serves live Alpaca data + committed state files
```

## CRITICAL: Vercel Path Resolution (DO NOT CHANGE)
On Vercel, the serverless function `api/index.js` lives at `/var/task/`. The `__dirname` IS the project root — do NOT use `path.resolve(__dirname, '..')` because that resolves to `/var/` (one level above the actual root). The correct resolution:

```javascript
const ROOT_DIR = IS_VERCEL ? __dirname : localPath;
```

This is the single most critical line in the entire dashboard. Changing it incorrectly will cause ALL data files to return empty (trade_log=0, signals={}), which has happened during audits and took multiple deploy cycles to diagnose.

## Dashboard Directory Structure
```
dashboard/
├── server.js              # Express API — 50+ endpoints, Alpaca proxy
├── api/index.js           # Vercel serverless entry point
├── vercel.json            # Vercel deployment config
├── package.json           # Dependencies: express, cors
├── data/                  # Synced by Actions from root data/ (COMMITTED to git)
├── event-driven-bot/data/ # Synced by Actions from P3 (COMMITTED to git)
├── political-copy-bot/data/ # Synced by Actions from P2 (COMMITTED to git)
├── journal/               # Synced by Actions from root journal/ (COMMITTED to git)
├── config/                # risk_limits.json, watchlist.json only (portfolios.json is gitignored)
├── public/
│   ├── index.html         # Homepage with live ticker (12s refresh)
│   ├── portfolio.html     # Portfolio list (60s card refresh)
│   ├── portfolio-detail.html  # Portfolio dashboard (30s refresh)
│   ├── market-pulse.html  # Market pulse (2.5s micro-tick + 30s full)
│   ├── alerts.html        # Alerts (5s neural signals + 12s ticker)
│   ├── orders.html        # Orders (30s refresh)
│   ├── research.html      # Research & AI (12s ticker)
│   ├── settings.html      # Settings (static)
│   ├── screener.html      # Screener (30s watchlist refresh)
│   ├── crypto-terminal.html  # Crypto (5s-30s multi-interval refresh)
│   ├── stock-detail.html  # Stock detail (15s refresh)
│   └── assets/            # JS, CSS, theme files
└── .vercel/               # Vercel project link (gitignored)
```

Note: `dashboard/data/`, `dashboard/event-driven-bot/data/`, etc. are COMMITTED to git (NOT gitignored). They are automatically synced by every GitHub Actions workflow run before commit. Do NOT add them to .gitignore.

## Vercel Environment Variables (REQUIRED for live data)
Set in Vercel Dashboard → Project Settings → Environment Variables:

| Variable | Purpose |
|----------|---------|
| `PORTFOLIO_1_API_KEY` | P1 Alpaca paper API key |
| `PORTFOLIO_1_API_SECRET` | P1 Alpaca paper API secret |
| `PORTFOLIO_2_API_KEY` | P2 Alpaca paper API key |
| `PORTFOLIO_2_API_SECRET` | P2 Alpaca paper API secret |
| `PORTFOLIO_3_API_KEY` | P3 Alpaca paper API key |
| `PORTFOLIO_3_API_SECRET` | P3 Alpaca paper API secret |
| `SUPABASE_URL` | Supabase system-of-record URL (read path for charts/equity) |
| `SUPABASE_ANON_KEY` | Supabase anon key (RLS: read-only) |
| `DASHBOARD_ACCESS_TOKEN` | Gates POST/mutation endpoints. **Unset = mutations fail-closed (503).** |
| `DASHBOARD_ALLOWED_ORIGINS` | CORS allow-list (comma-sep). Default: prod URL + localhost. |

Without the PORTFOLIO_* keys, the dashboard falls back to committed JSON state files only.
All of the above are **already set in Vercel production** (configured 2026-05). See the
"ENTERPRISE HARDENING & SYSTEM OF RECORD" section for the full credential map.

## Dashboard Data Sources (Priority Order)
1. **Live Alpaca API** (primary) — positions, equity, P&L, quotes, news, clock, sectors
2. **Committed state files** (fallback) — data/*.json, journal/*.json, portfolio subdirs
3. **Environment variables** (config) — API keys, base URLs

## Dashboard Auto-Refresh Intervals (All Active)
| Page | Component | Interval |
|------|-----------|----------|
| Home | Market ticker + featured prices | 12s |
| Portfolio List | Card values (equity, return, positions) | 60s |
| Portfolio Detail | Positions, equity, P&L, orders widget | 30s |
| Market Pulse | Price micro-ticks (synthetic) | 2.5s |
| Market Pulse | Full quotes, sectors, clock refresh | 30s |
| Orders | Order list | 30s |
| Screener | Watchlists | 30s |
| Stock Detail | Price, fundamentals | 15s |
| Crypto Terminal | Orderbook | 5s |
| Crypto Terminal | Trades | 8s |
| Crypto Terminal | Snapshot | 10s |
| Crypto Terminal | Positions | 15s |
| Crypto Terminal | Bars | 30s |
| Alerts | Neural signals feed | 5s |
| All pages | Index ticker marquee | 8-12s |

---

# CRITICAL RULES & CONSTRAINTS

## Git / Security (NON-NEGOTIABLE)
- **NEVER commit API keys or secrets** to git
- `config/portfolios.json` — gitignored (contains all API keys)
- `config/alpaca_config.json` — gitignored (created by GitHub Actions from Secrets)
- `dashboard/config/portfolios.json` — gitignored (contains API keys)
- `dashboard/node_modules/` — gitignored (npm dependencies, installed by Vercel)
- `dashboard/.vercel/` — gitignored (local Vercel project link)
- GitHub Secrets store all API keys for Actions workflows
- `dashboard/data/`, `dashboard/event-driven-bot/data/`, `dashboard/political-copy-bot/data/`, `dashboard/journal/`, `dashboard/config/risk_limits.json`, `dashboard/config/watchlist.json` — COMMITTED (synced by Actions, deployed to Vercel)

## Risk & Trading (NON-NEGOTIABLE)
- NEVER override hardcoded risk limits in `config/risk_limits.json`
- ALWAYS use limit orders (no market orders except stop-loss exits)
- ALWAYS log reasoning for every trade decision
- Capital preservation > capturing every opportunity
- Paper trading only until live-readiness gates are met
- Self-learning parameters have bounds (e.g., position_size_multiplier: 0.5–1.5)

## Code Quality Standards
- All 4 `load_json()` functions must use `default if default is not None else {}` pattern (NOT `default or {}`)
- All `save_json()` use `json.dump(data, f, indent=2)` consistently
- Market-open guards required at BOTH workflow level AND Python function level
- Daily loss checks must use `day_start_equity` from portfolio_state (not Alpaca `last_equity`)
- All `compute_metrics()` callers must handle `None` values (no trades scenario)
- Git push retries must log failures (no silent `2>/dev/null` suppression)

## Vercel Deployment

### CRITICAL: includeFiles Format (DO NOT CHANGE)
The `includeFiles` glob in `vercel.json` uses **brace expansion** syntax — NOT comma-separated:
```json
"includeFiles": "{data,event-driven-bot/data,political-copy-bot/data,journal,config}/**"
```
- Commas in the string do NOT match multiple patterns on Vercel — they're treated as literal characters.
- Brace expansion `{a,b,c}/**` is the ONLY supported way to match multiple directory trees.
- Array format `["data/**", ...]` is NOT accepted — Vercel throws "should be string" error.
- **NEVER change this format.** Even adding a single comma breaks the deployment silently.

### Build Cache Trap
Vercel aggressively caches builds. If `vercel.json` changes don't seem to take effect:
1. The cache is masking the change — ALWAYS use `--force` when modifying `vercel.json`:
   ```
   cd dashboard && vercel --prod --force
   ```
2. Verify with: `curl https://autotradingportfolios.vercel.app/api/health`

### Deployment Verification (MANDATORY — Run After Every Deploy)
```
# Local pre-deploy check
bash dashboard/validate.sh

# Deploy with force (bypass cache)
cd dashboard && vercel --prod --force

# Wait 10s for propagation, then verify
sleep 10
curl -s https://autotradingportfolios.vercel.app/api/health | python3 -c "
import json, sys
d = json.load(sys.stdin)
for k in ['tradeLog','signals','state']:
    f = d.get('files',{}).get(k,{})
    assert f.get('exists'), f'FAIL: {k} missing on Vercel'
    print(f'OK: {k} ({f.get(\"size\",0)} bytes)')
"
curl -s https://autotradingportfolios.vercel.app/api/portfolio/portfolio_1/details | python3 -c "
import json, sys
d = json.load(sys.stdin)
tl = len(d.get('trade_log',[]))
assert tl > 0, f'FAIL: trade_log empty ({tl} entries)'
print(f'OK: trade_log={tl}, positions={len(d.get(\"positions\",{}))}')
"
```
- If `trade_log` returns 0, **roll back immediately** — data files are not deployed.
- A `smoke-test.yml` GitHub Action runs automatically on every push to `main`.

### Deployment Checklist
- [ ] `bash dashboard/validate.sh` passes (all data files present, >10 bytes, git-tracked)
- [ ] `vercel.json` uses brace expansion `{a,b}/**` format
- [ ] Deploy with `vercel --prod --force` (force bypasses cache)
- [ ] Post-deploy: `curl /api/health` shows all files `exists: true`
- [ ] Post-deploy: `curl /api/portfolio/:id/details` shows `trade_log > 0`

### Key Files
- `dashboard/build.sh` — **validates data files during Vercel build** (fails build if any missing)
- `dashboard/validate.sh` — pre-deploy check script (run locally before pushing)
- `dashboard/vercel.json` — `includeFiles` uses brace expansion
- `.github/workflows/smoke-test.yml` — automatic post-deploy verification
- Vercel project root = `dashboard/` directory
- Deploy: `cd dashboard && vercel --prod --force`

---

# TROUBLESHOOTING — Common Failure Modes

## Dashboard shows all zeros / empty data (trade_log=0, signals={})
**Root Cause**: `ROOT_DIR` is resolving to `/var/` instead of `/var/task/` on Vercel.
**Fix**: DO NOT use `path.resolve(__dirname, '..')`. Use `__dirname` directly.
**Verify**: `curl https://autotradingportfolios.vercel.app/api/health` → rootDir must be `/var/task`.

## Dashboard shows mock data / no live prices
**Root Cause**: Vercel environment variables missing or `config/portfolios.json` not found.
**Fix**: Ensure all 6 `PORTFOLIO_*_API_KEY`/`PORTFOLIO_*_API_SECRET` vars are set in Vercel → Settings → Environment Variables → Production.

## GitHub Actions workflows block each other
**Root Cause**: Concurrency group collision. All workflows must use unique groups.
**Fix**: Each workflow has its own group: `p1-trading`, `p1-monitor`, `p2-trading`, etc. Never use `trading-pipeline`.

## Data files exist locally but not on Vercel
**Root Cause**: One of three things (check in order):
1. **Build cache**: Vercel cached old build without data files. Fix: `cd dashboard && vercel --prod --force`
2. **`includeFiles` format broken**: Commas used instead of brace expansion in `vercel.json`. Fix: `"includeFiles": "{data,event-driven-bot/data,political-copy-bot/data,journal,config}/**"`
3. **Files not committed**: `dashboard/data/` must be in git, not in `.gitignore`. Run `git ls-files dashboard/data/trade_log.json` to verify.
**Verify**: `curl https://autotradingportfolios.vercel.app/api/health` → all files must show `exists: true`.
**Prevention**: Run `bash dashboard/validate.sh` before every push. Post-deploy smoke test runs automatically via GitHub Actions.

## Trade log has entries but P&L is always $0
**Root Cause**: `close_trade()` was using `current_price` instead of `filled_avg_price` from order response.
**Fix**: Use `order_result.get("filled_avg_price")` from the placed order, not the position's current price.

## Self-learning poisoned: win_rate always 50% with no trades
**Root Cause**: `compute_metrics()` returned `win_rate: 0.5` when zero closed trades exist.
**Fix**: Return `None` for win_rate and all ratio metrics. All callers must handle `None`.

## `load_json` returns {} when it should return 0 or False
**Root Cause**: Using `default or {}` instead of `default if default is not None else {}`.
**Fix**: All 4 copies of `load_json` must use the `default is not None` pattern.

---

# BRANDING — RiseWealth Brand Kit (Name: "Auto Trading")
The dashboard uses the **RiseWealth Brand Kit** (saved at `docs/branding/`), rebranded as **"Auto Trading."** — keep this name everywhere.

### Design Tokens (Single Source of Truth)
| Token | Light | Dark |
|-------|-------|------|
| `--page` | `#FFF7F0` | `#0E0805` |
| `--surface` | `#FFFFFF` | `#1A0F08` |
| `--ink` | `#1A0F08` | `#FFF1E8` |
| `--muted` | `#7A6B5E` | `#A39A92` |
| `--line` | `rgba(26,15,8,0.07)` | `rgba(255,255,255,0.08)` |
| `--teal` (primary) | `#E55A1F` | `#FF8A3D` |
| `--teal-dark` (hover) | `#C9461A` | `#FFA86A` |
| `--teal-soft` | `#FFF1E8` | `rgba(229,90,31,0.15)` |

### Solar Ramp (10-step)
`#FFF1E8` → `#FFD9BD` → `#FFC396` → `#FFA86A` → `#FF8A3D` → `#F26B1F` → **`#E55A1F`** (primary) → `#C9461A` → `#A33A14` → `#6A220A`

### Typography
- **Display/Money**: `DM Serif Display`, serif — headlines, large numbers
- **UI**: `Manrope` — all body text, labels, buttons
- **Monospace**: `IBM Plex Mono` / `JetBrains Mono` — data, codes, IDs
- **Arabic**: `IBM Plex Sans Arabic` — RTL mode

### Wordmark Pattern
`"Auto"` in --ink + `"Trading."` in --teal, italic, DM Serif Display. Period always present.

### Component Styles
- **Cards**: `border-radius: 0.85rem`, `border: 1px solid var(--line)`, subtle hover glow
- **Buttons**: pill shape (`border-radius: 999px`), CTA shadow `0 8px 18px rgba(229,90,31,0.30)`
- **Tags/Badges**: pill, uppercase, 0.68rem, accent backgrounds
- **Shadows**: `--rw-sh-1: 0 1px 2px rgba(26,15,8,0.04), 0 6px 14px rgba(26,15,8,0.05)`

### Design Rules
- NEVER change production layout dimensions without visual testing
- Warm browns and oranges ONLY — no cold blues/grays
- Keep premium density — financial terminal aesthetic
- All changes must respect RTL (Arabic) support
- Brand kit source files: `docs/branding/RiseWealth Brand Kit.html`

### Dashboard Files
- `dashboard/public/assets/news-public.css` — global theme variables & nav
- `dashboard/public/assets/portfolio.css` — portfolio pages
- `dashboard/public/market-pulse.html` — market pulse page (inline styles)
- `dashboard/public/assets/market-pulse.js` — market pulse logic
- `dashboard/public/assets/portfolio-detail.js` — portfolio detail logic
- `dashboard/public/assets/portfolio-store.js` — data store
- `dashboard/server.js` — Express API (Vercel serverless)
- `dashboard/vercel.json` — Vercel deployment config
- `dashboard/build.sh` — Vercel pre-build data sync script
- Production URL: https://autotradingportfolios.vercel.app

---

## Constraints
- NEVER override hardcoded risk limits
- ALWAYS use limit orders (no market orders except stop-loss exits)
- ALWAYS log reasoning for every trade decision
- Capital preservation > capturing every opportunity
- Paper trading only until live-readiness gates are met
- Self-learning parameters have bounds (e.g., position_size_multiplier: 0.5–1.5)
- NEVER commit API keys or dashboard/config/portfolios.json
- All 9 trading GitHub Actions workflows have per-portfolio concurrency groups (14 workflows total incl. ci/codeql/heartbeat/market-data/smoke-test)
- Market-open checked at BOTH workflow and Python levels
- Dashboard deploys from dashboard/ directory only (not repo root)

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
