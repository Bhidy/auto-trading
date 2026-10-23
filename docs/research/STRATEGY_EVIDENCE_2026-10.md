# Strategy Evidence Review — which systematic strategies actually earn their keep (2026-10)

> **Status:** research-lane evidence review. **Not investment advice. PAPER ONLY.** Nothing here changes a live
> parameter, risk limit or workflow. Every candidate below must go through the repo's normal path:
> pre-registered spec in `docs/specs/*.json` → offline backtest (T2 lane) → DSR/PBO gate → ≥90 days paper → `docs/LIVE_READINESS.md`.
>
> **Number labels used throughout:**
> `[lit]` = taken from the cited paper/source · `[proxy]` = an ETF or index's realised record ·
> `[repo]` = this repo's own measured result · `[est]` = my own estimate, *not verified* — must be measured before use.

---

## 1. Executive summary

**Verdict.** The strongest evidence for durable, cost-robust, out-of-sample excess *risk-adjusted* return that this
system can actually trade (long-only US ETFs, daily bars, monthly decisions, requests-only runtime) is
**multi-asset trend following with inverse-volatility sizing and a T-bill fallback**. Behind it come
**relative momentum on whole sectors and regions (sector/country ETFs, not single stocks), with an absolute-trend filter and risk scaling**, and
**a managed-futures (trend) ETF sleeve** that holds real long/short trend exposure we cannot build ourselves.
Single-stock factor ideas, congressional copy-trading, and post-earnings drift have weak evidence, or evidence we
cannot use, for a large-cap, free-data, low-trade-count book.

Five points the owner should take away:

1. **No strategy here reliably beats SPY on raw return in a bull market.** The realistic goal is SPY-like or slightly
   lower return with **roughly half the drawdown**. That gives a better Sharpe/Calmar ratio and, most importantly, keeps
   the book alive under our **18% kill switch**. Buying and holding SPY would itself have breached 18% in 2020 (about −34%), in 2022
   (about −25%) and in April 2025 (about −19%) `[proxy]`. **The kill switch therefore needs a mechanism that controls
   drawdown, whatever we think about alpha.** That is the strongest argument for trend/volatility overlays in this repo.
2. **Our own failures match the literature.** The 8-ETF equal-weight core lost in 2022 because it held long duration
   (TLT fell about −31%) and four equity ETFs, with no rule to step aside `[repo]`. The literature's answer is a trend filter
   whose fallback is **T-bills, not bonds**: stock–bond correlation turned positive in 2022, about +0.5 `[lit]`. P1's
   multi-factor stock score having no edge, and 12-1 single-stock momentum equalling equal-weight plus survivorship, also match
   the evidence: large-cap US single-stock momentum has been weak since 2009, and survivorship inflates it.
3. **Trend following works over a century but goes through cycles.** AQR's 1880–2013 time-series momentum earned a 0.77 net Sharpe
   with zero correlation to equities `[lit]`, but only 0.62 in 2000–2013 `[lit]`. The SG Trend Index made +20.9% (2008) and
   +27.4% (2022) `[lit]`, then fell −20.4% from May 2024 to May 2025, its second-worst drawdown since 2000 `[lit]`. Expect multi-year
   flat periods.
4. **Long-only ETF trend is not the same as managed futures.** Without shorts it cannot *profit* from falling bond or
   equity markets. It can only step aside into T-bills. Its job is to cut drawdowns, not to deliver crisis alpha. If we want
   crisis alpha, a small sleeve of managed-futures ETFs (DBMF/KMLM/CTA) is the implementable proxy. DBMF made about +21.5% in
   2022 `[proxy]`, but these funds have short histories, charge about 0.85–0.95% in fees, and lost money in 2023–2025 `[proxy]`.
5. **Honest long-run expectations for the recommended blend:** CAGR about 5–9%, volatility about 7–10%, Sharpe about 0.5–0.8,
   max drawdown about 10–18% `[est]`. Compare SPY over the long run: about 10% CAGR, about 16% volatility, Sharpe about 0.4–0.5,
   max drawdown about −50% to −55%. The 2016–2026 window that Alpaca data covers was unusually kind to SPY (Sharpe about 0.8–0.9 `[est]`). Judging any
   defensive strategy only on that window's Sharpe against SPY will under-rate it. Pre-register drawdown and Calmar criteria too.

**Top 3 to pre-register** (full specs in §4):
- **S1 `matf-v1`: multi-asset long-only trend.** 10 risky ETFs. Each one's trend score is the average of 4 votes (63/126/252-day
  return in excess of T-bills, plus price above its 200-day average). Weights are inverse-volatility, scaled down to an 8% portfolio
  volatility target, with a T-bill basket as fallback. Rebalanced weekly in 4 tranches. *Candidate P1 core.*
- **S2 `secmom-v1`: risk-managed relative momentum on sector and regional ETFs, with an absolute filter.** Top 6 of 13 by 12-1 and 6-1
  momentum. A name is held only if its own trend is positive, and sleeve volatility is capped at 12%. *Candidate P3 replacement.*
- **S3 `crisis-core-v1`: a static balanced core with a managed-futures sleeve.** Equity index ETFs + DBMF/KMLM/CTA + IEF + T-bills,
  rebalanced monthly with a band. *Candidate P2 base/ballast, with the congressional satellite kept small.*

---

## 2. Our constraints, and what they rule in or out

| Constraint | Consequence for strategy choice |
|---|---|
| Free IEX daily bars, about 10 years (about 2016–2026), adjusted bars available (`adjustment=all`) | Monthly/weekly signals on liquid ETFs are fine: IEX vs consolidated close noise is immaterial at that horizon. **2008 is not in the Alpaca sample.** Check 2008 behaviour offline (T2 lane) with free long-history sources: Ken French data library, AQR public datasets, index/mutual-fund proxies. |
| No fundamentals or earnings feed on the cloud path | Value, quality and PEAD at single-stock level would need a separate point-in-time fundamentals pipeline (`fetch_fundamentals_pit.py` exists in research only). **Factor ETFs are the only cheap proxy.** |
| No survivorship-free stock universe | Single-stock cross-sectional strategies get biased upward (already seen in our 112-name momentum test `[repo]`). **ETF universes are survivorship-safe**: sector SPDRs have existed since 1998. |
| 12% per ETF, 8% per stock, 55% mega-cap-tech cluster, 12 trades/day | No single ETF can hold the whole defensive allocation, so we need a **cash basket of ≥8 T-bill/short-Treasury ETFs** (or must accept 0%-yield broker cash). Monthly rebalances of 15–20 ETFs need no-trade bands and multi-day queuing to stay under 12 trades/day. |
| 160% gross, 25% short | Leverage and modest shorting are allowed, but **v1 specs are unlevered and long-only**. A short or overlay leg is a later, separately pre-registered variant. |
| Daily loss 4%, kill switch 18% DD | **Design target: max drawdown ≤ 12% in backtest**, leaving 6 points of margin for live drawdowns worse than the backtest. This alone rules out unhedged equity-beta books. |
| requests-only runtime, pure-Python | Everything in §4 needs only returns, rolling standard deviations, a small covariance matrix (≤13×13) and sorting, all trivially pure-Python. |
| Limit orders | ETF spreads are 1–3 bps. Use marketable limits (e.g. last ±0.3%) at the open. Model 5+5 bps per side (repo floor), with 20 bps per side as a stress case. |

