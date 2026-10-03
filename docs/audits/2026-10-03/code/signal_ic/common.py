import json
import math

OUT = "/tmp/audit_2026_10_03/agentE"
HORIZONS = [1, 5, 10, 21]
DEFENSIVE = {"SHY", "BIL", "TLT", "GLD"}

BARS = json.load(open(f"{OUT}/bars.json"))
CAL = [b["d"] for b in BARS["SPY"]]
CIDX = {d: i for i, d in enumerate(CAL)}
OPEN = {s: {b["d"]: b["o"] for b in v} for s, v in BARS.items()}
CLOSE = {s: {b["d"]: b["c"] for b in v} for s, v in BARS.items()}


def fwd(sym, day, h, excess=False):
    """Open(t+1) -> Open(t+1+h). Signal at day t, executed next-day open."""
    i = CIDX.get(day)
    if i is None or i + 1 + h >= len(CAL):
        return None
    d0, d1 = CAL[i + 1], CAL[i + 1 + h]
    o = OPEN.get(sym, {})
    if d0 not in o or d1 not in o or not o[d0]:
        return None
    r = o[d1] / o[d0] - 1
    if excess:
        s = fwd("SPY", day, h)
        if s is None:
            return None
        r -= s
    return r


def rank(xs):
    idx = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and xs[idx[j + 1]] == xs[idx[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[idx[k]] = avg
        i = j + 1
    return r


def pearson(a, b):
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def spearman(a, b):
    return pearson(rank(a), rank(b))


def mean(x):
    return sum(x) / len(x) if x else float("nan")


def std(x):
    if len(x) < 2:
        return float("nan")
    m = mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))


def nw_t(x, lag):
    """Newey-West (Bartlett) t-stat of the mean."""
    n = len(x)
    if n < 3:
        return float("nan")
    m = mean(x)
    e = [v - m for v in x]
    g0 = sum(v * v for v in e) / n
    s = g0
    for L in range(1, min(lag, n - 1) + 1):
        w = 1 - L / (lag + 1)
        gl = sum(e[i] * e[i - L] for i in range(L, n)) / n
        s += 2 * w * gl
    if s <= 0:
        return float("nan")
    return m / math.sqrt(s / n)


def t_simple(x):
    if len(x) < 3:
        return float("nan")
    sd = std(x)
    return mean(x) / (sd / math.sqrt(len(x))) if sd > 0 else float("nan")


def series_stats(series, h, step=None):
    """series: list of (day, value) in date order. Returns mean/std/hit/NW t/non-overlap t."""
    vals = [v for _, v in series]
    step = step or h
    nono = vals[::step]
    return {
        "n": len(vals), "mean": mean(vals), "std": std(vals),
        "hit": mean([1.0 if v > 0 else 0.0 for v in vals]) if vals else float("nan"),
        "t_nw": nw_t(vals, max(h, 1)), "n_nonov": len(nono), "t_nonov": t_simple(nono),
    }
