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

## 2. Strategy validation gates (per portfolio, on PAPER history)

| Gate | Threshold | Source |
|------|-----------|--------|
| Track record | ≥ 90 trading days live-paper, uninterrupted | `data/trade_log.json` + journals |
| Out-of-sample Sharpe | ≥ 1.0 (walk-forward, net of modeled costs) | `scripts/backtest/walk_forward.py` |
| Max drawdown | ≤ 15% over the paper period | `scripts/backtest/metrics.py` on live equity |
| Profit factor | ≥ 1.3 | `performance_tracker.compute_metrics` |
| Closed-trade sample | ≥ 50 closed trades (statistical floor) | trade log |
| Regime coverage | Profitable (or controlled-loss) across ≥ 2 distinct regimes | journal regime tags |

> P3 is a static fundamental+breakout strategy (no self-learning loop), so its
> walk-forward number is a robustness check, not a tuning gate.

## 3. Operational gates

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

## 6. Strategy-gate status snapshot (2026-07-04, ~day 27 of 90)

| Portfolio | Track record | OOS Sharpe ≥1.0 | PF ≥1.3 | ≥50 closed | Verdict |
|---|---|---|---|---|---|
| P1 core (passive) | — | beta (n/a) | n/a | n/a | Only defensible early live (fractional, see `LIVE_CORE_RAMP.md`) |
| P1 satellite | ~27d | fails | fails | 61 ✓ | **Stays OFF** until it beats buy-and-hold OOS |
| P2 copies | ~27d | unproven | n/a | ~6 ❌ | Paper; engine fixed, re-measure ≥30 post-fix round trips |
| P3 breakout | ~27d | ~0 live | ~1 | 30 ❌ | Paper; stop restructure shipped, re-measure ≥30 round trips |

**Live capital remains NO-GO.** Earliest credible review ~end of Sep 2026. The passive-core
fractional ramp is the only defensible earlier deployment and requires the human sign-off in
`LIVE_CORE_RAMP.md` §6.

_Last updated: 2026-07-04. Owner: Senior Chief Quant. Review: monthly._
