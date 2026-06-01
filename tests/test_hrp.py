"""Tests for the T2 HRP research module.

T2 modules use numpy (requirements-research.txt). CI runs on the requests-only
deps, so this whole module SKIPS there via importorskip — keeping the CI gate
green while the math is still validated locally / in the research lane.
"""
import os
import sys

import pytest

np = pytest.importorskip("numpy")   # skip entire module when numpy is absent (CI)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts"), os.path.join(REPO_ROOT, "scripts", "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from research.hrp import (  # noqa: E402
    hrp_weights,
    ledoit_wolf_identity,
    quasi_diag_order,
    recursive_bisection,
)


def _block_returns(n=400, seed=7):
    """Two correlated blocks: {0,1} share a factor, {2,3} share another; blocks
    are independent. Asset 3 is the most volatile."""
    rng = np.random.default_rng(seed)
    f1 = rng.normal(0, 0.01, n)
    f2 = rng.normal(0, 0.01, n)
    a0 = f1 + rng.normal(0, 0.002, n)
    a1 = f1 + rng.normal(0, 0.002, n)
    a2 = f2 + rng.normal(0, 0.002, n)
    a3 = f2 + rng.normal(0, 0.02, n)   # higher idiosyncratic vol
    return np.column_stack([a0, a1, a2, a3])


def test_ledoit_wolf_delta_in_unit_interval_and_conditions():
    R = _block_returns()
    cov, delta = ledoit_wolf_identity(R)
    assert 0.0 <= delta <= 1.0
    assert cov.shape == (4, 4)
    # Shrinkage cannot make conditioning worse than the raw sample covariance.
    sample = np.cov(R, rowvar=False)
    assert np.linalg.cond(cov) <= np.linalg.cond(sample) + 1e-6


def test_quasi_diag_order_is_a_permutation():
    R = _block_returns()
    cov, _ = ledoit_wolf_identity(R)
    d = np.sqrt(np.clip((1 - np.corrcoef(R, rowvar=False)) / 2, 0, None))
    order = quasi_diag_order(d)
    assert sorted(order) == [0, 1, 2, 3]
    # Correlated pairs should sit adjacent in the quasi-diagonal order.
    pos = {a: i for i, a in enumerate(order)}
    assert abs(pos[0] - pos[1]) == 1
    assert abs(pos[2] - pos[3]) == 1


def test_hrp_weights_sum_to_one_and_nonnegative():
    R = _block_returns()
    w, delta = hrp_weights(R, ["A", "B", "C", "D"])
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(v >= 0 for v in w.values())
    assert 0.0 <= delta <= 1.0


def test_hrp_underweights_the_most_volatile_asset():
    R = _block_returns()
    w, _ = hrp_weights(R, ["A", "B", "C", "D"])
    # D (asset 3) is the most volatile -> should get the smallest weight.
    assert w["D"] == min(w.values())


def test_recursive_bisection_equal_for_identity_cov():
    cov = np.eye(4)
    w = recursive_bisection(cov, [0, 1, 2, 3])
    w = w / w.sum()
    assert np.allclose(w, 0.25, atol=1e-9)