---

## 3. Evidence by strategy family

### 3.1 Time-series momentum / trend following (multi-asset)

**Core evidence (grade A for the futures long/short version):**
- Moskowitz, Ooi & Pedersen (2012, JFE): 58 futures and forwards across all asset classes, 1985–2009. Each asset's own past
  12-month return predicts its next month's return. Returns persist for 1–12 months then partly reverse. Profits are largest in extreme markets
  ("crisis alpha") `[lit]`.
- Hurst, Ooi & Pedersen (2017, JPM), *A Century of Evidence*: an equal-weighted blend of 1/3/12-month trend signals, each position
  sized to equal volatility, portfolio volatility targeted at 10%. **Jan 1880–Dec 2013: 14.9% gross / 11.2% net of 2/20 fees, 9.7% volatility, net Sharpe
  0.77, correlation 0.00 to US equities and −0.04 to 10-year bonds.** Positive in every decade; 2000–2013 net Sharpe 0.62. Positive in 8
  of the 10 worst 60/40 drawdowns. An 80/20 blend of 60/40 and trend raised Sharpe from 0.38 to 0.54 and cut max drawdown from −62.3% to
  −50.2% `[lit]`.
- Baltussen, Swinkels & van Vliet (2021, JFE), *Global Factor Premiums*: 217 years (1800–2016) of asset-class factors. Trend
  and momentum premiums survive multiple-testing adjustments with **limited out-of-sample decay**, and are largely unrelated to
  macro or downside risk `[lit]`.
- Levine & Pedersen (2016, FAJ): time-series momentum and moving-average crossovers are equivalent in their general form. A
  12-month horizon beat 1- and 3-month horizons on 58 futures `[lit]`. **Implication:** Faber's 10-month SMA and the
  12-month return-sign rule are near-substitutes. Averaging several lookbacks reduces the risk of picking one by luck, but does not create edge.

**Critiques (the honest part):**
- Huang, Li, Wang & Zhou (2020, JFE): asset-by-asset predictability is weak. The pooled t-statistic fails bootstrap critical values.
  Much of the TSMOM profit can be matched by a strategy based on the historical mean, with no predictability needed `[lit]`.
- Kim, Tse & Wald (2016): much of the alpha comes from **volatility scaling**, which is close to risk parity. Monthly alpha falls
  from 1.27% to 0.41% without it, and the edge vanished in 2009–2013 `[lit]`.
- Goyal & Jegadeesh (2018, RFS): TSMOM beats cross-sectional momentum largely because it carries a time-varying net long
  position in risk assets `[lit]`. **For us this is fine.** We want "long risk assets while they trend up, T-bills otherwise".
  We just should not call it alpha.

**Recent record:** SG Trend Index **+20.9% in 2008, +27.4% in 2022** (MSCI ACWI −42.2% and −18.4%) `[lit]`. Then **−20.4% from May 2024 to
May 2025**, the second-largest drawdown since 2000. There have been 16 drawdowns >10% since 2000, roughly one every 18–24 months `[lit]`.

**Long-only ETF versions (what we can trade):**
- Faber (2007; updated 2013), *A Quantitative Approach to TAA*: 5 asset classes, each held only when above its 10-month SMA, otherwise
  T-bills. The trend rule cut max drawdown from about −46% to under −10% in the original sample `[lit]`. Faber's later revisit reports outperformance
  in 2008–09 but **underperformance vs stocks in 6 of the next 8 years** `[lit]`. An independent replication (200-day rule)
  found Sharpe 0.68 and 6.05% CAGR for 2006–Mar 2025, vs 0.81 and 11.7% in-sample for 1972–2005 `[lit]`. **This is clear post-publication decay in
  return, with the risk reduction largely intact.**
- Clare, Seaton, Smith & Thomas (2016, JBEF): 95 global indices in 5 asset classes, 1993–2015, gross. Equal-weight
  6.6% return / Sharpe 0.33 / max drawdown −46.6%. **10-month SMA trend: 8.0% / 0.79 / −11.6%.** Risk parity plus trend: 6.9% / 1.06 / −4.9%
  `[lit]`. In-sample, ends before 2022.

**2020 / 2022 behaviour of long-only trend `[est]`:** in 2020, monthly rules exit late (end of Feb/Mar) and re-enter late (May/June).
That gives a whipsaw of roughly −5% to −10% relative to buy-and-hold, and it is why we tranche. In 2022, equities, REITs, TLT and IEF all fell below trend
in Q1, so the book drifts to T-bills, commodities (DBC +~19% in 2022) and partly gold. A loss of roughly 0% to −8% is expected,
vs SPY −18%. It **cannot** earn the managed-futures +20–30% because it cannot short bonds.

**Turnover/costs:** with monthly decisions, roughly 100–300% one-way turnover per year `[est]`. At 10 bps per side that costs
0.2–0.6%/yr, so the strategy is cost-robust. AQR's own cost assumption for 2003–2013 was 1–10 bps one-way by asset class `[lit]`.

**Grade: A** for the phenomenon; **B+** for long-only ETF implementations, whose edge is mostly drawdown reduction.

### 3.2 Dual momentum / GEM (Antonacci 2014)
- Rule: at each month-end, compare US and ex-US stocks on 12-month total return. Hold the winner if it beats T-bills, otherwise hold aggregate bonds.
- Proponents report out-of-sample extensions for 1950–1973 and 2012–2018 `[lit, proponent source]`. **I found no
  independent, peer-reviewed post-2014 evaluation.** Newfound Research showed that results depend heavily on
  *rebalance-date luck* (which day of the month you trade), and that tranching across rebalance dates is the fix `[lit]`.
- Known failures: **2020**, where it switched into bonds as equities were recovering (whipsaw) `[lit]`; **2022**, where the fallback asset
  (aggregate bonds, AGG about −13%) was itself in a bear market `[proxy]`; and a binary all-in/all-out switch between two equity assets.
- **Grade: B−.** The ingredients (absolute plus relative momentum) are sound. The implementation is too concentrated and depends on its
  path. S1/S2 keep the ingredients and fix the flaws: a diversified universe, T-bill fallback, tranching and inverse-vol sizing.

### 3.3 Volatility-managed portfolios
- Moreira & Muir (2017, JF): scaling factor exposure by the inverse of last month's realised variance gives large alphas and higher Sharpe
  for market, value, momentum, profitability and other factors `[lit]`.
