"""Pure allocator tests (scripts/backtest/allocators.py) — deterministic synthetic fixtures."""
import math
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest.allocators import (  # noqa: E402
    ALLOCATORS,
    crisis_core_target_weights,
    matf_target_weights,
    percentile_ranks,
    secmom_select,
    secmom_target_weights,
    tbill_basket,
    trend_score,
)

N = 600
S1 = ["SPY", "IWM", "EFA", "EEM", "VNQ", "IEF", "TLT", "TIP", "DBC", "GLD"]
S2 = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLRE", "XLC", "EFA", "EEM"]
S3 = ["SPY", "QQQ", "IWM", "EFA", "DBMF", "KMLM", "CTA", "IEF"]
BILLS = ["BIL", "SHV", "SGOV", "USFR"]


def _path(seed, drift, vol=0.01, n=N, start=100.0):
    """Deterministic pseudo-random walk (LCG) — no randomness across runs."""
    x, out, p = seed * 9973 + 17, [], start
    for _ in range(n):
        x = (1103515245 * x + 12345) % (2 ** 31)
        z = (x / 2 ** 31 - 0.5) * 3.4
        p *= math.exp(drift + vol * z)
        out.append(p)
    return out


def _universe(drift=0.0004, bill_drift=0.0001, listed=None):
    syms = sorted(set(S1 + S2 + S3 + BILLS))
    closes = {}
    for k, s in enumerate(syms):
        if s in BILLS:
            closes[s] = [100.0 * (1 + bill_drift) ** i for i in range(N)]
        else:
            closes[s] = _path(k + 1, drift + 0.0003 * ((k % 5) - 2), vol=0.006 + 0.002 * (k % 4))
    for s, first in (listed or {}).items():
        closes[s] = [None] * first + closes[s][first:]
    return closes


def _check_caps(w, cap=0.114):
    assert all(v >= 0 for v in w.values())
    assert all(v <= cap + 1e-12 for v in w.values()), w
    assert sum(w.values()) <= 1.0 + 1e-9


def test_cap_compliance_all_allocators_many_dates():
    closes = _universe(listed={"SGOV": 400, "DBMF": 350, "KMLM": 450, "CTA": 520, "XLC": 200})
    for sid, fn in ALLOCATORS.items():
        for t in range(330, N, 13):
            _check_caps(fn(closes, t, {}))


def test_no_look_ahead_poisoned_future():
    closes = _universe(listed={"SGOV": 400})
    t = 420
    poisoned = {s: v[:t + 1] + [1e9 if i % 2 else 1e-3 for i in range(N - t - 1)] for s, v in closes.items()}
    for sid, fn in ALLOCATORS.items():
        assert fn(closes, t, {}) == fn(poisoned, t, {}), sid
        truncated = {s: v[:t + 1] for s, v in closes.items()}
        assert fn(closes, t, {}) == fn(truncated, t, {}), sid


def _all_down(listed=None):
    closes = _universe(bill_drift=0.0002, listed=listed)
    for s in set(S1 + S2 + S3) - {"DBMF", "KMLM", "CTA"}:
        closes[s] = [100.0 * 0.999 ** i * (1 + 0.004 * ((i % 3) - 1)) for i in range(N)]
    return closes


def test_all_trends_negative_falls_back_to_bills_then_cash():
    closes = _all_down(listed={"SGOV": 590})
    w = matf_target_weights(closes, 500, {})
    assert all(w.get(s, 0) == 0 for s in S1)
    # SGOV not listed at t=500 -> BIL, SHV, USFR at 11.4% each, the rest is cash
    assert w == {"BIL": 0.114, "SHV": 0.114, "USFR": 0.114}
    assert abs(1 - sum(w.values()) - 0.658) < 1e-12
    w2 = secmom_target_weights(closes, 500, {})
    assert all(w2.get(s, 0) == 0 for s in S2)


def test_tbill_basket_availability_by_date():
    closes = {"BIL": [1.0] * 10, "SHV": [1.0] * 10, "SGOV": [None] * 5 + [1.0] * 5, "USFR": [1.0] * 10}
    assert tbill_basket(0.5, closes, 4) == {"BIL": 0.114, "SHV": 0.114, "USFR": 0.114}
    assert tbill_basket(0.5, closes, 5) == {"BIL": 0.114, "SHV": 0.114, "SGOV": 0.114, "USFR": 0.114}
    assert tbill_basket(0.05, closes, 5) == {"BIL": 0.05}
    assert tbill_basket(0.0, closes, 5) == {}


