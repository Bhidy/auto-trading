# Forensic Audit, Alpha Validation & Remediation — 2026-10-03

**Scope:** P1 Self-Improving Brain, P2 Capitol Shadow, P3 Cautious Sniper (Alpaca paper, $100K each).
**Window:** 2026-05-26/27 → 2026-10-02 close (90 trading days).
**Sources:** broker truth (Alpaca fills, orders, positions and daily equity), point-in-time signals from git history, Actions logs, and simulations on SIP history from 2017 onward.
**Reproducibility:** code, results and provenance are in [`docs/audits/2026-10-03/`](2026-10-03/MANIFEST.json).
**Labelling:** every simulated number is labelled SIMULATION. Everything else is broker-verified.

> **Senior Expert Verdict: NO-GO for real money.** None of the three books has demonstrated an
> investment edge. All three trail SPY. The largest losses came from **defects**, not from markets.
> Those defects are fixed and covered by tests (739 passing). Capital recommendation: **PAPER ONLY**.

---

## Executive summary

| Book | Return | SPY | Excess | β | Up / down capture | Max DD | Sharpe (ann.) |
|---|---|---|---|---|---|---|---|
| P1 | **−2.98%** | +3.74% | **−6.72pp** | 0.48 | 0.37 / 0.54 | −7.80% | −0.77 |
| P2 | +2.04% | +3.08% | −1.04pp | 0.56 | 0.58 / 0.58 | −3.32% | 0.74 |
| P3 | **−2.01%** | +3.08% | **−5.09pp** | 0.56 | 0.63 / 0.78 | −9.15% | −0.37 |
| **All** | **−0.98%** ($297,049) | +3.1–3.7% | ≈ −4.3pp | | | | |

Four findings explain nearly all of it:

1. **P1 has been frozen since 2026-07-07 by a phantom kill switch.** Alpaca returned `equity=$26,060.51` for
   one read; that was the account's cash with every position priced at $0. Eighteen minutes earlier the
   same endpoint returned $92,583.88. The kill switch trusted the single read, computed a "73.94% drawdown",
   and latched a **permanent** halt. For three months:
   - the halt blocked every buy and every monthly rebalance;
   - the monitor's stops kept selling;
   - P1 ended up **63% cash**;
   - no alert ever fired.
2. **Momentum names were stopped out by rules they were exempt from.** Momentum limit orders filled after
   the confirm window. Reconciliation rebuilt those lots *without* `order_class`, so the active-sleeve −4% /
   4-day stops treated them as active trades. AMD, INTC, LRCX, MU, MRK, GS and MS were sold within 1–5 days
   (−$2,116 realized).
3. **P3 orphan exit orders opened an unintended short.** A re-armed GTC stop outlived its position, and on
   2026-08-06 it opened a **14-share DDOG short in a long-only book**. A sign-blind reconciler re-logged
   that short as a long, so it showed `in_sync=true` for two months. V and LLY carried the same orphan
   stops, still live at the time of the audit (LLY 0.3% from its trigger).
4. **No sleeve has a demonstrated edge.** Live point-in-time signal IC is **zero or negative**:
   - P1 composite, 10-day IC −0.12;
   - P3 breakout ≈ 0 (|t| ≤ 1.4);
   - P3 news negative (22% one-day hit rate);
   - P2 copies: median excess −0.4pp, t = 1.0;
   - momentum: true out-of-sample not significant. Its long-run "excess" is survivorship bias
     (equal-weighting the same universe does as well), and the Deflated Sharpe of excess over SPY is
     **0.26** with N = 262 trials.

The dashboard hid all of this. Production served committed data frozen at **2026-07-04**, which showed:
- P1 "+2.8% PASS", "ACTIVE / kill switch armed", 80% ready;
- P3 profit factor 1.74 "Healthy" (truth 0.85).

---

## A. Investment diagnosis — why the portfolios underperformed

**Attribution** (sum of daily decompositions vs SPY; cash earns 4%; selection = invested sleeve vs SPY):

