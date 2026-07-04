# Go-Live Checklist — Passive Core, Fractional (AUTHORIZED 2026-07-04)

**Owner sign-off is recorded** (`LIVE_CORE_RAMP.md` §6). This checklist converts that
authorization into the exact, ordered steps. It is scoped to the **P1 passive core only** —
active sleeves stay paper. **No real capital has been deployed. Paper keeps running as the
reference book throughout.**

> Why there is still a sequence after sign-off: a sign-off authorizes the *decision*. It cannot
> itself open a brokerage account, pass KYC, fund it, or mint API keys — those are actions only
> you can take at Alpaca, and I do not move money or place live orders. My job is to make the
> rest turnkey and verify each gate. That work is done; the human + time gates remain.

---

## Legend
- 🧑 **You** (I cannot do this — account/money/secrets)
- 🤖 **Me** (done, or I do it with you on the day)
- ⏳ **Time** (must simply elapse)

---

## A. Preconditions still open

| # | Gate | Owner | Status |
|---|------|-------|--------|
| A1 | Engine runs core-only; D8 regime-tilt live | 🤖 | ✅ done |
| A2 | Live limits bind end-to-end (`RISK_PROFILE=live` → `risk_limits.live.json` everywhere) | 🤖 | ✅ done (`shared/risk_config.py`, 6 loads rerouted, tested) |
| A3 | Runbook exists (halt / liquidate / rollback / key rotation) | 🤖 | ✅ done (`docs/RUNBOOK.md`) |
| A4 | Kill-switch drill green in CI | 🤖 | ✅ done (`tests/test_kill_switch_drill.py`) |
| A5 | **14 consecutive days, all 14 workflows green, ZERO unhandled exceptions** | ⏳ | **OPEN — the clock reset with today's change-set (2026-07-04). Target ≥ 2026-07-18.** |
| A6 | **Separate LIVE Alpaca account provisioned (KYC) + funded with the fractional amount** | 🧑 | **OPEN — only you can do this** |
| A7 | **Live API keys generated; added as GitHub secrets `PORTFOLIO_1_LIVE_API_KEY` / `_SECRET`** | 🧑 | **OPEN — only you can do this** |
| A8 | Live trading workflow wired (disabled, double-gated) | 🤖+🧑 | Ready to build the day A6/A7 land — see §C |

---

## B. Your steps (🧑), in order

1. **Open a separate LIVE Alpaca account** (never the paper account). Complete identity
   verification. Keep it distinct from `PA3HULQQ8OOH` (paper).
2. **Fund it with the fractional amount only** — 5–10% of intended size (e.g. $5k–$10k of a
   $100k target). Do not fund the full amount.
3. **Generate LIVE API keys** in that account (base URL `https://api.alpaca.markets`).
4. **Add them as GitHub repository secrets:** `PORTFOLIO_1_LIVE_API_KEY`,
   `PORTFOLIO_1_LIVE_API_SECRET`. **Never commit keys.**
5. **Tell me A6/A7 are done and A5 has elapsed.** I then do §C with you.

## C. The day it goes live (🤖 with you)

6. I add a `p1-live-*` workflow that is **triple-gated and fail-closed**:
   - runs only if the `PORTFOLIO_1_LIVE_*` secrets exist (absent → no config → no orders),
   - runs only if repo variable `P1_LIVE_ENABLED == 'true'` (you flip it deliberately),
   - `workflow_dispatch` first (manual) before any schedule,
   - sets `RISK_PROFILE=live` (→ 6% ETF cap / 2% daily / 10% kill-switch, now enforced end-to-end),
   - core-only (`active_entries_enabled=false`), limit-first orders, base URL `api.alpaca.markets`.
7. **Manual dispatch once**, market-closed, as a dry check: confirm it reads the LIVE account,
   loads live limits, and places nothing out of hours.
8. Enable for one session; confirm the first live core orders match the paper core's intent and
   fill; watch fills/slippage/tracking-error vs paper for **2 weeks** (`LIVE_CORE_RAMP.md` §4).
9. Scale to the next tranche only if the fractional period stays clean (zero unhandled
   exceptions, zero reconciliation breaks, halts never fired on a system fault).

## D. Verify (each live session)

- `curl https://api.alpaca.markets/v2/account` (live keys) → equity matches expectation.
- Reconciliation `in_sync`; `execution_integrity.json` not anomalous.
- Live equity tracks the paper core within tolerance.

## E. Rollback (any system fault → paper)

1. Set `P1_LIVE_ENABLED=false` (or delete the live secrets) → live workflow fails closed.
2. Flatten the live account per `RUNBOOK.md` §2 if positions are open.
3. Log it in `RUNBOOK.md` §7. Root-cause before re-attempting.

---

**Bottom line:** everything an engineer can safely pre-build is built and tested. Go-live now
waits on **A5 (≈2 weeks of green), A6, A7 (your live account + keys)** — then §C is a single
short session. Live capital remains formally NO-GO on the *satellites* regardless; this path is
the passive core only.
