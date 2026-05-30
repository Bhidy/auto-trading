"""Life-cycle accounting realism — regulatory fees + corporate actions (C5).

The audit's accounting gap: logged P&L excludes regulatory fees and ignores
corporate actions, which makes realized P&L and every downstream metric (Sharpe,
profit factor, the live-readiness gates themselves) misleading on real money.
This module is the single source of truth for:

  * estimate_regulatory_fees  — SEC Section 31 (sells), FINRA TAF (sells, capped),
                                CAT (both sides). Defaults approximate published
                                US-equity rates and are fully overridable.
  * net_proceeds              — fee-adjusted cash effect of a fill.
  * realized_pnl              — entry→exit P&L NET of round-trip fees.
  * apply_split / apply_cash_dividend — corporate-action adjustments to a lot.
  * split_realized_unrealized — aggregate realized vs unrealized across the book.

Pure and dependency-free so it runs identically in the backtester, in CI, and on
the live ledger. Paper and backtest P&L become comparable to live.
"""
from datetime import datetime, timezone

# --- Regulatory fee schedule (approximate published US equity rates) --------
# These are deliberately conservative defaults; override per-call via `schedule`.
DEFAULT_FEE_SCHEDULE = {
    "sec_fee_per_dollar": 0.0000278,  # Section 31, sells only (~$27.80 / $1M)
    "taf_per_share": 0.000166,        # FINRA Trading Activity Fee, sells only
    "taf_max_per_trade": 8.30,        # TAF per-trade cap
    "cat_fee_per_share": 0.000035,    # Consolidated Audit Trail, buys + sells
}


def _round_cents(x):
    return round(x + 1e-12, 2)


def _is_sell(side):
    return str(side or "").lower() in ("sell", "sell_short", "short")


def estimate_regulatory_fees(side, qty, price, *, schedule=None):
    """Estimate per-fill regulatory fees. SEC fee + TAF apply to sells only; CAT
    applies to both sides. Returns a breakdown plus `total` (rounded to cents)."""
    sch = {**DEFAULT_FEE_SCHEDULE, **(schedule or {})}
    qty = abs(float(qty or 0))
    price = abs(float(price or 0))
    notional = qty * price

    sec_fee = 0.0
    taf = 0.0
    if _is_sell(side):
        sec_fee = notional * sch["sec_fee_per_dollar"]
        taf = min(qty * sch["taf_per_share"], sch["taf_max_per_trade"])
    cat_fee = qty * sch["cat_fee_per_share"]

    total = sec_fee + taf + cat_fee
    return {
        "sec_fee": round(sec_fee, 6),
        "taf": round(taf, 6),
        "cat_fee": round(cat_fee, 6),
        "total": _round_cents(total),
    }


def net_proceeds(side, qty, price, *, schedule=None):
    """Cash effect of a fill, net of fees. Buys cost MORE (notional + fees);
    sells yield LESS (notional - fees). Returns a negative number for a buy
    (cash out) and positive for a sell (cash in)."""
    qty = abs(float(qty or 0))
    price = abs(float(price or 0))
    notional = qty * price
    fees = estimate_regulatory_fees(side, qty, price, schedule=schedule)["total"]
    if _is_sell(side):
        return _round_cents(notional - fees), fees
    return _round_cents(-(notional + fees)), fees


def realized_pnl(side, qty, entry_price, exit_price, *, schedule=None,
                 include_fees=True):
    """Realized P&L for a round trip, NET of entry+exit regulatory fees.

    `side` is the ENTRY side ('buy' for a long, 'sell'/'short' for a short).
    """
    qty = abs(float(qty or 0))
    entry_price = float(entry_price or 0)
    exit_price = float(exit_price or 0)
    long_side = not _is_sell(side)

    gross = ((exit_price - entry_price) if long_side
             else (entry_price - exit_price)) * qty

    fees = 0.0
    if include_fees:
        entry_fill_side = "buy" if long_side else "sell"
        exit_fill_side = "sell" if long_side else "buy"
        fees += estimate_regulatory_fees(entry_fill_side, qty, entry_price,
                                         schedule=schedule)["total"]
        fees += estimate_regulatory_fees(exit_fill_side, qty, exit_price,
                                         schedule=schedule)["total"]

    return {
        "gross_pnl": _round_cents(gross),
        "fees": _round_cents(fees),
        "net_pnl": _round_cents(gross - fees),
    }


