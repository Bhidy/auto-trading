# Operational Runbook — Auto Trading (by RiseWealth)

**Purpose:** the incident + operations procedures required as a precondition of any live
deployment (`docs/LIVE_CORE_RAMP.md` §2). Applies to the paper program today and to the
fractional-live passive core if/when it is authorized. **Paper is the default and the
reference book at all times.**

> Golden rule: **exits are never blocked; entries are.** Every procedure here preserves
> the ability to flatten risk. When in doubt, reduce risk and page a human.

---

## 0. System map (where things live)

| Thing | Location |
|---|---|
| Engines | `scripts/` (P1), `political-copy-bot/scripts/` (P2), `event-driven-bot/scripts/` (P3) |
| Broker client (single source of truth) | `shared/alpaca_http.py` |
| Hardcoded risk limits (never relaxed) | `config/risk_limits.json` (P1), per-bot `config/risk_limits.json` |
| Live-ramp limits (separate) | `config/risk_limits.live.json` |
| Orchestration | 14 GitHub Actions workflows (`.github/workflows/`) |
| State (system of record) | Supabase `auto-trading-prod` + committed git-JSON |
| Dashboard | Vercel `autotradingportfolios.vercel.app` |
| Secrets | GitHub Actions secrets + Vercel env (never in git) |

---

## 1. Kill switch & halt override

**Automatic (already live, drilled in CI — `tests/test_kill_switch_drill.py`):**
- Daily loss ≥ 4% → 24h halt. Weekly loss ≥ 8% → 7-day halt. Drawdown ≥ 18% → **liquidate all +
  lockdown**. P3 has its own 5% daily kill-switch. These fire in the intraday monitor and set
  `halted`/`halt_until` in `data/portfolio_state.json`.

**Manually HALT a portfolio (stop new entries, keep exits):**
1. Edit that portfolio's `data/portfolio_state.json`: set `"halted": true`, `"halt_reason": "<why>"`,
   `"halt_until": "<ISO ts>"`. Commit + push.
2. Verify next monitor run logs the halt and places no new entries.

**Manually RESUME:** set `"halted": false`, clear `halt_until`, commit + push. Confirm a clean
monitor run before expecting entries.

**Override a stuck automatic halt:** the halt is data, not code — editing `portfolio_state.json`
as above overrides it. Never edit `config/risk_limits.json` to dodge a halt; that is the hard
control and must stay intact.

---

## 2. Manual liquidation (flatten a book NOW)

Preferred (auditable, uses the real fill path):
- Trigger the portfolio's monitor workflow with a liquidation intent, or run the bot's kill-switch
  path locally against the correct keys.

Fallback (broker-direct, when automation is down):
1. In the Alpaca dashboard for the affected **account**, cancel all open orders, then close all
   positions.
2. Immediately set `"halted": true` in that portfolio's `portfolio_state.json` and commit, so the
   next automated run does not re-enter.
3. Reconcile: the next EOD writes `data/reconciliation_report.json`; confirm `in_sync`. If the
   trade log drifted, run `python3 scripts/rebuild_closed_pnl_from_broker.py --portfolio <p2|p3>`
   (dry-run first, then `--apply`) to rebuild realized P&L from broker truth.

**Never** place discretionary directional trades by hand. Liquidation only.

---

## 3. One-command rollback to paper (live → paper)

The paper system runs continuously and is the reference book, so rollback = **disable the live
workflows**; nothing about paper changes.
1. Disable every `p1-live-*` workflow (Actions UI → workflow → ⋯ → Disable), or delete the
   `PORTFOLIO_1_LIVE_*` secrets so the live workflow fails closed and places nothing.
2. Flatten the live account per §2 (fallback path) if positions are open.
3. Record the rollback (date, reason, equity snapshot) in the incident log below.
4. Root-cause before any re-attempt; re-run the `LIVE_CORE_RAMP.md` preconditions from scratch.

---

## 4. Key rotation

Scope: **paper keys and live keys are always separate accounts.** Rotate on any suspected
exposure and on a fixed schedule.
1. In Alpaca, generate a new key/secret for the specific account (paper or live).
2. Update the GitHub Actions secret(s): `P1_API_KEY`/`P1_API_SECRET` (paper) or
   `PORTFOLIO_1_LIVE_*` (live); and the Vercel env `PORTFOLIO_1_API_KEY`/`_SECRET` (dashboard read).
3. Revoke the old key in Alpaca **only after** a green workflow run confirms the new one works.
4. Never commit keys. `config/portfolios.json`, `config/alpaca_config.json` stay gitignored.
5. Supabase: rotate `SUPABASE_SERVICE_ROLE_KEY` (write path) independently; the anon key is
   read-only (RLS) and lower-risk.

---

## 5. Common incidents → response

| Symptom | First check | Action |
|---|---|---|
| A portfolio went stale (no run) | Heartbeat issue / `heartbeat.yml` | Re-run the missed workflow; check Actions logs for the failing step |
| P2 `disclosure_feed_reachable` violation | `strategy_conformance.json` | Expected if Capitol Trades WAF-blocks runners; the House-Clerk fallback should engage — confirm `house_fd` in logs. Only a problem if BOTH sources fail |
| Dashboard shows zeros | `curl /api/health` → `rootDir` must be `/var/task` | See CLAUDE.md troubleshooting; usually a Vercel path/deploy issue, not the engine |
| Trade log P&L looks wrong | broker vs log | `rebuild_closed_pnl_from_broker.py` (dry-run → apply); it is idempotent |
| Reconciliation not `in_sync` | `reconciliation_report.json` | Read-only audit; investigate orphan/unlogged before trading further |
| CI red | `ci.yml` run | Do not deploy engine changes until green (ruff + pytest are the gate) |

---

## 6. Escalation

1. Reduce risk first (halt entries; liquidate if drawdown is accelerating).
2. Capture evidence (Actions logs, `reconciliation_report.json`, `execution_integrity.json`).
3. Notify the owner (Senior Chief Quant). Live-capital incidents are always human-decision.

---

## 7. Incident log (append-only)

| Date | Portfolio | Summary | Action taken | Resolved |
|---|---|---|---|---|
| _(none yet — paper only)_ | | | | |

_Last updated: 2026-07-04. Review: on every incident and monthly._
