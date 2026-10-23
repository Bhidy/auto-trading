# Live-Readiness Gate — Auto Trading (by RiseWealth)

> **Status: PAPER ONLY.** Real capital must not be deployed until every gate
> below is met and signed off. This is a hard control, not a guideline.

The system is fully autonomous on paper across three portfolios (P1 Self
Improving Brain, P2 Capitol Shadow, P3 Cautious Sniper). The gates below codify
the institutional bar for promoting any single portfolio from paper to live.

---

## 1. Engineering integrity gates (all must be GREEN)

| Gate | Requirement | How verified | Status |
|------|-------------|--------------|--------|
| Order idempotency | Every order sends a deterministic `client_order_id`; duplicate fires are 422-skipped | `tests/test_client_idempotency.py`, `test_shared_alpaca_http.py` | ✅ |
| HTTP resilience | 429/5xx + network errors retried w/ backoff; never crash a session | `test_shared_alpaca_http.py` | ✅ |
| Fill accuracy | Trades logged at real `filled_avg_price`, never a phantom limit price | `test_execution.py` | ✅ |
| Position reconciliation | EOD audit flags trade-log↔broker drift (`reconciliation_report.json`) | `test_reconciliation.py` | ✅ |
| Self-learning safety | Param changes gated by out-of-sample walk-forward; reverted if not validated | `test_self_learning_gate.py` | ✅ |
| Test + lint gate | `pytest` + `ruff` green on every push (CI) | `.github/workflows/ci.yml` | ✅ |
| Security scan | CodeQL + Dependabot active, no open high-severity alerts | GitHub Security tab | ✅ |
| No silent failures | Heartbeat watchdog alerts on any missed daily run | `.github/workflows/heartbeat.yml` | ✅ |
| No fabricated data | Dashboard shows only real equity (no synthetic backfill) | `dashboard/server.js` `realEquityBackfill` | ✅ |
| Dashboard auth | Trade-mutation endpoints fail-closed behind `DASHBOARD_ACCESS_TOKEN` | live curl (401 w/o token) | ✅ |
| Cloud-path purity | Trading/EOD import closure is heavy/CLI/LLM-free; `requirements.txt` stays `requests`-only | `tests/test_trading_path_purity.py` | ✅ |
| Tool pinning | Vendored Alpaca skill/CLI pinned by commit + sha256; floating `main` rejected | `tests/test_skills_lock_pinned.py`, `config/vendored_tools.lock.json` | ✅ |
| Research provenance | Calibrated-friction artifact carries a fingerprint sidecar (p90, floored, refuse-on-small-N) | `tests/test_friction.py`, `test_research_provenance.py` | ✅ |
| Backtest no-look-ahead | Engine prefix invariant to future bars; metrics match an independent recompute | `tests/test_reference_parity.py` | ✅ |

## 2. Strategy validation gates — v2.1 (pre-registered 2026-10-23, methodology 2.1.0)

Evaluated **per sleeve-version**, not per account. Every sleeve is registered in the
human-owned `config/strategy_registry.json` (id, book, `start_date`, status, evidence
basis, `claims_edge`, `owns_book_edge`, honest `trial_count` with its source, and dated
`book_halts`). Evidence starts at `start_date`, so a strategy change resets the track record;
sessions a book was halted/frozen are excluded from the evidence window. Computed daily by `scripts/readiness_engine.py`
(pure math in `shared/readiness.py`) into `data/readiness_report.json`. Thresholds are
the constants in `shared/readiness.py::THRESHOLDS`, echoed into every report; changing
one is a methodology change (bump the version, add a §7 entry, never tune to a result).

