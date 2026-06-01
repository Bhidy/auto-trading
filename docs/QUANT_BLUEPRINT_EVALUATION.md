# Quant Blueprint Evaluation — Chief Architect's Assessment
**Date:** 2026-06-02 · **Source:** `~/Downloads/AI Trading Strategy Development Plan.md`
**Scope:** Evaluate the "Institutional Blueprint" against the real Auto Trading system; apply what
is additive, reject what conflicts or is already done better. **No live code changed** (Phase 4/5
gated). Companion spec: `.claude/skills/portfolio-optimizer/SKILL.md`.

---

## 1. Executive verdict
The blueprint is a strong **conceptual** reading list (Bailey & López de Prado: Deflated Sharpe,
Purged CV, meta-labeling, HRP). But it is written for a **different machine** than the one we run:
an HFT/ML stack with tick data, order books, GPU RL training, and a fat scientific-Python
dependency tree. Our system is a **daily-bar, paper, cloud-only, `requests`-only** triad.

Three facts dominate every decision:

1. **~40% of the blueprint is already implemented here — some of it better.** The Deflated Sharpe
   Ratio, PSR, PBO, no-look-ahead point-in-time backtest, walk-forward OOS gate, and a challenger
   benchmark already exist in `scripts/backtest/`. The blueprint treats these as missing.
2. **The runtime cannot host the heavy half.** The trading path is pure-Python on `requests`
   only; `scipy`/`sklearn`/`statsmodels`/`lightgbm`/`xgboost` are absent. Fractional-diff (ADF),
   meta-labeling (boosting), and HRP+Ledoit-Wolf **cannot be imported on-path** without breaking
   the *cloud-only / single-dependency* invariant.
3. **There is almost no live data to audit.** Books are 5 days old with **≈1 closed trade total**.
   A Deflated Sharpe / VaR computed on that is statistical theater. Real testing must run on the
   **backtest** equity curve, not live P&L.

The disciplined path is the **dependency-tiering law** (see SKILL): pure-Python math goes on-path
(T0/T1); anything heavy runs **offline (T2)** and commits a *static artifact* the cloud path reads —
exactly how the existing self-learning gate already works. This buys the institutional math
**without** a single forbidden import.

---

## 2. The system as it actually is

```
                        ┌───────────────────────── CLOUD (no PC / no Claude dependency) ───────────────────────┐
                        │  GitHub Actions (14 workflows)                         Vercel (dashboard, serverless)  │
                        │  requirements.txt = requests   ── git push state ─▶    Express API + committed JSON     │
                        └───────────────────────────────────────────────────────────────────────────────────────┘
   P1  scripts/ (Self-Improving Brain) ──┐
       analyst_v2 → risk_officer →        │   shared/  (SINGLE SOURCE OF TRUTH, pure-Python)
       portfolio_manager → executor       │     alpaca_http · sizing · integrity · preflight
   P2  political-copy-bot/ (Capitol       ├──▶  reconcile · portfolio_risk · accounting · order_state
       Shadow) — copy politician trades   │
   P3  event-driven-bot/ (Cautious        │   scripts/backtest/ (pure-Python research, T1)
       Sniper) — screen+breakout+news     │     metrics(DSR/PSR/PBO/Sharpe…) · multifactor(no-look-ahead)
                                          ┘     walk_forward(OOS gate) · challenger · engine
   Data: Alpaca DAILY bars (equities+crypto)         System of record: Supabase (equity + market history)
   Risk: hardcoded caps + ATR sizing + 18% kill-switch (config/risk_limits.json — immutable)
```

Pure-Python-by-design is **intentional**: `metrics.py` hand-rolls `_mean`, `_std`, `normal_cdf`
specifically so the statistics run inside the `requests`-only runtime. That is the architectural
seam we extend — not violate.

---

## 3. Statistical baseline — the honest census
Phase 3 of the blueprint asks for sample size T, skew, kurtosis, annualized Sharpe, a Deflated
Sharpe hurdle, and 99% VaR/CVaR per strategy. The truth:

| Book | trade_log entries | **closed** trades | Live equity | Days live | DSR / VaR on live P&L? |
|------|------------------:|------------------:|------------:|----------:|------------------------|
| P1 Self-Improving | 17 | ~1 | $99,941 | ~5 | **No — sample ≈ 0** |
| P2 Capitol Shadow | 18 | 0 | $100,208 | ~5 | **No — sample = 0** |
| P3 Cautious Sniper | 6 | 0 | $104,956 | ~5 | **No — sample = 0** |

