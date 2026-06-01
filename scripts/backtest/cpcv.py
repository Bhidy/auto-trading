"""
Combinatorial Purged Cross-Validation (CPCV) — split generation (T1, pure-Python).

The sequential walk-forward in walk_forward.py respects chronology but yields a
SINGLE path: a strategy can pass by luck on one historical ordering. CPCV (López de
Prado, *Advances in Financial Machine Learning*, ch. 7) instead partitions the
series into N contiguous groups, tests on every C(N, k) combination of k groups,
and reconstructs many out-of-sample paths — turning one point estimate into a
DISTRIBUTION of OOS performance. Two leakage guards are mandatory for financial
series whose labels span multiple bars:

  * PURGING — drop training observations whose label horizon overlaps the test
              window (else the model trains on outcomes it will be tested on).
  * EMBARGO — drop a buffer of training observations immediately AFTER each test
              block, to kill serial-correlation bleed from delayed reactions.

This module only GENERATES the index splits (pure, deterministic, dependency-free);
the caller runs its own backtest per split and feeds the resulting Sharpe set to
metrics.deflated_sharpe_ratio / probability_of_backtest_overfitting. No look-ahead,
no model assumptions, no third-party libraries — safe for the requests-only runtime.
"""
from itertools import combinations
from math import comb


def make_groups(n_obs, n_groups):
    """Partition indices [0, n_obs) into `n_groups` contiguous, near-equal groups.

    Returns a list of (start, end_exclusive) ranges covering every index exactly
    once. Earlier groups absorb the remainder when n_obs is not divisible by
    n_groups, so coverage is complete and deterministic.
    """
    if n_obs <= 0 or n_groups <= 0 or n_groups > n_obs:
        raise ValueError("require 0 < n_groups <= n_obs")
    base, extra = divmod(n_obs, n_groups)
    groups = []
    start = 0
    for g in range(n_groups):
        size = base + (1 if g < extra else 0)
        groups.append((start, start + size))
        start += size
    return groups


def n_splits(n_groups, n_test_groups):
    """Number of train/test splits generated = C(n_groups, n_test_groups)."""
    return comb(n_groups, n_test_groups)


def n_backtest_paths(n_groups, n_test_groups):
    """Number of complete OOS paths reconstructable = C(N,k)·k/N (López de Prado)."""
    return n_splits(n_groups, n_test_groups) * n_test_groups // n_groups


def _contiguous_runs(sorted_idx):
    """Yield (start, end_inclusive) for each maximal contiguous run in a sorted list."""
    if not sorted_idx:
        return
    run_start = prev = sorted_idx[0]
    for i in sorted_idx[1:]:
        if i == prev + 1:
            prev = i
            continue
        yield (run_start, prev)
        run_start = prev = i
    yield (run_start, prev)


def combinatorial_splits(n_obs, n_groups=6, n_test_groups=2, label_horizon=1,
                         embargo_pct=0.01):
    """Yield CPCV splits as dicts:

        {"test_groups": (g_i, ...), "test_idx": [...], "train_idx": [...],
         "n_purged": int, "n_embargoed": int}

    `train_idx` is already PURGED (label-overlap with the test set removed) and
    EMBARGOED (buffer after each contiguous test block removed). `label_horizon` =
    number of bars a label spans (purge looks ahead this many bars); `embargo_pct` =
    fraction of n_obs dropped after each test block. Deterministic; splits are
    emitted in itertools.combinations order. test_idx and train_idx are disjoint.
    """
    if n_test_groups <= 0 or n_test_groups >= n_groups:
        raise ValueError("require 0 < n_test_groups < n_groups")
    groups = make_groups(n_obs, n_groups)
    horizon = max(0, int(label_horizon))
    embargo = int(round(max(0.0, embargo_pct) * n_obs))

    for combo in combinations(range(n_groups), n_test_groups):
        test_idx = sorted(i for g in combo for i in range(*groups[g]))
        test_set = set(test_idx)

        # Embargo: the `embargo` indices immediately AFTER each contiguous test run.
        embargo_set = set()
        for (_, run_end) in _contiguous_runs(test_idx):
            embargo_set.update(range(run_end + 1, min(n_obs, run_end + 1 + embargo)))

        train_idx = []
        n_purged = 0
        for i in range(n_obs):
            if i in test_set or i in embargo_set:
                continue
            # Purge: label of train obs i spans [i, i+horizon]; drop if it touches test.
            if any((i + h) in test_set for h in range(0, horizon + 1)):
                n_purged += 1
                continue
            train_idx.append(i)

        yield {
            "test_groups": combo,
            "test_idx": test_idx,
            "train_idx": train_idx,
            "n_purged": n_purged,
            "n_embargoed": len(embargo_set - test_set),
        }
