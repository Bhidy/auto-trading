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

## 2. Strategy validation gates — v2 (pre-registered 2026-10-23, methodology 2.0.0)

Evaluated **per sleeve-version**, not per account. Every sleeve is registered in the
human-owned `config/strategy_registry.json` (id, book, `start_date`, status, evidence
basis, honest `trial_count` with its source). Evidence starts at `start_date`, so a
strategy change resets the track record. Computed daily by `scripts/readiness_engine.py`
(pure math in `shared/readiness.py`) into `data/readiness_report.json`. Thresholds are
the constants in `shared/readiness.py::THRESHOLDS`, echoed into every report; changing
one is a methodology change (bump the version, add a §7 entry, never tune to a result).

| # | Gate | Threshold (hard) | Applies to |
|---|------|------------------|------------|
| 1 | Track record | ≥ **90 trading sessions** since `start_date` (exchange calendar, not calendar days) | all |
| 2 | **Benchmark-relative edge** | OLS of daily excess return on SPY excess return (rf = BIL daily total return): **alpha > 0** AND **DSR ≥ 0.95** of the appraisal ratio at the registry `trial_count` AND Newey-West (lag 5) **t ≥ z_req** = 1.645 + E[max of N null z] AND **n ≥ 60** daily returns. Below 60 ⇒ `insufficient`. | all |
| 3 | Max drawdown | ≤ 15% peak-to-trough over the window | all |
| 4 | Kill-switch headroom | 18% − current drawdown ≥ 6 pts (STRATEGY_EVIDENCE §8.3 margin) | all |
| 5 | Worst day | > −4% (the daily-loss halt) | all |
| 6 | Daily CVaR 95% | ≤ 3.0% (historical); **refused below 60 returns** | all |
| 7 | Closed round trips | ≥ 50 whole trades (partial exits aggregated per lot) | trade-based |
| 8 | Profit factor | ≥ 1.3, judged only once gate 7 passes | trade-based |
| 9 | Regime coverage | ≥ 2 regime groups (bull = STRONG_BULL/BULL, correction = CORRECTION/RECOVERY, bear = BEAR/STRONG_BEAR; analyst SPY tags from the weekly journals), each ≥ 5 sessions, no group's compounded return < −8% | all |
| 10 | Reconciliation | broker vs ledger `in_sync = true`, report ≤ 1 session old | book |
| 11 | Duplicate orders | 0 (one engine order per symbol/side/session; reconciliation rows excluded) | sleeve rows |
| 12 | Slippage | average adverse slippage ≤ 15 bps vs the recorded reference, one sample per order | sleeve rows |
| 13 | Data freshness | book state updated within 1 session (heartbeat sources) | book |
| 14 | Exception-free | ≥ 30 consecutive sessions with zero failed/timed-out runs of the book's workflows (incl. Guardian) | book |

**Status vocabulary:** `pass`, `fail`, `insufficient` (not enough data yet), `not_measured`
(no instrument — e.g. P2 writes no drift audit), `not_applicable`. Only `pass` counts;
nothing passes by default.

**Verdict:** `GO` only if **every** hard gate passes; `NOT_ELIGIBLE` for `exits_only` /
`quarantined` sleeves (no new evidence accrues); otherwise `NOT_READY`. There is **no
percentage score** — the report gives gates passed / total, the **binding gate** (the open
evidence gate with the longest ETA; `not_measured` gates are listed separately as
measurement gaps, which still block GO) and an **ETA**. The edge ETA is a power estimate,
n_req = (z_req · σ_eff / α)², with σ_eff the larger of the residual and HAC volatility; α ≤ 0
or n_req > 2,520 sessions ⇒ "not converging". `GO` makes a sleeve eligible for the §4 human
review — it never deploys capital.

**Attribution honesty:** no book yet has a clean sleeve-level return series, so every edge
and risk number is computed on the **whole account** and flagged `attribution: book_level`
(P2 copies share the book with the benchmark ETF sleeve; the P3 allocator shares it with
running-off legacy lots). Sleeve P&L is never fabricated.

**Why v2 replaces "OOS Sharpe ≥ 1.0" (and is stricter in statistical terms):**
- An absolute Sharpe is earned by beta. SPY alone ran at ~0.66 over 2026-05-26..10-21 and in many years
  above 1.0; a leveraged or fully invested index book would "pass" with zero skill. v2
  regresses out SPY and tests only the **alpha**.
- A Sharpe point estimate ignores sampling error. Over 90 sessions the standard error of an
  annualized Sharpe is ≈ √(252/90) ≈ 1.67, so 1.0 is ~0.6 SE from zero — noise. v2 needs the
  alpha t-stat to clear z_req, which at our honest trial counts (13–60) is **3.3–4.0**, i.e.
  an annualized appraisal ratio of ~6 over 90 sessions or ~2.5 over two years.
