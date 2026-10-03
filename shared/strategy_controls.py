"""Human-owned strategy controls: may a book open NEW positions?

``config/strategy_controls.json`` is the single, reviewed switchboard a human
uses to quarantine a strategy (governance — audit 2026-10-03, Phase 27). It is
NEVER written by code, and it only ever gates NEW ENTRIES: exits, stops,
exit-order hygiene and reconciliation always run, so a quarantined book's open
positions keep being protected while they run off.

Fails CLOSED: a missing, unreadable or malformed entry means "no new entries"
(logged), because an unknown control state must never open risk.
"""
import json
from pathlib import Path

CONTROLS_FILE = Path(__file__).resolve().parent.parent / "config" / "strategy_controls.json"


def load_controls(path=None):
    try:
        with open(path or CONTROLS_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def entries_enabled(portfolio_id, controls=None, path=None):
    """(enabled: bool, reason: str). Pure given ``controls``."""
    controls = controls if controls is not None else load_controls(path)
    if controls is None:
        return False, "strategy_controls.json missing/unreadable — failing closed"
    book = controls.get(portfolio_id)
    if not isinstance(book, dict) or not isinstance(book.get("new_entries_enabled"), bool):
        return False, f"no valid new_entries_enabled flag for {portfolio_id} — failing closed"
    if book["new_entries_enabled"]:
        return True, "enabled"
    return False, (f"QUARANTINED by human control: {book.get('reason') or 'no reason given'} "
                   f"(since {book.get('changed_at') or 'unknown'})")