| Book | Avg invested | Selection | Cash / β drag | Trading & execution residual | Total |
|---|---|---|---|---|---|
| P1 | 51% (36–37% from Aug) | −1.78pp | **−2.29pp** | −1.66pp | −5.73pp |
| P2 | 75% | **+0.84pp** | −1.24pp | −0.22pp | −0.62pp |
| P3 | 70% | −1.12pp | −0.52pp | **−2.92pp** | −4.56pp |

- **P1**
  - June: the active multi-factor satellite lost −$6,448. That sleeve is disabled now; its aggressive-growth
    bucket had PF 0.01.
  - July onward: frozen at ~37% invested by the phantom halt.
  - **This is an operational failure, not evidence about the momentum strategy.**
- **P2**
  - Mostly passive ETFs (~69%) plus 25% average cash.
  - Positive selection came from **one May cohort** (9 names, 2 politicians).
  - Since July 2, the copy sleeve lost $396 while the passive sleeve made $700.
- **P3**
  - The trading residual is the stop-loss engine: intraday stops realize losses at the lows, and gaps
    run through them.
  - Entries have no edge.
  - The book captures more of SPY's downside (0.78) than its upside (0.63).

**Benchmark suitability.** SPY (total return) is the right benchmark for all three: each book is a long-only
US large-cap equity mandate. P1 and P3 also held ETFs, bonds and gold at times, which only deepens the
measured lag in a rising market.

## B. Trade diagnosis — why expectancy and profit factor are weak

All figures are broker FIFO round trips. Expectancy ≈ P(win)·AvgWin − P(loss)·AvgLoss.

| Book | n | Win % | Avg win | Avg loss | Payoff | PF | E / trade | Break-even win % |
|---|---|---|---|---|---|---|---|---|
| P1 | 92 | 36% | 1.69% | 3.41% | 0.51 | **0.29** | **−1.58%** | 66% |
| P2 | 13 | 46% | 21.4% | 6.6% | 2.19 | 1.88 | +6.36% | 31% |
| P3 | 74 | 30% | 10.8% | 6.0% | 1.79 | **0.85** | **−1.03%** | 36% |

- **P1:** losers ran to −3.4% while winners were cut at +1.7%. The −4% / 4-day stops were then applied to
  momentum lots in error: 7 trades, −$2,116, average −9.3% on the max-loss exits.
- **P3:**
  - 40 of 74 exits (54%) were stop-losses, averaging −6.75% and totalling −$19.2K. Thirteen take-profits
    averaged +11.6% (+$11.9K).
  - **The July "exit restructure" (wider stops) made things worse live, not better:**

    | P3 entries | n | Win % | PF | P&L |
    |---|---|---|---|---|
    | Before 07-06 | 39 | 36% | 1.02 | +$250 |
    | After | 35 | **23%** | **0.64** | **−$3,461** |

    The backtest had promised a 60–66% win rate. Wider stops cannot rescue a zero-IC entry; they just
    make each loss larger.
  - One late-filled lot (MU) was reconstructed **without a stop** and rode to **−23.8%**.
- **P2:** a positive PF on 13 trades is not statistically meaningful (median excess −0.4pp).
  - Its age bug **dumped PG two seconds after buying it**: an unfilled May order made a September re-copy
    look 116 days old.
  - Off-spec PANW trailing stop: −13.3%, where a 63-day hold would have been ≈ +5%.

**Other metric reconciliations.** The dashboard's 0.24 and 0.21 profit factors were not the same metric:
- 0.24 is a P1 dollar-PF on the trade log frozen on 07-04 (61 trades);
- 0.21 is a %-weighted P1-only figure labelled "All".

The truth is P1 0.29, P2 1.88, P3 0.85.

## C. Bugs found (defect register)