| # | Gate | Threshold (hard) | Applies to |
|---|------|------------------|------------|
| 1 | Track record | ≥ **90 active trading sessions** since `start_date` (exchange calendar; halted/frozen sessions excluded — v1 required an uninterrupted record) | all |
| 2 | **Benchmark-relative edge** | OLS of daily excess return on SPY excess return (rf = BIL daily total return); decided by an **always-valid one-sided confidence sequence** on alpha (normal mixture, ρ = 252 sessions, scale = Newey-West lag-5 long-run sd): **PASS iff the lower bound > 0** at level **0.05 / K** (K = max(6, live edge-claiming sleeves)) and n ≥ 60 halt-free daily returns. `fail` iff the upper bound < 0; otherwise `insufficient`. Not applicable to `claims_edge: false` sleeves; only the `owns_book_edge` sleeve of a shared account may pass it. | edge sleeves |
| 3 | Max drawdown | ≤ 15%, the **stricter** of the version window and the whole paper period of the book | all |
| 4 | Kill-switch headroom | live kill threshold − drawdown from the **live engine's reference** ≥ 6 pts (STRATEGY_EVIDENCE §8.3): P1 18% from `risk_officer.drawdown_reference_equity` (max(start, verified peak)); P2 15% from $100,000; P3 has no drawdown switch in its engine, so the system 18% from its starting equity applies | all |
| 5 | Worst day | > −4% (the daily-loss halt) | all |
| 6 | Daily CVaR 95% | ≤ 3.0% (historical); **refused below 60 returns** | all |
| 7 | Closed round trips | ≥ 50 whole trades (partial exits aggregated per lot) | trade-based |
| 8 | Profit factor | ≥ 1.3, judged only once gate 7 passes | trade-based |
| 9 | Regime coverage | ≥ 2 regime groups (bull = STRONG_BULL/BULL, correction = CORRECTION/RECOVERY, bear = BEAR/STRONG_BEAR; analyst SPY tags from the weekly journals), each ≥ 5 sessions, no group's compounded return < −8% | all |
| 10 | Reconciliation | broker vs ledger `in_sync = true`, report ≤ 1 session old | book |
| 11 | Duplicate orders | 0 (one engine order per symbol/side/session; reconciliation rows excluded) | sleeve rows |
| 12 | Slippage | average adverse slippage ≤ 15 bps vs a **decision/arrival** price (quote or last trade recorded at signal/submit), one sample per order. Sleeves that log only their limit price (P1, P2) are `not_measured` — limit headroom is not execution quality | sleeve rows |
| 13 | Data freshness | book state updated within 1 session (heartbeat sources) | book |
| 14 | Exception-free | ≥ 30 consecutive sessions with zero failed/timed-out runs of the book's workflows (incl. Guardian) | book |

**Status vocabulary:** `pass`, `fail`, `insufficient` (not enough data yet), `not_measured`
(no instrument — e.g. P2 writes no drift audit), `not_applicable`. Only `pass` counts;
nothing passes by default.

**Verdict:** `GO` only if **every** hard gate passes. `NOT_ELIGIBLE` for `exits_only` /
`quarantined` sleeves (no new evidence accrues). `BETA_SLEEVE` for `claims_edge: false`
sleeves (readiness = risk/ops only; the book series is never credited to them).
`FORWARD_TEST_PASS` is the ceiling for `forward_test` sleeves — their parent spec failed its
promotion gate, so a pass never means GO; promotion needs a new registry version. Otherwise
`NOT_READY`. There is **no percentage score** — the report gives gates passed / total, the
**binding gate** (the open evidence gate with the longest ETA; `not_measured` gates are listed
separately as measurement gaps, which still block GO) and an **ETA range**: the expected
first passage of the sequential boundary if the true alpha equals the estimate (median),
the estimate − 1 s.e. (pessimistic) or + 1 s.e. (optimistic). "Not converging" only if the
always-valid upper bound on alpha ≤ 0, or the passage is beyond 10 years even at that upper
bound; fewer than 20 returns ⇒ "too early". `GO` makes a sleeve eligible for the §4 human
review — it never deploys capital.

**Data hygiene (v2.1):** a daily return with |r| > 25% is a data fault (phantom equity read,
unrecorded flow) — excluded and warned, never used. Deposits/withdrawals/journals
(Alpaca activities CSD/CSW/JNLC/JNLS) exclude that session's return; if activities cannot be
read the report warns that flows are unverified.

**Attribution honesty:** no book yet has a clean sleeve-level return series, so every edge
and risk number is computed on the **whole account**. When sleeves of one account overlap in
time, exactly one (`owns_book_edge`) may own the edge test (`attribution: book_level`); the
others are `book_level_shared` and cannot GO on edge (P2: copies own it, the benchmark ETF
sleeve claims no edge). Sleeve P&L is never fabricated.

**Why v2 replaces "OOS Sharpe ≥ 1.0":**
- An absolute Sharpe is earned by beta. SPY alone ran at ~0.66 over 2026-05-26..10-21 and in many
  years above 1.0; a fully invested index book would "pass" with zero skill. v2 regresses out SPY
  and tests only the **alpha**.
- A Sharpe point estimate ignores sampling error. Over 90 sessions the standard error of an
  annualized Sharpe is ≈ √(252/90) ≈ 1.67, so 1.0 is ~0.6 SE from zero — noise.

