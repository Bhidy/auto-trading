"""Pre-trade self-check (preflight) — catch config/param/sizing drift BEFORE any
order, and fail CLOSED on a hard failure.

The 2026-06-01 incident shipped a broken sizing function to production unnoticed.
A single canary — "size a known ($100 price, $2 ATR) instrument and assert the
result is sane" — would have caught it instantly, before a single order. This
module is that canary, plus account-health, risk-limit sanity, an optional crypto
canary, and a param-bounds clamp (the one allowed auto-remediation: a self-learned
param outside its declared legal bound is clamped back to the bound and logged).

Pure and dependency-injected (sizing_fn, data_fresh) so it is fully CI-testable.
"""
from shared.sizing import MAX_WEIGHT_PCT, volatility_position_pct

# Declared legal bounds for self-learned params (mirror performance_tracker's
# bounds). Out-of-bounds is clamped back — a provably safe remediation.
PARAM_BOUNDS = {
    "position_size_multiplier": (0.5, 1.5),
    "atr_risk_target_pct": (0.25, 3.0),
    "confidence_buy_threshold": (0.1, 0.95),
    "confidence_short_threshold": (0.1, 0.95),
}

# Generous corruption-detector ranges for hardcoded risk limits. A value outside
# these does not mean "aggressive" — it means the config is corrupt (0, negative,
# or a limit so large it is effectively disabled). Calibrated so P1/P2/P3 configs
# all pass; only genuine corruption trips them.
_LIMIT_RANGES = {
    "max_daily_loss_pct": 25,
    "max_weekly_loss_pct": 50,
    "kill_switch_drawdown_pct": 50,
    "max_gross_exposure_pct": 500,
    "max_short_exposure_pct": 200,
    "max_crypto_exposure_pct": 100,
}


def _risk_limit_sanity(limits):
    issues = []
    msp = limits.get("max_single_position_pct", {})
    if isinstance(msp, dict):
        for k, v in msp.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                issues.append(f"max_single_position_pct[{k}]={v} not numeric")
                continue
            if not (0 < fv <= 50):
                issues.append(f"max_single_position_pct[{k}]={v} outside (0,50]")
    for key, hi in _LIMIT_RANGES.items():
        if key in limits:
            try:
                v = float(limits[key])
            except (TypeError, ValueError):
                issues.append(f"{key}={limits[key]} not numeric")
                continue
            if not (0 < v <= hi):
                issues.append(f"{key}={v} outside (0,{hi}]")
    return issues


def _account_health(account):
    if account is None:
        return ["account info unavailable"]
    issues = []
    status = str(account.get("status", "")).upper()
    if status and status != "ACTIVE":
        issues.append(f"account status is {status} (expected ACTIVE)")
    if account.get("trading_blocked"):
        issues.append("trading_blocked is true")
    if account.get("account_blocked"):
        issues.append("account_blocked is true")
    try:
        if float(account.get("equity", 0)) <= 0:
            issues.append("equity <= 0")
    except (TypeError, ValueError):
        issues.append("equity not numeric")
    return issues


def _clamp_params(params):
    clamped = dict(params or {})
    notes = []
    for key, (lo, hi) in PARAM_BOUNDS.items():
        if key not in clamped:
            continue
        try:
            v = float(clamped[key])
        except (TypeError, ValueError):
            continue
        nv = min(max(v, lo), hi)
        if nv != v:
            clamped[key] = nv
            notes.append(f"{key} {v} -> clamped to {nv} (legal [{lo},{hi}])")
    return clamped, notes


def _sizing_canary(params, sizing_fn):
    """Size a known ($100 price, $2 ATR) instrument; the result must be sane.
    With the 2026-06-01 *100 bug this returns ~0.2% and FAILS the 0.5% floor."""
    target = float(params.get("atr_risk_target_pct", 1.0))
    stop = float(params.get("trailing_stop_atr_mult", 2.5))
    mult = float(params.get("position_size_multiplier", 1.0))
    pct = sizing_fn(2.0, 100.0, target, stop, mult)
    qty = int(100_000 * pct / 100 / 100)  # $100k equity, $100 price
    ok = (0.5 <= pct <= MAX_WEIGHT_PCT) and qty >= 1
    return ok, (f"$100/$2ATR -> {pct}% (qty {qty}); expected "
                f"[0.5,{MAX_WEIGHT_PCT}]% and qty>=1")


def _crypto_canary(params, sizing_fn):
    """A BTC-like ($100k price, $3k ATR) position must size above dust."""
    target = float(params.get("atr_risk_target_pct", 1.0))
    stop = float(params.get("trailing_stop_atr_mult", 2.5))
    mult = float(params.get("position_size_multiplier", 1.0))
    pct = sizing_fn(3000.0, 100_000.0, target, stop, mult)
    notional = 100_000 * pct / 100
    return (pct > 0 and notional >= 1.0), (f"$100k/$3kATR -> {pct}% "
                                           f"(${notional:,.0f} notional)")


def run_preflight(*, limits, account, params=None, sizing_canary=False,
                  crypto_canary=False, data_fresh=None, portfolio_id=None,
                  sizing_fn=volatility_position_pct):
    """Run all applicable checks. Returns (ok, result).

    HARD failures (block trading, fail-closed): account health, risk-limit sanity,
    the sizing canary (when enabled), and stale data (when data_fresh is False).
    The param clamp and a failed crypto canary are WARNINGS (non-blocking).
    """
    hard, warnings, checks = [], [], {}

    acc = _account_health(account)
    checks["account_health"] = {"ok": not acc, "issues": acc}
    hard += acc

    rl = _risk_limit_sanity(limits or {})
    checks["risk_limits"] = {"ok": not rl, "issues": rl}
    hard += rl

    clamped_params, clamp_notes = _clamp_params(params)
    checks["param_clamps"] = clamp_notes
    warnings += clamp_notes

    if sizing_canary:
        ok, detail = _sizing_canary(clamped_params, sizing_fn)
        checks["sizing_canary"] = {"ok": ok, "detail": detail}
        if not ok:
            hard.append(f"SIZING CANARY FAILED: {detail} — sizing math may be "
                        f"broken (2026-06-01 class); refusing to trade")

    if crypto_canary:
        ok, detail = _crypto_canary(clamped_params, sizing_fn)
        checks["crypto_canary"] = {"ok": ok, "detail": detail}
        if not ok:
            warnings.append(f"crypto canary failed: {detail}")

    if data_fresh is False:
        hard.append("data freshness check failed — bars/signals stale or missing; "
                    "refusing to trade on stale data")
    checks["data_fresh"] = data_fresh

    ok = len(hard) == 0
    return ok, {
        "ok": ok,
        "portfolio_id": portfolio_id,
        "hard_failures": hard,
        "warnings": warnings,
        "clamped_params": clamped_params,
        "checks": checks,
    }