- **Cederburg, O'Doherty, Wang & Yan (2020, JFE):** across 103 equity strategies, the **real-time, implementable versions earn
  lower Sharpe and certainty-equivalent returns than unmanaged portfolios** most of the time. Momentum, ROE and BAB are the exceptions, and the cause is
  structural instability in the spanning regressions `[lit]`. Barroso & Detzel (2021) find the gains do not survive transaction costs
  for most factors `[lit]`.
- Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert (2018, JPM, Man AHL): volatility targeting **raises Sharpe for risk
  assets such as equities and credit** (the leverage effect), has negligible Sharpe effect for bonds/FX/commodities, and **thins the left tail and reduces max
  drawdowns in all asset classes** and in 60/40 and risk-parity portfolios `[lit]`.
- Bongaerts, Kang & van Dijk (2020, FAJ): *conventional* volatility targeting does not consistently help global equities and can
  *increase* drawdowns. **Conditional** targeting, which acts only in extreme volatility states, improves Sharpe and drawdown at lower turnover
  `[lit]`.
- **For a long-only, unlevered ETF book:** volatility targeting can only *de-risk* (scaler ≤ 1). That makes it a tail-risk tool, not an alpha source.
  Use it as a cap ("never more than X% vol"), not as a return engine. **Grade: B** for tail and drawdown control; **C** as alpha.

### 3.4 Cross-sectional momentum improvements
- **Momentum crashes** (Daniel & Moskowitz 2016, JFE): crashes happen in "panic" states, after market declines with high volatility, at the
  rebound. In Mar–May 2009 past losers rose about 163% while past winners rose about 8% `[lit]`. A dynamic version that scales on forecast mean and variance roughly
  doubles Sharpe `[lit]`.
- **Risk-managed momentum** (Barroso & Santa-Clara 2015, JFE): scaling the momentum factor to constant volatility (6-month realised)
  nearly eliminates crashes and raises Sharpe from about 0.53 to 0.97, 1927–2011 `[lit]`. This is one of the few cases where Cederburg et al.
  find volatility management survives out of sample.
- **Residual momentum** (Blitz, Huij & Martens 2011, JEF): ranking on factor-model residual returns roughly doubles risk-adjusted return
  (gross Sharpe about 0.90 vs 0.45, 1926–2009) `[lit]`. Huij & Lansdorp (2017) out-of-sample (2009–2015): still better than plain momentum,
  but **both are unattractive in US stocks** post-publication `[lit]`.
- **Industry and country momentum:** Moskowitz & Grinblatt (1999) show much of stock momentum is industry momentum. Asness, Moskowitz &
  Pedersen (2013) find momentum across country indices and asset classes `[lit]`. Industry and country ETFs give **survivorship-free,
  low-cost, low-trade-count** access to this.
- **Implementability:** single-stock large-cap momentum with free data has survivorship bias (no point-in-time index
  membership), an 8% name cap, a 12 trades/day limit, and weak US evidence after 2009. Our own 112-stock test found it about equal to equal-weight plus
  survivorship `[repo]`. MTUM 2021–2026: Sharpe 0.73 vs SPY 0.74 `[repo]`. Over about 10 years MTUM's cumulative return was about 391% vs SPY about 325%
  `[proxy]`, so beta and tech exposure explain most of it, and it is not robustly risk-adjusted.
- **Grade: B** for sector/country ETF momentum with an absolute filter and risk scaling. **C** for single-stock momentum in this system.

### 3.5 Low volatility / BAB, quality/profitability, value
- **Low-volatility/BAB:** Frazzini & Pedersen (2014) BAB. Novy-Marx & Velikov (2022, JFE), *Betting Against Betting Against
  Beta*: BAB's returns come from non-standard construction that equal-weights in effect. It holds about $1.05 per dollar in the smallest 1% of stocks.
  Net of costs it is positive mainly because it loads on profitability and investment `[lit]`. **ETF reality:** USMV fell about 9% in 2022 vs SPY
  about 18–20%, but returned about 45% vs 92% over five years `[proxy]`. It is a lower-beta equity holding, not alpha in a bull market. It also carries
  rate risk as a bond proxy.
- **Quality/profitability:** Novy-Marx (2013, JFE): gross profits-to-assets predicts returns about as strongly as book-to-market
  `[lit]`. Jensen, Kelly & Pedersen (2023, JF): most factors replicate (more than 80% of US factors stay significant under alternative constructions), cluster into 13
  themes, and hold up across 93 countries `[lit]`. QUAL-type ETFs deliver a mild, low-tracking-error tilt. Free-data stock-level
  implementation is not possible without point-in-time fundamentals.
- **Value:** strong long-run premium (Baltussen et al.; Asness et al. 2013), but the worst factor drawdown on record ran from 2007 to 2020,
  followed by a 2021–22 rebound `[lit]`. VLUE's construction differs from academic HML. Expect long dry spells.
- **Replication and decay discipline:** McLean & Pontiff (2016, JF): anomaly returns are 26% lower out-of-sample and 58% lower after publication
  `[lit]`. Hou, Xue & Zhang (2020, RFS): 65% of 452 anomalies fail |t| ≥ 1.96 once microcaps are handled, 82% at the multiple-testing
  hurdle. Effects that survive are smaller than first reported `[lit]`. Harvey, Liu & Zhu (2016, RFS): a new factor needs t ≳ 3.0 `[lit]`.
  Novy-Marx & Velikov (2016, RFS): most anomalies with under 50% monthly turnover survive costs. Few with higher turnover do `[lit]`.
- **Grade: B** for the premia existing; **C** for "an ETF tilt adds risk-adjusted return over SPY in our window". Use them at most
  as equity building blocks inside S1/S2/S3, not as a standalone sleeve.

### 3.6 Risk parity / All-Weather vs 60/40 vs SPY
- Long-run case: equalising risk across asset classes gives a higher Sharpe than capital-weighted 60/40. Clare et al. find risk-parity Sharpe 0.67 vs
  equal-weight 0.33 (1993–2015, gross) `[lit]`.
- **2022 was the stress test it failed:** the HFR Risk Parity index fell −19.5% and most products trailed 60/40's −16.1%. AQR's risk parity fund fell −10.5%
  (peer-leading). Bridgewater's All Weather had its worst drawdown on record, roughly −22% `[lit]`. Stock–bond correlation was about +0.5 `[lit]`. Leverage on duration is
  the weak point. **Unlevered** risk parity under our 12% caps is mostly bonds and T-bills, so return is low and it is still hit by inflation.
- **Grade: B** as a diversification principle, **C** as a standalone book. Use its *sizing idea* (inverse-vol) inside S1 with a trend
  filter, which is exactly the combination Clare et al. found best `[lit]`.