def test_trend_score_votes():
    up = [100 * 1.001 ** i for i in range(300)]
    bil = [100 * 1.0001 ** i for i in range(300)]
    p = {"lookbacks": [63, 126, 252], "sma": 200, "hurdle": "BIL"}
    assert trend_score({"A": up, "BIL": bil}, "A", 299, p) == 1.0
    down = [100 * 0.999 ** i for i in range(300)]
    assert trend_score({"A": down, "BIL": bil}, "A", 299, p) == 0.0
    assert trend_score({"A": up, "BIL": bil}, "A", 200, p) is None  # insufficient history


def test_matf_vol_target_scales_down_only():
    closes = _universe(drift=0.002)
    lo = matf_target_weights(closes, 500, {"vol_target": 0.02})
    hi = matf_target_weights(closes, 500, {"vol_target": 5.0})
    risky_lo = sum(lo.get(s, 0) for s in S1)
    risky_hi = sum(hi.get(s, 0) for s in S1)
    assert risky_lo < risky_hi
    assert risky_hi <= 10 * 0.114 + 1e-12


def test_percentile_ranks_ties_and_order():
    r = percentile_ranks({"a": 1.0, "b": 2.0, "c": 2.0, "d": 3.0})
    assert r["a"] == 0.0 and r["d"] == 1.0 and r["b"] == r["c"] == 0.5


def test_secmom_buffer_keeps_incumbent_ranked_7():
    closes = _universe(drift=0.001)
    p = {"prev_held": []}
    ranked, passes, selected, held = secmom_select(closes, 500, {**_secmom_defaults(), **p})
    assert len(selected) == 6 and selected == ranked[:6]
    passing_7_8 = [s for s in ranked[6:8] if passes[s]]
    if passing_7_8:
        inc = passing_7_8[0]
        _, _, sel2, _ = secmom_select(closes, 500, {**_secmom_defaults(), "prev_held": [inc]})
        assert inc in sel2 and len(sel2) == 6
    # an incumbent ranked worse than the buffer is dropped
    if len(ranked) > 9:
        _, _, sel3, _ = secmom_select(closes, 500, {**_secmom_defaults(), "prev_held": [ranked[-1]]})
        assert ranked[-1] not in sel3


def test_secmom_failing_filter_slot_goes_to_bills():
    closes = _all_down()
    w = secmom_target_weights(closes, 500, {})
    assert sum(w.get(s, 0) for s in S2) == 0
    assert set(w) <= set(BILLS)


def test_secmom_eligibility_requires_history():
    closes = _universe(listed={"XLC": 300})
    ranked, _, _, _ = secmom_select(closes, 500, _secmom_defaults())
    assert "XLC" not in ranked  # only 201 bars of own history < 273
    ranked2, _, _, _ = secmom_select(closes, 590, _secmom_defaults())
    assert "XLC" in ranked2


def test_crisis_core_mf_availability_and_remainder():
    closes = _universe(listed={"DBMF": 350, "KMLM": 450, "CTA": 520, "SGOV": 400})
    w0 = crisis_core_target_weights(closes, 340, {})
    assert not any(s in w0 for s in ("DBMF", "KMLM", "CTA"))
    assert abs(sum(w0.get(s, 0) for s in ("SPY", "QQQ", "IWM", "EFA", "IEF")) - 0.57) < 1e-12
    assert w0 == {"SPY": .114, "QQQ": .114, "IWM": .114, "EFA": .114, "IEF": .114,
                  "BIL": .114, "SHV": .114, "USFR": .114}  # 8.8% cash
    w1 = crisis_core_target_weights(closes, 560, {})
    assert all(w1[s] == 0.114 for s in ("DBMF", "KMLM", "CTA", "IEF"))
    assert abs(w1["BIL"] - 0.088) < 1e-12 and abs(sum(w1.values()) - 1.0) < 1e-12


def _secmom_defaults():
    from backtest.allocators import SECMOM_DEFAULTS
    return dict(SECMOM_DEFAULTS)