**Why v2.1 decides edge with a confidence sequence (adversarial review, 2026-10-23):**
- *Repeated looks.* The engine re-evaluates every session. A fixed threshold crossed "the first
  day it happens" is a sequential test with no error control: with v2.0's rule (N = 1) a
  zero-alpha sleeve reached a false GO in 21–26% of simulated paths over 2–5 years. The normal-
  mixture confidence sequence (Robbins; Howard, Ramdas, McAuliffe & Sekhon 2021) bounds the
  probability that the lower bound **ever** exceeds the true alpha by the stated level, at every
  look, forever (Ville's inequality).
- *Multiplicity.* Up to ~6 live sleeve-versions are evaluated at once; Bonferroni α/K with a
  pre-registered floor K = 6 keeps the **family-wise** false-GO ≤ 5%.
- *Backtest trial counts do not deflate live returns.* Selection over N backtests inflates the
  backtest, not post-selection out-of-sample returns, so v2.0's z_req = 1.645 + E[max of N] was
  the wrong correction (it demanded ~20 years for IR 0.8). DSR at the backtest trial count is kept
  as an informational number.
- *ρ = 252 sessions.* Expected passage times are nearly flat in ρ (IR 0.8: 4,590–5,180 sessions
  for ρ from 63 to 2,016); 252 is at the minimum for IR 0.8–1.2. No ρ makes IR 0.5–1.0 detectable
  in 1–2 years: even a single fixed-sample one-sided test at 0.05/6 needs ~2,260 sessions for
  IR 0.8.

**Validation** (`scripts/research/readiness_sequential_sim.py` runs the engine code; 5 years of DAILY looks; CI pins a fast version in
`tests/test_readiness_engine.py`):

| Scenario | False GO over 5 years |
|---|---|
| zero alpha, iid normal, level 0.05/6 (1,000 paths) | **0.20%** (target ≤ 0.83%) |
| zero alpha, iid normal, level 0.05 (K = 1) | 1.40% (7/500; target ≤ 5%) |
| zero alpha, AR(1) 0.15 residuals, level 0.05/6 | 0.20% (1/500) |
| zero alpha, Student-t(4) residuals, level 0.05/6 | 0.00% (0/500) |
| v2.0 fixed rule, N = 1, same setup | **30.7%** (looks every 5 sessions, 300 paths) |

| True annual IR (β 0.5, 10% residual vol) | Median sessions to GO | P(GO by 2 / 5 / 10 / 20 y) |
|---|---|---|
| 0.5 | > 20 years | 0% / 3% / 8% / 23% |
| 0.8 | 3,987 (≈ 15.8 y) | 1% / 10% / 30% / 66% |
| 1.2 | 1,740 (≈ 6.9 y) | 3% / 33% / 71% / 99% |

> Practical consequence: live paper evidence alone cannot certify a realistic edge (IR ≤ 1) in
> under ~7 years at a 5% family error. That is the honest statistics, not a defect of the gate:
> real-capital decisions must rest on pre-registered research evidence (STRATEGY_EVIDENCE tiers)
> with the live record used to *refute* (risk, ops, `fail` on a significantly negative alpha),
> not to prove.

## 3. Operational gates

Items 10–14 of §2 are now computed per book by the engine every session. The remaining
one-off controls:

- [ ] 30 consecutive days with **zero unhandled exceptions** in any workflow run.
- [ ] Heartbeat watchdog has alerted correctly at least once (tested failure path).
- [ ] Supabase persistence verified (`SUPABASE_URL` + keys set; equity history accumulating).
- [x] Kill-switch + daily/weekly loss halts exercised (scripted CI drill: `tests/test_kill_switch_drill.py` — liquidate+lockdown, daily-loss halt, healthy no-halt; runs on every push).
- [x] Runbook exists for: key rotation, halt override, manual liquidation, rollback → `docs/RUNBOOK.md`.
- [ ] Secrets rotation policy in place; live keys scoped to a *separate* live account.

## 4. Go-live procedure (when all gates pass)

1. Sign-off recorded (date, who, which portfolio, the metric snapshot).
2. Provision a **separate live Alpaca account** (never reuse paper keys).
3. Start with **fractional capital** (e.g. 5–10% of intended size) for 2 weeks.
4. Tighten hardcoded risk limits for the live ramp (lower max position %, daily loss).
5. Monitor daily; scale only after the fractional period meets the same gates.

## 5. Currently OPEN before any live consideration

- Supabase as the **sole** system of record (currently dual-written with git-JSON).
- ~~P2/P3 EOD reconciliation parity~~ → **DONE (2026-07-04):** P2 and P3 now reconcile
  to broker FIFO truth with exit-reason attribution and an idempotent repair tool
  (`scripts/rebuild_closed_pnl_from_broker.py`); both logs verified to the cent.
- ~~A scripted kill-switch drill in CI~~ → **DONE:** `tests/test_kill_switch_drill.py`
  runs on every push (simulated drawdown → asserts liquidate + lockdown).

## 6. Strategy-gate status snapshot — Readiness Engine v2.1 (as of session 2026-10-22)

Source: `data/readiness_report.json` generated 2026-10-23 16:13Z (Alpaca 1D portfolio history,
account activities, calendar, SIP adjusted SPY/BIL bars, GitHub run history). Edge level 0.05/6
= 0.0083 per sleeve, ρ = 252. Alpha bounds are always-valid, annualized, BOOK-level.

| Sleeve (registry id) | Status | Sessions (active) | Alpha/yr (β) | Always-valid bounds | Verdict | Gates | Binding gate · ETA |
|---|---|---|---|---|---|---|---|
| P1 momentum v1 | exits_only | 78 (**1** — frozen 07-07..10-22) | — (n = 1) | — | **NOT_ELIGIBLE** | 8/12 | edge · too early |
| P1 multi-factor satellite | quarantined | 16 (16) | −77.9% (0.84) | [−524%, +368%] | **NOT_ELIGIBLE** | 7/14 | edge (n = 15) · PF 0.33 on 61 trades |
| P2 copy v2 (owns P2 edge) | active | 78 (78) | +2.8% (0.45) | [−42.9%, +48.5%] | **NOT_READY** | 7/14 | edge · no central projection; optimistic (α̂ + 1 s.e.) ≈ 486 sessions → 2028-09 |
| P2 benchmark ETF | active, no edge claim | 100 (100) | not applicable | — | **BETA_SLEEVE** | 8/11 | exception-free streak · 2026-11-16 |
| P3 legacy event-driven | quarantined | 90 (90) | −11.9% (0.57) | [−131%, +107%] | **NOT_ELIGIBLE** | 11/14 | edge · PF 0.99 on 81 trades |
| P3 crisis_core_v1 forward | forward_test (cap FORWARD_TEST_PASS) | 0 | — | — | **NOT_READY** | 3/12 | edge · too early (first fills 2026-10-23) |

Book facts: whole-paper-period max DD P1 7.8%, P2 3.3%, P3 9.2%; kill-switch headroom vs the
live references P1 15.2 pts (18% from $100K), P2 15.0 pts (15% from $100K; book above start),
P3 17.1 pts. The only cash flow detected is the 2026-05-27 funding deposit (excluded). All books
are 13 clean sessions into the 30-session exception-free gate (Guardian failed 2026-10-05).
Measurement gaps: P2 has no drift audit (reconciliation), and P1/P2 log only limit prices
(slippage not measurable vs arrival).

**No sleeve is GO. Live capital remains NO-GO.** At realistic edges the sequential test needs
years (§2 power table); the live record's job now is to refute (risk, ops, a significantly
negative alpha), not to certify.

