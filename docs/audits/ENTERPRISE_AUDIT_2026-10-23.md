# Enterprise Audit & Remediation — 2026-10-23

Branch `claude/project-repo-audit-a0d1d3`. Method: baseline ("before") audit by five
independent auditors → root-cause fixes by scoped engineers → independent adversarial
review of the money path → independent "after" audit (incl. a simulation of the next
real P1 session on live state) → fixes for every after-audit finding.

## 1. Verdicts

| Question | Verdict |
|---|---|
| Install `Jakeschincariol/day-trader-skill`? | **No.** Clean code (315/315 tests, stdlib, no telemetry), but it is a human-in-the-loop intraday ORB tool that refuses scheduled/background orders — incompatible with the owner's fully-automated requirement — and it uses MARKET entries, duplicates P2/P3/risk/backtest modules, and its risk gate fails open in 3 High cases. |
| Engineering / operations | **Conditional Go (paper)** after merge + first verified runs. |
| Real money | **No-Go.** No book has statistically significant edge; readiness gates fail (§5). Not a licensed advisor — the go-live decision is the owner's. |

## 2. What was broken (root causes)

| Sev | Defect | Root cause |
|---|---|---|
| Critical | **P1 frozen 108 days**, every run green | Kill switch latched 2026-07-07 on a bad $26K equity read (73.94% "drawdown" vs 2.74% real); halts had no evidence, no expiry, no governed clear. |
| Critical | Dashboard order/close endpoints reachable without a token | Auth gate checked a case-sensitive `/api/` prefix while Express routed case-insensitively (`POST /API/.../order`). |
| Critical | Dashboard showed losses as gains, wrong-zone clock, $0.00 changes, stale crypto tape, wrong readiness returns | Abs-value money formatter; local time labelled ET; prev = today's close; ascending queries returned oldest data. |
| High | P2 duplicate copy-sells (CB, HD on 10-15) and overwritten trade-log rows | Queued Guardian dispatch ran from the commit at dispatch time; commit script overlaid older state on newer. |
| High | P2 scan timed out daily (34 silent cancellations) | 14 × 75 s retries against a WAF-blocked feed > 15-min timeout; alerting ignored `cancelled`. |
| High | Production dashboard served July state (incl. wrong halt flag) | Data-only commits never redeploy; bundle frozen at last code deploy. |
| High | Fabricated figures (movers, $100K/$200K placeholders, seeded equity series) | Old mock fallbacks never removed — violated the honesty rule. |
| High | P1 exits booked at unfilled prices; 22 orders vs 12/day cap; momentum book unmanaged while halted | Fill read from submit response; momentum ran before preflight/budget; halt check preceded the sell side. |
| High | Self-learning kept 4 unapproved "de-risk" knob changes (backtest Sharpe 0.13 → −1.43) | De-risk path bypassed the walk-forward gate; no-bars path failed open. |
| High | CI blind to config changes (main red since 10-03) | `ci.yml` path filter excluded `config/**`; tests read live governance state. |

Plus ~40 Medium/Low defects (UTC-vs-ET dating, idempotency gaps, path traversal into broker
URLs, prototype lookups, npm vulnerabilities, RTL/responsive issues) — all fixed; see commits.

## 3. What shipped (commits on this branch)

| Commit | Scope |
|---|---|
| `43d780bd` | Dashboard: auth bypass, live-state overlay, honest fallbacks, input validation, 0 npm vulns; CI: config/dashboard paths, schedule, node security suite; hermetic tests |
| `121d4139` | Crypto tape/chart newest-first |
| `5ffaf049` | P2/P3/ops: Guardian sync + freshness, 3-way JSON state merge, House feed first + circuit breaker, alerting on cancelled/timed_out, heartbeat ET dates, P2 exit idempotency, politician-matched copy-sells, P3 day_start_equity |
| `b2906940` | P1: evidence-stamped halts, governed single-use clear, verified latch (refuses the 7/7 glitch), exits-only mode + 25% disaster floor, TradeBudget, real-fill booking ledger, fail-closed learning, peak-equity DD, ET session anchors |
| `9f0c8ca0` / `6e59776e` | Frontend: signed money, ET times, real prev close, paper labels, unverified-halt banner, offline honesty, 375–1440 responsive, RTL |
| `85cdd970` | Governance: P1 phantom-halt clear (committee-approved) |
| `5080f732` | Dashboard after-audit: no placeholder equity offline, honest histories, halt verification fields, zero-risk smoke probe |
| (final) | P1 after-audit fixes: per-lot disaster floor runs before momentum + month exclusion, no-position exit guard, sticky halt fields + atomic ledger withholding in state merge, frozen monthly targets, UUID trade ids, Guardian broker-truth freshness, P2 non-stop exits as marketable limits; this report |

