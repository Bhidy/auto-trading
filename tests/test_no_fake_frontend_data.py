"""Zero-fake-data guard (institutional honesty rule, enforced in CI).

PRODUCT.md principle 4 and CLAUDE.md are explicit: ONLY real Alpaca/Supabase
data reaches the surface — never fabricated equity/price/quote values. This
test makes that an enforced invariant instead of a convention: it fails the
build if synthetic/dummy data is (re)introduced into the dashboard frontend or
the server's response paths.

Context: a dormant `portfolio-showcase.js` once shipped fabricated equity
($765,078.75 etc.) via `Math.random`. It was removed; this guard stops any
regression.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "dashboard" / "public" / "assets"
PUBLIC = ROOT / "dashboard" / "public"
SERVER = ROOT / "dashboard" / "server.js"

# `Math.random` is legitimate ONLY for the decorative 3D homepage scene and for
# local client-side id/seed generation. It must NEVER drive a rendered
# price/quote/equity on a data page. Any new use elsewhere must be justified by
# adding the file here (with a comment) — the failure message says so.
MATH_RANDOM_ALLOWED = {
    "home.js",            # WebGL particle field + decorative hero candles (not data)
    "portfolio-store.js",  # local transaction-id generation for user sandboxes
}

# Hard-banned: known fabricated-data generators that must never come back.
# The generate* names use a trailing "(" so a *live* definition/call is caught
# but a historical comment ("replaces the former generateStrategyBackfill") is
# not. The mock* names were unique showcase variables — bare match is correct.
BANNED_TOKENS = [
    "generateStrategyBackfill(",  # the deleted synthetic equity backfill (def/call)
    "generateBackfill(",
    "mockTotalVal",               # portfolio-showcase fabricated totals
    "mockReturnPct",
    "mockCashBalance",
]


def _js_files():
    return sorted(ASSETS.glob("*.js"))


def test_no_unexpected_math_random_in_frontend():
    offenders = [
        f.name for f in _js_files()
        if f.name not in MATH_RANDOM_ALLOWED and "Math.random" in f.read_text()
    ]
    assert not offenders, (
        "Math.random found in data-page script(s): " + ", ".join(offenders) + ". "
        "Render only real Alpaca/Supabase values. If this use is non-data "
        "(animation / id / seed), add the file to MATH_RANDOM_ALLOWED with a "
        "justifying comment."
    )


def test_no_banned_fabrication_tokens_anywhere():
    targets = _js_files() + list(PUBLIC.glob("*.html")) + [SERVER]
    offenders = []
    for f in targets:
        if not f.exists():
            continue
        txt = f.read_text()
        offenders += [f"{f.name}:{tok}" for tok in BANNED_TOKENS if tok in txt]
    assert not offenders, (
        "Fabricated-data generator(s) reintroduced: " + ", ".join(offenders)
    )


def test_showcase_fabrication_files_stay_deleted():
    # The dormant fabricated-data showcase must never return.
    for name in ("portfolio-showcase.js", "portfolio-showcase.css"):
        assert not (ASSETS / name).exists(), (
            f"{name} was removed (it rendered fabricated equity). Do not re-add it."
        )
