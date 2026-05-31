# Design

Visual system for Auto Trading (by RiseWealth). Source of truth for tokens lives in
`docs/branding/risewealth-tokens.css` and `dashboard/public/assets/news-public.css`. This
file captures the system so design variants stay on-brand. Identity is already committed:
the fonts and the warm solar palette are non-negotiable brand assets, not open choices.

## Visual Theme

Molten institutional intelligence. Warm bronze-and-ember surfaces with a living, emissive
3D centerpiece. Dark is the default and the hero condition (a quant reading markets in a dim
room at 2am, where glow and depth read best); light is fully supported and equally premium.
Color strategy: **Committed → Drenched** in the RiseWealth solar orange. The accent is
load-bearing, not a 10% garnish.

## Color

Tokens are CSS variables; both themes ship. Never use pure `#000`/`#fff`; neutrals are
tinted toward the warm hue.

### Dark (default)
- `--page` `#0E0805` (near-black, warm-tinted)
- `--surface` `#1A0F08`
- `--ink` `#FFF1E8`
- `--muted` `#A39A92`
- `--line` `rgba(255,255,255,0.08)`
- `--teal` (primary) `#FF8A3D`
- `--teal-dark` (hover) `#FFA86A`
- `--teal-soft` `rgba(229,90,31,0.15)`

### Light
- `--page` `#FFF7F0`
- `--surface` `#FFFFFF`
- `--ink` `#1A0F08`
- `--muted` `#7A6B5E`
- `--line` `rgba(26,15,8,0.07)`
- `--teal` (primary) `#E55A1F`
- `--teal-dark` `#C9461A`
- `--teal-soft` `#FFF1E8`

### Solar ramp (10-step, for gradients, glow, 3D emission)
`#FFF1E8 → #FFD9BD → #FFC396 → #FFA86A → #FF8A3D → #F26B1F → #E55A1F → #C9461A → #A33A14 → #6A220A`

Profit/loss semantics (data only, never decorative): green `#16a34a`/`#22c55e`,
red `#dc2626`/`#ef4444`.

## Typography

Committed brand identity. Do not substitute.

- **Display / money / hero**: `DM Serif Display`, serif. Oversize, tight tracking, italic
  cut used for the accent word ("Trading.", "Real-time Edge."). This is the typographic
  risk lane: enormous serif moments are on-brand.
- **UI / body**: `Manrope`. Weights 400–800.
- **Data / codes / tickers / labels**: `IBM Plex Mono`. Uppercase, letter-spaced, ~0.68rem
  for tags and eyebrows.
- **Alt display**: `Sora` (existing `.display` utility).
- **Arabic / RTL**: `IBM Plex Sans Arabic`.

Scale: fluid `clamp()`, ratio ≥1.25 between steps. On dark, add 0.05–0.1 line-height. Body
measure capped 65–75ch.

## Components

- **Cards**: `border-radius: 0.85rem`, `1px solid var(--line)`, subtle hover glow. NOT to be
  used as an identical repeating grid (see Layout bans). When cards appear, sizes vary.
- **Buttons**: pill, `border-radius: 999px`. CTA shadow `0 8px 18px rgba(229,90,31,0.30)`,
  lift on hover (`translateY(-2px)`), never bounce.
- **Tags / badges**: pill, uppercase, `0.68rem`, mono, `--teal-soft` background.
- **Wordmark**: "Auto" in `--ink` + "Trading." in `--teal` italic, DM Serif Display. Period
  always present. Custom solar logo mark to its left.

## Elevation

- `--rw-sh-1: 0 1px 2px rgba(26,15,8,0.04), 0 6px 14px rgba(26,15,8,0.05)`
- `--shadow` (card): light `0 26px 68px rgba(122,107,94,0.12)`, dark `0 26px 68px rgba(0,0,0,0.65)`
- Glow accents use solar-ramp colors at low alpha, never a hard neon ring.

## Layout

- Asymmetric / bento composition over centered stacks. Break the grid for emphasis.
- Fluid `clamp()` spacing; vary rhythm (generous section separation, tight groupings).
- One dominant idea per fold; long deliberate scroll.
- Existing fixed nav (height 5rem, blur 22px), `.backdrop` grid, `.aurora` radial layers.

### Bans (on top of impeccable shared/brand bans)
- No identical card grid of icon + heading + text (the current homepage failure).
- No large rounded-corner icon above every heading.
- No gradient text (`background-clip:text` + gradient). Accent via solid `--teal`, weight, size.
- No glassmorphism as a default decorative reflex (purposeful nav blur is fine).
- No cold blues / primary greens / grays beyond `--muted`.

## Motion

- Living centerpiece: WebGL (Three.js) emissive 3D object + particle field, perpetual slow
  motion, reacts to pointer and scroll. Bloom/glow in solar colors.
- Page-load: one orchestrated staggered reveal (GSAP), typographic choreography on the hero.
- Scroll: GSAP ScrollTrigger reveals, parallax, section pinning where it earns attention.
- Curves: ease-out exponential (quart/quint/expo). No bounce, no elastic. Never animate
  layout properties; transform/opacity only. Collapsing sections animate `grid-template-rows`.
- `prefers-reduced-motion`: freeze 3D to a static frame, reveals become instant, no loops.
