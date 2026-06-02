"""P1 capital-recycling (rotation) — 2026-06-02 audit.

P1 deployed ~100% on day one and froze: it held 14 names at 86% gross / $80 cash
and could not act on its own #1/#2-ranked adds (XLK conf 0.86, SPY 0.72) while
still holding low-conviction HOLDs (TSLA 0.08, XLI 0.01, XLY 0.05). Capital only
ever freed up when a stop/TP happened to fire, so in a flat market it never
traded. compute_rotation_plan frees cash for high-conviction starved BUYs by
exiting the weakest HOLDs — but ONLY when genuinely starved, and never churns
between similar-conviction names. These tests lock that behavior.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
for _p in (REPO_ROOT, SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from portfolio_manager import compute_rotation_plan  # noqa: E402

EQUITY = 100_000.0


def _pos(symbol, mv, qty):
    return {"symbol": symbol, "market_value": mv, "qty": qty}


def _validated(approved, rejected):
    return {"approved_orders": approved, "rejected_orders": rejected}


def _buy(symbol, conf, dollars):
    return {"symbol": symbol, "signal": "BUY", "confidence": conf,
            "approved_dollar_amount": dollars}


def _hold(symbol, conf):
    return {"symbol": symbol, "signal": "HOLD", "confidence": conf}


# --- The guard: rotation is OFF unless the book is genuinely starved ----------

def test_no_rotation_when_not_starved():
    # cash = 5% of equity (> 3% threshold) — even with a starved-looking buy.
    validated = _validated([_buy("XLK", 0.86, 12_000)], [_hold("TSLA", 0.08)])
    positions = [_pos("TSLA", 5_000, 13)]
    assert compute_rotation_plan(positions, validated, cash=5_000, equity=EQUITY) == []


def test_no_rotation_without_approved_buys():
    validated = _validated([], [_hold("TSLA", 0.08)])
    positions = [_pos("TSLA", 5_000, 13)]
    assert compute_rotation_plan(positions, validated, cash=80, equity=EQUITY) == []


# --- The core behavior: exit the weakest HOLDs to fund a starved BUY ----------

def test_rotates_weakest_holds_first():
    validated = _validated([_buy("XLK", 0.86, 12_000)],
                           [_hold("TSLA", 0.08), _hold("XLI", 0.01)])
    positions = [_pos("TSLA", 5_000, 13), _pos("XLI", 4_800, 28)]
    plan = compute_rotation_plan(positions, validated, cash=80, equity=EQUITY)
    assert [p["symbol"] for p in plan] == ["XLI", "TSLA"]   # weakest conviction first
    assert all(p["side"] == "sell" for p in plan)
    assert all(p["qty"] > 0 for p in plan)


def test_stops_once_need_is_met():
    # Buy needs $5k, cash $80 -> need ~$4.9k. The first $5k exit covers it; the
    # bot must NOT keep selling the second name.
    validated = _validated([_buy("XLK", 0.86, 5_000)],
                           [_hold("A", 0.01), _hold("B", 0.02)])
    positions = [_pos("A", 5_000, 10), _pos("B", 5_000, 10)]
    plan = compute_rotation_plan(positions, validated, cash=80, equity=EQUITY)
    assert [p["symbol"] for p in plan] == ["A"]


# --- Anti-churn and safety rails ---------------------------------------------

def test_edge_gate_prevents_churn():
    # HOLD at 0.70 vs BUY at 0.86 -> only a 0.16 edge (< 0.25). Not worth the swap.
    validated = _validated([_buy("XLK", 0.86, 12_000)], [_hold("DIA", 0.70)])
    positions = [_pos("DIA", 5_000, 9)]
    assert compute_rotation_plan(positions, validated, cash=80, equity=EQUITY) == []


def test_never_rotates_a_name_we_want_to_buy():
    # NVDA is held but it's an approved BUY this run — must never be sold to fund
    # another buy. With no HOLD candidates left, there is nothing to rotate.
    validated = _validated([_buy("NVDA", 0.90, 8_000), _buy("XLK", 0.86, 12_000)], [])
    positions = [_pos("NVDA", 5_000, 25)]
    assert compute_rotation_plan(positions, validated, cash=80, equity=EQUITY) == []


def test_respects_max_rotations():
    validated = _validated([_buy("XLK", 0.90, 40_000)],
                           [_hold("A", 0.01), _hold("B", 0.02), _hold("C", 0.03)])
    positions = [_pos("A", 4_000, 1), _pos("B", 4_000, 1), _pos("C", 4_000, 1)]
    plan = compute_rotation_plan(positions, validated, cash=80, equity=EQUITY, max_rotations=2)
    assert [p["symbol"] for p in plan] == ["A", "B"]        # weakest two only


def test_skips_candidate_over_rotation_cap():
    # A single $20k (20%) HOLD exceeds the 15% daily rotation cap -> skipped, even
    # though the book is starved. The cap means the cap.
    validated = _validated([_buy("XLK", 0.90, 30_000)], [_hold("BIG", 0.05)])
    positions = [_pos("BIG", 20_000, 100)]
    assert compute_rotation_plan(positions, validated, cash=80, equity=EQUITY) == []


def test_fail_safe_on_degenerate_equity():
    validated = _validated([_buy("XLK", 0.90, 12_000)], [_hold("TSLA", 0.08)])
    positions = [_pos("TSLA", 5_000, 13)]
    assert compute_rotation_plan(positions, validated, cash=80, equity=0) == []
    assert compute_rotation_plan(positions, validated, cash=80, equity="x") == []


def test_real_2026_06_02_scenario():
    # The actual book: $80 cash, holding low-conviction HOLDs while high-conviction
    # adds (XLK 0.86, SPY 0.72) are starved. Rotation should free cash by exiting
    # the weakest HOLDs while honoring the safety rails.
    approved = [_buy("XLK", 0.861, 11_964), _buy("SPY", 0.718, 11_964)]
    rejected = [_hold("TSLA", 0.076), _hold("XLI", 0.013), _hold("XLY", 0.05),
                _hold("DIA", 0.466), _hold("BIL", 0.34)]
    positions = [_pos("TSLA", 5_681, 13), _pos("XLI", 4_877, 28),
                 _pos("XLY", 4_987, 41), _pos("DIA", 4_575, 9), _pos("BIL", 19_973, 218)]
    plan = compute_rotation_plan(positions, _validated(approved, rejected),
                                 cash=80, equity=EQUITY)
    syms = [p["symbol"] for p in plan]
    assert plan                                      # starved -> rotation happens
    assert "XLI" in syms and "XLY" in syms           # weakest HOLDs exited first
    assert "BIL" not in syms                          # $19,973 alone > 15% rotation cap
    assert not ({"XLK", "SPY"} & set(syms))          # never sells the names we're buying
    assert all(p["side"] == "sell" and p["qty"] > 0 for p in plan)
    assert sum(p["est_value"] for p in plan) <= EQUITY * 0.15   # within daily cap