| ID | Sev | Defect | Evidence | Status |
|---|---|---|---|---|
| C1 | **Critical** | Kill switch latched a permanent halt on one unvalidated equity read | Actions log 2026-07-07T14:24:45Z `equity=$26,060.51` vs $92,583.88 at 14:06; commit cadcf71d | **Fixed** — `shared/equity_guard.py`; every halt/liquidation re-values the book from market data first; halt records its evidence. *Latched halt NOT cleared (owner decision).* |
| C2 | **Critical** | The same single read could liquidate P3 (5% daily-loss) and the P1 monitor book | event_driven_bot.py kill switch; autonomous_runner.py monitor | **Fixed** (same guard, confirm-before-act) |
| C3 | **Critical** | P3 re-arm placed GTC stops on positions mid-exit → orphans → unintended short | DDOG fills 07-22 → short 08-06; V/LLY orphans live | **Fixed** — re-arm excludes any symbol with an open sell or closed this run; `shared/order_hygiene.py` cancels orphans and flattens shorts every P2/P3 session. *Live V/LLY orders: see J.* |
| C4 | **Critical** | Reconciler sign-blind (`abs(qty)`): DDOG −14 re-logged as a +14 long, `in_sync` for 2 months | reconcile.py `_num`; commit b4467743 | **Fixed** — signed, side-aware; new `short_positions` field |
| C5 | **Critical** | Late fills reconciled without sleeve tag → momentum lots stopped as "active"; P3 MU unprotected −23.8% | trade_log reconcile_reason `unlogged_position`, order_class None | **Fixed** — sleeve recovered from broker `client_order_id` prefix; provenance-aware exemptions; MPC lot re-tagged with evidence |
| C6 | **Critical** | Dashboard served 07-04 data for 91 days; readiness showed P1 +2.8% PASS / 80% / ACTIVE; P3 PF 1.74 from *unrealized* P&L; hardcoded `sharpePass:true` | smoke-test.yml deploys on code paths only | **Fix implemented** (see I) |
| H1 | High | No alert on a halted book or a short in a long-only book | heartbeat.py | **Fixed** — `assess_safety_state`, re-alerts daily |
| H2 | High | P2 kill switch skipped its own stop-losses and politician-SELL copies | politician_bot.py run_monitor / run_scan_and_trade | **Fixed** — exits never gated; new buys blocked |
| H3 | High | P2 position age used closed/unfilled lots → instant "time exit" on re-copy | PG 09-21 14:25:07 buy → 14:25:09 sell | **Fixed** — `position_age_days` (open, filled lots only) |
| H4 | High | Momentum rebalance and P2 sleeve trims used `abs(market_value)` → a "trim" grows a short | portfolio_manager / politician_bot | **Fixed** — long-only engines, sells clamped to held qty |
| H5 | High | Weekly-loss limit never enforced (momentum/core bypass; P2/P3 none) | controls audit | **Open** |
| H6 | High | Exit orders lack `client_order_id`; guardian / monitor / trading in different concurrency groups → double-exit possible | controls audit | **P1 fixed** (`p1stop`/`p1tp` deterministic ids; long-only guard). P2 exits still open (mitigated by hygiene sweep) |
| H7 | High | P1 cap trims sell from a stale positions read | autonomous_runner.py | **Fixed** — fresh re-read, qty clamped to held |
| H8 | High | P2 feed: Capitol Trades dead in 126/126 scans; no Senate source; Guardian scans from a stale checkout; conformance hardcoded `true` | P2 forensics | **Open** |
| H9 | High | P3 technicals refresh only at the Monday screen (frozen 4/5 days; 08-31 screen reused for 9 sessions) | signal IC forensics | **Open** |
| H10 | High | No strategy-level quarantine switch for any book | controls audit | **Fixed** — `config/strategy_controls.json` (human-owned, fail-closed, entries only) |
| M1 | Med | Supabase equity history: only 11–16 of ~91 days within $5 of broker close; rows on holidays; 08-27 missing | dashboard audit | Open |
| M2 | Med | Kill-switch base is fixed $100K (not high-water mark); P3 has no drawdown kill switch | controls audit | Open |
| M3 | Med | P1 liquidation runs `close_all` before `cancel_all`; 207 partial failures ignored | controls audit | Open |
| M4 | Med | Momentum sleeve runs before preflight / risk officer / trade cap | controls audit | Open |
| M5 | Med | Two contradictory betas on one page (regression 0.48 vs sector-table 1.05) | dashboard audit | Fix implemented |
| M6 | Med | P2 trade log: duplicate rows per order, 16 `pending_new` rows, limit-not-fill exit prices | P2 forensics | Open |
| L1 | Low | Stale `gross_exposure_pct: 86.26` in P1 state (true 37.5%); nothing writes it any more | portfolio_state.json | Open |
| L2 | Low | No abnormal-price band; `_quote_is_fresh` fails open | controls audit | Open |

