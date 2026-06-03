"""P2 benchmark sleeve — 2026-06-02 audit follow-up.

P2 sat 90% in idle cash between political disclosures. compute_sleeve_orders
deploys idle cash (above the reserve) into a diversified ETF basket, each name
within the single-position cap, with a deadband and a per-run cap to avoid churn.
The political copies remain the alpha overlay on top of this passive base.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P2_SCRIPTS = os.path.join(REPO_ROOT, "political-copy-bot", "scripts")
for _p in (REPO_ROOT, P2_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from politician_bot import (  # noqa: E402
    SLEEVE_SYMBOLS,
    classify_capital,
    compute_sleeve_orders,
)

CFG = {
    "enabled": True,
    "symbols": ["SPY", "QQQ", "DIA", "IWM"],
    "per_name_target_pct": 7.0,
    "min_cash_reserve_pct": 10.0,
    "rebalance_band_pct": 2.0,
    "max_orders_per_run": 3,
}


def _pos(symbol, mv):
    return {"symbol": symbol, "market_value": mv}


def test_disabled_or_missing_returns_empty():
    assert compute_sleeve_orders(100_000, 90_000, [], {**CFG, "enabled": False}) == []
    assert compute_sleeve_orders(100_000, 90_000, [], {}) == []


def test_deploys_idle_cash_into_basket():
    orders = compute_sleeve_orders(100_000, 90_000, [], CFG)
    assert len(orders) == 3                       # capped at max_orders_per_run
    assert all(o["side"] == "buy" for o in orders)
    assert all(o["notional"] == 7000 for o in orders)   # 7% of $100k per name


def test_respects_cash_reserve():
    # cash $12k, reserve $10k -> $2k investable, which is NOT > the $2k band.
    assert compute_sleeve_orders(100_000, 12_000, [], CFG) == []


def test_skips_names_already_at_target():
    pos = [_pos("SPY", 7000), _pos("QQQ", 7000)]
    syms = {o["symbol"] for o in compute_sleeve_orders(100_000, 90_000, pos, CFG)}
    assert "SPY" not in syms and "QQQ" not in syms
    assert syms <= {"DIA", "IWM"}


def test_trims_when_over_target():
    pos = [_pos("SPY", 12_000)]                   # 12% vs 7% target -> trim ~$5k
    orders = compute_sleeve_orders(100_000, 5_000, pos, CFG)
    spy = next(o for o in orders if o["symbol"] == "SPY")
    assert spy["side"] == "sell" and spy["notional"] == 5000


def test_deadband_prevents_tiny_orders():
    # SPY at $6k vs $7k target -> $1k delta < $2k band -> no SPY order.
    pos = [_pos("SPY", 6_000)]
    orders = compute_sleeve_orders(100_000, 90_000, pos, CFG)
    assert all(o["symbol"] != "SPY" for o in orders)


def test_every_sleeve_buy_stays_within_single_position_cap():
    orders = compute_sleeve_orders(100_000, 90_000, [], CFG)
    assert all(o["notional"] <= 100_000 * 0.08 for o in orders)   # < 8% stock/ETF cap


def test_fail_safe_on_degenerate_equity():
    assert compute_sleeve_orders(0, 90_000, [], CFG) == []
    assert compute_sleeve_orders("x", 90_000, [], CFG) == []


def test_real_2026_06_02_p2_scenario():
    # $100,154 equity, $89,908 cash, ~$8.7k in political copies, no sleeve yet.
    pos = [_pos("HD", 1238), _pos("INTU", 1276), _pos("MEDP", 1341),
           _pos("PG", 1394), _pos("T", 1455), _pos("TER", 2703)]
    orders = compute_sleeve_orders(100_154, 89_908, pos, {**CFG, "symbols": SLEEVE_SYMBOLS})
    assert orders                                  # idle cash finally gets deployed
    assert len(orders) <= CFG["max_orders_per_run"]
    assert all(o["side"] == "buy" for o in orders)


# --- Honest beta/alpha disclosure (committee rec #4) ------------------------

def test_classify_capital_splits_beta_alpha_cash():
    positions = [
        {"symbol": "SPY", "market_value": "20000"},    # sleeve -> beta
        {"symbol": "QQQ", "market_value": "10000"},     # sleeve -> beta
        {"symbol": "SPGI", "market_value": "8000"},     # politician copy -> alpha
    ]
    c = classify_capital(positions, SLEEVE_SYMBOLS, cash=62_000, equity=100_000)
    assert c["sleeve_beta_pct"] == 30.0
    assert c["politician_alpha_pct"] == 8.0
    assert c["cash_pct"] == 62.0
    assert c["sleeve_beta_value"] == 30_000.0


def test_classify_capital_handles_bad_input():
    assert classify_capital([], SLEEVE_SYMBOLS, 0, 0)["sleeve_beta_pct"] == 0.0
    assert classify_capital(None, SLEEVE_SYMBOLS, "x", "y")["politician_alpha_pct"] == 0.0


def test_classify_capital_all_sleeve_is_pure_beta():
    positions = [{"symbol": s, "market_value": "5000"} for s in ["SPY", "DIA", "IWM"]]
    c = classify_capital(positions, SLEEVE_SYMBOLS, cash=85_000, equity=100_000)
    assert c["politician_alpha_pct"] == 0.0
    assert c["sleeve_beta_pct"] == 15.0
