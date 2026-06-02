"""Canonical, unit-safe position sizing — shared by P1/P2/P3.

WHY THIS EXISTS (read before editing):
On 2026-06-01 P1 silently stopped opening positions. Root cause: an inline
risk-parity sizing formula in analyst_v2 had a stray `* 100`, making every
suggested position size 100x too small (0.11%–0.37% instead of 11%–37%). The
risk officer then computed `qty = int(equity*pct/100 / price) = 0`, and the
executor silently skipped every order. The run reported "success" while placing
nothing — a silent correctness failure.

The fix is not just the arithmetic; it is to have ONE tested sizing function
that every strategy routes through, with units documented and asserted, so the
error cannot reappear in a copy. Pure, dependency-free, fully CI-testable.

UNITS (the thing that bit us):
  * `atr_risk_target_pct` is a PERCENT of equity to risk per trade (1.0 == 1%).
  * `risk_pct` (computed here) is the per-share stop distance as a FRACTION of
    price (0.09 == 9%).
  * The returned weight is a PERCENT of equity (11.0 == 11%), because the risk
    officer multiplies it by `equity/100`.
"""

# Absolute guardrail: no single position weight from sizing may exceed this,
# regardless of inputs. The risk officer applies tighter per-instrument caps
# (e.g. 8% stock / 12% ETF) on top of this — this is a last-resort ceiling.
MAX_WEIGHT_PCT = 12.0


def volatility_position_pct(atr, price, atr_risk_target_pct, stop_atr_mult,
                            size_mult=1.0, hard_cap_pct=MAX_WEIGHT_PCT):
    """Risk-parity position size as a PERCENT of equity.

    Sizes the position so that being stopped out (price moves against you by the
    ATR-based stop distance) loses approximately `atr_risk_target_pct`% of equity.

    Derivation (all symbols explicit to prevent the unit error that caused the
    2026-06-01 incident):
        risk_per_share [$]   = atr * stop_atr_mult
        risk_pct [fraction]  = risk_per_share / price
        loss_at_stop         = equity * (weight%/100) * risk_pct
        set loss_at_stop = equity * (atr_risk_target_pct/100)
        =>  weight% = atr_risk_target_pct / risk_pct        # NOT risk_pct*100

    Returns a percent in [0, hard_cap_pct] after applying `size_mult`. Returns
    0.0 on any invalid/degenerate input so the caller treats it as "no trade"
    (and the risk officer will reject qty<=0 loudly rather than silently skip).
    """
    try:
        atr = float(atr)
        price = float(price)
        atr_risk_target_pct = float(atr_risk_target_pct)
        stop_atr_mult = float(stop_atr_mult)
        size_mult = float(size_mult)
        hard_cap_pct = float(hard_cap_pct)
    except (TypeError, ValueError):
        return 0.0

    if atr <= 0 or price <= 0 or stop_atr_mult <= 0 or atr_risk_target_pct <= 0:
        return 0.0

    risk_per_share = atr * stop_atr_mult
    risk_pct = risk_per_share / price  # fraction of price
    if risk_pct <= 0:
        return 0.0

    weight_pct = (atr_risk_target_pct / risk_pct) * max(size_mult, 0.0)
    if weight_pct <= 0:
        return 0.0
    return round(min(weight_pct, max(hard_cap_pct, 0.0)), 2)


def realized_risk_pct(weight_pct, atr, price, stop_atr_mult):
    """Inverse check: given a position weight (% of equity), how much of equity
    is actually at risk if stopped out? Used by tests/invariants to assert the
    sizing math is self-consistent (realized risk ≈ atr_risk_target_pct).
    Returns a PERCENT of equity. 0.0 on degenerate input."""
    try:
        weight_pct = float(weight_pct); atr = float(atr)
        price = float(price); stop_atr_mult = float(stop_atr_mult)
    except (TypeError, ValueError):
        return 0.0
    if price <= 0 or atr <= 0 or stop_atr_mult <= 0:
        return 0.0
    risk_pct = (atr * stop_atr_mult) / price
    return round((weight_pct / 100.0) * risk_pct * 100.0, 4)


def shares_for_dollar_risk(equity, risk_budget_pct, atr, stop_atr_mult):
    """Dollar-based risk sizing → integer shares. This is the model P3 already
    uses (event_driven_bot.compute_position_size) and the canonical form for any
    dollar-sized strategy. shares = (equity * risk_budget_pct/100) / (atr*stop).
    Returns 0 on degenerate input."""
    try:
        equity = float(equity); risk_budget_pct = float(risk_budget_pct)
        atr = float(atr); stop_atr_mult = float(stop_atr_mult)
    except (TypeError, ValueError):
        return 0
    if equity <= 0 or risk_budget_pct <= 0 or atr <= 0 or stop_atr_mult <= 0:
        return 0
    stop_distance = atr * stop_atr_mult
    if stop_distance <= 0:
        return 0
    return int((equity * risk_budget_pct / 100.0) / stop_distance)


def meets_min_notional(qty, price, *, floor_usd=0.0, equity=None, floor_pct=0.0):
    """True if an order's notional (qty*price) clears the minimum-position floor.

    Guards against capital-starved "stub" fills. Observed live 2026-06-02: P1 had
    $80 cash, approved a $11,964 XLE order, the executor down-sized it to whatever
    cash allowed and placed **3 shares = $184** — a meaningless position that just
    consumed the last dollar and blocked everything behind it. A floor turns that
    into a clean skip instead of noise.

    The floor is the GREATER of an absolute USD floor (`floor_usd`) and `floor_pct`%
    of equity (when `equity` is given), so it scales with the book. Returns True
    when no floor is configured (floor == 0). Returns False on degenerate input."""
    try:
        notional = float(qty) * float(price)
    except (TypeError, ValueError):
        return False
    if notional <= 0:
        return False
    floor = float(floor_usd or 0.0)
    if equity and floor_pct:
        try:
            floor = max(floor, float(equity) * float(floor_pct) / 100.0)
        except (TypeError, ValueError):
            pass
    return notional >= floor


def position_add_room_qty(existing_value, price, equity, max_pct, *, fractional=False):
    """Max ADDITIONAL quantity addable to an existing position without the
    resulting total (existing + add) breaching the single-position cap.

    The risk officer caps a NEW order to `max_pct` of equity but does NOT subtract
    what is already held, so a single add to a partially-filled name can land at
    up to ~2x the cap (observed live 2026-06-02: P1 AMZN 13.5%, GOOGL 10.4% on an
    8% stock cap). Callers cap the order qty to this room so a 20%/8% cap means
    exactly that — not twice the position size. Whole shares unless `fractional`
    (crypto). Returns 0 when there is no room or on degenerate input."""
    try:
        existing_value = float(existing_value); price = float(price)
        equity = float(equity); max_pct = float(max_pct)
    except (TypeError, ValueError):
        return 0.0 if fractional else 0
    if price <= 0 or equity <= 0 or max_pct <= 0:
        return 0.0 if fractional else 0
    room_dollars = max(max_pct / 100.0 * equity - max(existing_value, 0.0), 0.0)
    qty = room_dollars / price
    return qty if fractional else int(qty)
