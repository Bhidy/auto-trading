# Plan — Portfolio Detail: "Portfolio vs S&P 500" Module + Never-Fail Live Engine

**Target page:** `https://autotradingportfolios.vercel.app/portfolio-detail?id=all` (and `?id=portfolio_1|2|3`)
**Files touched (3, surgical):**
- `dashboard/public/assets/portfolio-detail.js` — chart card rewrite + live engine
- `dashboard/public/assets/portfolio.css` — new component styles (append only)
- `dashboard/public/portfolio-detail.html` — only if a markup hook is needed (likely untouched)

**Out of scope:** stock-detail page, server.js, the rest of the page's *visual* layout. The live engine wraps the whole page but does not restyle holdings/bottom/panels.

---

## Phase 0 — Documentation Discovery (DONE — facts grounded in code)

### Allowed APIs / data contracts (verified, real)
| Source | Endpoint / fn | Shape | File:line |
|--------|---------------|-------|-----------|
| Portfolio equity (daily) | `GET /api/supabase/equity?portfolio_id={id}&start={YYYY-MM-DD}` | `[{date, equity, cash, pnl, pnl_pct, positions_count}]` (for `all`: `[{date, equity}]` aggregated) | `dashboard/server.js:1419` |
| SPY benchmark (daily) | `GET /api/supabase/market?symbol=SPY&start={YYYY-MM-DD}` | `[{date, close_price, open_price, high_price, low_price, volume}]` | `dashboard/server.js:1451` |
| Equity fallback (Alpaca/intraday) | `PFStore.loadEquityHistory(pfId, period)` | `{source, base_value, history:[{date, equity}]}` | `portfolio-store.js:113` |
| SPY fallback (Alpaca IEX) | `GET /api/market/bars/SPY?timeframe=1Day&limit=400&start=&end=` | `[{t, o,h,l,c,v}]` | `dashboard/server.js:1335` |
| Live metrics | `PFStore.loadPortfolio(pfId)` → `PFStore.computeMetrics(p)` | `{totalValue,totalReturn,totalGain,cashBalance,...}` | `portfolio-store.js:147` |
| Chart lib | Chart.js v4.4.0 UMD (already loaded) | `type:'line'` | `portfolio-detail.html:106` |

### Branding tokens (must use; from CLAUDE.md + portfolio.css)
- Primary orange `--teal`=`#E55A1F` (dark `#FF8A3D`); hover `--teal-dark`; soft `--teal-soft`.
- Surfaces `--surface`/`--page`, text `--ink`/`--muted`, hairline `--line`.
- Radius `--pf-radius` (.75rem) / `--pf-radius-sm` (.5rem). Mono `--pf-mono` (IBM Plex Mono). Display: DM Serif Display. UI: Manrope.
- Pos/neg `.pf-pos` (`--pf-green`) / `.pf-neg` (`--pf-red`).
- Card = `.pf-card` (1px `--line`, hover glow). Buttons pill. Tags uppercase .68rem.

### Existing structures to reuse / replace (verified)
- Chart container: `renderBody()` injects `<div class="pf-card pf-chart-card" id="chartCard">` — `portfolio-detail.js:259`.
- Builder: `renderChartCard()` `:299–378`; drawer: `initChart()` `:451–823`; helpers `stat()` `:380`, `toReturn()` `:825`, `toDrawdown()` `:831`.
- State vars: `chartPeriod='All', chartMode='value', showBenchmark=true` `:27`. Stock-chart vars `selectedSymbol/selectedChartType` `:34–35`.
- Existing 30s refresh loop `:151–158` calls `refreshLiveData()` `:166` (header + holdings + orders ONLY — chart NOT refreshed today).
- "Technical Chart: BIL" = `toggleButtonHtml` `:311–317` + stock branch `:460–657` (to be removed). "SPY badge" = `pf-benchmark-toggle` `:335`. Raw-$ axis = `:735` y-tick `$`.
- Holding clicks that hijack the chart into stock mode: row click `:1079–1086`, mini-card click `:1245–1248`. Must be redirected (see Phase 4).

