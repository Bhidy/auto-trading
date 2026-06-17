"""Advisory event-context consumer (pure-stdlib, FAIL-OPEN).

Reads ``data/event_context.json`` — a STATIC, OPTIONAL artifact built OFFLINE by
``scripts/research/build_event_context.py`` (upcoming corporate actions, fresh
news, liquidity rank). It is ADVISORY ONLY: callers MUST run correctly when it is
absent, malformed, or stale (fail-open returns ``{}``).

IMPORTANT: this is a capability, not yet wired into any live bot decision.
Activating advisory vetoes in the live entry path is a deliberately
committee-gated change (it alters trade decisions) — see the plan's deferred
items. Pure-stdlib so it is safe on the requests-only path if/when adopted.
"""
import json
import os
from datetime import datetime, timezone

MAX_AGE_HOURS = 36


def load_event_context(data_dir, max_age_hours=MAX_AGE_HOURS, now=None):
    """Load the advisory context, or ``{}`` if absent/malformed/stale (fail-open)."""
    path = os.path.join(data_dir, "event_context.json")
    try:
        with open(path) as f:
            ctx = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(ctx, dict):
        return {}

    asof = ctx.get("as_of")
    if asof:
        try:
            ts = datetime.fromisoformat(asof)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            now = now or datetime.now(timezone.utc)
            if (now - ts).total_seconds() / 3600.0 > max_age_hours:
                return {}  # stale -> fail-open
        except ValueError:
            return {}
    return ctx


def adverse_entry_flags(symbol, ctx):
    """Advisory reasons to be cautious entering ``symbol`` now (empty = no concern)."""
    flags = []
    ca = (ctx.get("corporate_actions") or {}).get(symbol)
    if ca:
        flags.append(f"corporate action ({ca.get('type')}) in {ca.get('days_until')}d")
    liq = (ctx.get("liquidity") or {}).get(symbol)
    if liq and liq.get("rank_pct") is not None and liq["rank_pct"] < 0.25:
        flags.append("bottom-quartile liquidity")
    return flags