## D. Strategies tested (every meaningful candidate, not just the winner)

| # | Candidate | Test | Result |
|---|---|---|---|
| 1 | P1 multi-factor composite | Live point-in-time IC, 89 days | IC +0.01 / −0.07 / −0.12 / −0.11 at 1/5/10/21d; quintiles **inverted**. No edge. |
| 2 | P1 factors (trend, momentum, RS, RSI, MACD, BB, volume, regime) | Per-factor IC | Trend/momentum/RS = one triple-counted 1–3-month bet with negative IC. RSI small positive (n.s.). MACD/BB/volume ≈ 0. Regime has no cross-sectional effect and its timing leaned wrong (n.s.). |
| 3 | P1 SHORT signals | Forward excess | Shorted names beat SPY by +7.1% over 10d (≈3 independent bets). Wrong-way. |
| 4 | P3 breakout score + components | 18 weekly screens | Score IC ≈ 0. BB-breakout +0.08 (t 2.3) is the only positive component; the RSI rule is negative (t −2.2). |
| 5 | P3 news catalysts | 33 events | −0.77% at 1d (t −1.8), 22% hit rate. |
| 6 | P3 exit restructure (2.5 / 5.0 ATR) | Live vs backtest | Backtest win 60–66% → live 23%. **Backtest/live divergence.** |
| 7 | P2 copy sleeve (live) | 15 copies vs SPY | Mean +3.5pp but median −0.4pp, t 1.0; one cohort. |
| 8 | P2 copy (backtest, 63d hold) | Repo backtest re-read | 2024–26 alpha ≈ +0.08%; 2026 −0.70% (t −0.37). |
| 9 | Momentum frozen spec (top-13, 12-1, max4/sector, vol 0.25, 90%) | True OOS 07-06 → 10-02 | +5.87% vs SPY +3.00%, P(active>0) 0.67; **ex-MPC/PSX −1.48%**. 13/13 parity with the live book. |
| 10 | Momentum 180-config surface (k, lookback, sector cap, vol target) | SIP 2017–2026, 5 bps | All beat SPY (survivorship). Only 34/180 beat the equal-weight universe's Sharpe. Deployed config at the 20–30th percentile. |
| 11 | Vol targeting (0.20 / 0.25 / none) | Same | Costs ~3.2pp/yr; drawdown unchanged (−30.2%); missed the April 2020 rebound. |
| 12 | SPY 200-day trend filter | Same | 8.0% CAGR vs 14.8% (−6.8pp/yr). |
| 13 | Baselines: SPY, RSP, EW universe, 60/40, 80/20 core-satellite, raw top-13 | Same | See G. |

## E. Anti-overfitting results

- **True out-of-sample.**
  - Momentum since the freeze: not significant (IR 0.88 over 64 days; driven by two refiners).
  - P3 exit restructure: failed out of sample.
  - The live signal ICs above are, by construction, out of sample.
- **Walk-forward / held-out window.**
  - 2017-03 → 2021-06, a period the 2026 spec search never saw: excess +1.45pp/yr, IR 0.15.
  - The search window itself: +4.9pp/yr, IR 0.41. Decay is consistent with selection bias.
- **Multiple testing (N = 262).**
  - Excess-over-SPY Deflated Sharpe **0.26** (fails the 0.95 bar). Even against zero it is 0.82.
  - Raw Deflated Sharpe 0.984 passes, but that only proves *owning equities*, not an edge.
  - PBO 0.20 (raw) / 0.09 (excess).
- **Parameter stability.** The surface is broad but the deployed point is mediocre. Smaller k gives more
  CAGR at the same Sharpe. No isolated peak, so not curve-fit — **it just isn't better than equal weight**.
