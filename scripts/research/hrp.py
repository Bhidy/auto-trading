"""
Hierarchical Risk Parity (HRP) + Ledoit-Wolf shrinkage — T2 research (numpy).

HRP (López de Prado, *Advances in Financial Machine Learning*, ch. 16) allocates
risk WITHOUT inverting the covariance matrix — the step that makes Markowitz
mean-variance brittle and prone to extreme, unstable weights. It:

  1. converts the correlation matrix to a distance matrix d = √(½(1−ρ));
  2. clusters assets by that distance (single-linkage) and reads off the
     dendrogram leaf order (quasi-diagonalization);
  3. recursively bisects the ordered list, splitting capital between the two
     halves in inverse proportion to each half's variance.

Inputs are first regularized with **Ledoit-Wolf (2004) shrinkage** toward a
scaled-identity target (the canonical `cov1para`), which conditions the noisy
sample covariance. Implemented in NUMPY ONLY (no scipy/sklearn) so the artifact
is fully reproducible anywhere numpy is present. Output weights are ADVISORY
target tilts — the consumer MUST clamp them inside the hardcoded caps in
config/risk_limits.json; HRP never relaxes a limit.
"""
import numpy as np


def ledoit_wolf_identity(returns):
    """Ledoit-Wolf (2004) shrinkage of the sample covariance toward μ·I (cov1para).

    `returns`: array (n_obs, n_assets). Returns (cov_shrunk, shrinkage_delta) with
    delta in [0, 1] (0 = pure sample covariance, 1 = pure scaled identity).
    """
    X = np.asarray(returns, dtype=float)
    t, n = X.shape
    X = X - X.mean(axis=0, keepdims=True)
    sample = (X.T @ X) / t                       # MLE sample covariance
    mean_var = np.trace(sample) / n
    prior = mean_var * np.eye(n)                  # shrinkage target μ·I
    x2 = X ** 2
    phi = float(np.sum((x2.T @ x2) / t - sample ** 2))   # Σ est. Var(s_ij)·t
    gamma = float(np.sum((sample - prior) ** 2))         # ||S − target||²_F
    kappa = phi / gamma if gamma > 0 else 0.0
    delta = max(0.0, min(1.0, kappa / t))
    cov = delta * prior + (1.0 - delta) * sample
    return cov, float(delta)


def _cov_to_corr(cov):
    d = np.sqrt(np.clip(np.diag(cov), 0, None))
    outer = np.outer(d, d)
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = np.where(outer > 0, cov / outer, 0.0)
    return np.clip(corr, -1.0, 1.0)


def _distance(corr):
    """Correlation distance d_ij = √(½(1 − ρ_ij)) ∈ [0, 1]."""
    return np.sqrt(np.clip((1.0 - corr) / 2.0, 0.0, None))


def quasi_diag_order(dist):
    """Single-linkage agglomerative clustering → dendrogram leaf order (quasi-
    diagonalization). O(n³) but n is tiny (≤ a few dozen symbols). Pure numpy.
    """
    n = dist.shape[0]
    if n == 0:
        return []
    if n == 1:
        return [0]
    clusters = {i: [i] for i in range(n)}
    linkage = []                                 # scipy-style rows: (a, b, dist, size)
    active = list(range(n))
    next_id = n

    def cluster_dist(a, b):
        return min(dist[i, j] for i in clusters[a] for j in clusters[b])

    while len(active) > 1:
        best = None
        for x in range(len(active)):
            for y in range(x + 1, len(active)):
                a, b = active[x], active[y]
                dd = cluster_dist(a, b)
                if best is None or dd < best[0]:
                    best = (dd, a, b)
        dd, a, b = best
        clusters[next_id] = clusters[a] + clusters[b]
        linkage.append((a, b, dd, len(clusters[next_id])))
        active.remove(a)
        active.remove(b)
        active.append(next_id)
        next_id += 1

    # Expand the root merge into a left-to-right leaf ordering (preorder leaves).
    root = next_id - 1
    order, stack = [], [root]
    while stack:
        node = stack.pop()
        if node < n:
            order.append(node)
        else:
            a, b, _, _ = linkage[node - n]
            stack.append(b)      # push right first so left is expanded first
            stack.append(a)
    return order


def _cluster_var(cov, idx):
    """Variance of an inverse-variance-weighted sub-portfolio over `idx`."""
    sub = cov[np.ix_(idx, idx)]
    ivp = 1.0 / np.diag(sub)
    ivp = ivp / ivp.sum()
    return float(ivp @ sub @ ivp)


def recursive_bisection(cov, sort_ix):
    """Allocate weights by recursively bisecting the quasi-diagonal order and
    splitting capital between halves in inverse proportion to cluster variance.
    Returns a weight array indexed by ORIGINAL asset index."""
    n = len(sort_ix)
    w_pos = np.ones(n)                           # weights indexed by position in sort_ix
    clusters = [list(range(n))]
    while clusters:
        nxt = []
        for c in clusters:
            if len(c) <= 1:
                continue
            half = len(c) // 2
            left, right = c[:half], c[half:]
            var_l = _cluster_var(cov, [sort_ix[i] for i in left])
            var_r = _cluster_var(cov, [sort_ix[i] for i in right])
            alpha = 1.0 - var_l / (var_l + var_r) if (var_l + var_r) > 0 else 0.5
            for i in left:
                w_pos[i] *= alpha
            for i in right:
                w_pos[i] *= (1.0 - alpha)
            nxt.append(left)
            nxt.append(right)
        clusters = nxt
    weights = np.zeros(n)
    for pos, asset in enumerate(sort_ix):
        weights[asset] = w_pos[pos]
    return weights


def hrp_weights(returns, symbols, shrink=True):
    """Compute HRP target weights for `symbols` from a (n_obs, n_assets) returns
    matrix. Returns (weights_dict, shrinkage_delta). Weights are non-negative and
    sum to 1.0. ADVISORY — clamp inside risk_limits.json before any use.
    """
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 2 or returns.shape[1] != len(symbols):
        raise ValueError("returns must be (n_obs, len(symbols))")
    if shrink:
        cov, delta = ledoit_wolf_identity(returns)
    else:
        cov, delta = np.cov(returns, rowvar=False), 0.0
    cov = np.atleast_2d(cov)
    corr = _cov_to_corr(cov)
    order = quasi_diag_order(_distance(corr))
    w = recursive_bisection(cov, order)
    total = w.sum()
    if total > 0:
        w = w / total
    return {symbols[i]: float(w[i]) for i in range(len(symbols))}, float(delta)
