# Tri-Portfolio Institutional Audit & Investment-Committee Review
**Date:** 2026-07-04 · **Auditor:** Senior Chief Quant (institutional-audit-qa + investment-committee skills)
**Scope:** P1 Self-Improving Brain, P2 Capitol Shadow, P3 Cautious Sniper — performance accuracy, strategy effectiveness, live-capital readiness, strategy recommendation.
**Evidence chain verified:** live Alpaca accounts (all 3), committed trade logs/journals, GitHub Actions history, Vercel production API, repo backtest artifacts, external research (academic + market data as of July 2026). Dashboard equity reconciles to Alpaca **to the cent** for all three portfolios.

---

## 1. Executive Summary

Over ~27 trading days (2026-05-27 → 2026-07-03), the $300K paper program is at **$295,922 (-1.36%)** against a flat market (SPY -0.75%). The **engineering layer is genuinely institutional-grade** (all 14 workflows green, idempotent orders, honest walk-forward gates that correctly rejected every optimization candidate that couldn't beat buy-and-hold, dashboard reconciled to the cent). The **strategy layer has no validated edge anywhere** — the system's own June-18 research proved passive SPY/QQQ dominates every active sleeve, and this audit confirms it with live forensics. The books are protected today (P1 in core-only risk-off; P2/P3 capped), but **three of the program's alpha engines are broken or dark**, and **two of three committed trade logs are materially wrong**, which poisons self-evaluation.

| | P1 Self-Improving Brain | P2 Capitol Shadow | P3 Cautious Sniper |
|---|---|---|---|
| Equity (2026-07-04) | $94,336 | $101,735 | $99,851 |
| Return since inception | **-5.66%** | **+1.74%** | -0.15% |
| vs SPY (-0.75%) | -4.9pp | +2.5pp | +0.6pp |
| Sharpe (27d ann.) | -3.52 | +1.55 | +0.02 |
| Max drawdown | -6.72% | -2.59% | -5.89% (peaked +6.05% on 6/15) |
| Win rate (closed, broker truth) | 32.8% (61 closes) | ~6 round trips (n too small) | 33.3% (30 round trips) |
| Profit factor | **0.24** | n/a (sample) | 0.98 |
| Current state | Passive 8-ETF core, active entries DISABLED | ETF beta sleeve + **dead copy feed since 5/29** | 54% cash after stop cascade; news tranche NEVER traded |

**Overall risk rating:** HIGH (strategy layer) / LOW (engineering layer) / HIGH (data-integrity of P2+P3 logs).
**Release decision (live capital): NO-GO** — details in §6.

---

## 2. What actually happened (root causes, evidence-backed)

### P1 — Self-Improving Brain (-5.66%)
- **~75% of the loss = bad signals.** The multifactor engine issued its highest-conviction scores (0.75–0.86) at the late-May top and kept buying into the June 4–10 selloff (SPY -4.2%). Aggressive-growth bucket: **-$3,994 across 23 trades at 26% win rate** (GOOGL 0-for-5 → -$1,163). SPY-only regime detection never downgraded fast enough.
- **~20% = exit asymmetry.** Winners cut at +1.41% avg (50% partial take-profit) while losers rode 4–15 days to -5…-10.8% on wide 2.5-ATR trailing stops. Win/loss ratio 0.42. Holds ≥4 days produced 94% of losses; whipsaw (0–1d) lost only $131 — the problem was slow exits, not tight stops.
- **Self-learning did NOT cause it — it reacted late but correctly.** All 60 gated loosening attempts were refused (fails closed); the 10 actual knob changes (6/17–18) were all risk-*decreasing* (threshold 0.50→0.70, sizing to 0.5 floor). Kill switch/halts never breached (worst day -2.84% < 4%).
- **June 18 pivot (committee-approved):** `active_entries_enabled=false`, `core_weight=1.0`, passive 8-ETF basket. Since then P1 tracks the market (-1.41% vs SPY -0.25%, mostly residual satellite wind-down). Its own 5y study: active-only OOS Sharpe **-1.11**, passive core **+1.08**.
- Churn was free on paper ($10.45 fees) but the same 8.4×/month turnover would cost ~$420/month live at the 5bps floor.

### P2 — Capitol Shadow (+1.74%, but the headline is misleading)
- **By capital it is 95.6% passive** (68.1% designed ETF beta sleeve + 27.5% cash); only 4.4% is politician copies. **By P&L the tiny copy sleeve produced ~81% of all profit** (≈+$1,214 vs +$281 from the $69K ETF sleeve). Sharpe 1.55 is beta + good sector rotation, not copy alpha.
- **The copy engine has been dead since 2026-05-29.** Capitol Trades feed fails 14/14 fetches every run; `strategy_conformance.json` has said `FEED DARK` daily since 6/18 with no operator action. All 13 copies ever made date from 5/27–5/29. 4 of 13 (29%) never filled (0.15% limit offset, no re-peg).
- **The live exit rules amputate the measured edge.** Repo backtest (1,492 clean copy events): 63-day hold alpha **+1.64%/event (t=3.76)**; P2's deployed 25%-TP+trailing-stop rules: **+0.11% (t=0.41)**. The 6/18 loss-reducers (15% stop, 252d hold, conviction cap 1.0) shipped, but the time-exit fix did not.
- **External evidence is against the thesis:** peer-reviewed research (Eggers-Hainmueller 2013; NBER w26975; Karadas 2019) finds congressional alpha vanished after the 2012 STOCK Act; real average disclosure lag ~49 days; NANC's ETF outperformance is explainable as a mega-cap-tech tilt (~45% tech) that went flat in 2026. **Regulatory tail risk:** H.R. 7008 (ban new purchases) and H.R. 1908 (full divestiture) both advanced in 2026 — the signal source may be legislated away.
- **Data integrity:** the 6/18 reconciler wrote sign-flipped/duplicated realized-P&L rows (TER's ~+$662 winner logged as negative). P2's committed trade-log P&L is not trustworthy.

### P3 — Cautious Sniper (-0.15%, peaked +6.05%)
- **Primary cause: stops eating winners.** 19 of 30 exits (63%) died at the 1.5-ATR stop for **-$9,955**; 7 take-profits earned +$7,950. Win rate 33.3% vs 33.7% breakeven for the bracket geometry — structurally a coin-flip machine. Proof stops were inside noise: MPC stopped 6/18 (-$766) → re-bought same day → TP 7/2 (+$1,573); MU stopped 6/5 (-$1,232) → re-bought 6/8 → TP 6/15 (+$2,719). Entries buy upper-Bollinger extension (one at RSI 88); pre-6/18 sizing let single names reach 16.8% of equity (MRVL/FCX/MS/MU lost ~$6.6K).
- **CRITICAL BUG: the 20% news/event tranche has never traded.** `event_driven_bot.py:571-572` throws `AttributeError` on every news-signal execution (iterates a dict as a list); `p3-trading.yml:118` masks it with `|| true` so all runs show green. The strategy's headline differentiator is untested by construction.
- **CRITICAL DATA BUG: trade log shows -$6,183 realized; broker truth is -$187.** 18 of 30 closes have `pnl: null` (orphan-reconciled) — mostly winners (PANW +$1,787, MU +$1,487, CSCO +$855, MS +$1,820 across two). Log-implied win rate 8.3% vs real 33.3%. Anything reading the log misjudges P3 by ~$6K.
- **Dead risk config:** `max_gross_exposure_pct: 80` is never read — book hit 99.5% deployed on 6/22. Tranches (60/20/20) exist only as per-trade caps. The blanket 10-day re-entry cooldown (shipped 6/18) now blocks exactly the re-entries that made money.
- 54% cash is a ~10-day artifact (stop cascade + cooldowns + "already hold" skips), not a halt. The 9 open orders are healthy GTC bracket TP legs (stop legs `held`), not orphans.
- 5y backtest: 17 trades, 82% one name (INTC), DSR 0.60 < 0.95 — no validated edge.

---

## 3. Defect register (by severity)

| # | Sev | Portfolio | Defect | Evidence | Fix |
|---|---|---|---|---|---|
| D1 | **Critical** | P3 | News tranche crashes on every execution; masked by `\|\| true` | `event_driven_bot.py:571-572`; `p3-trading.yml:118`; 0 news trades ever despite ≥6 signal days | Iterate `watchlist["universe"]`; attach `atr` in `scan_news()`; remove `\|\| true`; regression test |
| D2 | **Critical** | P3 | Trade-log realized P&L wrong by ~$6K (18/30 nulls); win rate reads 8.3% vs real 33.3% | FIFO recompute vs Alpaca fills | Populate exit fields from broker bracket legs at EOD; backfill 18 nulls from `/v2/orders` |
| D3 | **Critical** | P2 | Disclosure feed dark since 5/29; `FEED DARK 14/14` daily, unactioned | `strategy_conformance.json` git history 6/18→7/2 | Diagnose in Actions logs (npm vs 429), pin/vendor MCP, fallback to in-repo House PTR PDF parser; escalate FEED DARK to GitHub issue |
| D4 | **High** | P2 | Reconciler wrote sign-flipped/duplicated realized P&L (TER +$662 logged negative) | trade_log vs fills reconstruction | Fix reconciler sign logic; rebuild P2 realized P&L from broker |
| D5 | **High** | P1+P3 | `exit_reason` never logged (59/61 and 30/30 closes = None) | `performance_tracker.py:91` has no reason param; 4 callers in `autonomous_runner.py` | Add reason param; pass stop/TP/rotation/reconcile |
| D6 | **High** | P3 | `max_gross_exposure_pct` dead config; tranches not cumulative; no min notional (dust: UNH 1sh, EMR 2sh) | 99.5% deployed 6/22; `event_driven_bot.py:588-628` | Cumulative tranche accounting; wire the cap; ~$2K notional floor |
| D7 | **High** | P2 | Live exits destroy measured alpha (t=3.76 @63d hold → t=0.41 live) | `p2_congress_copy_backtest.json` | Replace 25% TP with ~63-trading-day time exit; keep trailing stop as disaster brake |
| D8 | **Medium** | P1 | Passive core ignores regime: 45% defensive in BULL vs 20% target (uniform `eq_mult`, `portfolio_manager.py:164`) | positions + regime BULL 7/2 | Per-class regime tilt using existing `regime_allocation_modifier` |
| D9 | **Medium** | P1 | Passive-core defensive ETFs logged as `bucket:"core_equity"` — poisons future by-bucket learning | trade #79, $85.7K open cost | Correct bucket attribution |
| D10 | **Medium** | P2 | Stale-window filter admits negative-alpha 31–45d disclosures; tech-confirmation gate halves sample and lowers alpha (t 3.27→1.92) | backtest artifacts | `max_transaction_age_days` 45→30; make tech gate advisory |
| D11 | **Medium** | P3 | Blanket 10-day cooldown blocks the profitable re-entries (MU/MPC pattern) | trade forensics | Cooldown only after ≥2 consecutive stops, or allow re-entry on reclaim |
| D12 | **Low** | P2 | 29% of copy orders never filled (0.15% offset, no re-peg) | 4/13 unfilled | Re-peg or marketable limits for copies |

**Not verified:** exact cause of P2 feed failures (needs Actions stderr); whether P3 news signals carry any edge (never deployed); P2 per-skip filter attribution; intraday DD precision; dividend contributions; Supabase row-level contents (verified only via dashboard API + green market-data workflow).

---

## 4. Investment-committee verdicts (per portfolio)

### P1 — Self-Improving Brain
- **action:** HOLD (keep core-only mode) · **confidence:** 88
- **decision summary:** The passive-core wind-down was the right call and is working (tracks market since 6/18). The active multifactor satellite is measured at PF 0.24 live and OOS Sharpe -1.11 in its own 5y study — it must stay disabled until D5/D8/D9 ship and a candidate passes the walk-forward gate *including* the buy-and-hold challenger.
- **challenger review:** "Re-enable the satellite — the sample is only 61 trades in one regime." True, but the burden of proof is on the strategy; the gate exists precisely for this. NO new active entries.
- **what would change my mind:** a candidate with OOS Sharpe > challenger (0.93) across ≥9 windows, PBO near 0, after 5bps friction.

### P2 — Capitol Shadow
- **action:** REDUCE (beta sleeve) / FIX-THEN-WATCH (copy sleeve) · **confidence:** 80
- **decision summary:** Today P2 is a closet index fund with a dead alpha engine. The copy sleeve is the only live sleeve in the program showing green shoots (+81% of P2's P&L on 4.4% of capital, and the repo's own 1,492-event backtest shows t=3.76 at 63d holds in the 15–30d lag bucket) — but academic post-2012 evidence is null, the edge is 2020/2022-concentrated, and Congress may ban the signal source. Restore the feed (D3), fix exits (D7), tighten lag window (D10), then require **≥30 copy round trips** before any conviction. Do not credit Sharpe 1.55 to the strategy — it is beta.
- **challenger review:** strongest bear case — NANC's outperformance is a tech tilt, not information alpha, and the repo backtest's alpha decays to ~0 in 2024–2026. Accepted: the copy sleeve stays small (≤10% of P2) even after fixes.
- **what would change my mind (bullish):** post-fix live sample ≥30 round trips with positive alpha vs SPY at t≥2. **(bearish):** H.R. 7008/1908 passage → wind down P2 entirely.

### P3 — Cautious Sniper
- **action:** REDUCE RISK / FIX BEFORE RESUME · **confidence:** 85
- **decision summary:** The +6% June peak proves the entry screen can find winners (PANW, MU, CSCO, MS); the round-trip to zero proves the exit structure throws them away. 1.5-ATR stops under breakout-extension entries are inside daily noise (63% stop-out rate). Fix D1/D2/D6, then restructure the stop (2.5–3×ATR with proportionally halved size = same $ risk, walk-forward-gated) or enter on pullback-to-breakout instead of the BB break.
- **challenger review:** "17 trades in 5y backtest = no edge, kill P3." Fair — but the live sample (39 entries, 30 closes) is 2× the backtest and shows breakeven-not-negative economics with a specific, fixable structural flaw. One more quarter of paper under fixed exits is justified.
- **what would change my mind:** post-fix PF < 1.1 after 30 more round trips → fold P3 into the passive core.

### Cross-portfolio
- Correlation concentration is real: P1 core and P2 sleeve overlap on SPY/QQQ/IWM/DIA/XLI (~$80K combined index beta across books). Acceptable while in risk-off; revisit if satellites reactivate.

---

## 5. Prioritized improvement plan

**Week 1 (data truth + broken engines):** D1, D2, D3, D4, D5 — until these ship, the program cannot even measure itself honestly. Nothing else matters first.
**Week 2 (risk plumbing):** D6, D8, D9, D12 + escalate FEED DARK/news-crash to heartbeat alerts (silent-failure class).
**Weeks 3–4 (strategy, all walk-forward-gated + committee-approved):** D7, D10, D11; P1 satellite candidate re-test (the 6/17 candidate had OOS 0.56 vs challenger 0.93 — the bar stands).
**Retest plan:** each fix gets a regression test (the repo's 594-test suite is the right home); D1 needs a no-ATR-signal path test; D2/D4 need a broker-vs-log reconciliation test in CI; re-run `p2_congress_copy_backtest` with the 63d exit + 30d lag window to re-confirm before enabling.

---

## 6. Live money: when, and with what

**Verdict: NO-GO today. Nothing is close.** Gates (docs/LIVE_READINESS.md) vs reality:

| Gate | Threshold | P1 | P2 | P3 |
|---|---|---|---|---|
| Track record | ≥90 trading days | ~27 | ~27 | ~27 |
| OOS Sharpe | ≥1.0 | -0.55 per-trade | n/a (no live copy sample) | ~0 |
| Profit factor | ≥1.3 | 0.24 | n/a | 0.98 |
| Closed trades | ≥50 | 61 ✅ | ~6 ❌ | 30 ❌ |
| Max DD | ≤15% | 6.7% ✅ | 2.6% ✅ | 5.9% ✅ |
| Regimes | ≥2 | 1 | 1 | 1 |

Plus the external statistics: 90 days of daily returns **cannot** distinguish a true Sharpe 1.0 from zero at 95% confidence (Bailey–López de Prado MinTRL: years, not months), and live performance typically runs **30–50% below** paper/backtest (QuantPedia: 33% mean OOS decay). So treat the 90-day gate as a *plumbing* gate, not proof of edge.

**Realistic timeline:**
- **Earliest gate-eligible date: ~end of September 2026** (90 trading days from 5/27), and only if a sleeve is by then PF ≥1.3 with ≥50 closes — currently none is on track.
- **The only thing defensibly live-able earlier is the passive core itself** (it's beta — it doesn't need paper to prove it, it needs the D8 regime-tilt fix). If you want real money working sooner: fund a **separate live account** with the 8-ETF core at **5–10% of intended capital** per your documented ramp procedure, tightened limits, while ALL active sleeves stay paper. That is the committee-sanctioned bridge.
- **Active sleeves go live individually**, never together, each only after: its own gate pass + 2-week fractional ramp + live-vs-paper tracking-error check. On current evidence P2's fixed copy sleeve is the most plausible first candidate (Q4 2026 at the earliest, ≥30 post-fix round trips), P3 second (Q4+), P1 satellite last (needs a candidate that beats buy-and-hold, which 48 tries haven't produced).

---

## 7. Best strategy — existing or new?

**The evidence (yours and the world's) converges on one answer: a regime-tilted passive core with small, provable satellites — which is P1's current architecture, done properly. Not a new engine.**

1. **Core (80–90% of capital): the 8-ETF passive basket with regime tilt (fix D8).** Your own 15-window study: passive core OOS Sharpe 1.83 vs active -0.33; the challenger (buy-and-hold) beat all 48 optimized candidates. External: SPY +7–10% YTD 2026; momentum-factor ETFs (MTUM ~+26% trailing) beat every homegrown signal tested. Consider adding a momentum-factor ETF (MTUM-style) as a 9th basket member — it delivers cross-sectional momentum at 0.15% ER without the turnover costs that kill DIY momentum (Lesmond/Novy-Marx-Velikov evidence).
2. **Satellite 1 (≤10%): P2's copy sleeve after D3/D7/D10** — the only sleeve with both live green shoots and a t>3 backtest signal, held 63 days, 15–30d lag window only. Hard-capped, with a legislative kill trigger.
3. **Satellite 2 (≤10%): P3 after D1/D2/D6 + exit restructure** — entries are fine, exits are broken; fix and re-measure.
4. **Retire ambitions, not the system:** P1's active multifactor stays off until it beats the challenger out of sample. A "new strategy" search is not justified — the infrastructure's honest verdict machinery is the most valuable asset you've built, and it is telling you the same thing the academic literature tells everyone: **after costs, at retail scale, unproven active signals lose to the index.** Realistic net Sharpe target for the whole program: **0.8–1.5. Anything promising more is overfit.**

---

## 8. Senior Expert Verdict

**Paper program: CONDITIONAL GO** — keep running, but Week-1 fixes (D1–D5) are mandatory conditions; the program is currently flying on instruments that misreport two of three books.
**Live capital: NO-GO** — no sleeve passes the strategy gates; earliest credible review ~end of September 2026, and only the passive core (fractional, separate account) is a defensible earlier deployment.
**Strategy: KEEP the core-satellite architecture the system already adopted on 2026-06-18; fix the three broken engines; add nothing new until the existing ones are measured honestly.**

---

## 9. Remediation status (updated 2026-07-04, same day)

All twelve defects are now fixed and shipped across two commits; CI green.

| # | Sev | Fix | Status |
|---|-----|-----|--------|
| D1 | Critical | P3 news tranche un-crashed + CI unmasked | ✅ shipped |
| D2 | Critical | P3 P&L rebuilt from broker FIFO (-$6,183 → -$288); exit_reason attributed | ✅ shipped |
| D3 | Critical | P2 feed root-caused (WAF blocks runner IPs) + House-Clerk fallback (stdlib PTR parser, 467/467 parity) | ✅ shipped |
| D4 | High | P2 reconciler sign-bug fixed; log rebuilt (-$285 → +$808, = broker) | ✅ shipped |
| D5 | High | `close_trade` reason param + 4 P1 call sites | ✅ shipped |
| D6 | High | P3 gross cap + cumulative tranches + $2k min-notional | ✅ shipped |
| D7 | High | P2 25% take-profit → ~63-trading-day alpha-capture exit | ✅ shipped |
| D8 | Med | P1 core regime-tilt by class (BULL ~45% → ~17% defensive) | ✅ shipped |
| D9 | Med | P1 defensive-ETF bucket attribution | ✅ shipped |
| D10 | Med | P2 lag 45→30d; technical gate → advisory | ✅ shipped |
| D11 | Med | P3 cooldown → consecutive-stop only | ✅ shipped |
| D12 | Low | P2 copy BUYs peg to ask (marketable) | ✅ shipped |

**Follow-on strategy artifacts (this session):**
- `docs/LIVE_CORE_RAMP.md` — the fractional-live ramp plan for the passive core (separate account, 5–10%, tightened limits). Sign-off block left blank pending your authorization.
- `docs/CORE_SATELLITE_SPEC.md` — the recommended target architecture (80–90% regime-tilted passive core + MTUM factor sleeve + two capped, individually-gated satellites).

**Still requires the clock, not code:** (a) the passive core's D8 fix runs in tonight's/next EOD; (b) P2's House-Clerk fallback first exercises on the next scheduled P2 scan; (c) live capital remains NO-GO until `LIVE_READINESS.md` gates pass (~Q4 2026), with the passive-core fractional ramp the only defensible earlier move.

## 10. Chief-expert recommendations + operational completion (2026-07-04)

Beyond the D1–D12 defects, every actionable chief-expert recommendation was executed on a
**validate-then-ship** basis, and the operational live-ramp preconditions were completed:

| Item | Outcome |
|---|---|
| **P3 stop restructure** (rec) | **SHIPPED** — OOS-validated (Sharpe 0.19→0.78, DD↓, beats SPY challenger); stop 2.5 / TP 5.0 / trail 2.5 in P3 config. `data/p3_exit_restructure_backtest.json`. |
| **MTUM factor sleeve** (rec) | **VALIDATED MARGINAL → DEFERRED** — +0.037 Sharpe (noise) with +0.9pp DD against elevated momentum-crash risk; not added. `data/mtum_core_inclusion_study.json`. |
| **P2 disclosure observability** (rec) | **SHIPPED** — copies carry transaction/disclosure/observed dates + lag; skipped disclosures logged with reasons (`data/p2_skipped_disclosures.json`). |
| **P1 hard max-loss + loser time-stop** (rec #2) | **SHIPPED, gated** — active-sleeve-scoped (never the passive core); caps the 0.42 win/loss asymmetry when the satellite reactivates. |
| **P1 regime brake on entries** (rec #3) | **SHIPPED, dormant** — blocks new longs in adverse short-horizon regimes; active when the satellite reactivates. |
| **Operational runbook** | **DONE** — `docs/RUNBOOK.md` (kill switch, halt override, manual liquidation, rollback, key rotation, incidents). |
| **Kill-switch drill in CI** | **DONE** — `tests/test_kill_switch_drill.py` (already CI-wired); `LIVE_READINESS.md` open item closed. |
| **P2/P3 reconciliation parity** | **DONE** — broker-FIFO rebuild + exit-reason attribution; `LIVE_READINESS.md` open item closed. |

**Deliberately NOT done (human-gated):** deploying real capital. The fractional-live core ramp
(`docs/LIVE_CORE_RAMP.md`) is turnkey but its §6 sign-off is the owner's decision; live money
stays NO-GO until the strategy gates pass (§6 snapshot above). Everything an engineer can safely
complete is complete.
