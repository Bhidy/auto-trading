# Strategy Lab Results — pre-registered S1/S2/S3 + combos (2026-10-23)

> **SIMULATION. Research lane, PAPER ONLY, not investment advice.** Specs: `docs/specs/matf_v1.json`,
> `secmom_v1.json`, `crisis_core_v1.json` (pre-registered 2026-10-23T11:16Z, before any engine code existed; sha256 in
> `data/strategy_lab_results.json`). Engine: `scripts/research/strategy_lab.py`; signals: `scripts/backtest/allocators.py`.
> Each registered run was executed **once**. This is an **in-sample confirmation test**: the specs were written knowing
> how 2016–2026 played out.

## Verdict

**No candidate passes. Do not promote any of them to paper forward-testing as specified.**

| Candidate | C1 MDD ≤ 12% | C2 Calmar ≥ SPY | C3 Sharpe ≥ .5 & DSR ≥ .95 | C4 2022 ≥ SPY+8pp | C5 ±25% stable | C6 20 bps Sharpe ≥ .4 | Overall |
|---|---|---|---|---|---|---|---|
| S1 `matf-v1` | PASS (11.95%) | FAIL (0.30) | FAIL (0.26 / 0.45) | PASS | PASS (max Δ 0.06) | FAIL (0.23) | **FAIL** |
| S2 `secmom-v1` | FAIL (15.4%) | FAIL (0.35) | FAIL (0.40 / 0.61) | PASS | PASS (max Δ 0.12) | FAIL (0.36) | **FAIL** |
| S3 `crisis-core-v1` | FAIL (14.8%) | PASS (0.57) | FAIL (0.73 / 0.90) | PASS | PASS (max Δ 0.004) | PASS (0.73) | **FAIL** |
| Combo A: S1+S2 50/50 | FAIL (12.9%) | FAIL (0.35) | FAIL (0.37 / 0.57) | PASS | PASS | FAIL (0.33) | **FAIL** |
| Combo B: S1+S2+S3 thirds | FAIL (13.5%) | PASS (0.440 vs 0.437, a hair) | FAIL (0.55 / 0.77) | PASS | PASS | PASS (0.53) | **FAIL** |

Sharpe = annualized Sharpe of daily returns **in excess of BIL** (the pre-registered metric). Span 2017-06-01 → 2026-10-22
(2,362 sessions), SIP dividend-adjusted bars, 10 bps per side (5 cost + 5 slippage, `friction.py` floor).

## Headline numbers vs SPY (buy & hold, dividends reinvested)

| | CAGR | Vol | Excess Sharpe | Raw Sharpe (rf=0) | Sortino | Max DD | Calmar | 2018 | 2020 | 2022 |
|---|---|---|---|---|---|---|---|---|---|---|
| **SPY** | 14.78% | 18.1% | 0.72 | 0.85 | 1.20 | 33.8% | 0.44 | −4.96% | +18.45% | −18.18% |
| S1 matf-v1 | 3.56% | 4.4% | 0.26 | 0.81 | 1.08 | 11.95% | 0.30 | −2.43% | −1.18% | −3.86% |
| S2 secmom-v1 | 5.36% | 7.8% | 0.40 | 0.71 | 0.95 | 15.41% | 0.35 | −2.70% | −0.63% | −7.11% |
| S3 crisis-core-v1 | 8.47% | 8.3% | 0.73 | 1.02 | 1.42 | 14.77% | 0.57 | −2.21% | +13.60% | −4.00% |
| Combo A (S1+S2) | 4.49% | 5.9% | 0.37 | 0.78 | 1.04 | 12.92% | 0.35 | −2.56% | −0.90% | −5.57% |
| Combo B (thirds) | 5.96% | 6.5% | 0.55 | 0.92 | 1.25 | 13.54% | 0.44 | −2.45% | +4.07% | −4.98% |

All max drawdowns sit in Feb–Mar 2020. Recovery: S1 2021-04-23, S2 2021-02-12, S3 2020-07-15, SPY 2020-08-10.

## Diagnostics (reported, not criteria)

| | Turnover 1-way/yr | Orders/yr | Avg in T-bills + cash | of which 0% cash | Worst month | Worst day | Worst 5-day | CPCV Sharpe min / median / max (15 paths) |
|---|---|---|---|---|---|---|---|---|
| SPY | — | — | 0% | 0% | −12.6% (2020-03) | −10.8% | −15.6% | 0.04 / 0.69 / 1.36 |
| S1 | 86% | 97 | 49.9% | 13.7% | −5.9% (2020-03) | −2.4% | −6.7% | −0.51 / 0.35 / 1.04 |
| S2 | 132% | 134 | 48.3% | 12.1% | −6.8% (2020-03) | −4.5% | −7.7% | −0.29 / 0.37 / 1.10 |
| S3 | 14% | 27 | 25.1% | 6.1% | −4.9% (2020-03) | −4.1% | −8.5% | 0.09 / 0.75 / 1.34 |