## 7. Methodology changelog

| Version | Date | Change | Reason |
|---|---|---|---|
| 2.1.0 | 2026-10-23 | Edge decided by an always-valid one-sided normal-mixture confidence sequence (ρ = 252, HAC scale) at 0.05/K, K = max(6, live edge sleeves); DSR@backtest-trials and t_HAC/z_req demoted to informational. New verdicts BETA_SLEEVE (`claims_edge: false`) and FORWARD_TEST_PASS (cap for forward tests); one edge owner per shared account (`book_level_shared`). Kill headroom vs each live engine's reference; max DD = stricter of window and whole paper period; halted sessions excluded (`book_halts`); abs(r) > 25% data faults and Alpaca cash-flow sessions excluded; slippage only vs a decision/arrival price; ETA as median/pessimistic/optimistic range; id-less trade rows distinct; cron dedup only once today's equity point exists. | Adversarial review 2026-10-23: daily re-evaluation of a fixed threshold gave 21–26% false GO at zero alpha over 2–5 y; backtest trial counts wrongly deflated live returns; P2 benchmark sleeve was scored on the copy book; window-peak headroom differed from the live kill switches; a frozen P1 counted as track record; P2's journal phantom ($27.9K) would have entered as data; P2 "slippage" was limit headroom. |
| 2.0.0 | 2026-10-23 | Readiness Engine v2: per-sleeve registry; trading-session counting with version reset; benchmark-relative alpha (OLS on SPY, rf = BIL, Newey-West lag 5) + DSR ≥ 0.95 at the honest trial count replaces absolute OOS Sharpe ≥ 1.0; kill-switch headroom, worst day, CVaR95, regime coverage and five operational gates computed; binding gate + power-analysis ETA; no percentage score. Kept: 90 sessions, DD ≤ 15%, PF ≥ 1.3, ≥ 50 trades. | Audit 2026-10-23 of the readiness page: P1 Sharpe gate hard-coded PASS from a stale July constant, hard-coded backtest chips, calendar days counted as trading days and never reset on strategy change, live Sharpe never computed, PF/sample mixed versions and sleeves, "60% ready" gauge, no ETA, regime and operational gates never computed. |
| 1.0 | 2026-06 | Original §2 table (track record, OOS Sharpe ≥ 1.0, DD, PF, trades, regimes). | Initial live-readiness bar. |

_Last updated: 2026-10-23 (methodology 2.1.0). Owner: Senior Chief Quant. Review: monthly; §6 regenerates daily in `data/readiness_report.json`._
