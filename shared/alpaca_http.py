"""
Hardened Alpaca HTTP + order primitives — shared by P1, P2, and P3.

Every portfolio's broker calls route through this module so the money path is
identical everywhere:
  * resilient_request  — retries 429/5xx + network errors (exp backoff + jitter,
                         honors Retry-After); 4xx (except 429) raise immediately.
  * make_client_order_id — deterministic per portfolio/symbol/side/day key so a
                         retried or duplicate scheduled run can never double-place.
  * confirm_fill        — polls order status and returns the REAL filled qty/price,
                         never a phantom fill.

Zero third-party deps beyond `requests`.
"""
import random
import time

import requests

RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 4
BACKOFF_BASE = 0.5


def _retry_wait(resp, attempt):
    """Honor server Retry-After (429); else exponential backoff + jitter."""
    if resp is not None:
        ra = resp.headers.get("Retry-After")
        if ra:
            try:
                return float(ra)
            except ValueError:
                pass
    return BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.3)


def resilient_request(method, url, headers, params=None, json_body=None,
                      timeout=30, logger=None):
    """Single resilient HTTP entry point for all broker calls.

    Retries transient failures (429/5xx, connection/timeout) with backoff.
    A 204 returns {}; other 4xx raise immediately (no retry).
    """
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.request(method, url, headers=headers, params=params,
                                 json=json_body, timeout=timeout)
            if r.status_code in RETRY_STATUS and attempt < MAX_RETRIES:
                wait = _retry_wait(r, attempt)
                if logger:
                    logger.warning(f"Alpaca {r.status_code} on {method} {url} — "
                                   f"retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s")
                time.sleep(wait)
                continue
            if r.status_code == 204:
                return {}
            r.raise_for_status()
            return r.json() if r.text else {}
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.3)
                if logger:
                    logger.warning(f"Alpaca network error on {method} {url}: {e} — "
                                   f"retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s")
                time.sleep(wait)
                continue
            raise
    if last_exc:
        raise last_exc


def make_client_order_id(prefix, symbol, side, day=None):
    """Deterministic idempotency key. Alpaca rejects a duplicate
    client_order_id (422), so a retried/duplicate run cannot double-place the
    same symbol/side on the same UTC day."""
    if day is None:
        day = time.strftime("%Y%m%d", time.gmtime())
    safe_symbol = str(symbol).replace("/", "")
    return f"{prefix}-{day}-{safe_symbol}-{side}"


def evaluate_asset_gate(asset, signal_side, *, quote_fresh=True,
                        require_borrow_for_short=True):
    """Pure pre-trade tradability + borrow gate for a NEW entry (BUY or SHORT).

    This is the single source of truth for the two critical real-money safety
    gates the audit flagged:

      * Easy-to-borrow (ETB): P1 actively places SHORT (sell-to-open) orders. A
        short on a hard-to-borrow name is canceled pre-market or charged punitive
        borrow fees, silently corrupting risk and P&L. A SHORT is therefore
        FAIL-CLOSED: it is rejected unless the asset is confirmed shortable AND
        easy_to_borrow. Borrow status changes daily, so callers must pass a FRESH
        asset (re-checked at execution time, not cached).

      * Halt / not-tradable: new entries into a non-tradable/inactive asset, or
        one whose market data is stale (a halt proxy), are rejected. Exits are
        never routed through this gate, so risk-reducing closes are unaffected.

    Args:
        asset: dict from Alpaca ``GET /v2/assets/{symbol}`` (or None if the
            lookup failed / was unavailable).
        signal_side: "BUY" / "LONG" or "SHORT" / "SELL_SHORT".
        quote_fresh: caller-computed freshness of the latest quote/trade during
            market hours. False is treated as a possible halt/LULD condition and
            blocks NEW entries.
        require_borrow_for_short: keep True in production. Only relax in tests.

    Returns:
        (ok: bool, reasons: list[str], asset_info: dict)
    """
    side = str(signal_side or "").upper()
    is_short = side in ("SHORT", "SELL_SHORT", "SELL")
    reasons = []

    if asset is None:
        # No broker confirmation available. Longs may proceed (the broker will
        # reject an untradable symbol anyway); shorts FAIL CLOSED — you cannot
        # short what you cannot confirm is borrowable.
        info = {"tradable": None, "shortable": None, "easy_to_borrow": None,
                "status": None, "borrow_verified": False}
        if is_short and require_borrow_for_short:
            reasons.append("SHORT blocked: borrow status unverified "
                           "(no asset metadata; fail-closed)")
            return False, reasons, info
        if not quote_fresh:
            reasons.append("New entry blocked: market data stale (possible halt)")
            return False, reasons, info
        return True, reasons, info

    status = asset.get("status")
    tradable = bool(asset.get("tradable", False))
    shortable = bool(asset.get("shortable", False))
    etb = bool(asset.get("easy_to_borrow", False))
    info = {
        "tradable": tradable,
        "shortable": shortable,
        "easy_to_borrow": etb,
        "status": status,
        "borrow_verified": bool(asset),
    }

    if status is not None and status != "active":
        reasons.append(f"Asset not active (status={status})")
    if not tradable:
        reasons.append("Asset not tradable on the broker")
    if not quote_fresh:
        reasons.append("New entry blocked: market data stale (possible halt/LULD)")

    if is_short and require_borrow_for_short:
        if not shortable:
            reasons.append("SHORT blocked: asset is not shortable")
        elif not etb:
            reasons.append("SHORT blocked: asset is not easy-to-borrow (HTB)")

    return (len(reasons) == 0), reasons, info


def confirm_fill(client, order_id, timeout=8.0, poll=1.0, logger=None):
    """Poll an order until terminal/filled or timeout.

    `client` must expose get_order(order_id). Returns
    (status, filled_qty, filled_avg_price). Never fabricates a fill.
    """
    if not order_id:
        return "unknown", 0.0, None
    deadline = time.time() + timeout
    status, filled_qty, filled_price = "unknown", 0.0, None
    while time.time() < deadline:
        try:
            o = client.get_order(order_id)
        except Exception as e:
            if logger:
                logger.warning(f"Could not poll order {order_id}: {e}")
            break
        status = o.get("status", "unknown")
        filled_qty = float(o.get("filled_qty") or 0)
        fap = o.get("filled_avg_price")
        filled_price = float(fap) if fap else None
        if status in ("filled", "canceled", "rejected", "expired"):
            break
        time.sleep(poll)
    return status, filled_qty, filled_price