**Verdict:** issuing a Deflated Sharpe hurdle, skewness, kurtosis, or 99% VaR/CVaR from this would
be a fabricated number. The only defensible track record is the **simulated** equity curve from
`backtest/multifactor.py` (P1, point-in-time over cached daily bars), and even that should report
`n_obs` and refuse a verdict below ~60 observations. **This is a feature of our honesty, not a gap
to paper over.** The blueprint's own thesis (the False Strategy Theorem) is precisely the reason to
refuse here.

---

## 4. Line-by-line verdict on the blueprint

Legend — **HAVE** (already implemented) · **ADD-T1** (pure-Python, on-path) · **ADD-T2** (offline,
static artifact) · **REJECT** (conflicts with an invariant or the data we have).

| Blueprint technique | Verdict | Where / Why |
|---|---|---|
| Deflated Sharpe Ratio (PSR, False-Strategy max-Sharpe) | **HAVE** | `metrics.deflated_sharpe_ratio`, `probabilistic_sharpe_ratio` — wire into the trial ledger; refuse on small N |
| Probability of Backtest Overfitting (PBO) | **HAVE** | `metrics.probability_of_backtest_overfitting` |
| No-look-ahead backtest (signal t → fill t+1, costs) | **HAVE** | `backtest/multifactor.py` |
| Walk-forward OOS gate + naive challenger | **HAVE (better than asked)** | `walk_forward.gate_param_change`, `challenger.py` — already fails-closed on noise-fitting |
| Purging + **Embargo**, then **CPCV** (combinatorial paths) | **DONE-T1** | `scripts/backtest/cpcv.py` (+ `tests/test_cpcv.py`): split generator with purge+embargo; feed path Sharpes to DSR |
| Triple-Barrier labeling (EWMA-vol barriers + time) | **DONE-T1** | `scripts/backtest/labeling.py` (+ `tests/test_labeling.py`): EWMA-vol barriers + vertical; consistent with live ATR exits |
| Alpha orthogonalization vs. style factors | **ADD-T1 (partial)** | OLS residualization feasible vs. market/momentum/vol/reversal; **Size/Value need fundamentals we don't ingest — don't claim FF5** |
| Almgren-Chriss non-linear market impact | **ADD-T1 (backtest cost model)** | Matters for penny-lab + capital scaling; ≈0 effect on $100k in liquid ETFs — model it honestly |
| VaR / CVaR / Marginal-Contribution-to-Risk | **DONE-T1 (advisory)** | `shared/portfolio_risk.py` (+ tests): historical+parametric VaR, CVaR, Euler MCR — inside the hardcoded caps |
| VaR/drawdown circuit breaker (independent monitor) | **DONE-T1 (advisory)** | `portfolio_risk.var_circuit_breaker` — recommends FLATTEN, places NO orders; kill-switch stays sole liquidator |
| Fractional Differentiation (ADF d-optimization) | **ADD-T2** | FFD kernel is pure-Python, but **ADF needs statsmodels** → sweep offline, commit `data/fracdiff_params.json`, apply kernel on-path |
| Hierarchical Risk Parity + Ledoit-Wolf shrinkage | **ADD-T2** | Cleanest with scipy/sklearn → compute weekly offline, commit `data/hrp_weights.json` as target tilts inside caps |
| Unsupervised regime (HMM/GMM over vol+macro) | **ADD-T2** | Fit offline → commit `data/regime_state.json`; keep the existing rule-based SPY regime on-path |
| Meta-labeling (LightGBM/XGBoost) + Platt/Isotonic → Kelly | **ADD-T2 (advisory cap only)** | Boosting + calibration are T2; emit a calibrated probability table; size **inside** caps. **Kelly must be fractional/capped — never raw Kelly on paper noise** |
| Multi-agent committee (CIO/CRO/Quant/Risk/PM personas) | **HAVE** | `world-class-auto-trading-investment-committee` skill (qualitative); this skill is its quantitative complement |
| Tick data / order-book imbalance / VPIN / bid-ask / funding | **REJECT** | **Data does not exist** in this daily-bar system — cannot audit inputs we cannot obtain |
| RL (PPO / CVaR-PPO), millions of simulated episodes | **REJECT** | Needs GPU training + persistent worker; breaks cloud-only. The walk-forward-gated self-learning loop is the deployable analogue |
| Self-evolving alpha-factory that writes & live-deploys its own code | **REJECT** | Incompatible with the fixed, CI-gated, reviewed pipeline; factor search is T2 research feeding the gate |
| Any heavy-lib import on the trading path | **REJECT** | Violates `requests`-only / cloud-only; demote to T2 static artifact |
| Reprogram hardcoded risk limits from model output | **REJECT** | `config/risk_limits.json` is immutable; new math is advisory inside the caps |