# --- Corporate actions ------------------------------------------------------

def apply_split(qty, avg_price, numerator, denominator):
    """Adjust a lot for a stock split. A `numerator:denominator` split means
    `denominator` old shares become `numerator` new shares (2:1 forward => 2,1;
    1:10 reverse => 1,10). Share count and average cost adjust inversely so the
    position's total cost basis is preserved."""
    numerator = float(numerator)
    denominator = float(denominator)
    if numerator <= 0 or denominator <= 0:
        raise ValueError("split ratio must be positive")
    factor = numerator / denominator
    new_qty = float(qty) * factor
    new_avg = float(avg_price) / factor if factor else float(avg_price)
    return round(new_qty, 8), round(new_avg, 6)


def apply_cash_dividend(qty, dividend_per_share):
    """Cash received from a cash dividend (does not change the lot's basis)."""
    return _round_cents(abs(float(qty or 0)) * float(dividend_per_share or 0))


def apply_corporate_actions(position, actions):
    """Apply an ordered list of corporate actions to a single position lot.

    `position`: {"qty": ..., "avg_price": ...}
    `actions`: list of {"type": "split"|"dividend", ...}. Returns the updated
    position plus accumulated `cash` from dividends. Read-model only — places no
    orders.
    """
    qty = float(position.get("qty", 0))
    avg = float(position.get("avg_price", position.get("avg_entry_price", 0)))
    cash = 0.0
    applied = []
    for a in actions or []:
        atype = a.get("type")
        if atype == "split":
            qty, avg = apply_split(qty, avg, a.get("numerator", 1),
                                   a.get("denominator", 1))
            applied.append({"type": "split", "numerator": a.get("numerator"),
                            "denominator": a.get("denominator")})
        elif atype == "dividend":
            d = apply_cash_dividend(qty, a.get("amount_per_share", 0))
            cash += d
            applied.append({"type": "dividend", "cash": d})
    return {
        "qty": round(qty, 8),
        "avg_price": round(avg, 6),
        "cash": _round_cents(cash),
        "applied": applied,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# --- Realized vs unrealized split ------------------------------------------

def split_realized_unrealized(closed_trades, open_positions, *, schedule=None):
    """Aggregate realized P&L (from closed trades, net of fees) and unrealized
    P&L (from open positions marked to current price). Makes the ledger honest
    about what is booked vs what is still at risk."""
    realized = 0.0
    realized_fees = 0.0
    for t in closed_trades or []:
        if t.get("pnl") is not None and t.get("exit_price") is None:
            continue
        entry = t.get("entry_price")
        exit_ = t.get("exit_price")
        qty = t.get("qty")
        side = t.get("side", "buy")
        if entry is None or exit_ is None or not qty:
            # Fall back to any pre-computed pnl if fields are incomplete.
            realized += float(t.get("pnl") or 0)
            continue
        r = realized_pnl(side, qty, entry, exit_, schedule=schedule)
        realized += r["net_pnl"]
        realized_fees += r["fees"]

    unrealized = 0.0
    for p in open_positions or []:
        qty = abs(float(p.get("qty", 0)))
        avg = float(p.get("avg_price", p.get("avg_entry_price", 0)))
        cur = float(p.get("current_price", p.get("mark_price", avg)))
        long_side = str(p.get("side", "long")).lower() in ("long", "buy")
        unrealized += ((cur - avg) if long_side else (avg - cur)) * qty

    return {
        "realized_pnl": _round_cents(realized),
        "realized_fees": _round_cents(realized_fees),
        "unrealized_pnl": _round_cents(unrealized),
        "total_pnl": _round_cents(realized + unrealized),
    }