- It deflates for **multiple testing** (DSR at the registry trial count) and uses a
  **HAC** standard error, so serial correlation cannot inflate significance.
- The backtest/walk-forward Sharpe stays a research input (`docs/specs/`, strategy lab); it is
  no longer a go-live gate, because a backtest cannot certify live paper evidence.

> Practical consequence: with today's alphas, edge ETAs are years, not weeks. That is the
> honest answer, not a defect of the gate.

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

## 6. Strategy-gate status snapshot — Readiness Engine v2 (as of session 2026-10-22)

Source: `data/readiness_report.json` generated 2026-10-23 15:40Z (Alpaca 1D portfolio history,
Alpaca calendar, SIP adjusted SPY/BIL bars, GitHub run history). All returns are BOOK-level.

| Sleeve (registry id) | Status | Sessions | Alpha/yr (β) | t_HAC vs z_req | DSR @ N | Verdict | Gates | Binding gate · ETA |
|---|---|---|---|---|---|---|---|---|
| P1 momentum v1 (`p1-momentum-v1`) | exits_only | 78 | +5.5% (0.17) | 0.48 vs 3.55 | 0.08 @ 20 | **NOT_ELIGIBLE** | 9/12 | edge · not converging (n_req ≈ 4,705) |
| P1 multi-factor satellite (`p1-multifactor-satellite-v2`) | quarantined | 16 | −70.9% (0.84) | −4.28 vs 3.99 | 0.00 @ 60 | **NOT_ELIGIBLE** | 8/14 | edge (n = 16) · PF 0.33 on 61 trades |
| P2 copy v2 (`p2-copy-v2`) | active | 78 | +2.8% (0.45) | 0.37 vs 3.77 | 0.04 @ 34 | **NOT_READY** | 8/14 | edge · not converging (n_req ≈ 8,090); 3/50 round trips |
| P2 benchmark ETF (`p2-benchmark-etf-v1`) | active | 100 | +7.2% (0.53) | 1.08 vs 1.65 | 0.85 @ 1 | **NOT_READY** | 8/12 | edge · est. 2027-05-24 (beta sleeve; book-level alpha) |
| P3 legacy event-driven (`p3-event-driven-legacy`) | quarantined | 90 | −11.6% (0.57) | −0.56 vs 3.35 | 0.01 @ 13 | **NOT_ELIGIBLE** | 11/14 | edge · not converging; PF 0.99 on 81 trades |
| P3 crisis_core_v1 forward (`p3-crisis-core-v1-forward`) | forward_test | 0 | — | — | — | **NOT_READY** | 2/12 | edge · too early (first fills 2026-10-23) |

Book-level facts behind the table: max DD P1 1.8%, P2 3.3%, P3 9.2% (legacy window); every
book is only **13 clean sessions** into the 30-session exception-free gate (a Guardian run
failed 2026-10-05); P2 has **no broker-vs-ledger drift audit** (reconciliation `not_measured`).

**No sleeve is GO. Live capital remains NO-GO.** The only sleeve with a projectable edge ETA
is the P2 benchmark ETF sleeve, whose "alpha" is the whole P2 book's and is beta-dominated —
it is not evidence of copy-trade skill.

## 7. Methodology changelog

| Version | Date | Change | Reason |
|---|---|---|---|
| 2.0.0 | 2026-10-23 | Readiness Engine v2: per-sleeve registry; trading-session counting with version reset; benchmark-relative alpha (OLS on SPY, rf = BIL, Newey-West lag 5) + DSR ≥ 0.95 at the honest trial count replaces absolute OOS Sharpe ≥ 1.0; kill-switch headroom, worst day, CVaR95, regime coverage and five operational gates computed; binding gate + power-analysis ETA; no percentage score. Kept: 90 sessions, DD ≤ 15%, PF ≥ 1.3, ≥ 50 trades. | Audit 2026-10-23 of the readiness page: P1 Sharpe gate hard-coded PASS from a stale July constant, hard-coded backtest chips, calendar days counted as trading days and never reset on strategy change, live Sharpe never computed, PF/sample mixed versions and sleeves, "60% ready" gauge, no ETA, regime and operational gates never computed. |
| 1.0 | 2026-06 | Original §2 table (track record, OOS Sharpe ≥ 1.0, DD, PF, trades, regimes). | Initial live-readiness bar. |

_Last updated: 2026-10-23 (methodology 2.0.0). Owner: Senior Chief Quant. Review: monthly; §6 regenerates daily in `data/readiness_report.json`._
