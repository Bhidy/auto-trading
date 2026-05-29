"""Indicator math correctness — the hand-rolled SMA/EMA/RSI/ATR/Bollinger/MACD
that the entire signal engine depends on."""
import math

import analyst_v2 as az


def test_sma_basic():
    assert az.sma([1, 2, 3, 4, 5], 5) == 3.0
    assert az.sma([2, 4, 6], 2) == 5.0  # last two: (4+6)/2


def test_sma_insufficient_data_returns_none():
    assert az.sma([1, 2], 5) is None


def test_ema_responds_more_to_recent():
    # Accelerating series: recent values rise faster, so EMA (recent-weighted)
    # leads the trailing SMA. (A perfectly linear ramp would make them equal.)
    data = [float(i * i) for i in range(1, 31)]
    ema = az.ema(data, 10)
    sma = az.sma(data, 10)
    assert ema > sma


def test_rsi_all_gains_is_100():
    closes = list(range(1, 30))  # strictly increasing
    assert az.rsi(closes) == 100.0


def test_rsi_bounded_0_100():
    closes = [10, 11, 9, 12, 8, 13, 7, 14, 6, 15, 5, 16, 4, 17, 3, 18]
    val = az.rsi(closes)
    assert val is not None
    assert 0.0 <= val <= 100.0


def test_rsi_insufficient_data():
    assert az.rsi([1, 2, 3]) is None


def test_atr_positive_for_volatile_series():
    n = 20
    highs = [10 + i for i in range(n)]
    lows = [9 + i for i in range(n)]
    closes = [9.5 + i for i in range(n)]
    a = az.atr(highs, lows, closes)
    assert a is not None and a > 0


def test_bollinger_bands_ordering():
    closes = [100 + math.sin(i) for i in range(40)]
    lower, mid, upper = az.bollinger_bands(closes)
    assert lower < mid < upper


def test_bollinger_insufficient_data():
    assert az.bollinger_bands([1, 2, 3]) == (None, None, None)


def test_macd_line_positive_in_uptrend():
    closes = [float(i) for i in range(1, 60)]  # steady uptrend
    macd_line, signal_line, hist = az.macd(closes)
    assert macd_line is not None
    assert macd_line > 0  # fast EMA above slow EMA in an uptrend
