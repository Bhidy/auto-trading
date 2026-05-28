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
All 9 workflows use isolated concurrency groups (`p1-trading`, `p1-monitor`, `p2-trading`, etc.). This ensures P1, P2, and P3 can ALL run in parallel without blocking each other.

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
7. **Commit state** — `git add data/ journal/ → commit → push` with 3 retries

### Defense-in-Depth: Market-Open Guards
Every trading/monitor code path has DOUBLE protection:
- **Workflow level**: `if: steps.market.outputs.is_open == 'true'`
- **Python level**: `if not alpaca.is_market_open(): return` inside each function

This applies to: P1 trading-session, P1 intraday-monitor, P2 scan-and-trade, P2 monitor, P3 trading-session, P3 intraday-monitor, P3 news-scan.

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
    → build.sh copies data files (data/, journal/, config/) into dashboard/
    → Express serverless API serves live Alpaca data + committed state files
```

## Dashboard Directory Structure
```
dashboard/
├── server.js              # Express API — 50+ endpoints, Alpaca proxy
├── api/index.js           # Vercel serverless entry point
├── vercel.json            # Vercel deployment config
├── build.sh               # Pre-deploy: copies data files from parent dirs
├── package.json           # Dependencies: express, cors
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

Without these, the dashboard falls back to committed JSON state files only.

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
- `dashboard/data/` — gitignored (stale mirrors, regenerated by build.sh)
- `dashboard/.vercel/` — gitignored (local Vercel project link)
- GitHub Secrets store all API keys for Actions workflows

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
- Vercel project root = `dashboard/` directory
- `build.sh` copies parent data files before build
- `includeFiles` in vercel.json must include `data/**,event-driven-bot/data/**,political-copy-bot/data/**,journal/**,config/**`
- `buildCommand` must be ≤ 256 chars (use shell script)
- Deploy from dashboard directory: `cd dashboard && vercel --prod`

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
- All 9 GitHub Actions workflows have per-portfolio concurrency groups
- Market-open checked at BOTH workflow and Python levels
- Dashboard deploys from dashboard/ directory only (not repo root)
