"""Tests for triple-barrier labeling (labeling)."""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest.labeling import (  # noqa: E402
    ewma_vol_series,
    returns_from_prices,
    triple_barrier_labels,
)


# --- Helpers ----------------------------------------------------------------

def test_returns_from_prices():
    rs = returns_from_prices([100, 110, 99])
    assert round(rs[0], 6) == 0.1  # 110/100 - 1
    assert round(rs[1], 6) == round(99 / 110 - 1, 6)


def test_ewma_vol_series_length_and_nonneg():
    rs = [0.01, -0.02, 0.015, -0.01, 0.02]
    vol = ewma_vol_series(rs, span=3)
    assert len(vol) == len(rs)
    assert all(v >= 0 for v in vol)


def test_ewma_vol_empty():
    assert ewma_vol_series([]) == []


# --- Triple barrier ---------------------------------------------------------

def _seed(p=100.0):
    # Low-vol oscillation to seed a small sigma, then a clear directional move.
    return [p, p + 0.5, p, p + 0.5, p, p + 0.5, p]


def test_upper_barrier_labels_plus_one():
    prices = _seed() + [100.5, 100.0, 120.0]   # big jump up at the end
    labels = triple_barrier_labels(prices, pt=2.0, sl=2.0, max_horizon=5, vol_span=5)
    ev = next(d for d in labels if d["t0"] == 6)
    assert ev["label"] == 1
    assert ev["touch"] == "upper"
    assert ev["ret"] > 0


def test_lower_barrier_labels_minus_one():
    prices = _seed() + [99.5, 100.0, 80.0]     # big drop at the end
    labels = triple_barrier_labels(prices, pt=2.0, sl=2.0, max_horizon=5, vol_span=5)
    ev = next(d for d in labels if d["t0"] == 6)
    assert ev["label"] == -1
    assert ev["touch"] == "lower"
    assert ev["ret"] < 0


def test_vertical_barrier_labels_zero_when_barriers_wide():
    prices = _seed() + [100.5, 100.0, 100.5, 100.0]
    # Very wide barriers (pt=sl=50 sigma) -> nothing touched -> time barrier (0).
    labels = triple_barrier_labels(prices, pt=50.0, sl=50.0, max_horizon=3, vol_span=5)
    ev = next(d for d in labels if d["t0"] == 6)
    assert ev["label"] == 0
    assert ev["touch"] == "vertical"


def test_skips_events_without_room_or_history():
    prices = _seed() + [120.0]
    labels = triple_barrier_labels(prices, max_horizon=3, vol_span=5)
    t0s = [d["t0"] for d in labels]
    assert 0 not in t0s                 # no prior return
    assert (len(prices) - 1) not in t0s  # no room ahead