### 3.7 Congressional trading (P2's thesis)
- **Pre-STOCK Act, trade-date returns:** Ziobrowski et al. (2004, JFQA): Senate purchases beat the market by 85 bps/month, 1993–1998 `[lit]`.
  Ziobrowski et al. (2011, Business & Politics): House purchases beat it by 55 bps/month, 1985–2001 `[lit]`.
- **Contradicting:** Eggers & Hainmueller (2013, JOP): the average congressional portfolio trailed a passive index by 2–3%/yr in 2004–2008, and
  members showed no information advantage. Only local and donor-linked holdings outperformed `[lit]`.
- **Post-STOCK Act:** Belmont, Sacerdote, Sehgal & Van Hoek (NBER w26975, 2020; published 2022): Senate purchases from 2012 to 2020
  slightly *lagged* matched benchmarks (−11/−28/−17 bps at 1/3/6 months) `[lit]`. A 2020–2024 House study using **disclosure dates**
  (5,225 purchases) found **significantly negative** 20- and 40-day CARs and about −40 bps/month alpha after costs `[lit — authors and venue not verified]`.
  A 2024 Utrecht thesis (2020–2023) found no significant abnormal returns `[lit, weak]`.
- **The one strong positive:** Wei & Zhou (NBER w34524, 2025), *"Captain Gains"*: lawmakers who become **leaders** outperform matched
  peers by about 47 points/yr *after* gaining leadership, through influence and corporate-access channels. The effect persists after the STOCK Act `[lit]`. **Caveat: transaction-level
  data. It was not shown to be capturable after the up-to-45-day disclosure lag (not verified).** There were only about 20 leaders in 1995–2021, so N is tiny.
- **ETFs:** NANC (Democrat trades) beat the S&P from 2023 to mid-2024 and returned about +20.8% in 2025. KRUZ (Republican trades) lagged in 2023–24 and returned about +18.8% in 2025
  `[proxy]`. NANC is heavily weighted to mega-cap tech, so its outperformance is plausibly sector beta. No factor-adjusted alpha has been verified.
- **Our data:** P2 scorecard N = 3 post-cohort round trips (alpha t = −1.19), 34 honest trials, INSUFFICIENT_N `[repo]`.
- **Grade: C.** Mixed evidence that decays over time, with the best recent evidence pointing to zero or negative returns after disclosure. If P2 continues, it should be
  a **small satellite** (≤20–30% of the P2 book), restricted ex ante to the most defensible sub-signal (leadership, committee-relevant, cluster
  buys), measured against a pre-registered N ≥ 50 gate. The rest of P2 should sit in S3.

### 3.8 Post-earnings-announcement drift and event strategies
- Martineau (2022, Critical Finance Review): **PEAD has been non-existent in large stocks since about 2006** and has recently disappeared in
  microcaps too `[lit]`. Two 2025 papers (Dickerson, Julliard & Mueller, JFE; Hirshleifer, Peng & Wang, RFS) say it is alive. Subrahmanyam
  shows that for Feb 2001–Dec 2024 the drift-factor t-statistic falls from 2.18 to **1.43 once microcaps are removed** `[lit]`.
- It needs a point-in-time earnings and estimates feed that we do not have on the cloud path, plus single-stock trades limited by the 8% cap and 12 trades/day.
- P3's breakout/news sleeve showed no edge `[repo]`, consistent with this.
- **Grade: C/D for large caps. Do not pursue.**

### 3.9 Crypto (≤10% cap)
- Liu & Tsyvinski (2021, RFS) document strong time-series momentum in crypto `[lit]`. The sample is short, the asset has a single regime history, and volatility is
  about 60–80%. **Grade: C.** At most, an optional ≤5% trend-filtered BTC sleeve inside S1's risk budget, pre-registered separately. Not
  recommended for v1.

---

## 4. Ranked candidates

Expected ranges are long-run, net of 10 bps per side, unlevered, long-only unless stated. They are **literature-informed estimates `[est]`, not
promises.** 2008/2020/2022 entries are `[lit]`/`[proxy]` where a source exists, else `[est]`.

| # | Candidate | Evidence | Sharpe | CAGR | Max DD | 2008 | 2020 | 2022 | Turnover (1-way/yr) | Implementable here? |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Multi-asset long-only trend, inverse-vol, T-bill fallback (S1)** | **A/B+** | 0.5–0.8 | 5–8% | 10–18% | small loss to flat (Faber-type ≈ −10% or better) `[lit/est]` | whipsaw, −5 to −10% vs B&H `[est]` | ≈ 0 to −8% (drifts to bills, commodities) `[est]` | 100–300% | **Yes.** ETFs, monthly, pure-Python. Needs a ≥8-ETF T-bill basket. |
| 2 | **Managed-futures ETF sleeve (DBMF/KMLM/CTA) inside a balanced core (S3)** | A (strategy) / B (replicators) | 0.4–0.7 (blend) | 5–8% | 12–20% | MF +20.9% (SG Trend) `[lit]` | MF mixed `[est]` | DBMF ≈ +21.5% `[proxy]`; SG Trend +27.4% `[lit]` | low (static mix) | **Yes.** But ETF histories only start 2019–22, fees 0.85–0.95%, 2023–25 weak. |
| 3 | **Sector/region ETF relative momentum + absolute filter + vol cap (S2)** | B | 0.5–0.8 | 6–10% | 12–22% | filter → mostly bills `[est]` | whipsaw, then strong tech/discretionary `[est]` | energy/staples/utilities winners; filter → bills `[est]` | 150–400% | **Yes.** Survivorship-free; XLC/XLRE history is short. |
| 4 | Conditional volatility-target overlay on equity | B (tails) / C (alpha) | ≈ SPY Sharpe ±0.1 | below SPY | ~20–30% | cuts exposure late `[est]` | cut after first leg `[est]` | partial help `[est]` | 50–150% | Yes, as a **cap inside S1–S3**, not standalone. |
| 5 | Low-vol / quality factor ETFs (USMV, SPLV, QUAL) | B / C | ≈ SPY ±0.1 | 7–10% | 30–40% | −25 to −35% `[est]` | −30%+ `[est]` | USMV ≈ −9% `[proxy]` | ~20% | Yes, as equity building blocks only. |
| 6 | GEM / dual momentum | B− | 0.4–0.7 | 6–10% | 15–25% | in bonds, OK `[lit]` | whipsaw into bonds `[lit]` | bond fallback lost ≈ −13% `[proxy]` | ~100% | Yes, but superseded by S1/S2. |
| 7 | Unlevered risk parity / All-Weather | B / C | 0.4–0.6 | 3–6% | 15–25% | good (bonds rallied) | OK | **bad** (−13% to −22% for levered peers) `[lit]` | low | Yes, but low return under caps. Use only its inverse-vol idea. |
| 8 | Large-cap single-stock momentum (residual/risk-managed) | B (lit) / C (here) | 0.3–0.6 | ≈ SPY | 25–40% | crash risk `[lit]` | Nov-2020 reversal `[est]` | −18% (MTUM-like) `[est]` | 200–400% | **Poor.** Survivorship, caps, trade limits. |
| 9 | Value (stock-level or VLUE) | B (long-run) / C | 0.3–0.5 | ≈ SPY | 35–55% | very bad | very bad | relative win `[est]` | ~50% | Poor without point-in-time fundamentals. |
| 10 | Congressional copy (P2) | C | unknown (≈0 post-disclosure) | — | — | n/a | n/a | n/a | high | Yes technically; **evidence weak**. Small satellite only. |
| 11 | PEAD / earnings events | C/D | ≈0 for large caps `[lit]` | — | — | — | — | — | very high | **No** (no earnings feed; effect gone in large caps). |
| 12 | Crypto TSMOM | C | unknown | — | 30–60% | n/a | — | BTC ≈ −64% B&H `[proxy]` | med | ≤5% optional, later. |

