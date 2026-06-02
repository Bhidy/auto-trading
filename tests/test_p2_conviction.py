"""P2 conviction model — politician track-record weighting + cluster-buy boost.

Copies were a flat size regardless of who disclosed or how many members piled
into the same name. The conviction model scales each copy by the politician's
credibility tier and by cluster strength (distinct politicians buying the same
ticker), CLAMPED so it only moves size within the hardcoded caps — never past
them. These tests lock the math and the clamp.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P2_SCRIPTS = os.path.join(REPO_ROOT, "political-copy-bot", "scripts")
for _p in (REPO_ROOT, P2_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from politician_bot import (  # noqa: E402
    compute_conviction_multiplier,
    count_cluster_buys,
    politician_weight,
)


# --- cluster detection -------------------------------------------------------

def test_counts_distinct_politicians_per_ticker():
    pairs = [("NVDA", "Pelosi"), ("NVDA", "Khanna"), ("NVDA", "Pelosi"),
             ("TER", "McCaul")]
    counts = count_cluster_buys(pairs)
    assert counts["NVDA"] == 2          # Pelosi counted once, + Khanna
    assert counts["TER"] == 1


def test_cluster_ignores_blank_ticker_or_name():
    counts = count_cluster_buys([("", "Pelosi"), ("NVDA", ""), ("NVDA", "Khanna")])
    assert counts == {"NVDA": 1}


# --- politician weighting ----------------------------------------------------

def test_tiered_politician_gets_its_weight():
    tiers = {"Nancy Pelosi": 1.4}
    assert politician_weight("Nancy Pelosi", tiers) == 1.4


def test_untiered_politician_defaults_to_one():
    assert politician_weight("Nobody Special", {"Nancy Pelosi": 1.4}) == 1.0
    assert politician_weight("", {"Nancy Pelosi": 1.4}) == 1.0
    assert politician_weight("X", {}) == 1.0


# --- conviction multiplier (weight x cluster, clamped) -----------------------

def test_lone_average_politician_is_neutral():
    assert compute_conviction_multiplier(1.0, 1) == 1.0


def test_cluster_boosts_size():
    # 3 politicians, neutral weight: 1 + 2*0.25 = 1.5
    assert compute_conviction_multiplier(1.0, 3) == 1.5


def test_weight_and_cluster_compound_but_clamp():
    # Pelosi 1.4 x cluster-of-2 (1.25) = 1.75 -> clamped to max 1.5
    assert compute_conviction_multiplier(1.4, 2, max_mult=1.5) == 1.5


def test_clamps_to_min():
    assert compute_conviction_multiplier(0.2, 1, min_mult=0.75) == 0.75


def test_nonpositive_weight_treated_as_neutral():
    assert compute_conviction_multiplier(0, 1) == 1.0


def test_bad_input_returns_neutral():
    assert compute_conviction_multiplier("x", 2) == 1.0
    assert compute_conviction_multiplier(1.2, None) == 1.0


def test_never_exceeds_max_regardless_of_inputs():
    for w in (1.0, 1.2, 1.4, 3.0):
        for c in (1, 2, 5, 20):
            assert compute_conviction_multiplier(w, c, max_mult=1.5) <= 1.5
