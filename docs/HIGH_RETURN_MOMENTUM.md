# High-Return Strategy — Research + Honest Verdict (2026-07-04)

**Client objective:** highest achievable return, accepting higher risk (bigger drawdowns),
long-only, $100k, daily bars, within the hardcoded caps. This documents what the deep research
(6 independent web-research passes + a 5-year backtest on our own data) actually found, and the
resulting **paper-gated** plan. Evidence: `data/high_return_momentum_backtest.json`; engine:
`scripts/momentum_selector.py`.

---

## 1. The answer: concentrated cross-sectional MOMENTUM

Of every high-return systematic class tested (concentrated momentum, dual momentum, sector
rotation, trend-following, leveraged trend, quality-momentum), **cross-sectional momentum — hold
the top-N highest 12-1-month-momentum large-caps, rebalance monthly, long-only — is the
strongest, best-evidenced candidate.** It is a Nobel-adjacent, replicated-since-1993 anomaly
(Jegadeesh-Titman), and it was the clear winner on our own 5-year data.

**Our backtest (124 large-caps, 2021-2026, net 10bps/side), cap-compliant top-13:**
24.3% CAGR · 24.7% max DD · Sharpe 1.09 · Deflated Sharpe **0.966 (passes the 0.95 gate)** —
the only strategy in the whole audit to clear that bar.

## 2. …but the honest number is ~half that, with a fat tail

Three corrections the research forced (this is why we test before we deploy):

- **Survivorship bias.** Our 124-name universe is *current* large-caps; delisted losers are
  excluded. Momentum backtests on such universes collapse when delistings are added
  (S&P 100 momentum **26% → 12.2% CAGR**; Nasdaq 100 **46%/-41%DD → 16.4%/-83%DD**). Our 24.3%
  is materially inflated.
- **Academic + live reality.** Peer-reviewed concentrated long-only momentum realistically earns
  **~12-15% CAGR, ~20-27% max drawdown, Sharpe ~0.6-0.9** (Daniel-Moskowitz; Barroso-Santa-Clara).
  Live proof: **MTUM since inception 13.3% vs SPY 12.3%** — the edge is *smoother drawdowns*
  (-34% vs -55%), not dramatically higher return. The concentrated fund QMOM: 11.6% CAGR, 0.85
  Sharpe, -39% DD, and it **lagged in 2025 (+2.4%)**.
- **Momentum crashes.** Long-short momentum crashed **-73% (2009), -91% (1932)**. Long-only
  *avoids the worst* (the crash is a short-leg "losers crash up" effect), but still takes
  **-20% to -30%** in bear-market rebounds, with a fat negative-skew tail.

**Realistic expectation: modestly beat the market (a few CAGR points, mostly via risk-adjusted
return) with occasional -25%+ drawdowns and multi-year stretches of *lagging* a simple index.**
NOT a money-doubler. Anyone quoting 24%+ is selling a survivorship/curve-fit artifact.

## 3. The highest-value risk control (do not skip it)

- **Volatility-targeting** (Barroso-Santa-Clara, peer-reviewed): scale exposure inversely to
  recent realized vol → Sharpe **0.53 → 0.97**, worst month **-79% → -28%**. Single biggest
  data-free improvement.
- **200-day market-trend filter** (in `momentum_selector` as `use_trend`): roughly **halves**
  max drawdown by sitting out the panic-state rebounds that cause crashes. Costs some upside via
  whipsaw. Optional, off by default.
- Both are drawdown-reducers; use at least one before any real capital.

## 4. Timing: right now (mid-2026) is the WORST moment to chase it

The 2024-2026 regime research is emphatic: momentum is **extremely crowded** (SPMO AUM
$300M→$16B), Mag-7 ≈33% of the S&P, semis ≈18% of the index and ≈70% of 2026's gains, SOX +65%
YTD (~65% above its 200-DMA — a level only seen in the 2000 dot-com bubble), equity risk premium
≈0, June-2026 Mag-7 -$2T, July-2 SOX -6%, Burry shorting semis. Verdict: **do not extrapolate
2023-2025 momentum returns forward; the tape is transitioning from clean-trend to whipsaw** —
historically the worst environment for momentum-chasing.

## 5. What is built + WIRED (paper), and the plan

**LIVE ON P1 PAPER (2026-07-04).** The momentum sleeve is now the primary allocator for P1's
**paper** account (owner chose the aggressive 90% setting):
- `scripts/momentum_selector.py` — selection engine (12-1 momentum, top-K, guaranteed ≤8%/name,
  optional 200-day trend gate). `scripts/portfolio_manager.compute_momentum_rebalance_orders` —
  the rebalance engine. `autonomous_runner.run_momentum_sleeve` — wired into `trading-session`
  AFTER the kill-switch/daily-loss/halt guards, so it obeys every hard stop. 19 unit tests.
- **Config (`data/strategy_params.json`) — AUDIT-CORRECTED 2026-07-04:**
  `momentum_sleeve_enabled=true`, `momentum_sleeve_weight=0.90`, `momentum_top_k=13`,
  **`momentum_use_trend=false`** (the trend filter cut CAGR 24%→9% below SPY in our bull —
  it's a drawdown reducer, not a return tool), **`momentum_max_per_sector=4`** (kills the
  ~55%-semiconductor concentration the un-capped version produced). Validated config
  (top-13, no-trend, max-4/sector): **18.3% CAGR / 24.4% DD / Sharpe 0.97 vs SPY 11.6%**.
  Audit also fixed: trend FAIL-SAFE (missing market data → cash, not deploy) and exempted
  momentum positions from the intraday −4% hard-stop / breakeven stops (they're
  monthly-rebalanced, not stop-managed). **No market-crash protection now — a real-money
  version needs volatility-targeting.**
- **Behaviour:** monthly rebalance to the top-13 highest-momentum large-caps at ~6.9%/name (90%
  of equity), rest cash; goes fully to cash when SPY < its 200-day average. It REPLACES the
  passive core while enabled. **Fully reversible:** set `momentum_sleeve_enabled=false` → P1
  reverts to the passive core next session.
- **First rebalance:** fires on the next market-open P1 trading-session (sells the 9 core ETFs,
  buys the 13 momentum names — dry-run verified: 22 orders, 90% deployed, all ≤8%).
- **Dry-run snapshot (2026-07-04):** picks were MU/INTC/AMD/LRCX/AMAT/KLAC/AVGO/ADI (semis) +
  GOOGL/CSCO/CAT/GS/C — i.e. heavily semiconductors, exactly the crowded leadership §4 warns about.

**Plan / guardrails:**
  1. It runs on **paper only** and builds a real track record; measured against `LIVE_READINESS.md`.
  2. It stays **paper** until it passes those gates (OOS Sharpe, ≥50 trades, drawdown control).
  3. Real money only ever as a **satellite ≤10%**, hedged (trend/vol filter), never the whole
     book, never aggressively into a crowded top. The 90% paper setting is to MEASURE the strategy
     cleanly — it is explicitly not a real-money allocation.

**Bottom line:** momentum is the real answer to "highest return," and the engine is ready — but
the truth is a *modest, risk-controlled* edge with real crash risk, deployed on **paper first**
and **not aggressively into today's crowded top**. That honesty is the difference between
investing and gambling.