---

## 5. Pre-registration specs for the top 3

Shared conventions for S1–S3. These must be fixed in each `docs/specs/*.json` **before** any bar is evaluated:

- **Data:** Alpaca daily bars, `adjustment=all` (total return), IEX feed. Warm-up is 252 bars, so the evaluation span starts about 2017.
  **Second dataset (T2 lane, offline only):** long-history proxies (index or mutual-fund total-return series) back to at least 1998 to observe
  2000–02 and 2008. Its provenance and survivorship must be stated, and it is reported separately, never pooled.
- **Signal timing:** all signals use closes up to and including t−1. **Execute at the next open** (t) with marketable limit orders. No intrabar
  information.
- **Friction:** `scripts/backtest/friction.py` floor of 5 bps cost + 5 bps slippage per side. **Stress case: 20 bps per side.**
- **T-bill basket (all specs):** fill in this priority order, each ≤ 11.4% (= 12% × 0.95):
  `BIL, SHV, USFR, TFLO, GBIL (from 2016-09), SGOV (from 2020-06), SHY, SCHO, VGSH`. Any remainder above basket capacity
  is broker cash, modelled at 0%. *(Governance question for the owner, not a change: should T-bill ETFs get a documented exemption from
  the 12% ETF cap? Today the cap forces the 9-ETF basket.)*
- **Trade-count discipline:** a no-trade band of |target − current| < 1.5% of equity means no trade (except to zero a position whose target is 0).
  Sells go before buys. If more than 12 orders are needed, queue the rest to the next session in order of |Δw|.
- **Tranching:** where specified, the book target is the **mean of the last 4 weekly target vectors**. This cuts rebalance-date luck (Newfound Research).
- **Honest trial count:** each spec starts at `n_trials = 1`. Every variant run (including the robustness grid) increments N, and the
  DSR is computed with that N.
- **Acceptance criteria (proposed; fix before the run):** on the Alpaca span, net of friction:
  - **C1** Max drawdown ≤ **12%** (design target; LIVE_READINESS hard limit is 15%).
  - **C2** Calmar ≥ SPY Calmar on the same span.
  - **C3** Sharpe ≥ 0.5 **and** DSR ≥ 0.95 at the honest N.
  - **C4** 2022 calendar return ≥ SPY 2022 + 8 pp.
  - **C5** Robustness: every neighbouring grid point (below) keeps Sharpe within 0.15 of the main spec and max drawdown ≤ 15%. No parameter cliffs.
  - **C6** The 20 bps stress case still passes C1 and C3 (Sharpe ≥ 0.4 allowed).
  - **Not** a criterion: beating SPY's CAGR or Sharpe over 2017–2026 (a one-regime bull window).
  Passing promotes the spec to ≥ 90 days of **paper** forward testing, not to live.

### S1 — `matf-v1`: multi-asset long-only trend (candidate P1 core)

| Item | Spec |
|---|---|
| Risky universe (10) | **SPY** (US large), **IWM** (US small), **EFA** (developed ex-US), **EEM** (EM), **VNQ** (US REIT), **IEF** (7–10y UST), **TLT** (20y+ UST), **TIP** (TIPS), **DBC** (commodities), **GLD** (gold). All trade from ≤ 2007, so they are survivorship-safe. |
| Defensive | T-bill basket (shared conventions). |
| Trend score | For each risky i at each weekly snapshot (last close of the week): `x_k = R_i(k) − R_BIL(k)` for k ∈ {63, 126, 252} trading days (total return), and `v_sma = 1[close > SMA_200]`. **T_i = mean(1[x_63>0], 1[x_126>0], 1[x_252>0], v_sma) ∈ {0, .25, .5, .75, 1}.** |
| Volatility | σ_i = stdev of daily log returns over 63 days × √252, floored at 2%. |
| Raw weights | `w_i = T_i · (1/σ_i) / Σ_j (1/σ_j)` (inverse-vol share of the full 10-asset set; an asset in downtrend leaves its share in T-bills). |
| Caps | w_i ≤ 11.4%. Excess goes to the T-bill basket; it is **not** redistributed to other risky assets. Mega-cap cluster is not binding (no QQQ/XLK). |
| Portfolio vol cap | σ_p from a 126-day sample covariance of risky weights. Scale `k = min(1, 0.08/σ_p)`, so it only de-risks. Final `w_i·k`, remainder to T-bills. **No leverage.** |
| Rebalance | Weekly target snapshot. Book target = mean of last 4 snapshots (tranching). Trade at the first session's open of the next week, subject to the 1.5% band. |
| Expected turnover / cost | 100–300% one-way/yr, costing ≈ 0.2–0.6%/yr at 10 bps per side `[est]`. |
| Robustness grid (counts as trials) | Lookback sets {42,105,210}/SMA150 and {84,168,315}/SMA250; vol target 6% / 10%; σ window 42 / 126; band 1% / 2.5%. |
| Expected (long-run) `[est]` | CAGR 5–8%, vol 6–9%, Sharpe 0.5–0.8, max drawdown 10–18%. 2022: about 0 to −8%. 2020: whipsaw cost. Bull years: lags SPY by 5–15 pp. |
| Why it fixes the 8-ETF core | Same diversified building blocks, but TLT/IEF/VNQ/equities **exit to T-bills** when trending down (all did in H1 2022), and sizing is by risk, not by capital. |

### S2 — `secmom-v1`: sector/region relative momentum with absolute filter (candidate P3 replacement)