## 4. Evidence (after)

- Python suite **829 passed** (baseline: 742 passed, 2 failed); ruff clean; trading-path purity holds; `requirements.txt` still requests-only; `risk_limits.json` untouched.
- Dashboard node suite **14/14** (auth bypass, traversal, prototype ids, malformed input, no fabricated data, offline honesty).
- Simulation of the next P1 session on the real committed state + broker snapshot (market-data GETs only, orders blocked): halt cleared on a cross-checked $97,258 read (DD 2.74%); disaster floor sells CAT (worst lot −28.6%) **before** momentum and excludes it for the month; momentum places 11 limit orders (sells C, GOOGL, MPC, PSX; buys AMAT, AMD, DE, INTC, JNJ, LLY, MRK), MU/SLB/TGT deferred by the 12/day cap; a same-day re-run places 0 orders; monitor/EOD 0 orders. Phantom-read and disagreeing-read scenarios neither latch, liquidate nor clear.
- Frontend: 14 pages × 375/834/1440 × light/dark, zero console errors, no horizontal overflow, AR verified.

## 5. Strategy & live readiness (measured, 2026-05-26 → 2026-10-21)

| Book | Return | Sharpe | Max DD | Closed-trade PF | DSR |
|---|---|---|---|---|---|
| P1 | −1.90% | −0.43 | 7.8% | 0.37 (t = −3.1, real loss) | 0.63 |
| P2 | **+4.53%** | 1.42 | 3.3% | 2.27 (n = 19) | 0.64 |
| P3 | −0.78% | −0.09 | 9.2% | 0.97 | 0.64 |
| Combined | +0.61% | 0.22 | 4.8% | — | — |
| SPY | +3.02% | 0.66 | 4.5% | — | — |

None passes DSR ≥ 0.95. Momentum's backtest excess over equal-weight is +2.9%/yr (t = 0.38)
— market exposure plus survivorship, not selection skill.

## 6. Forward plan (pre-registered — no step ships without its acceptance test)

**Phase 0 — Deploy & verify (now).** Merge → CI green → Deploy & Smoke Test green → watch
the first P1 session: halt cleared with a `halt_governance.json` record, ≤12 limit orders,
reconciliation in sync at EOD. Rollback = revert the merge (state merge keeps data safe).

**Phase 1 — Prove the plumbing (30 trading days).** Zero unhandled exceptions, zero
duplicate orders, zero reconciliation drift, every failure alerted within one run.
Heartbeat shows all three books fresh daily. This is the "operational" half of LIVE_READINESS.

**Phase 2 — Evidence-led allocation (research lane, offline).**
1. *Passive core* for idle capital (8 ETFs within the 12% cap). Accept if, over 10
   walk-forward windows, Sharpe ≥ SPY − 0.15 and max DD ≤ SPY's; live tracking error ≤ 3%/yr over 60 days.
2. *P2 satellite* (10–20%), measured vs beta-matched SPY. Accept after ≥ 50 new round trips:
   alpha t ≥ 2.0, PF ≥ 1.3, DSR ≥ 0.95.
3. *P1 multi-factor & P3* stay off until a pre-registered redesign passes walk-forward mean
   Sharpe ≥ SPY + 0.3 over ≥ 10 windows, CPCV median > 0, DSR ≥ 0.95 (honest trial count).

**Phase 3 — Real money (earliest, if gates pass).** Passive core: after Phase 1 + owner
sign-off (fractional ramp per `LIVE_CORE_RAMP.md`). P2 satellite: ~mid-2027 (trade count).
P1/P3 active: not before a redesign + 90 days paper.

## 7. Remaining risks / not verified

- Real fill behaviour and opening-auction spreads (simulation filled at limit).
- GitHub cron throttling persists; Vercel crons (now post-open in EDT and EST) and, if
  installed, Supabase pg_cron (`docs/guardian-external-trigger.sql`) drive Guardian — the
  pg_cron layer's presence is not verified.
- P2 is House-only while Capitol Trades stays WAF-blocked (Senate disclosures not covered).
- Statistical confidence: confirming Sharpe 1.0 at 95% needs ~2.7 years of data; passing the
  90-day gate is necessary, not sufficient.
