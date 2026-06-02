"""P2 conviction-scaled %-of-book sizing — 2026-06-02 audit.

With the flat trade_size_scaling table, P2 copied ~$1,500 per disclosure and
deployed only ~$10K of a $100K book — sitting 90% in idle cash. The copy size was
decoupled from the book size, so the portfolio could never get invested. The fix
sizes each copy as a percent of equity, scaled by the disclosed trade-size bucket
(the conviction proxy), bounded by the single-position and max-trade-value caps.
These tests lock the new sizing and its backward-compatible fallback.

NOTE: the bucket keys use an EN DASH (–, U+2013), matching config/risk_limits.json.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P2_SCRIPTS = os.path.join(REPO_ROOT, "political-copy-bot", "scripts")
for _p in (REPO_ROOT, P2_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from politician_bot import RiskManager  # noqa: E402

PCT_LIMITS = {
    "max_single_position_pct": 8.0,
    "max_trade_value_usd": 8000,
    "min_trade_value_usd": 200,
    "base_position_pct": 4.0,
    "size_bucket_multiplier": {
        "1K–15K": 0.75, "15K–50K": 1.25, "50K–100K": 1.5,
        "100K–250K": 1.75, "250K–500K": 2.0, "500K–1M": 2.0, "1M–5M": 2.0,
    },
    "trade_size_scaling": {"1K–15K": 1500, "15K–50K": 3000},
}


def _rm(limits):
    # Bypass __init__ (which builds an Alpaca client / loads files); get_trade_size
    # only reads self.limits.
    rm = RiskManager.__new__(RiskManager)
    rm.limits = limits
    return rm


def test_percent_of_book_scales_with_equity():
    # 4% * 0.75 = 3% of $100k = $3,000 — double the old flat $1,500.
    assert _rm(PCT_LIMITS).get_trade_size("1K–15K", 100_000) == 3000


def test_larger_disclosure_bucket_larger_copy():
    rm = _rm(PCT_LIMITS)
    assert rm.get_trade_size("15K–50K", 100_000) == 5000     # 4% * 1.25 = 5%
    assert rm.get_trade_size("250K–500K", 100_000) == 8000   # 4% * 2.0 = 8% (cap)


def test_capped_at_max_trade_value_on_large_book():
    # 3% of $1M = $30k, but max_trade_value caps every single copy at $8,000.
    assert _rm(PCT_LIMITS).get_trade_size("1K–15K", 1_000_000) == 8000


def test_floor_applies_on_tiny_book():
    # 3% of $5,000 = $150 -> floored to the $200 minimum trade value.
    assert _rm(PCT_LIMITS).get_trade_size("1K–15K", 5_000) == 200


def test_unknown_bucket_uses_base_multiplier_of_one():
    # Unrecognised bucket -> multiplier 1.0 -> 4% of $100k = $4,000.
    assert _rm(PCT_LIMITS).get_trade_size("???", 100_000) == 4000


def test_backward_compatible_legacy_table_without_base_pct():
    legacy = {k: v for k, v in PCT_LIMITS.items() if k != "base_position_pct"}
    # No base_position_pct -> falls back to the flat scaling table ($1,500).
    assert _rm(legacy).get_trade_size("1K–15K", 100_000) == 1500


def test_never_exceeds_single_position_cap():
    rm = _rm(PCT_LIMITS)
    for bucket in PCT_LIMITS["size_bucket_multiplier"]:
        for equity in (50_000, 100_000, 250_000, 1_000_000):
            size = rm.get_trade_size(bucket, equity)
            assert size <= equity * PCT_LIMITS["max_single_position_pct"] / 100.0 + 1e-6
            assert size <= PCT_LIMITS["max_trade_value_usd"] + 1e-6
            assert size >= PCT_LIMITS["min_trade_value_usd"] - 1e-6
