"""Two-source confirmation of broker equity before it may drive a risk decision.

INCIDENT (2026-07-07 14:24Z): Alpaca paper returned P1 account equity=$26,060.51
for one read — exactly the account's cash; every position was transiently priced
at zero. Eighteen minutes earlier the same endpoint returned $92,583.88. The P1
kill switch trusted that single read, computed a "73.94% drawdown", and latched a
permanent halt. P1 then sat ~62% in cash for three months while the monitor's
stops kept selling. The same unvalidated read also feeds P1's monitor
liquidation, the risk officer, P2's kill check and P3's daily-loss liquidation —
any of which would have liquidated a whole book on that glitch.

RULE: an equity read may trigger a halt or liquidation only when it is
corroborated by valuing the book INDEPENDENTLY: cash plus every position's qty x
a market-data price (a different service from the account endpoint). A real
crash agrees with itself and still trips the switch; a mis-priced account
snapshot does not.

Two call patterns:
  * ``max_jump_pct=15`` (default) — a cheap plausibility screen at session start:
    ordinary moves are accepted with zero extra API calls.
  * ``max_jump_pct=0`` — ALWAYS corroborate. Callers use this immediately before
    any halt or liquidation, because the daily-loss triggers (4-5%) sit far
    below any plausibility threshold.

A name market data cannot price falls back to the broker's own mark for that
position, so one halted stock cannot stop a genuine crash from tripping the
switch; if more than half the book is unpriceable the read stays unconfirmed.

Pure and dependency-free (T0): callers inject the I/O as callables so this is
fully CI-testable.
"""


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def confirm_equity(account, positions, *, reference_equity=None, get_price=None,
                   max_jump_pct=15.0, tol_pct=2.0):
    """Decide whether ``account['equity']`` is trustworthy enough to act on.

    Args:
        account: the broker account dict (needs ``equity`` and ``cash``).
        positions: the broker positions list (``symbol``, ``qty`` signed or with
            ``side``). Used only when a confirmation is needed.
        reference_equity: the last equity we trusted (prior saved state / prior
            close). Without one, the read is accepted (nothing to compare to).
        get_price: ``callable(symbol) -> float`` returning an independent
            market-data price. Required to CONFIRM a large move; without it a
            large move is reported unconfirmed (fail-safe: no halt on a glitch).
        max_jump_pct: |move vs reference| above which confirmation is required.
        tol_pct: max disagreement between broker equity and the independent
            valuation for the read to be confirmed.

    Returns a dict: ``ok`` (act on it?), ``equity``, ``reason``, plus evidence
    (``reference_equity``, ``jump_pct``, ``independent_equity``,
    ``disagreement_pct``, ``unpriced``) suitable for logging into halt state.
    """
    equity = _f(account.get("equity"))
    cash = _f(account.get("cash"))
    out = {"ok": False, "equity": equity, "cash": cash,
           "reference_equity": reference_equity, "jump_pct": None,
           "independent_equity": None, "disagreement_pct": None,
           "unpriced": [], "reason": None}

    if equity <= 0:
        out["reason"] = f"non-positive broker equity {equity}"
        return out

    ref = _f(reference_equity) if reference_equity is not None else 0.0
    if ref <= 0:
        out.update(ok=True, reason="no reference equity; accepted unconfirmed")
        return out

    jump = abs(equity / ref - 1.0) * 100.0
    out["jump_pct"] = round(jump, 2)
    if jump <= max_jump_pct:
        out.update(ok=True, reason="within normal range")
        return out

    if get_price is None:
        out["reason"] = (f"equity moved {jump:.1f}% vs last trusted ${ref:,.2f} and no "
                         f"independent price source was supplied to confirm it")
        return out

    independent = cash
    held = 0
    for p in positions or []:
        sym = p.get("symbol")
        qty = _f(p.get("qty"))
        if p.get("side") == "short" and qty > 0:
            qty = -qty
        if not sym or qty == 0:
            continue
        held += 1
        try:
            px = _f(get_price(sym))
        except Exception:
            px = 0.0
        if px <= 0:
            out["unpriced"].append(sym)
            independent += _f(p.get("market_value"))       # broker's own mark
            continue
        independent += qty * px
    out["independent_equity"] = round(independent, 2)

    if held and len(out["unpriced"]) * 2 > held:
        out["reason"] = (f"equity moved {jump:.1f}% and {len(out['unpriced'])}/{held} "
                         f"positions could not be independently priced: {out['unpriced'][:5]}")
        return out

    disagreement = abs(equity / independent - 1.0) * 100.0 if independent > 0 else float("inf")
    out["disagreement_pct"] = round(disagreement, 2)
    if disagreement <= tol_pct:
        out.update(ok=True, reason=(f"large move {jump:.1f}% CONFIRMED by independent "
                                    f"valuation ${independent:,.2f}"))
        return out

    out["reason"] = (f"broker equity ${equity:,.2f} disagrees {disagreement:.1f}% with "
                     f"independent valuation ${independent:,.2f} — suspected bad broker "
                     f"read; refusing to act on it")
    return out