**Risk-limit replay (no halts simulated):** none breaches the 18% kill switch (SPY does: 33.8%). Daily −4% halt: S2 once
(−4.48%), S3 once (−4.10%), S1 and both combos never (SPY 15 times). Rolling-5-day −8% weekly halt: S3 once (−8.53%), others never.
**Cap compliance:** post-rebalance max weight 11.40–11.41% everywhere; S3 drifted above 12% at a close 39 times (max 12.43%),
each trimmed at the next open by the drift guard — S3 runs 8 names at 11.4% with only 0.6 pp headroom.

**Neighbourhood (C5):** no cliffs. S1 Sharpe range 0.25–0.32 across 10 variants; S2 0.28–0.43 across 16; S3 0.728–0.733.
All S2 variants also fail C1 (MDD 15.1–16.7%).

**S3 with all three managed-futures ETFs listed (2022-03-08 → 2026-10-22, information only, ~4.6y):** S3 CAGR 9.5%,
MDD 9.7%, excess Sharpe 0.68, Calmar 0.98 vs SPY 15.5% / 22.1% / 0.70 / 0.70. Before 2019-05-08 S3 held **no** managed
futures (34.2% in bills/cash), so the 2020 drawdown that fails C1 was taken without most of its intended hedge.

## Trial count and DSR

- Honest lab N = **38** (S1 12, S2 18, S3 4, combos 4), exactly as registered. SR0 (expected max under the null) = 0.305
  annualized. DSR: S1 0.45, S2 0.61, S3 **0.90**, Combo A 0.57, Combo B 0.77. At N = 40 (adding the 2 passive-core-ew8 looks)
  the values barely move (S3 0.90).
- Not pooled but noted: `data/trial_ledger.json` (60 P1 self-learning trials), `data/p2_scorecard.json` (34 P2 trials).
- PSR vs 0 (no deflation): S3 0.986, Combo B 0.951, S2 0.885, S1 0.787. Even S3's edge over T-bills is not significant once
  the 38 looks are counted.

## What the evidence says

1. **Drawdown control works; return does not survive it.** S1 cut MDD from 33.8% to 12.0% and 2022 from −18.2% to −3.9%, but earned
   only 3.6% CAGR — about 1.1 pp/yr over T-bills (BIL 2.45% CAGR on the same span). Its raw Sharpe (0.81) looks good only because half the book is T-bills.
2. **The 12% cap plus a 4-ETF T-bill basket leaves 12–14% of S1/S2 in 0%-yield cash.** Est. drag ≈ 0.3%/yr (13.7% × 2.45%; not run). The
   evidence doc's open governance question stands (a T-bill exemption or a larger basket). Fixing it would not change any verdict:
   S1 and S2 fail C2 by a wide margin.
3. **S3 is the closest.** It fails on two counts: MDD 14.8% (from 2020, when only DBMF existed) and DSR 0.90. Its excess Sharpe (0.73)
   is no better than SPY's (0.72): it is a lower-beta book, not alpha.
4. **Sector momentum (S2) is the weakest candidate.** It fails C1 at every neighbour, has the highest turnover, and adds nothing
   over S1 in combination.
5. The verdicts hold under either Sharpe definition: S1 and S2 fail C2, and S3 fails C1, regardless of rf.

## Recommendation

- **Deploy nothing from this lab to any book as a promoted strategy.** Per the registered rules: record the failure and do not tune.
- **If the owner wants a next step,** the only candidate worth a *new* pre-registration is an S3 v2 with lower equity beta, sized to
  meet MDD ≤ 12%. It would be trial #39+ on the same history, so any pass would be weaker evidence, not stronger. It also needs
  ≥ 90 days of paper before any capital decision.
- **P1/P3 do not get a replacement from S1/S2.** Their drawdown control is real, but the return over cash is too thin to clear DSR.

## Caveats

- **In-sample confirmation test, one regime.** The window is a decade of US-equity bull market with V-shaped crashes. Long-only trend
  is structurally weak at V-shaped crashes; 2008-type slow bears are not in the sample.
- Managed-futures history is short (all three funds only from 2022-03). ETF fees are inside the adjusted prices.
- Alpaca's adjustment puts SPY 2018 at −4.96% vs a published ≈ −4.6%. Other years match to ≤ 0.1 pp. The gap affects all symbols
  alike and changes no verdict.
- Uninvested cash earns 0%. Fills are at the official open with modelled friction, without partial fills or a limit-order miss model.
- The C5 combo test substitutes neighbours into component books (derived blends, not new trials).
