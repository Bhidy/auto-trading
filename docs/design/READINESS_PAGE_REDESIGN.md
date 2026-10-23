# Live-Readiness page: redesign plan (2026-10-23)

## 0. Verdict on the current page (audit "before", measured)

| Metric | Measured | Why it fails |
|---|---|---|
| Charts | 0 | Every fact is prose or a table cell |
| Words (one book) | 590 | The reader has to read in order to see anything |
| Distinct font sizes | 17 (13 of them between 11.8 and 16.8 px) | No hierarchy: everything reads at the same volume |
| Mobile height vs desktop | 3,783 vs 1,988 px (1.9×) | Mobile is a long scroll of tables |
| Cross-strategy view | none (one book per tab) | "Why is nothing GO?" needs three tabs and six cards |
| Root cause | `readiness_report.json` held **no time series** | A page cannot draw the truth it is never given |

## 1. What a top professional does that the brief does not ask for

1. **Design the decision, not the page.** The page answers one question per strategy: *is it cleared for capital, and if not, what is the single binding constraint and when could it clear?* Everything else is supporting evidence, kept one click away.
2. **Show evidence as a trajectory.** A verdict is the end of a sequential test. The honest picture is the **always-valid confidence band on alpha** narrowing session by session towards the zero line. GO is the moment the band's lower edge clears zero. That chart is the signature device: no competitor can paste it in, because it comes from this engine.
3. **Put every gate for every strategy in one matrix** (sleeves × gates, grouped Evidence / Risk / Operations). A model-risk committee scans a matrix, not six ledgers.
4. **Fix the data contract, not the CSS.** The engine now emits the series (book equity vs SPY, drawdown, and the confidence-sequence path at every session). The browser draws geometry and computes **no statistics**: that invariant is kept.

## 2. Rawest material

Not the digested narrative strings. The sources are:
- the Alpaca daily equity series per account;
- SPY/BIL daily bars;
- the per-session bounds of the predictable confidence sequence (`shared/readiness.predictable_cs(path=True)`, the same numbers the decision used);
- the gate objects (status, value, threshold) per sleeve.

All of these flow through `data/readiness_report.json` → `/api/readiness`, verbatim.

## 3. Methods and tools

- **Information design:**
  - Tufte data-ink and small multiples.
  - Direct labelling at line ends (no legends), 1 px dashed light gridlines, 1.5 px data strokes with a halo underlay (measured on Our World in Data's grapher).
  - Few-style bullet bars for "x of y".
  - Status encoded by **shape and colour** (●, ◐, ✕, dashed ○), so it stays colour-blind safe.
- **Visual language:**
  - Measured from Linear (near-black layered surfaces, quint-out easing, −0.02 em display tracking) and Mercury (light display weight, restraint).
  - Rendered in the RiseWealth tokens only. A dark ink hero band block-colours the page in both themes, so the brand's warm palette never reads as a generic cream-and-rust template.
- **Engineering:**
  - Inline SVG generated at the container's real pixel width, re-rendered on resize, so text never shrinks on phones.
  - A pure, node-tested chart module (`assets/readiness-charts.js`); time axes stay LTR in Arabic, as financial convention requires.
  - One motion engine (CSS only), `prefers-reduced-motion` means no motion.
- **Verification:**
  - Node tests: every plotted point maps back to a report value; no NaN in any path; off-scale values are clamped and marked.
  - Browser probe at 390 / 834 / 1440 × light / dark × EN / AR: `scrollWidth === clientWidth`, measured contrast, zero console errors.

## 4. What proves it right (besides the builder)

1. **The engine itself.** Each chart point carries its report value. A test asserts plotted = reported, so the page cannot drift from the decision.
2. **A five-second cold read.** Above the fold, a stranger can say how many strategies are cleared (0 of 6), which is closest, what blocks it, and when.
3. **Automated probes.** No overflow, AA contrast measured, no NaN/undefined, zero console errors, reduced-motion respected.
4. **Production smoke.** The deploy workflow's smoke test and `/api/readiness` stay byte-identical to the engine output.

## 5. The rewritten brief (what is being built)

> Rebuild `/readiness` as a model-risk evidence wall in the RiseWealth brand. It answers, in under five seconds and under 120 words above the fold:
> - how many strategy versions are cleared for live capital;
> - which one is closest;
> - what single gate binds it;
> - when it could clear.
>
> Lead with a dark brand hero holding the verdict count and the signature chart: the always-valid alpha confidence band of the closest strategy converging on the zero line.
>
> Follow with one sleeves × gates matrix and per-book small multiples (equity vs SPY, drawdown vs the 15 % gate and the kill switch). Then per-strategy cards with the evidence funnel, the track-record and incubation progress, and the full gate ledger collapsed for auditors.
>
> The engine supplies every series; the browser computes nothing statistical.
>
> Ship it EN/AR, light/dark, 390–1440 with zero overflow, AA contrast, reduced motion respected, node tests binding every plotted value to the report, and a before/after audit.

## 6. Page architecture

| Band | Ground | Content |
|---|---|---|
| Hero | brand dark ink (`#0E0805` / `#1A0F08`) in both themes | "0 / 6 cleared"; closest strategy, binding gate, ETA; **evidence funnel** of the closest edge-claiming sleeve |
| Matrix | page | sleeves × 16 gates, status glyphs, verdict pill per row, tap a cell for value vs threshold |
| Books | surface cards on page | segmented P1 / P2 / P3; equity vs SPY and underwater-drawdown small multiples; strategy cards (verdict, bullet bar, track ring, incubation bar, mini funnel); ledger + narrative collapsed |
| Footer | page | methodology, provenance, disclosure: one line each |

## 7. Risks and their controls

| Risk | Control |
|---|---|
| Early confidence bands are huge (±800 %) and would crush the chart | Y-domain fitted to the last 60 % of the path; off-scale values clamped to the frame with an arrow marker and labelled |
| A chart implies edge where none is credited | Book-level and shared series carry a "book-level, not credited" tag; empty states state the missing count (e.g. "0 of 60 returns") instead of drawing nothing |
| Arabic breaks charts | Charts render `dir="ltr"` (time runs left to right); labels translated; zero negative tracking on Arabic |
| Regression of the existing data guards (stale report, unavailable report, unknown verdict) | Loading, validation and alert logic carried over unchanged from the current page; existing node tests keep running |
| Report size | About 137 KB, served `no-store` and cached server-side; series rounded to 5 decimals |

## 8. Acceptance (the QA gate this plan is closed against)

- 0 console errors; `scrollWidth === clientWidth` at 390 / 834 / 1440 in EN and AR, light and dark.
- Fewer than 120 words above the fold at 1440; mobile height at most 1.6× desktop.
- Node: every chart point traces to a report value; no NaN; clamped values marked.
- Contrast measured ≥ 4.5 : 1 for body text and ≥ 3 : 1 for chart strokes on both grounds.
- Self-review rubric (global design authority §5) ≥ 8 on every line, scored honestly after the build.
