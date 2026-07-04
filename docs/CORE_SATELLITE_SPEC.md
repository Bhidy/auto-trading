# Strategy Spec — Core-Satellite (the recommended architecture)

**Drafted 2026-07-04 · Owner: Senior Chief Quant · Status: the committee's recommended target state.**

This is the answer to "what is the best strategy — one of the three, or a new one?"
**Neither a single existing bot nor a new engine. The best strategy is the core-satellite
architecture the system already began adopting on 2026-06-18, built out properly.** The
evidence — the repo's own studies *and* the external literature — converges here.

---

## 1. The thesis in one paragraph

After costs, at $100k retail scale with daily rebalancing and no HFT, **unproven active
signals lose to the index** (Lesmond; Novy-Marx & Velikov; the repo's own 48-candidate
walk-forward search, all rejected). What survives is a **low-turnover, regime-aware passive
core** carrying the market's beta, with **small, hard-capped satellites** that are only funded
while they *demonstrably* earn out-of-sample edge over buy-and-hold. Grow a satellite when it
earns its keep; starve it when it doesn't. Realistic whole-program target after costs:
**net Sharpe 0.8–1.5.** Anything promising more is overfit.

## 2. Allocation

| Sleeve | Target weight | Contents | Status | Gate to fund/grow |
|---|---|---|---|---|
| **Passive core** | **80–90%** | SPY, QQQ, IWM, DIA (equity) + TLT, GLD, SHY, BIL (defensive), regime-tilted | **LIVE (paper), fix shipped** | Always on; it is beta |
| **+ Momentum factor** | within the core | Add **MTUM** (or equiv.) as a core basket member | Proposed | 0.15% ER; 2026's best factor (see §4) |
| **Satellite 1 — P2 copies** | **≤10%** | Congressional copy sleeve | Paper, engine fixed (D3/D7/D10) | ≥30 post-fix round trips, positive alpha vs SPY at t≥2 |
| **Satellite 2 — P3 breakout** | **≤10%** | Event-driven fundamental+breakout | Paper, plumbing fixed (D6) + exits to restructure | PF ≥1.1 over ≥30 more round trips |
| **P1 active satellite** | **0% until proven** | Multifactor scorer | **Disabled** | A candidate that beats the buy-and-hold challenger OOS (48 tries have not) |

Core + satellites are hard-capped so that even if both satellites went to zero, the program
still holds the market. The satellites are option-like: small premium, capped downside,
convex upside if an edge is real.

## 3. The core, done properly (what changed)

- **Regime tilt by class (shipped, D8).** The core no longer applies one multiplier to all 8
  ETFs — it splits equity vs defensive and tilts each by the regime table
  (`core_class_targets`). A BULL tape now holds ~17% defensive (near the 20% target), not the
  ~45% the old uniform allocator produced; bear regimes raise both the defensive share and the
  cash reserve. Hard 12% ETF cap never breached.
- **Honest bucket attribution (shipped, D9).** Defensive core ETFs are logged as `defensive`,
  not `core_equity`, so by-bucket learning stats are truthful.
- **Rebalance cadence:** the existing 5% drift band + daily EOD is right for a low-turnover
  core — do not increase turnover (costs are the enemy here).

## 4. A momentum-factor ETF in the core — VALIDATED MARGINAL, DEFERRED

External evidence (mid-2026): momentum was the **best-performing factor** of the cycle
(MTUM beating the S&P; JPM Factor Views), and the implementable version for a $100k book is
the **factor ETF, not a homegrown scorer** (MTUM, 0.15% ER, no DIY turnover). So we tested it.

**Validation (`data/mtum_core_inclusion_study.json`, 2021-06→2026-06, net of 10bps/side):**
adding MTUM to the equity core (SPY/QQQ/IWM/DIA) moved Sharpe 0.637 → **0.674 (+0.037)**,
Sortino 0.919 → 0.971, total return 63.9% → 70.0% — but **max drawdown +0.9pp**, and MTUM
standalone carries a **32.7% max drawdown** vs SPY's 25.4% (the momentum-crash tail).

**Committee decision: DEFER — do not add to the live basket yet.** The Sharpe gain is within
noise, it *adds* drawdown, the 2021–2026 window was momentum-favorable, and JPM flags the
**widest momentum dispersion since 1990** (a documented crash precursor). This is a weak
improvement against a live tail — capital-preservation discipline says prefer no change.
Re-test on a bear-inclusive window (or once dispersion normalizes) before adopting; if adopted,
it enters the **equity** class under the same 12% cap, and the regime tilt already trims it in a
downturn. Same honest "beats-baseline-but-not-enough" outcome as the 48 rejected P1 candidates —
the gate, not hope, decides.

## 5. The satellites, with their kill triggers

- **P2 copies (≤10%):** now sources disclosures from the official House Clerk index when the
  Capitol Trades feed is dark (D3), holds to the ~63-trading-day alpha-capture horizon instead
  of the edge-destroying 25% take-profit (D7), and only admits fresh (≤30d) disclosures (D10).
  **Legislative kill trigger:** H.R. 7008 / H.R. 1908 (2026 congressional trading bans) advanced
  this year — if either passes, wind P2 down; the signal source is being legislated away.
- **P3 breakout (≤10%):** gross/tranche/min-notional caps now enforced (D6) and the cooldown no
  longer blocks profitable single-stop recoveries (D11). **Open work before growth:** restructure
  the 1.5-ATR stop (too tight — 63% stop-out rate; widen to 2.5–3×ATR with proportionally halved
  size, or enter on pullback-to-breakout) and re-measure over ≥30 round trips. Fold into the core
  if PF stays <1.1.
- **P1 active satellite:** stays off. Re-enable only via the existing walk-forward gate with a
  candidate whose OOS Sharpe beats the buy-and-hold challenger (0.93) across ≥9 windows, PBO≈0,
  net of 5bps friction.

## 6. Risk budget & non-negotiables

- Hardcoded risk limits in `config/risk_limits.json` are never relaxed; every satellite sizes
  *inside* them. New risk math (regime tilt, caps) is advisory within the hard caps.
- No Claude/LLM in the autonomous loop — the committee advises a human; it is not a runtime
  dependency (`feedback_cloud_only_no_claude_pc`).
- Live capital only per `LIVE_CORE_RAMP.md` (core, fractional, separate account) and
  `LIVE_READINESS.md` (satellites, individually, earliest ~Q4 2026).

## 7. What "done" looks like

A single $300k program reorganized as **one regime-tilted passive core (with a momentum-factor
sleeve) carrying the market, plus two capped, individually-gated satellites that are grown only
on demonstrated OOS edge** — measured honestly, because the trade logs now tell the truth
(D2/D4/D5). That is the institutional answer: disciplined beta, small convex bets, and the
humility to let the walk-forward gate — not hope — decide what gets capital.