### Anti-patterns to avoid
- ❌ Do NOT fabricate equity/price data (CLAUDE.md "Honesty rule"). No synthetic backfill — real Supabase/Alpaca only; on absence, keep last-good or show an honest empty state.
- ❌ Do NOT compare raw dollar NAV vs SPY price on one axis (the bug we're fixing).
- ❌ Do NOT hardcode the KPI numbers from the mockup (+0.74% / +24.80% / Sharpe 0.18…). Compute them.
- ❌ Do NOT invent Chart.js options; use documented v4 keys (`scales.y.title`, `suggestedMin/Max`, `borderDash`, `segment` optional).
- ❌ Do NOT add `setInterval` per-segment that stacks; one orchestrator, overlap-guarded.

---

## Phase 1 — Data & math core (pure functions, reusable, testable)

**What to implement** (new private fns in `portfolio-detail.js`, no DOM):

1. `periodToStartDate(period)` — map `1D/1W/1M/3M/6M/YTD/All` → ISO start (`All` = 2y back). (Adapt existing `:665`.)
2. `fetchEquitySeries(period)` → `Promise<[{date, equity}]>`, **never rejects**:
   - intraday (`1D`): `PFStore.loadEquityHistory(pfId,'1D')` → `.history`.
   - else: `GET /api/supabase/equity?portfolio_id=&start=`; if `>=3` rows use it, else fall back to `loadEquityHistory`. `.catch(()=>[])`.
3. `fetchSpySeries(period, startDate, endDate, intraday)` → `Promise<{byKey:{dateKey:close}, ok}>`, **never rejects**:
   - non-intraday: try `GET /api/supabase/market?symbol=SPY&start=` (`close_price`); if `<3` rows fall back to `/api/market/bars/SPY` (`c`). intraday: 5Min bars. `.catch(()=>({byKey:{},ok:false}))`.
4. `normalize(values, base)` → `values.map(v => v/base*100)` (rebased to 100). Guard `base>0`.
5. `alignSpyIndex(equityRows, spyByKey, intraday)` → SPY closes forward-filled onto equity dates, then rebased to 100 at first available close. (Adapt `alignSpyToBValues` `:748`.)
6. `dailyReturns(values)` → `[(v[i]/v[i-1]-1)]`.
7. `computeSharpe(equityVals, intraday)` → annualized `mean/std*sqrt(252)`; `null` for intraday or `<3` points.
8. `computeBeta(pDaily, spyDaily)` → `cov/var(spy)`; `null` if insufficient/var≈0.
9. `maxDrawdownPct(indexSeries)` → most-negative `(v/runningPeak-1)*100`.
10. `bestWorst(equityRows)` → `{best:{value,date}, worst:{value,date}}` by equity.

Reuse existing `toReturn()`/`toDrawdown()` for mode transforms.

**Verification checklist**
- `normalize([100000,101000],100000)` → `[100,101]`. `maxDrawdownPct([100,110,99])` ≈ `-10`.
- `fetchEquitySeries`/`fetchSpySeries` resolve (never throw) when offline — temporarily block network in devtools, confirm no uncaught rejection.
- `computeSharpe`/`computeBeta` return `null` (not `NaN`) on empty/flat input. Callers render `—`.

**Anti-pattern guards:** no `Math.random`/synthetic series anywhere; every fetch has `.catch` returning a safe empty value.

---

## Phase 2 — Chart card markup: the "Portfolio vs S&P 500" module (reusable components)

**What to implement** — rewrite `renderChartCard()` `:299–378`. Build the static shell ONCE (so live updates patch numbers, not rebuild DOM). Six reusable string-builder "components" (vanilla-JS render fns, matching existing `stat()`/`kpi()` idiom):

- `ChartControls()` → period strip `1D 1W 1M 3M 6M YTD ALL` (ALL default) + mode strip `Growth Index | Return % | Drawdown` (Growth Index default). Reuse `.pf-period-btn`/`.pf-mode-btn`.
- `PerformanceKpiCard(label, valueId, hintId)` → KPI card with `id` hooks. Four instances: Portfolio Return, S&P 500 Return, Relative Performance, Max Drawdown.
- `ChartLegend()` → "Portfolio" solid orange swatch · "S&P 500" dashed gray swatch.
- `InsightBadge(id)` → pill, id hook for "Portfolio underperformed/outperformed S&P 500 by X%".
- `MetricSummaryRow(ids)` → footer row: Starting Capital · Current NAV · Best Value (+date) · Worst Value (+date) · Risk/Return (Sharpe | Beta).
- `LivePill(id)` → pulsing dot + "Updated HH:MM:SS".

**Header copy:** title `Portfolio vs S&P 500` (DM Serif Display), subtitle `Normalized performance, indexed to 100 at start date`. Note line: `Both lines start at 100 so you can compare performance fairly.`

**Layout order inside `#chartCard`:** header(title+subtitle+LivePill) → ChartControls → 4× PerformanceKpiCard (grid) → note → ChartLegend + InsightBadge → `<canvas#perfChart>` (height ~320px) → MetricSummaryRow.

**Remove:** `toggleButtonHtml` (Technical Chart) `:311–317,360–366`; `pf-benchmark-toggle` SPY badge `:335–337,368–375`; `showBenchmark` var/usages. Set `chartMode` default `'index'` (rename from `'value'`) at `:27`.

**Verification checklist:** ALL + Growth Index active on load; controls wired to `chartMode`/`chartPeriod` + call `initChart()`; no "Technical Chart"/old SPY toggle in DOM (`grep -c "Technical Chart" portfolio-detail.js` → 0).

**Anti-pattern guards:** KPI/summary values come from element-id patching in Phase 3, never inlined literals.

---

## Phase 3 — Drawer: normalized rendering + KPI/summary patching (rewrite portfolio branch of `initChart`)

**What to implement** — replace `initChart()` `:451–823` (delete stock branch `:460–657` and stock helpers `STOCK_PERIOD_MAP/_stockBarCache/fetchRealStockHistory/generateStockHistoryFallback` `:385–449`).

Flow (race-safe + never-fail):
```
var _benchToken = 0, _benchLastGood = null;
initChart():
  token = ++_benchToken
  fetchEquitySeries(chartPeriod).then(eqRows => {
    if (token !== _benchToken) return                 // stale guard
    if (eqRows.length < 2) { if(!_benchLastGood) drawEmpty(); return }   // keep last-good
    fetchSpySeries(...).then(spy => {
      if (token !== _benchToken) return
      renderBenchmark(eqRows, spy)                     // compute + draw + patch DOM
    })
  })   // all fetches already self-catch
```

`renderBenchmark`:
- `pIndex = normalize(equityVals, equityVals[0])`; `spyIndex = alignSpyIndex(...)`.
- mode → datasets: **index** = `pIndex`/`spyIndex`; **return** = `toReturn(equityVals)`/`spyIndex.map(v=>v-100)`; **drawdown** = `toDrawdown(pIndex)`/`toDrawdown(spyIndex)`.
- Datasets: Portfolio = solid `#E55A1F`, width 2.5, gradient fill only in index/return; S&P = `#7a6b5e` (dark `#a39a92`), `borderDash:[6,4]`, no fill.
- Y-axis: `scales.y.title.text` = `Growth Index (Rebased)` / `Return %` / `Drawdown %`; for index use dynamic `suggestedMin/Max` from both series ±pad (lands ~95–130 on ALL). Tooltip shows index to 2dp / `%`.
- Patch KPIs (by id): pReturn=`pIndex.last-100`, spyReturn=`spyIndex.last-100`, relative=`pReturn-spyReturn`, maxDD=`maxDrawdownPct(pIndex)`; color `.pf-pos/.pf-neg`.
- InsightBadge: relative<0 → "Portfolio underperformed S&P 500 by |x|%"; >0 → "outperformed"; ≈0 → "tracking the S&P 500".
- MetricSummaryRow: Starting Capital=`pfId==='all'?300000:100000`; Current NAV=`metrics.totalValue`; Best/Worst from `bestWorst(eqRows)` (value + `MMM D, YYYY`); Sharpe=`computeSharpe`, Beta=`computeBeta` (→ `—` if null).
- LivePill → `Updated HH:MM:SS`. Set `_benchLastGood = {...}`.

**Verification checklist:** id=all renders two rebased lines both starting at 100; Growth/Return/Drawdown switch cleanly; KPI signs/colors match (underperform → red Relative); offline refresh keeps last chart (no blank); Sharpe/Beta show `—` on 1D. Visual check vs the user's reference mock.

**Anti-pattern guards:** never `perfChart.destroy()` before new data validated; no `$`-dollar y-axis; no synthetic fill.

---

## Phase 4 — Holding-click routing (don't let clicks hijack the dedicated chart)

**What to implement:** since the chart card is now benchmark-only, holding row click `:1079–1086` and mini-card click `:1245–1248` must NOT set `selectedChartType='stock'`/`renderChartCard()`. Replace with navigation to the existing stock page: `window.location.href = '/stock-detail.html?symbol=' + sym` (preserves drill-down). Remove now-dead `selectedSymbol/selectedChartType` usage.

**Verification checklist:** clicking a holding leaves the benchmark chart intact / navigates away; `grep -n "selectedChartType" portfolio-detail.js` shows no chart-card mutation paths.

**DECIDED (user):** navigate to `/stock-detail.html?symbol=X`. Do NOT modify stock-detail.js in this plan (out of scope). Interim behavior accepted: navigation works; stock-detail loads its default symbol until a later 2-line follow-up reads `?symbol=`. A `[[follow-up-stock-detail-symbol-param]]` note is filed for later.

---

## Phase 5 — Ultra never-fail LIVE engine (whole page + chart)

**What to implement:** replace the ad-hoc 30s loop `:151–158` with one resilient orchestrator `startLiveEngine()`:

- **Single scheduler**, `INTERVAL=30000`. **Overlap guard**: skip tick if previous still in-flight (`_tickInFlight`).
- **Segment isolation**: each segment in its own `try/catch` + `.catch` so one failure never aborts the others or the loop:
  1. `PFStore.loadPortfolio` → refresh `metrics`/`detailCache` → `renderHeader()` (KPI strip).
  2. `initChart()` (benchmark refresh — already race-safe/last-good).
  3. holdings table (`refreshLiveData` internals), 4. orders widget, 5. ticker ribbon (keep existing 8s), 6. smart panels (light).
- **Visibility aware**: `document.visibilitychange` — pause ticking when hidden; on re-show, run one immediate tick.
- **Network aware**: `window.online/offline` — on `online` fire an immediate tick; offline ticks just keep last-good (no error UI churn).
- **Self-healing**: errors counted, logged to `console.warn` (per CLAUDE.md "no silent suppression"); the loop never dies. Optional small "reconnecting…" state on LivePill after N consecutive failures, auto-clears on success.
- **Last-updated** timestamp surfaced via LivePill so "live" is provable to the user.

**Verification checklist:** leave page open — header/chart/holdings update every 30s without flicker; throttle/offline in devtools → no uncaught errors, last-good stays, recovers on reconnect; switch tab away/back → immediate refresh on return; no stacked intervals (`getEventListeners`/single timer).

**Anti-pattern guards:** no `2>/dev/null`-style silent catch; no multiple competing `setInterval`s for the same data; no full-DOM rebuild on tick (patch in place).

---

## Phase 6 — CSS (append to `portfolio.css`, brand-compliant)

New classes (light + dark, RTL-safe), after the `Chart card` block `:240–312`:
`.pf-bench-head`, `.pf-bench-sub`, `.pf-bench-kpis` (responsive grid → 2-col on narrow), `.pf-bench-kpi`, `.pf-bench-note`, `.pf-bench-legend` + swatches (solid orange / dashed gray), `.pf-bench-insight` (pill, teal-soft / pos / neg variants), `.pf-bench-summary` (5-col grid → wrap), `.pf-live-pill` + `@keyframes pf-live-pulse`. Reuse existing `.pf-period-strip/.pf-mode-strip` and `.pf-pos/.pf-neg`.

**Verification checklist:** matches reference mock spacing/hierarchy; dark + light both clean; RTL (toggle AR) not broken; mobile width wraps gracefully.

---

## Phase 7 — Final verification

1. **Visual** vs user reference: title/subtitle, ALL+Growth default, 4 KPI cards, note, insight badge, legend, 95–130-ish axis, summary row (Starting Capital / Current NAV / Best / Worst / Sharpe|Beta).
2. **Real-data honesty**: no synthetic/random; values trace to Supabase/Alpaca.
3. **Greps**: `grep -c "Technical Chart" portfolio-detail.js`→0; `grep -c "showBenchmark" …`→0; no `Math.random` in chart path; single `setInterval` for the live loop.
4. **Resilience**: offline/throttle/tab-switch matrix from Phase 5.
5. **No regressions** to header/holdings/bottom/panels layout.
6. Local preview (vanilla static — run `node dashboard/server.js` or open file) then ship via normal git→Vercel pipeline (per CLAUDE.md). Optional `bash dashboard/validate.sh`.

---

### Decisions (resolved)
- **Holding-click target (Phase 4): RESOLVED** → navigate to `/stock-detail.html?symbol=X`. stock-detail.js NOT modified here (out of scope); deep-link auto-load is a filed follow-up.
