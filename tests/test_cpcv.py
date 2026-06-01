"""Tests for Combinatorial Purged Cross-Validation split generation (cpcv)."""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from backtest.cpcv import (  # noqa: E402
    combinatorial_splits,
    make_groups,
    n_backtest_paths,
    n_splits,
)


# --- Group partitioning -----------------------------------------------------

def test_make_groups_covers_all_indices_once():
    groups = make_groups(10, 3)
    # base=3, extra=1 -> first group gets the remainder: 4,3,3
    assert groups == [(0, 4), (4, 7), (7, 10)]
    covered = [i for (s, e) in groups for i in range(s, e)]
    assert covered == list(range(10))


def test_make_groups_rejects_bad_args():
    with pytest.raises(ValueError):
        make_groups(5, 6)   # more groups than observations
    with pytest.raises(ValueError):
        make_groups(0, 1)


# --- Split / path counts ----------------------------------------------------

def test_split_and_path_counts():
    assert n_splits(6, 2) == 15            # C(6,2)
    assert n_backtest_paths(6, 2) == 5     # 15 * 2 // 6


# --- Combinatorial splits ---------------------------------------------------

def test_number_of_splits_matches_formula():
    splits = list(combinatorial_splits(12, n_groups=6, n_test_groups=2,
                                        label_horizon=0, embargo_pct=0))
    assert len(splits) == n_splits(6, 2) == 15


def test_train_and_test_are_disjoint_and_in_range():
    for sp in combinatorial_splits(12, n_groups=6, n_test_groups=2,
                                   label_horizon=0, embargo_pct=0):
        test_set, train_set = set(sp["test_idx"]), set(sp["train_idx"])
        assert test_set.isdisjoint(train_set)
        assert all(0 <= i < 12 for i in test_set | train_set)
    # With no purge/embargo, train + test partition the whole series.
    first = next(combinatorial_splits(12, n_groups=6, n_test_groups=2,
                                      label_horizon=0, embargo_pct=0))
    assert sorted(first["test_idx"] + first["train_idx"]) == list(range(12))


def test_purging_drops_label_overlap():
    # 12 obs, 6 groups of 2: g0=(0,2) g1=(2,4) g2=(4,6)... test on groups (0,2)
    # -> test_idx = [0,1,4,5]. With horizon=1, train obs 3 has label [3,4] touching
    # test index 4 -> purged.
    splits = list(combinatorial_splits(12, n_groups=6, n_test_groups=2,
                                       label_horizon=1, embargo_pct=0))
    sp = next(s for s in splits if s["test_groups"] == (0, 2))
    assert sp["test_idx"] == [0, 1, 4, 5]
    assert 3 not in sp["train_idx"]      # purged (label reaches into test)
    assert sp["n_purged"] >= 1


def test_embargo_drops_buffer_after_test_block():
    # embargo_pct chosen so embargo = round(0.1*12) = 1 index after each test run.
    splits = list(combinatorial_splits(12, n_groups=6, n_test_groups=2,
                                       label_horizon=0, embargo_pct=0.1))
    sp = next(s for s in splits if s["test_groups"] == (0, 2))
    # Test runs end at index 1 and index 5 -> embargo indices 2 and 6 removed.
    assert 2 not in sp["train_idx"]
    assert 6 not in sp["train_idx"]
    assert sp["n_embargoed"] >= 1


def test_rejects_invalid_test_group_count():
    with pytest.raises(ValueError):
        list(combinatorial_splits(12, n_groups=6, n_test_groups=6))
    with pytest.raises(ValueError):
        list(combinatorial_splits(12, n_groups=6, n_test_groups=0))