| Item | Spec |
|---|---|
| Universe (13) | **XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY** (since 1998), **XLRE** (from 2015-10), **XLC** (from 2018-06), **EFA, EEM**. An ETF is eligible only after 273 bars of its own history. |
| Relative score | `mom_12_1 = P(t−21)/P(t−252) − 1`; `mom_6_1 = P(t−21)/P(t−126) − 1`. Score = mean of the cross-sectional **percentile ranks** of the two. |
| Selection | **Top 6** by score. A selected ETF is held only if its **own** `R(252) − R_BIL(252) > 0` **and** close > SMA_200 (absolute filter). Otherwise its slot goes to T-bills. Holding buffer: an incumbent stays while ranked ≤ 8 and passing the filter (cuts turnover; Novy-Marx–Velikov buy/hold spread). |
| Weights | Inverse 63-day vol among held names, scaled to sum to 6 × 11.4% = 68.4%, each capped at 11.4%. XLK counts toward the 55% mega-cap-tech cluster (non-binding at ≤ 11.4%). |
| Risk management (Barroso–Santa-Clara style) | Sleeve realised vol over 126 days on the held weights. Scale `k = min(1, 0.12/σ_sleeve)`. Remainder to T-bills. |
| Rebalance | Weekly snapshots, 4-tranche mean, 1.5% band, next-open execution. |
| Robustness grid | Top 4 / top 8; lookbacks 9-1 & 3-1; buffer rank 7 / 9; vol cap 10% / 15%. |
| Expected `[est]` | CAGR 6–10%, vol 9–13%, Sharpe 0.5–0.8, max drawdown 12–22% (C1 may bind; if it fails C1 at the main spec, **do not tune** — record the failure). |
| Known risks | Sector momentum crashes at sharp V-shaped reversals (Mar–May 2009, Nov 2020 `[lit/est]`). XLC/XLRE have short histories. 13 assets is a narrow cross-section, so expect noisy relative signals. |

### S3 — `crisis-core-v1`: balanced core with a managed-futures sleeve (candidate P2 base, with the congress satellite capped)