- **Stress tests.**

  | Shock | Result |
  |---|---|
  | 2× / 4× costs | −0.4 / −1.1pp |
  | 1-day delay | −0.4pp |
  | Remove best 5 names (43% of P&L) | excess **−0.6pp**, IR −0.01 |
  | Best 5 months → cash | CAGR 11.6% (below SPY) |

  Yearly excess vs SPY ranges from −17.4 to +25.5pp; it lagged SPY in 5 of 10 years.
- **Survivorship.** Equal-weighting today's 115 large-caps beats RSP by **+7.4pp/yr**. That is roughly the
  whole momentum "edge". **Honest expected momentum excess: ≈ 0 (range −4 to +1pp/yr).**

## F. Best robust candidate architecture

*Recommended, not deployed.* It is "best" because it removes measured, controllable losses (cash drag,
stop churn, turnover), not because of a higher backtest return.

| Layer | Design | Evidence |
|---|---|---|
| **Core (80–90%)** | Broad US equity index exposure, fully invested, β ≈ 1, threshold rebalancing, no discretionary regime de-risking | SPY beat every book. The trend filter cost 6.8pp/yr. Regime timing had no positive value. Cash drag was −0.5 to −2.3pp in 90 days. |
| **Research satellites (≤ 10–20% total)** | Momentum at the **frozen** spec (no retuning; measured forward against pre-registered gates); P2 copy ≤ 10%; P3 **quarantined** until a new pre-registered hypothesis shows positive out-of-sample IC | D1–D12 |
| **Exits** | Core: none (rebalance only). Monthly sleeves: schedule-managed, **never intraday-stopped**. Hard caps and kill switches only. | P3 stop residual −2.92pp; P1 July misapplied stops |
| **Sizing** | Equal weight within a satellite; hard caps unchanged. Vol-targeting proposed **off** for the next spec version — a hypothesis, not a mid-test change. | Vol-target cost 3.2pp/yr with no DD benefit |
| **Execution** | Marketable limits; deterministic `client_order_id` on *every* order including exits (H6) | Controls audit |
| **Controls** | Two-source equity confirmation; exits never gated; long-only invariants enforced; human quarantine switch; heartbeat safety alerts | C1–C5, H1–H2, H10 |

**Constraint for the owner.** The immutable hard limit is 12% per ETF. A one-ticker index core is therefore
impossible, and spreading the S&P 500 across several tickers would evade the limit's intent. A real
benchmark core needs either a diversified multi-ETF equity core within 12% caps, or a **human-approved**
index-ETF exception to the cap. This code will never make that change.

## G. Current vs new vs benchmark (identical data and costs)

**Live paper, 90 days:** current system −0.98% vs SPY +3.1–3.7%.

**SIMULATION, 2017-03 → 2026-10, 5 bps:**

| Strategy | CAGR | Sharpe | Max DD | Excess vs SPY |
|---|---|---|---|---|
| SPY buy & hold (benchmark) | 14.8% | 0.86 | −33.8% | 0 |
| **80% SPY + 20% momentum (candidate shape)** | 16.6%* | 0.92* | −33.7% | +1.8pp* |
| Deployed momentum spec (current P1 config) | 18.2%* | 0.91 | −30.2% | +3.4pp* |
| Equal-weight same universe (no signal) | 18.3%* | 1.04 | −34.0% | +3.6pp* |
| RSP | 11.0% | 0.66 | −39.1% | −3.8pp |
| SPY 200-day trend filter | 8.0% | 0.67 | −25.1% | −6.8pp |
| 60/40 SPY/AGG | 9.6% | 0.87 | −21.7% | −5.2pp |

\* Inflated by about +7.4pp/yr of survivorship bias on the stock component.

P1's multi-factor engine and P3 cannot be backtested on this window without their full data pipelines. They
are judged on live out-of-sample IC instead (D1–D6).

## H. Failure conditions

| Component | When it struggles |
|---|---|
| Core | Full-β bear markets (−34% in 2020-style drawdowns) — it carries the market's drawdown by design |
| Momentum | Sharp reversals and momentum crashes (July 2026 −3.0% vs SPY −0.3%); sector concentration (the 2026 gain = refiners); monthly rebalancing cannot react to a 23-day crash |
| P2 | Feed outages, disclosure lag, Senate blind spot |
| All | Bad broker reads (now guarded), concurrent workflows (partly open, H6), stale dashboards (fixed) |

