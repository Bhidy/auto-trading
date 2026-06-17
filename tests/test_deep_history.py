"""The data-depth unlock: the committed deep-history cache (data/deep, ~3y) must
give the walk-forward stack enough out-of-sample windows that PBO (which needs
>=4 slices) becomes computable — the thing the 220-bar cache could never do, so
every 'validated' improvement on it was flagged thin-sample."""
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEEP = os.path.join(REPO_ROOT, "data", "deep")

pytestmark = pytest.mark.skipif(
    not os.path.isdir(DEEP) or not os.listdir(DEEP),
    reason="deep-history cache not present (run scripts/research/fetch_deep_history.py)")


def test_deep_cache_is_multi_year():
    from backtest.walk_forward import load_aligned_bars
    sb, spy = load_aligned_bars(DEEP, min_coverage=0.85)
    assert spy is not None and len(spy) >= 500          # ~2-3y, not the 220-bar cache
    assert len(sb) >= 15                                 # the full equity universe


def test_deep_cache_makes_pbo_computable():
    from backtest.walk_forward import load_aligned_bars, walk_forward
    sb, spy = load_aligned_bars(DEEP, min_coverage=0.85)
    out = walk_forward(sb, spy, params={}, warmup=150)
    assert out["aggregate"] is not None
    # >=4 OOS windows is the threshold below which PBO (CSCV) cannot be formed.
    assert out["aggregate"]["n_windows"] >= 4
