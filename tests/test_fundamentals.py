"""Fundamental-factor capability (SEC EDGAR quality/value/growth tilt).
Param-gated and OFF by default (fundamental_weight=0) -> exact parity. Point-in-
time by FILED date -> no look-ahead. The factor was rigorously REJECTED on 3-year
data (PBO 0.56, below buy-and-hold) — but the capability + no-fabrication data
pipeline are committed for future use on a wider universe."""
from backtest.multifactor import _fundamental_at, backtest_multifactor
from research.fetch_fundamentals import quality_score


def test_quality_score_directions():
    high = quality_score(rev_growth=0.30, net_margin=0.35, roe=0.45)
    low = quality_score(rev_growth=-0.10, net_margin=0.02, roe=0.03)
    assert high > 0.5 and low < -0.5          # strong vs weak fundamentals separate cleanly


def test_fundamental_at_is_point_in_time():
    series = [{"effective": "2023-02-01", "quality_score": 0.2},
              {"effective": "2024-02-01", "quality_score": 0.6}]
    assert _fundamental_at(series, "2022-12-31") is None     # before any filing -> no data
    assert _fundamental_at(series, "2023-06-01") == 0.2      # uses the 2023 10-K only
    assert _fundamental_at(series, "2024-06-01") == 0.6      # the 2024 10-K is now public
    assert _fundamental_at(None, "2024-06-01") is None


def _bars(closes, start="2024-01-01"):
    import datetime
    out, prev = [], closes[0]
    d = datetime.date.fromisoformat(start)
    for c in closes:
        out.append({"t": d.isoformat() + "T00:00:00Z", "o": prev, "h": max(c, prev) * 1.002,
                    "l": min(c, prev) * 0.998, "c": c, "v": 1_000_000})
        prev = c
        d += datetime.timedelta(days=1)
    return out


def _universe(n=260):
    return {"SPY": _bars([400 * (1.0006 ** i) for i in range(n)]),
            "AAA": _bars([100 * (1.001 ** i) for i in range(n)]),
            "BBB": _bars([100 * (1.0008 ** i) for i in range(n)])}


def test_fundamental_factor_off_by_default_is_noop():
    syms = _universe()
    fund = {"AAA": [{"effective": "2023-01-01", "quality_score": 1.0}]}
    # fundamentals supplied but weight unset -> the factor must not fire (parity).
    a = backtest_multifactor(syms, syms["SPY"], max_positions=2, warmup=200, buy_threshold=0.3)
    b = backtest_multifactor(syms, syms["SPY"], max_positions=2, warmup=200, buy_threshold=0.3,
                             fundamentals=fund)
    assert a["equity_curve"] == b["equity_curve"]


def test_fundamental_factor_engages_when_weighted():
    syms = _universe()
    fund = {"AAA": [{"effective": "2023-01-01", "quality_score": 1.0}],
            "BBB": [{"effective": "2023-01-01", "quality_score": -1.0}]}
    base = backtest_multifactor(syms, syms["SPY"], max_positions=2, warmup=200, buy_threshold=0.3)
    tilted = backtest_multifactor(syms, syms["SPY"], max_positions=2, warmup=200, buy_threshold=0.3,
                                  params={"fundamental_weight": 0.5}, fundamentals=fund)
    # A nonzero weight + real fundamental scores changes the selection/equity path.
    assert base["equity_curve"] != tilted["equity_curve"]
