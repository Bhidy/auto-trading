# Fractional-Live Ramp — Passive Core Only

**Status: PROPOSAL. No real capital is deployed until the sign-off in §6 is recorded.**
**Owner: Senior Chief Quant · Drafted 2026-07-04 · Supersedes nothing (additive to `LIVE_READINESS.md`).**

---

## 1. Why the passive core — and only the core — can go live before the 90-day gate

`docs/LIVE_READINESS.md` requires ≥90 paper trading days, OOS Sharpe ≥1.0, PF ≥1.3,
≥50 closed trades **per portfolio** before that portfolio sees real money. As of
2026-07-04 (~day 27) **no active sleeve passes**, and the external statistics say 90
days of daily returns cannot even distinguish a true Sharpe of 1.0 from zero at 95%
confidence (Bailey–López de Prado MinTRL). So the strategy gate is a *plumbing* gate,
not proof of edge — and it should stay that way for anything with a discretionary or
learned signal.

The **passive index core is different in kind**: it is deliberately *beta*, not alpha.
Its expected return is the market's, its risk is the market's, and its behaviour does
not depend on an unproven signal that needs a track record to validate. Its own 15-window
OOS study puts the diversified passive core at Sharpe ~1.08 vs the active satellite at
−1.11. There is nothing to "prove" about buying SPY/QQQ/IWM/DIA + a defensive sleeve —
the only engineering risk is execution plumbing, which paper has already exercised.

**Therefore:** the passive core is the one component for which a small, controlled live
deployment is defensible *now*. Every active sleeve (P1 satellite, P2 copies, P3
breakouts) stays 100% paper until it clears the full gate individually.

## 2. Hard preconditions (all must be TRUE before funding)

- [ ] P1 is running in core-only mode (`active_entries_enabled=false`, `core_weight=1.0`) — verified in `data/strategy_params.json`.
- [ ] The D8 regime-tilt fix is live (core no longer holds ~45% defensive in a bull tape) — `scripts/portfolio_manager.py::core_class_targets`, tests green.
- [ ] 14/14 GitHub Actions workflows green for ≥14 consecutive calendar days; heartbeat watchdog has fired correctly at least once (tested failure path).
- [ ] Dashboard reconciles to Alpaca to the cent for P1 (spot-checked live).
- [ ] A **separate live Alpaca account** is provisioned with its **own** API keys — never the paper keys, never the paper account. Keys stored only in GitHub Secrets + Vercel env (new `PORTFOLIO_1_LIVE_*` names), never committed.
- [ ] Runbook exists for: key rotation, halt override, manual liquidation, one-command rollback to paper.

## 3. Sizing & tightened limits for the live ramp

Real capital runs a **hardened** copy of the risk config — never the paper limits.

| Control | Paper (P1) | Live ramp (P1-live) | Rationale |
|---|---|---|---|
| Deployed capital | $100,000 | **5–10% of intended** (e.g. $5k–$10k of a $100k target) | Chan's survival-buffer discipline; prove live tracking before scale |
| Max daily loss halt | 4% | **2%** | Half the paper tolerance during the ramp |
| Max weekly loss halt | 8% | **4%** | " |
| Kill-switch drawdown | 18% | **10%** | Tighter lockdown while unproven live |
| Max single ETF position | 12% | **10%** | Extra concentration buffer |
| Order type | limit-first | limit-first, **marketable** | Fills matter more than saving a spread at this size |
| New active entries | disabled | **disabled (hard)** | Core-only; the satellite is not part of this ramp |

These live limits live in a separate `config/risk_limits.live.json` (already present) and
must be loaded by the live workflow — never share the paper `risk_limits.json`.

## 4. Go-live procedure

1. Record the sign-off (§6): date, who, metric snapshot, the exact commit SHA deployed.
2. Fund the separate live account with the fractional amount.
3. Point a **new** `p1-live-*` workflow set at the live keys + `risk_limits.live.json`.
   Reuse the exact engine code; only the account + limits differ. Keep paper P1 running in parallel.
4. Run for **2 weeks** fractional. Each day, compare live fills vs the paper book's
   fills on the same signals: track slippage, tracking error, and any reconciliation drift.
5. **Scale only if** the fractional period shows: live equity tracks the paper core within
   tolerance, zero unhandled exceptions, zero reconciliation breaks, and the tightened halts
   never had to fire on a plumbing bug. Then step to the next capital tranche and re-run §4.

## 5. Abort / rollback

- Any reconciliation break, unhandled exception, or halt triggered by a *system* fault (not a
  market move) → **liquidate the live core, revert the live workflows, return to paper**, and
  root-cause before re-attempting.
- Rollback is one action: disable the `p1-live-*` workflows (the paper system is untouched and
  keeps running as the reference book).

## 6. Sign-off (leave blank until authorized)

| Field | Value |
|---|---|
| Authorized by | _______ |
| Date | _______ |
| Portfolio | P1 passive core only |
| Commit SHA deployed | _______ |
| Fractional capital | _______ |
| Live limits file | `config/risk_limits.live.json` |
| Metric snapshot (equity/DD/workflow-green-days) | _______ |

> **Nothing above authorizes deploying the active P1 satellite, P2 copies, or P3 breakouts to
> real money. Those follow `LIVE_READINESS.md` individually, earliest ~Q4 2026.**