| Item | Spec |
|---|---|
| Holdings & weights | **Equity 45.6%:** SPY, QQQ, IWM, EFA at 11.4% each. **Managed futures 34.2%:** DBMF, KMLM, CTA at 11.4% each (before CTA's 2022-03 listing, split equally across the available ones, each ≤ 11.4%, remainder to IEF). **Ballast 20.2%:** IEF 11.4% + T-bill basket 8.8%. |
| Rule | Static strategic weights. **Monthly** rebalance on the first session's open, with a 2% band. No signals. The trend exposure lives inside the MF ETFs. |
| Optional variant (separate spec and trial) | Wrap the equity 45.6% in S1's trend score (T_i), with the off-trend share going to T-bills. |
| Turnover / cost | About 20–40%/yr, ≈ 0.05%/yr trading cost. **Fund fees ≈ 0.85–0.95% on 34% ≈ 0.3%/yr drag.** |
| History limits | DBMF from 2019-05, KMLM from 2020-12, CTA from 2022-03, so there are **≤ 5–7 years** of real data. For the T2-lane long-history check, proxy MF with the SG Trend Index (if licensed and obtainable) or AQR's public TSMOM factor series, labelled as proxy. |
| Illustrative 2022 `[est]` | Equity 45.6% × ≈ −18% ≈ −8.2 pp; MF 34.2% × ≈ +15% to +25% ≈ +5 to +8.6 pp; IEF ≈ −1.7 pp; bills ≈ +0.1 pp, for a book total of ≈ −5% to −1% vs SPY ≈ −18%. **Not a backtest. Must be measured.** |
| Expected `[est]` | CAGR 5–8%, vol 8–11%, Sharpe 0.4–0.7, max drawdown 12–20%. The weakness is long dry spells when trend sleeves lose (2023–25 `[proxy]`). |
| Congress satellite | If P2 keeps copying, the satellite is ≤ 25% of P2 equity, funded pro rata from S3. P2 scorecard gate (N ≥ 50, alpha t ≥ 2, DSR ≥ 0.95) decides survival. |

---

## 6. Combining sleeves — what maximizes Sharpe/Calmar

- **The diversification math:** trend (S1/S3-MF) has ≈ 0 long-run correlation to equities and rises in prolonged bear markets `[lit]`. Relative
  momentum (S2) is equity-beta-heavy, with expected correlation to SPY of ≈ 0.7–0.85 when invested `[est]`. Correlation between S1 and S2 is moderate
  (≈ 0.5–0.7 `[est]`) because both are trend-conditioned. The biggest Sharpe/Calmar gain comes from pairing **something that holds equity risk
  in uptrends** with **something that is flat or positive in slow bear markets**.
- **Suggested firm-level mix (three $100K books):** P1 = S1, P3 = S2, P2 = S3 (+ ≤ 25% congress satellite). This gives roughly 35–45%
  average equity beta at firm level and three structurally different engines that are each testable alone.
- **Firm-level expectation `[est]`:** CAGR about 6–9%, vol about 7–10%, Sharpe about 0.6–0.9, max drawdown about 10–16%. The literature anchor for the
  ceiling is the AQR 80/20 example (Sharpe 0.38 → 0.54) `[lit]`. Clare et al.'s risk parity + trend Sharpe of 1.06 is gross, in-sample and pre-2022, so treat it as an
  **upper bound, not a forecast**.
- **What not to do:** do not stack several timing overlays on the same equity exposure (trend × vol-target × regime × drawdown stop). Each
  extra rule adds trials and whipsaw. Do not add leverage to "catch up" to SPY until 90+ days of paper evidence exist and the owner
  explicitly approves a levered spec.

---

## 7. Honest caveats

1. **No strategy guarantees outperformance.** Each premium above went through a multi-year losing stretch inside its own sample:
   trend 2011–2013 and May 2024–May 2025, value 2007–2020, momentum 2009.
2. **Decay is real.** Expect about 25–60% of published edges to disappear after publication (McLean–Pontiff) `[lit]`. Faber-type trend return
   fell from about 11.7% to about 6% CAGR after 2005 in an independent replication `[lit]`. Use the lower half of every range above.
3. **The 2016–2026 window is one regime:** a long US-tech bull run with three fast crashes (2018Q4, 2020, Apr-2025) and one inflation bear (2022).
   Monthly trend is structurally bad at fast V-shaped crashes. Ten years cannot tell skill from luck at Sharpe 0.6, since the t-stat is ≈ 0.6·√10 ≈ 1.9.
   **Paper time and long-history proxies are mandatory, not optional.**
4. **Prior-knowledge contamination:** these specs were written knowing 2022's outcome and our own 8-ETF result. The Alpaca run is
   therefore a **confirmation test**, not a blind out-of-sample test, and must say so (as `passive_core_v2.json` already does).
5. **Regime risk:** if stock–bond correlation stays positive (inflation regime), bond ballast (IEF in S3) fails as it did in 2022. If markets chop
   without trends, S1/S3 bleed slowly. If momentum crashes, S2 gives back fast.
6. **Implementation drag that is easy to miss:** 0% yield on uninvested broker cash, ETF fees (MF ETFs ≈ 0.9%), IEX-only prints,
   partial fills on limit orders at the open, and the 12 trades/day queue delaying de-risking by a session.

---

## 8. What the investment-committee skill should add

**8.1 Evidence hierarchy (score every proposed strategy or parameter change):**

| Tier | Requirement | Examples |
|---|---|---|
| **A** | Effect documented over decades **and** several asset classes or countries; survives post-publication out-of-sample tests; independent replications; plausible risk or behavioural story; |t| ≥ 3. | Trend/TSMOM (Hurst et al.; Baltussen et al.), cross-asset momentum. |
| **B** | Peer-reviewed, replicated, but contested or decayed, or sensitive to construction or costs. | Vol targeting, BAB/low-vol, value, profitability, residual/risk-managed momentum, GEM. |
| **C** | Single study, thesis, vendor/ETF marketing, short sample, or contradicted by newer evidence. | Congressional copy post-STOCK Act, PEAD in large caps, crypto TSMOM. |
| **D** | Our own in-sample backtest only, any vendor "Sharpe > 1.5" claim, or forum backtests. | QuantConnect copy-congress Sharpe ≈ 0.9–1.05 claims. |

Rule: **no capital (even paper promotion) on D. C only as a satellite ≤ 25% of one book. A/B only via pre-registered spec.**

**8.2 Overfitting red flags (any two → REJECT or "research only"):**
- Backtest Sharpe > 1.2 for a long-only daily-bar ETF/stock strategy, or > 1.5 for anything. That is above what 100-year evidence supports.
- Honest trial count unknown, or DSR < 0.95 at the honest N, or PBO > 0.5 (the repo already computes these; `scripts/backtest/metrics.py`).
- Performance collapses at neighbouring parameters (a parameter cliff), at a different rebalance day (timing luck), or at 2× costs.
- The universe was chosen with hindsight (today's survivors or today's winners), or single-stock tests ran without point-in-time membership.
- Result depends on one regime or year (e.g. all excess return from 2022, or only from the 2023–25 tech run).
- Signal uses the bar it trades on (look-ahead), or fills at the close the signal was computed on.
- Turnover > 50%/month with costs under 10 bps per side, or no cost stress.
- "Explains" a known factor (beta, tech, size) as alpha. Require a regression on SPY plus a sector or factor proxy before calling anything alpha.

**8.3 Regime rules (advisory inputs, never overriding hard limits):**
- **Trend state per asset:** the S1 score T_i. The committee should veto *adding* to an asset with T_i ≤ 0.25 unless the spec explicitly says otherwise.
- **Volatility state:** if 21-day realised SPY vol is above its 90th percentile over 5 years, require the de-risking scaler (k < 1) to be applied, not overridden.
  Conditional, extremes-only volatility management (Bongaerts et al.) is preferred to continuous retuning.
- **Stock–bond correlation state:** if the 63-day SPY–IEF daily-return correlation is > +0.3, bonds are **not** a hedge. The defensive asset
  becomes T-bills only.
- **Kill-switch compatibility test:** any new book must show backtest max drawdown ≤ 12% (with 6 points of margin to the 18% kill switch), plus a
  one-week −10% equity shock scenario that does not breach the 4% daily stop more than once.
- **Momentum crash state:** if the market is down > 20% from its 1-year high **and** 21-day vol is in the top decile, relative-momentum sleeves (S2)
  scale to half until vol normalises (Daniel–Moskowitz panic state).

---

## 9. References

**Trend / time-series momentum**
- Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum", *JFE* 104(2). Abstract: https://academicnewsletter.sufe.edu.cn/info/356810
- Hurst, Ooi & Pedersen (2017), "A Century of Evidence on Trend-Following Investing", *JPM*. https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing (PDF used: https://www.TrendFollowing.com/whitepaper/Century_Evidence_Trend_Following.pdf)
- Baltussen, Swinkels & van Vliet (2021), "Global Factor Premiums", *JFE* 142(3). https://papers.ssrn.com/abstract=3325720
- Levine & Pedersen (2016), "Which Trend Is Your Friend?", *FAJ* 72(3). https://research.cbs.dk/en/publications/which-trend-is-your-friend/
- Huang, Li, Wang & Zhou (2020), "Time Series Momentum: Is It There?", *JFE* 135(3). https://alphaarchitect.com/an-empirical-challenge-for-trend-following/
- Kim, Tse & Wald (2016), "Time series momentum and volatility scaling", *J. Financial Markets*. Summary: https://quantpedia.com/deconstructing-the-time-series-momentum-strategy/
- Goyal & Jegadeesh (2018), "Cross-Sectional and Time-Series Tests of Return Predictability: What Is the Difference?", *RFS* 31(5).
- Faber (2007/2013), "A Quantitative Approach to Tactical Asset Allocation", *JWM*; revisit summary: https://www.etf.com/sections/index-investor-corner/swedroe-why-financial-trends-persist ; independent replication: https://concretumgroup.substack.com/p/global-tactical-asset-allocation
- Clare, Seaton, Smith & Thomas (2016), "The Trend Is Our Friend: Risk Parity, Momentum and Trend Following in Global Asset Allocation", *JBEF* 9. https://openaccess.city.ac.uk/id/eprint/17841/ ; summary: https://cxoadvisory.com/?p=21860
- Cambridge Associates (2025), "Does Trend-Following's Recent Struggle Signal That the Strategy Is Structurally Broken?" https://www.cambridgeassociates.com/insight/does-trend-followings-recent-struggle-signal-that-the-strategy-is-structurally-broken/
- Top Traders Unplugged, trend performance reports (SG Trend Apr-2025 −4.89%): https://www.toptradersunplugged.com/?p=17165
- Bloomberg/BNN (2022), AQR trend funds' 2022: https://ampvideo.bnnbloomberg.ca/aqr-trend-following-strategies-return-as-much-as-70-in-big-year-1.1829254
- DBMF record: https://stockanalysis.com/etf/dbmf ; https://totalrealreturns.com/n/DBMF ; KMLM: https://www.mutualfunds.com/etfs/kmlm-kfa-mount-lucas-index-strategy-etf/

**Dual momentum**
- Antonacci (2014), *Dual Momentum Investing* (McGraw-Hill). Robustness discussion: https://hedgefundalpha.com/investment-strategy/is-gary-antonaccis-global-equity-momentum-strategy-robust ; ReSolve "Craftsman's perspective": https://www.advisorperspectives.com/articles/2019/05/06/global-equity-momentum-a-craftsmans-perspective ; COVID whipsaw note: https://freefloat.substack.com/p/global-equities-momentum
- Newfound Research, rebalance timing luck / tranching: https://blog.thinknewfound.com/tag/rebalance-timing-luck/
- Keller & Keuning, PAA/DAA (canary universes): https://www.cxoadvisory.com/strategic-allocation/multi-class-momentum-portfolio-with-canary-crash-protection/

**Volatility management**
- Moreira & Muir (2017), "Volatility-Managed Portfolios", *JF* 72(4). https://www.nber.org/papers/22208
- Cederburg, O'Doherty, Wang & Yan (2020), "On the Performance of Volatility-Managed Portfolios", *JFE* 138. https://www.lehigh.edu/~xuy219/research/COWY.pdf
- Harvey et al. (2018), "The Impact of Volatility Targeting", *JPM*. https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf ; https://www.man.com/insights/the-impact-of-volatility-targeting
- Bongaerts, Kang & van Dijk (2020), "Conditional Volatility Targeting", *FAJ* 76(4). https://rpc.cfainstitute.org/research/financial-analysts-journal/2020/conditional-volatility-targeting

**Cross-sectional momentum**
- Daniel & Moskowitz (2016), "Momentum Crashes", *JFE* 122(2). https://www.nber.org/system/files/working_papers/w20439/w20439.pdf
- Barroso & Santa-Clara (2015), "Momentum Has Its Moments", *JFE* 116(1). https://ciencia.ucp.pt/en/publications/momentum-has-its-moments/
- Blitz, Huij & Martens (2011), "Residual Momentum", *JEF* 18(3). https://www.cxoadvisory.com/momentum-investing/stripping-risks-from-a-stock-momentum-strategy/ ; Huij & Lansdorp (2017) OOS revisit: https://repub.eur.nl/pub/100801
- Moskowitz & Grinblatt (1999), "Do Industries Explain Momentum?", *JF* 54(4).
- Asness, Moskowitz & Pedersen (2013), "Value and Momentum Everywhere", *JF* 68(3).

**Low-vol, quality, value, replication**
- Frazzini & Pedersen (2014), "Betting Against Beta", *JFE* 111(1).
- Novy-Marx & Velikov (2022), "Betting Against Betting Against Beta", *JFE* 146. https://mysimon.rochester.edu/novy-marx/research/BABAB.pdf
- Novy-Marx (2013), "The Other Side of Value: The Gross Profitability Premium", *JFE* 108(1). https://www.aqr.com/Our-Firm/AQR-Insight-Award/2012/Distinguished-Paper-1
- Novy-Marx & Velikov (2016), "A Taxonomy of Anomalies and Their Trading Costs", *RFS* 29(1). https://www.nber.org/papers/w20721.pdf
- McLean & Pontiff (2016), "Does Academic Research Destroy Stock Return Predictability?", *JF* 71(1). https://ivey.uwo.ca/media/3775549/pontiff.pdf
- Hou, Xue & Zhang (2020), "Replicating Anomalies", *RFS* 33(5). https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html
- Harvey, Liu & Zhu (2016), "…and the Cross-Section of Expected Returns", *RFS* 29(1). https://papers.ssrn.com/abstract=2513152
- Jensen, Kelly & Pedersen (2023), "Is There a Replication Crisis in Finance?", *JF* 78(5). https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf
- Asness, Ilmanen & Maloney (2017), "Market Timing: Sin a Little", *JOIM*. https://www.aqr.com/Insights/Perspectives/Sin-a-Little
- USMV vs SPY (5y, 2022): https://finance.yahoo.com/markets/options/articles/usmv-minimum-volatility-promise-got-140002776.html ; MTUM vs SPY (10y): https://247wallst.com/investing/2026/06/17/forget-the-plain-sp-500-the-momentum-version-captured-the-run-and-beat-it-by-15-this-year/

**Risk parity**
- CAIA (2023), risk parity in 2022: https://caia.org/node/7312 ; Milliman FRM year-end 2022: https://frm.milliman.com/-/media/frm/pdfs/3-1-23_frm-year-end_f.ashx ; stock–bond correlation: https://www.voronoiapp.com/markets/The-Death-of-the-6040-Bond-Hedge-8780

**Congressional trading**
- Ziobrowski, Cheng, Boyd & Ziobrowski (2004), "Abnormal Returns from the Common Stock Investments of the U.S. Senate", *JFQA* 39(4). https://Www.Gwern.net/doc/economics/2004-ziobrowski.pdf
- Ziobrowski, Boyd, Cheng & Ziobrowski (2011), House, *Business and Politics* 13(1). https://www.cambridge.org/core/journals/business-and-politics/article/abnormal-returns-from-the-common-stock-investments-of-members-of-the-us-house-of-representatives/BC6C6A524BBE96738BB94D37EF0FD1A5
- Eggers & Hainmueller (2013), "Capitol Losses: The Mediocre Performance of Congressional Stock Portfolios", *JOP* 75(2). https://www.mit.edu/~jhainm/Paper/CL.pdf
- Belmont, Sacerdote, Sehgal & Van Hoek (2020/2022), "Relief Rally: Senators as Feckless as the Rest of Us at Stock Picking", NBER w26975. https://www.nber.org/papers/w26975
- Wei & Zhou (2025), "'Captain Gains' on Capitol Hill", NBER w34524. https://www.nber.org/papers/w34524
- "Trading on the Hill: Can Investors Profit from Mimicking U.S. Congressional Stock Trades?" (Univ. of Gothenburg thesis): https://gupea.ub.gu.se/items/0e1aeba3-3354-493e-b192-bee7df3c107c ; Utrecht thesis (2020–2023): https://studenttheses.uu.nl/handle/20.500.12932/47365
- NANC/KRUZ records: https://www.etf.com/sections/etf-basics/nanc-vs-kruz-battle-congress-stock-trackers ; https://www.morningstar.com/funds/2-etfs-that-track-congressional-stock-trades ; 2025 summary: https://finviz.com/news/279401/top-10-congress-stock-traders-2025-nancy-pelosi-marjorie-taylor-greene-both-bet-big-on-nvda-but-who-came-out-on-top

**PEAD**
- Martineau (2022), "Rest in Peace Post-Earnings Announcement Drift", *Critical Finance Review*. https://cfr.ivo-welch.info/published/papers/martineau2021rest.pdf
- UCLA Anderson Review (2025), "Is Post-Earnings Announcement Drift a Thing Again?" (Subrahmanyam; Dickerson–Julliard–Mueller; Hirshleifer–Peng–Wang): https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/

**Crypto**
- Liu & Tsyvinski (2021), "Risks and Returns of Cryptocurrency", *RFS* 34(6).

*Verification notes:* figures tagged `[lit]` were read from the source or from a reputable summary of it. The 2020–2024 House
disclosure-date study's authors and venue could not be confirmed. GEM's post-2014 calendar-year returns, KMLM's total (vs price) 2022
return, and the exact Barroso–Santa-Clara Sharpe pair were not verified against primary tables. All `[est]` values are
unverified estimates to be replaced by measured results from the pre-registered runs.
