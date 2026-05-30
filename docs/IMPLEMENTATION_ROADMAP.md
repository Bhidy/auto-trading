# Implementation Roadmap — Audit Remediation to World-Class, Real-Money-Ready

> **Status: PLANNING / PAPER-ONLY.** This document converts the external audit
> ("World-Class Claude Skill Pack and Audit") into a concrete, evidence-grounded
> engineering roadmap. **No trade recommendations are made here.** It extends —
> does not replace — `docs/LIVE_READINESS.md`. Every finding below was verified
> against the actual source tree (file:line cited), not assumed.
>
> Doctrine (adopted from the audit, enforced as policy): **Claude proposes,
> scores, challenges, and explains. Deterministic policy code validates, sizes,
> and submits.** The path to real-money excellence is *better hierarchy, better
> validation, better broker-state handling, and stricter governance* — not more
> autonomy.
>
> _Author: Senior Chief Quant. Created: 2026-05-30. Review cadence: weekly during rollout._

---

## Section 0 — Audit Reconciliation (verified against source)

The audit explicitly states it was based on the architecture report and public
documentation, **not a source-code review**. My first job was to verify each
claim. Result: 5 of 7 gaps confirmed as-stated, 1 already substantially
mitigated (the audit didn't know), and 1 understated — I found a **more material
gap the audit missed**.

| # | Audit finding | Verified status in code | Evidence (file:line) | Severity |
|---|---------------|--------------------------|----------------------|----------|
| 1 | Model risk around self-learning needs validation/challenger/rollback | **PARTIALLY MITIGATED already.** A real walk-forward OOS gate exists, fails closed, reverts unvalidated knob changes. Audit under-credited this. Still missing: overfitting statistics (PBO/deflated Sharpe), challenger model, human sign-off, param-change provenance. | `scripts/backtest/walk_forward.py`; `performance_tracker.py:189` (`_GATED_KNOBS`), `:260-278` (gate + fail-closed revert) | **Medium** (narrower than audit claims) |
| 2 | Signal hierarchy — P2 congressional disclosures are structurally delayed; SEC/EDGAR primary should outrank | **CONFIRMED.** P2 scans "last 30 days" of *disclosures* with no transaction-date freshness gate and no fundamental/technical confirmation overlay. Disclosure lag (30–45d) stacks on the 30-day scan window → acting on up to ~75-day-stale signals. No SEC/EDGAR feed anywhere. | `political-copy-bot/config/watchlist.json` (`primary_scan_days:30`, no `max_disclosure_age`); EDGAR grep = NONE | **High** |
| 3 | Execution-state control — replace cron/poll with event-driven `trade_updates`; handle partial fill/reject/replace/halt/LULD | **CONFIRMED.** `confirm_fill` is an 8-second polling loop. No `trade_updates` WebSocket. No LULD/halt/circuit-breaker awareness ("halt" in code is only the *internal* portfolio flag). Mitigant: P3 already uses bracket/OCO orders. | `shared/alpaca_http.py:84-108`; `risk_officer.py:57` (internal flag only); trade_updates grep = NONE; P3 mitigant `event-driven-bot/scripts/alpaca_client.py:150` | **High** |
| 4 | Broker-rule awareness — FINRA 26-10 intraday margin (eff. 2026-06-04), ETB/HTB shorting | **CONFIRMED + UNDERSTATED.** No PDT/intraday-margin detection. **No easy-to-borrow gate at all — yet P1 actively places SHORT (sell) entries.** This is the single most material safety gap and the audit only mentioned it generically. | P1 shorts: `autonomous_runner.py:252,:367` (`side="sell"` for SHORT signals); borrow grep = NONE | **CRITICAL** |
| 5 | Full life-cycle accounting — fees (TAF/CAT), corporate actions, tax lots, T+1, reconciliation realism | **CONFIRMED.** No fee modeling, no corporate-action handling, no tax lots, no settlement awareness. Reconciliation is **symbol-presence only** — it does not detect quantity, average-price, or cost-basis drift. | fees/corp-action grep = NONE; `shared/reconcile.py:11-30` (symbol sets only) | **High** |
| 6 | Tax/compliance — wash-sale (IRS Pub 550), realized vs unrealized | **CONFIRMED.** No wash-sale detection, no realized/unrealized split in the ledger. | wash_sale grep = NONE | **Medium** (paper); **High** (live taxable) |
| 7 | Role of Claude / governance — advisory-only, hard code approves & submits | **CONFIRMED at code level.** No human-approval gate exists anywhere; self-learning auto-commits params to git. The new committee *skill* sets doctrine but nothing enforces "advisory-only" in code. | human_approval grep = NONE; `performance_tracker.py:279` auto-saves params | **High** |

**Bottom line:** the architecture and guardrails are strong (idempotent orders,
resilient HTTP, real fill confirmation, an OOS self-learning gate, annualized
risk metrics, EOD reconciliation, kill/loss halts). The remaining work is
**broker-state realism, signal-evidence hierarchy, accounting honesty, and
governance** — exactly where paper-grade systems silently fail with real money.

---

## Section 1 — Critical Fixes Before Real-Money Trading (P0 blockers)

These are hard go/no-go items. Real capital must not move until every one is GREEN.

### C1 — Easy-to-Borrow (ETB) pre-trade gate for all short entries  *(NEW — most material)*
- **Why:** P1 generates and submits SHORT orders (`autonomous_runner.py:367`)
  with no borrow check. A name that is hard-to-borrow (HTB) or flips ETB→HTB
  overnight gets the open short canceled pre-market or charged punitive borrow
  fees — silently corrupting both risk and P&L attribution.
- **Fix:** In `risk_officer.validate_trade`, add a mandatory gate for `SHORT`
  signals: query Alpaca asset `shortable` + `easy_to_borrow` immediately before
  approval; reject if not ETB. Re-check at execution time (borrow status changes
  daily). Store borrow status on the trade record.
- **Done when:** `tests/test_risk_officer.py` proves a HTB symbol short is
  rejected; no short order can be submitted without a fresh ETB confirmation.

### C2 — Event-driven order-state machine (replace the 8s poll)
- **Why:** `confirm_fill` (`shared/alpaca_http.py:84`) polls for ≤8s then gives
  up. Partial fills, late fills, replaces, and rejections after that window are
  invisible until the next cron — the system acts on a stale view of its own
  orders. This is the audit's #3 and a classic real-money failure mode.
- **Fix:** Add a `shared/order_state.py` consumer of Alpaca's `trade_updates`
  stream (fills, partial_fills, canceled, rejected, pending_replace, expired)
  running as a lightweight always-on worker OR, given the serverless
  constraint, a robust reconciling poller that (a) persists every order's last
  known state, (b) reconciles open orders every monitor run against the broker,
  (c) explicitly handles partial fills by adjusting logged qty/cost-basis.
- **Done when:** a partial fill and a post-window fill both reconcile correctly
  in a test; no order can sit in an unknown state across a monitor cycle.

### C3 — Market-halt / LULD / circuit-breaker awareness
- **Why:** No code distinguishes a tradeable symbol from a halted/LULD-banded
  one. Submitting into a halt or against an LULD band produces rejects or
  unexpected fills. Market-wide circuit breakers (7/13/20%) are entirely unmodeled.
- **Fix:** Pre-trade gate: check asset `status`/`tradable`, detect LULD/halt
  conditions from the latest quote/trade (stale or banded), and a system-wide
  "market stress" flag that pauses *new* entries (never blocks risk-reducing
  exits). Wire into both `risk_officer` and the P3 path.
- **Done when:** a simulated halted symbol is rejected for new entry but still
  exitable; a circuit-breaker flag pauses entries cleanly.

### C4 — Automated governance on self-learning parameter changes
- **Why:** `adapt_parameters` auto-writes `strategy_params.json` with no record
  of *why* a knob moved and no way to roll back. Even with the OOS gate, an
  adaptive change altering sizing/risk needs an auditable, reversible decision
  (audit governance gate + Fed SR 11-7 doctrine).
- **Design choice (fully automated, zero human):** governance is a
  **deterministic policy, not a person**. The walk-forward + overfitting gate is
  the approver; a change is auto-promoted only if it passes every codified gate
  (OOS Sharpe, PBO, Deflated Sharpe, challenger, hard bounds) and is otherwise
  auto-reverted. Every decision is written to an append-only provenance log and a
  last-known-good snapshot enables automatic rollback. No manual step exists.
- **Done when:** no knob reaches production without a recorded, gated decision;
  rollback restores the last validated set automatically.

### C5 — Fee- and corporate-action-aware P&L (accounting honesty)
- **Why:** Logged P&L excludes TAF/CAT regulatory fees and ignores dividends,
  splits, symbol/CUSIP changes. On real money this makes realized P&L and every
  downstream metric (Sharpe, profit factor, the live-readiness gates themselves)
  misleading.
- **Fix:** Add `shared/accounting.py`: apply modeled regulatory fees on
  buys/sells, and a corporate-actions reconciler (consume Alpaca corporate-action
  announcements; adjust qty/cost-basis on splits, record dividends). Backtests
  and live ledger both run through it.
- **Done when:** a split and a dividend correctly adjust a position in test;
  net-of-fee P&L is the only P&L the dashboard shows.

### C6 — Quantity & cost-basis reconciliation (not just symbol presence)
- **Why:** `compute_drift` (`shared/reconcile.py:11`) only compares *which*
  symbols are held vs logged. A wrong quantity or wrong average price (partial
  fill, missed corporate action) passes as "in_sync."
- **Fix:** Extend drift to compare qty and average entry price per symbol within
  a tolerance; emit `qty_drift` / `cost_basis_drift` classes. Block live promotion
  while any drift is open.
- **Done when:** `tests/test_reconciliation.py` catches a qty mismatch and a
  cost-basis mismatch, not only an orphan/unlogged symbol.

---

## Section 2 — High-Priority Improvements (risk, execution, validation, monitoring)

### Risk
- **R1 — Cross-portfolio aggregate risk.** P1/P2/P3 enforce limits in isolation;
  nothing caps *combined* single-name or sector exposure across the three $100K
  books (audit Example 4 is exactly this case). Add a cross-portfolio exposure
  reporter + a soft cap that flags when a name exceeds X% of the $300K aggregate.
- **R2 — Correlation & "portfolio heat."** Add per-portfolio open-risk
  (sum of distance-to-stop × size) and a pairwise-correlation snapshot so the
  risk chief can veto correlated stacking. Surfaces in the EOD report.
- **R3 — Volatility-targeted sizing.** Position sizing is ATR-based per trade but
  has no portfolio-level vol target. Add an annualized-vol estimate and scale
  gross exposure down in high-vol regimes (complements existing regime multipliers).
- **R4 — Tighter live-ramp limits.** Codify a separate `risk_limits.live.json`
  with materially tighter caps for the fractional live ramp (lower max position %,
  lower daily-loss %), selected by environment — never reuse paper limits live.

### Execution
- **E1 — Bracket/OCO everywhere.** P3 already uses bracket orders
  (`alpaca_client.py:150`); P1/P2 attach stops/TPs logically but rely on the
  monitor to enforce. Move P1/P2 to broker-native bracket/OCO so stops survive a
  missed monitor run.
- **E2 — Spread/slippage pre-trade gate.** Reject or downsize when the quoted
  spread exceeds a threshold or liquidity (ADV) is thin — make the audit's
  "execution feasibility" layer real, not implicit.
- **E3 — Limit-price discipline + repricing.** Define explicit limit logic
  (midpoint/▒bps) and a single repricing rule for unfilled limits, instead of
  blind resubmits.

### Validation
- **V1 — Overfitting statistics.** Add Probability of Backtest Overfitting (PBO,
  combinatorially-symmetric cross-validation) and a Deflated Sharpe Ratio that
  penalizes for the number of parameter trials — the audit cited this literature
  directly. Gate adaptive changes on PBO < 0.5 and positive deflated Sharpe.
- **V2 — Challenger model.** A simple, fixed benchmark strategy (e.g. regime-
  filtered buy-and-hold of the core book) that every adaptive change must beat
  OOS. If the "improvement" can't beat the dumb baseline, reject.
- **V3 — Factor IC tracking.** Track information coefficient / decay per factor so
  weights are evidenced, not assumed.

### Monitoring
- **M1 — Stale-state & drift alerts** beyond heartbeat: alert on open reconciliation
  drift, working-order age, borrow-status flips, and any rejected order.
- **M2 — Live-vs-paper fill drift log.** Record expected vs actual fill price per
  order so slippage is measured before real money, not after.
- **M3 — Kill-switch drill in CI.** Scripted simulated drawdown → assert halt +
  lockdown (already flagged open in `LIVE_READINESS.md §5`).

---

## Section 3 — Strategy Improvements (P1, P2, P3)

### P1 — Self-Improving Brain (challenge hardest; it adapts)
- Promote evidence hierarchy: when a primary issuer event (8-K/earnings) exists,
  it must outrank pure technical score (today scoring is purely
  price/indicator-derived in `analyst_v2.py`).
- Add the V1/V2 overfitting controls before any further loosening of
  `confidence_buy_threshold` (the knob most prone to noise-chasing —
  `performance_tracker.py:254-258`).
- Borrow-aware shorting (C1) is a *strategy* constraint here, not just plumbing:
  no short signal is actionable on a non-ETB name.
- Reconcile the **two inconsistent Sharpe definitions**: `metrics.py` is properly
  annualized; `performance_tracker.compute_metrics` emits a per-trade z-score
  `sharpe_estimate` (`:120-127`). Standardize on the equity-curve, annualized one
  everywhere so the gates measure what they claim.

### P2 — Capitol Shadow (demote to research-grade context)
- **Reclassify the feed as low-priority/medium-horizon context, not primary
  alpha** (audit #2). Hard rule: a congressional disclosure alone never triggers
  a trade.
- Add a **disclosure-age gate**: reject if `today − transaction_date` exceeds a
  freshness bound (the data is already 30–45d delayed; stacking a 30-day scan is
  worse). Store the lag on every candidate.
- Require a **confirmation overlay** (fundamental and/or technical and/or a fresh
  primary filing) before copying — convergence, not a single stale signal.
- Liquidity + concentration gate (don't stack into already-crowded mega-caps).

### P3 — Cautious Sniper (require convergence; respect catalyst decay)
- Make **SEC/EDGAR / company-originated events the primary catalyst source**;
  treat news-API sentiment as secondary confirmation (audit evidence gate). No
  EDGAR integration exists today.
- Enforce **catalyst-decay time stops**: news/catalyst trades must exit when the
  edge decays (the strategy intends this; make it an explicit, tested rule).
- Keep news-tranche position sizes strictly below core fundamental sizes unless
  evidence is unusually strong (already the design intent — enforce in code).

---

## Section 4 — Code-Level Implementation Tasks (file-by-file)

| ID | File(s) | Change | Tests |
|----|---------|--------|-------|
| T1 | `scripts/risk_officer.py` | Add ETB/shortable gate for SHORT; reject non-ETB. Add halt/LULD/tradable gate. Add spread/liquidity gate. | extend `tests/test_risk_officer.py` |
| T2 | `shared/order_state.py` (new) | Persisted order-state reconciler; partial-fill-aware qty/cost-basis updates. | `tests/test_order_state.py` (new) |
| T3 | `shared/alpaca_http.py` | Add `get_asset`/borrow + corporate-action helpers; keep idempotency/retry contract intact. | extend `tests/test_shared_alpaca_http.py` |
| T4 | `shared/accounting.py` (new) | Regulatory-fee model; corporate-action reconciler; realized/unrealized split. | `tests/test_accounting.py` (new) |
| T5 | `shared/reconcile.py` | Add qty + cost-basis drift classes to `compute_drift`. | extend `tests/test_shared_reconcile.py` |
| T6 | `scripts/performance_tracker.py` | Split propose/apply for params; write `param_change_request.json`; standardize on annualized Sharpe from `metrics.py`; rollback record. | extend `tests/test_self_learning_gate.py` |
| T7 | `scripts/backtest/metrics.py` + `walk_forward.py` | Add PBO + deflated Sharpe; gate on them; add regime-bucketed aggregation. | `tests/test_backtest_metrics.py`, `test_self_learning_gate.py` |
| T8 | `scripts/backtest/` (new `challenger.py`) | Fixed benchmark strategy; adaptive change must beat it OOS. | `tests/test_challenger.py` (new) |
| T9 | `political-copy-bot/` (`politician_bot.py`, `config/watchlist.json`) | Disclosure-age gate (`max_disclosure_age_days`); confirmation-overlay requirement; reclassify priority. | `tests/test_p2_disclosure_age.py` (new) |
| T10 | `event-driven-bot/` (`event_driven_bot.py`, new `edgar_client.py`) | EDGAR primary-filing catalyst source; catalyst-decay time stop. | `tests/test_p3_catalyst_decay.py` (new) |
| T11 | `scripts/autonomous_runner.py`, P2/P3 executors | Broker-native bracket/OCO for P1/P2; borrow re-check at execution. | extend `tests/test_execution.py` |
| T12 | `config/` | `risk_limits.live.json`; cross-portfolio aggregate-exposure config. | new `tests/test_live_limits.py` |
| T13 | `scripts/governance.py` (new) | Approval-record reader/writer; promote/rollback CLI; audit-trail append-only log. | `tests/test_governance.py` (new) |

> All new modules must follow existing conventions: route broker calls through
> `shared/alpaca_http.py`, keep `load_json(default if default is not None else {})`,
> send `client_order_id` on every order, and stay `ruff`-clean under the CI gate.

---

## Section 5 — Data & Logging Gaps to Fix

- **D1 — Trade record schema v2.** Add: `filled_avg_price` vs `intended_price`
  (slippage), `fees`, `borrow_status`, `order_class`, `parent_order_id`,
  `disclosure_lag_days` (P2), `catalyst_source` + `evidence_quality` (P3),
  `realized_pnl` vs `unrealized_pnl`. Today's record (`performance_tracker.log_trade`)
  lacks all of these.
- **D2 — Append-only decision/audit log.** Every signal, validation outcome,
  approval, and param change written immutably with rationale (Fed SR 11-7:
  documentation + audit trail). No silent state mutation.
- **D3 — Param-change provenance.** before/after, OOS evidence, PBO/deflated
  Sharpe, challenger result, approver, timestamp — one record per change.
- **D4 — Order-state history.** Persist each order's full state transitions
  (submitted→partial→filled/canceled/rejected) for live-vs-paper analysis.
- **D5 — Reconciliation severity.** Promote drift/working-order findings from
  informational JSON to alert-eligible events with severity.
- **D6 — One canonical metric source.** Eliminate the dual Sharpe definitions
  (D-section ties to T6); the dashboard and gates must read the same numbers.

---

## Section 6 — Backtesting & Walk-Forward Validation Requirements

The existing engine (`scripts/backtest/multifactor.py`, `walk_forward.py`,
`metrics.py`) is genuinely good — point-in-time, no look-ahead, cost+slippage
modeled, fails closed. Raise it to world-class:

1. **PBO (Probability of Backtest Overfitting)** via combinatorially-symmetric
   cross-validation; require **PBO < 0.5** for any promoted change.
2. **Deflated Sharpe Ratio** accounting for the number of trials; require it
   **> 0** (positive after multiple-testing haircut).
3. **Cost realism = live realism:** the same fee/borrow/corporate-action model
   from `shared/accounting.py` (C5) feeds the backtest, so paper and backtest
   P&L are comparable to live.
4. **Regime-bucketed reporting:** Sharpe/return/drawdown per detected regime, not
   just a single aggregate — the readiness gate "≥2 distinct regimes" becomes
   measured, not asserted.
5. **Challenger benchmark (V2):** every adaptive change must beat the fixed
   baseline OOS, net of costs.
6. **Minimum-sample discipline:** keep the existing ≥5/≥10 closed-trade gates;
   add a "do not tune below N OOS windows" guard in `walk_forward`.
7. **Reproducibility:** persist backtest artifacts (params, window definitions,
   seeds, results) so any promotion is auditable later.

---

## Section 7 — Dashboard Metrics to Add

Surface the truth the engine now computes (brand-compliant: warm palette, DM
Serif numbers, Manrope UI, pill tags — per `CLAUDE.md` branding):

- **Risk panel:** live annualized Sharpe/Sortino/Calmar (equity-curve based, the
  canonical ones), max drawdown, current portfolio heat, gross/net/short exposure
  vs limits, cross-portfolio aggregate single-name & sector exposure.
- **Execution-quality panel:** average slippage (intended vs filled), unfilled-
  limit age, partial-fill rate, rejected-order count, borrow-status flips.
- **Validation panel:** latest OOS walk-forward Sharpe, PBO, deflated Sharpe,
  challenger-beat yes/no, and **pending param-change requests awaiting approval**.
- **Accounting panel:** net-of-fee realized vs unrealized P&L, fees paid,
  dividends received, corporate actions applied, open reconciliation drift.
- **Evidence panel (P2/P3):** disclosure-lag distribution (P2), catalyst source +
  evidence-quality mix (P3).
- **Governance panel:** approval/rollback history, last param change + approver,
  kill-switch/halt status with countdowns.

---

## Section 8 — Governance & Manual-Approval Controls

Adopt the audit's six go-live gates as the control framework, enforced in code:

1. **Validation gate** — no param change to production sizing/risk without OOS +
   PBO + deflated Sharpe + challenger pass + recorded rollback (C4, T6, T7, T8).
2. **Event-driven execution gate** — order state is broker-reconciled, partial/
   reject/replace/halt handled explicitly (C2, C3, T2).
3. **Broker/rule-awareness gate** — ETB/HTB borrow, halt/LULD, fee accounting,
   corporate actions, and PDT/intraday-margin (FINRA 26-10, eff. 2026-06-04)
   detected and stored, never hardcoded (C1, C3, C5, T1, T3, T4).
4. **Evidence gate** — SEC/EDGAR & company-originated events primary; delayed
   congressional disclosures research-only (P2/P3 strategy, T9, T10).
5. **Accounting & tax gate** — wash-sale visibility, T+1 settlement awareness,
   realized-vs-unrealized, borrow fees, corporate actions in the ledger (C5, C6,
   D1, T4, T5).
6. **Governance gate (automated)** — **Claude advisory-only, enforced by code.**
   Hard policy approves, sizes, submits. Every parameter change reaching
   production is gated by the deterministic validation policy and recorded with
   provenance; failures auto-revert (C4, governance module). No human in the loop.

**Automated policy stops (deterministic hard stops — no human action):**
- Self-learning param change → must pass the full gate or it auto-reverts; every
  decision is logged with provenance and a last-known-good snapshot.
- `config/risk_limits*.json` is never modified programmatically; the live profile
  is strictly tighter and selected by `RISK_PROFILE`, falling back to paper.
- Any short → blocked unless a fresh ETB confirmation passes (fail-closed).
- Any entry into a halted/not-tradable/stale asset → blocked automatically.
- Loss/drawdown breaches → automatic 24h/7d halt or kill-switch liquidation.

> Note on "paper → live": promoting real capital is the one action that remains a
> deliberate human decision *by policy* (`docs/LIVE_READINESS.md`), because it is
> a capital-allocation choice, not a trading action. Day-to-day trading,
> adaptation, risk control, and rollback are fully autonomous.

---

## Section 9 — 30 / 60 / 90-Day Rollout Plan

> Sequenced so the highest-severity safety gaps land first, validation hardens
> next, and strategy/governance polish last. Each phase ends GREEN on CI
> (`pytest` + `ruff`) with new tests. **No real capital in any phase.**

### Days 0–30 — Safety & Broker Realism (close the P0s)
- C1 ETB short gate; C3 halt/LULD gate; C6 qty/cost-basis reconciliation.
- C2 order-state reconciler (partial-fill-aware) — first cut.
- C5 fee model + corporate-action reconciler — first cut; wire into backtest.
- D1 trade-record schema v2; D2 append-only audit log.
- M3 kill-switch drill in CI; M1 drift/borrow/reject alerts.
- **Exit criteria:** no short without ETB; no entry into halted/banded names;
  reconciliation catches qty & cost-basis drift; all green in CI.

### Days 31–60 — Validation & Governance
- V1 PBO + deflated Sharpe; V2 challenger model; V3 factor IC.
- C4 + T6 propose/apply split with `param_change_request.json` + rollback.
- T13 governance module (approval records, promote/rollback CLI).
- T7 regime-bucketed backtest reporting; unify Sharpe definition (D6).
- Dashboard: validation + governance panels (Section 7).
- **Exit criteria:** no production param change without full validation +
  approval record; one-command rollback proven; gates read one canonical metric.

### Days 61–90 — Strategy Evidence Hierarchy & Hardening
- T9 P2 disclosure-age gate + confirmation overlay + reclassification.
- T10 P3 EDGAR primary-catalyst source + catalyst-decay time stops.
- E1 bracket/OCO for P1/P2; E2 spread/liquidity gate; E3 limit discipline.
- R1–R4 cross-portfolio risk, heat, vol targeting, `risk_limits.live.json`.
- M2 live-vs-paper fill-drift log; remaining dashboard panels.
- Begin the **90-day clean paper track record** clock required by
  `LIVE_READINESS.md §2` (it runs concurrently and continues past day 90).
- **Exit criteria:** every Section-1/2/3 item GREEN; system runs the full audit
  control set on paper with zero unhandled exceptions.

> Note: the 90-day *engineering* rollout and the 90-day *paper track-record* gate
> are different clocks. Go-live requires both complete and signed off.

---

## Section 10 — Final Go-Live Checklist (before any real money)

**Engineering integrity** (extends `LIVE_READINESS.md §1`, all GREEN):
- [ ] ETB/HTB gate blocks every non-borrowable short (C1).
- [ ] Order-state machine handles partial/reject/replace/late-fill (C2).
- [ ] Halt/LULD/circuit-breaker gate pauses entries, never blocks exits (C3).
- [ ] Fees + corporate actions in ledger and backtest; P&L is net-of-fee (C5).
- [ ] Reconciliation catches symbol, qty, AND cost-basis drift; zero open drift (C6).
- [ ] Append-only audit log + param-change provenance live (D2, D3).

**Validation:**
- [ ] OOS walk-forward Sharpe ≥ 1.0, PBO < 0.5, deflated Sharpe > 0, beats challenger.
- [ ] One canonical, annualized metric source feeds gates + dashboard (D6).
- [ ] Regime-bucketed results show control across ≥ 2 regimes (measured).

**Strategy:**
- [ ] P2 trades only with fresh disclosure + confirmation overlay (never alone).
- [ ] P3 catalysts are EDGAR/company-primary; catalyst-decay stops enforced.
- [ ] Evidence hierarchy honored across all three books.

**Risk & execution:**
- [ ] Cross-portfolio aggregate exposure capped and visible (R1).
- [ ] `risk_limits.live.json` tighter than paper; selected by environment (R4).
- [ ] Bracket/OCO native on P1/P2/P3 (E1); spread/liquidity gate active (E2).

**Accounting & tax:**
- [ ] Wash-sale visibility in realized-P&L reporting (D1).
- [ ] T+1 settlement + borrow fees reflected; realized vs unrealized split.

**Governance (automated):**
- [x] Claude advisory-only enforced in code; hard policy approves/sizes/submits.
- [x] Every param→production change gated + recorded with provenance; auto-rollback.
- [ ] Separate **live** Alpaca account; live keys never reuse paper keys.
- [ ] Runbook complete: key rotation, halt override, manual liquidation, rollback.
- [ ] Kill-switch + daily/weekly halts drilled in CI and in paper.

**Track record** (`LIVE_READINESS.md §2`, per portfolio):
- [ ] ≥ 90 trading days clean paper; ≥ 50 closed trades; max DD ≤ 15%; PF ≥ 1.3.

**Sign-off:**
- [ ] Dated sign-off (who / which portfolio / metric snapshot) recorded.
- [ ] Fractional ramp plan (5–10% for 2 weeks) approved before scaling.

---

---

## Section 11 — Implementation Status (this delivery)

Built and shipped in this pass, **fully automated (zero manual steps)**, each
landed green on `pytest` + `ruff` with new tests. Test count grew 115 → 207.

| Item | Status | Modules | Tests |
|------|--------|---------|-------|
| C1 ETB short gate | ✅ Done | `shared/alpaca_http.evaluate_asset_gate`, `risk_officer.validate_trade`, `autonomous_runner` (lookup + money-path re-check) | `test_asset_gate.py` |
| C3 halt/tradable gate | ✅ Done | same gate (tradable/active/stale-quote) | `test_asset_gate.py` |
| C6 qty/cost-basis reconciliation | ✅ Done | `shared/reconcile.compute_drift` (+ P1 EOD detailed records) | `test_shared_reconcile.py` |
| C5 fees + corporate actions | ✅ Done | `shared/accounting.py`; net-of-fee P&L in `performance_tracker.close_trade` | `test_accounting.py` |
| C2 order-state reconciler | ✅ Done | `shared/order_state.py` (+ P1 monitor wiring) | `test_order_state.py` |
| V1+V2 PBO / Deflated Sharpe / challenger | ✅ Done | `backtest/metrics.py`, `backtest/challenger.py`, `walk_forward` gate | `test_overfitting.py` |
| C4 automated governance | ✅ Done | `shared/governance.py` (provenance + auto-rollback) | `test_governance.py` |
| T9 P2 disclosure-age + confirmation | ✅ Done | `politician_bot.py` (+ watchlist config) | `test_politician_signal_hierarchy.py` |
| T10 P3 catalyst-decay time stop | ✅ Done | `event_driven_bot.py` (+ `cancel_order`, config) | `test_catalyst_decay.py` |
| R1 cross-portfolio risk + heat | ✅ Done | `shared/portfolio_risk.py` | `test_portfolio_risk.py` |
| R4 tighter live limits | ✅ Done | `config/risk_limits.live.json`, `RISK_PROFILE`-aware `load_config` | `test_portfolio_risk.py` |
| D1 trade schema v2 | ✅ Done | `performance_tracker.log_trade` (slippage/borrow/order_class/evidence) | `test_trade_schema.py` |
| D6 canonical metric source | ✅ Done | `performance_tracker.equity_curve_metrics` + per-trade disambiguation | `test_trade_schema.py` |

**Deliberately deferred (follow-up, lower-risk, no money-path impact):**
- **Section 7 dashboard panels** — the engine now *computes* execution-quality,
  validation (PBO/DSR/challenger), accounting, cross-portfolio risk, and
  governance data; surfacing them as brand-compliant dashboard panels is
  front-end work that should follow with visual testing (per the design rules).
- **T8 standalone challenger CLI / T10 EDGAR primary feed** — the challenger
  benchmark is wired into the gate; a standalone EDGAR catalyst client for P3 is
  a data-source addition that needs its own integration tests.
- **Cross-portfolio reporter wiring** — `portfolio_risk` is unit-complete; the
  combined live reporter belongs in the dashboard/monitor layer (which holds all
  three API keys) and should read the three live accounts there.

Everything above keeps the system **100% autonomous**: no human approval, no
manual action. Governance, validation, rollback, borrow checks, halt checks, and
risk halts are all deterministic policy code.

---

_This roadmap is evidence-first and conservative by design. It makes the system
world-class by being more disciplined — not by trading more. No trade
recommendations are included; that is deliberate and per scope._