## I. Implemented fixes (files)

| File | Change |
|---|---|
| `shared/equity_guard.py` (new) | Two-source equity confirmation; plausibility screen + confirm-before-act; unpriceable-name fallback |
| `shared/order_hygiene.py` (new) | Orphan exit-order sweep + long-only short flatten |
| `shared/strategy_controls.py`, `config/strategy_controls.json` (new) | Human quarantine switch per book (fail-closed, entries only) |
| `shared/reconcile.py` | Signed / side-aware quantities; `short_positions`; `order_classes_from_orders`; sleeve-stamped reconstructed lots |
| `scripts/autonomous_runner.py` | Kill switch / monitor / daily-loss confirm-before-act; halt evidence; sleeve attribution in reconciliation; P1 quarantine gate; idempotent long-only stop/TP exits; fresh-clamped cap trims |
| `scripts/portfolio_manager.py` | `is_schedule_managed` (provenance-aware stop exemption); long-only momentum rebalance with sell clamp |
| `scripts/heartbeat.py` | `assess_safety_state` — daily alert for halted books and shorts in long-only books |
| `event-driven-bot/scripts/event_driven_bot.py` | Corroborated kill switch; re-arm excludes mid-exit symbols; hygiene at session and monitor start; quarantine gate |
| `political-copy-bot/scripts/politician_bot.py` | Exits never gated by the kill switch; `position_age_days`; long-only sleeve trims; quarantine / kill gate on buys; hygiene; cancel / close client methods |
| `data/trade_log.json` (+ dashboard copy) | MPC open lot re-tagged `momentum_sleeve`, with broker evidence recorded on the record |
| `tests/test_audit_2026_10_controls.py` (new) | 30 incident-reproduction tests (real numbers: $26,060.51 read, DDOG/V/LLY, PG 2-second hold, July late fills) |
| Dashboard (`dashboard/server.js`, `public/*`, `smoke-test.yml`) | Daily post-EOD redeploy + `data_as_of`; broker-FIFO trade-stats endpoint; inception-based readiness with hard veto gates; regression beta only; SPY total return |

**Regression:** full suite **739 passed**; ruff clean.

## J. Remaining risks and unresolved uncertainty

1. **P1 is still halted.** Clearing a phantom halt is safe in itself. What it does next, though, depends on
   the P1 configuration: the frozen momentum spec would deploy about 83% on Monday. That is an owner decision.
2. **Live orphan stops V (3.9% away) and LLY (0.3% away)** fire before the fix's first run (P3 09:50 ET
   Monday), unless they are cancelled before the 09:30 open. The DDOG −14 short (−$640) is flattened by that
   same 09:50 run.
3. Open defects H5, H6 (P2), H8, H9 and M1–M4, M6 (above).
4. **Sample size.** 90 days ≈ one market episode. "No edge" is a measured absence of evidence, not proof that
   momentum or copy trading can never work.
5. Price data is IEX/SIP from Alpaca, with known corporate-action errors corrected by hand. Whether the paper
   account credits dividends: **not verified**.

## K. Capital deployment recommendation

| Component | Classification |
|---|---|
| P1 multi-factor engine | **RESEARCH ONLY** (disabled; negative IC) |
| P1 momentum sleeve | **PAPER ONLY** (research sleeve; no demonstrated excess) |
| P2 copy sleeve | **PAPER ONLY** (≤10%; no demonstrated edge; pipeline barely alive) |
| P3 | **RESEARCH ONLY** — quarantine new entries recommended (zero-IC entries, PF 0.64 post-restructure) |
| Passive benchmark core | **Shadow-live candidate** only after ≥10 consecutive clean trading days on today's fixes and verified dashboard numbers. The 2026-07-04 ops sign-off is void: the phantom halt invalidated P1's paper track. |
| **System overall** | **PAPER ONLY — No-Go for real money** |

Nothing here promotes any capital automatically. Real-money eligibility is a human decision after
`docs/LIVE_READINESS.md` gates pass.