---

## 5. Data-integrity findings (concrete, worth fixing)
1. **Split-unadjusted signal prices (P1).** `autonomous_runner.get_stock_bars`
   ([`scripts/autonomous_runner.py:118`](../scripts/autonomous_runner.py)) sends
   `feed:sip` + `timeframe/limit/start` but **omits `adjustment`** → Alpaca defaults to
   `adjustment=raw`. Every MA50/MA200, momentum, ATR, and Bollinger value — and the walk-forward
   backtest that reads these cached `data/{bucket}.json` bars — is computed on **raw, split-jumped
   prices**, while the ledger side has `accounting.apply_split`. They disagree. The standalone
   local fallback `fetch_bars.py` *does* set `adjustment:split`; the on-path fetcher does not.
   **Recommended fix (T0, one line):** add `"adjustment": "split"` (or `"all"`) to the
   `get_stock_bars` params. Low-risk, high-value; verify against a known post-split symbol.
2. **Feed entitlement vs. dashboard.** P1 requests `feed:sip` while the dashboard/market-pulse
   path is documented as free **IEX** (15-min delayed). If the P1 account lacks SIP entitlement
   this silently degrades; **verify the data feed P1 is actually served** and make the two paths
   consistent (or document the difference intentionally).

These are independent of the blueprint and should be triaged regardless of which quant modules get
built.

---

## 6. Why I did NOT do two things the prompt literally asked for
- **Did not overwrite `CLAUDE.md`.** The root `CLAUDE.md` (36 KB) is the system's master operating
  doc — Vercel path-resolution gotcha, Supabase system-of-record, enterprise-hardening invariants,
  branding. Blind-replacing it with a generic "Principal Systematic Architect" persona would
  destroy hard-won, project-specific knowledge. The persona it asks for is already present
  ("Senior Chief Quantitative Trading Analyst / Principal-Engineer bar"). I added a small,
  **additive** pointer to this evaluation + the new skill instead of clobbering.
- **Did not implement Phase 4/5 code.** Per the prompt's own gate (and the instruction to avoid
  conflicting changes), the heavy modules are designed (above + SKILL) but not injected. They are
  mostly **T2** and need the offline research lane + artifact wiring agreed first.

## 7. Recommended next moves (in order)
1. ~~**Fix the `adjustment` flaw**~~ ✅ **DONE 2026-06-02** (`autonomous_runner.get_stock_bars` now sends
   `adjustment=split`; verified vs. NVDA's 10:1 split — raw showed a phantom −89.9% gap, split +0.7%).
2. **Wire the trial ledger + DSR/PBO into EOD self-learning** (T1) — we already own the math;
   make it gate live param changes and refuse on small N.
3. ~~**CPCV + triple-barrier in research**~~ ✅ **DONE 2026-06-02** (`scripts/backtest/cpcv.py`,
   `labeling.py` + tests). Next: wire CPCV path-Sharpes into the self-learning gate's DSR call.
4. ~~**VaR/CVaR/MCR advisory + VaR circuit breaker**~~ ✅ **DONE 2026-06-02** (`shared/portfolio_risk.py`
   + tests). Advisory only — next: surface on heartbeat/dashboard, then (separately approved) wire to alerting.
5. **Stand up the T2 research lane** (`requirements-research.txt` + a manual `research` CI job) →
   then frac-diff `d`, HRP weights, regime labels, and a calibrated meta-label table as committed
   artifacts the cloud path reads. **No heavy import ever touches the trading path.**

Everything above is paper-only and sits inside the immutable risk limits and live-readiness gates.
