"""Human-owned strategy controls: may a book open NEW positions?

``config/strategy_controls.json`` is the single, reviewed switchboard a human
uses to quarantine a strategy (governance — audit 2026-10-03, Phase 27). It is
NEVER written by code, and it only ever gates NEW ENTRIES: exits, stops,
exit-order hygiene and reconciliation always run, so a quarantined book's open
positions keep being protected while they run off.

Fails CLOSED: a missing, unreadable or malformed entry means "no new entries"
(logged), because an unknown control state must never open risk.

It also carries an optional, human-owned ``halt_clear`` REQUEST per book (see
``halt_clear_for``). That request can never clear a halt by itself — the runner
honours it only after an independent, cross-checked equity read.
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


# ---------------------------------------------------------------------------
# Human-owned HALT CLEAR (audit 2026-10-23, C1)
# ---------------------------------------------------------------------------
# A kill-switch halt has no expiry by design. Before this, nothing could clear
# one short of hand-editing data/portfolio_state.json — so a halt latched on a
# phantom read (2026-07-07) froze P1 for 108 days with every run green. The
# clear is a REQUEST, never a command: the runner applies it only after a fresh
# cross-checked equity read proves drawdown is below the kill threshold, and it
# is keyed to ONE specific halt so a stale block can never clear a future one.
#
# Optional per-portfolio block in config/strategy_controls.json:
#   "halt_clear": {
#     "clears_halt_set_at": "<halt_set_at of the halt in portfolio_state.json>",
#     "halt_reason_match":  "<exact halt_reason>",   # legacy halts with no halt_set_at
#     "reason": "...", "changed_at": "YYYY-MM-DD", "changed_by": "..."
#   }
# At least one key field is required; reason/changed_at/changed_by are required
# (governance provenance). Code NEVER writes this file.

HALT_CLEAR_REQUIRED = ("reason", "changed_at", "changed_by")


def halt_clear_for(portfolio_id, controls=None, path=None):
    """(clear_or_None, problem_or_None). A malformed block is surfaced as a
    problem and treated as absent (fail closed: an invalid clear never clears)."""
    controls = controls if controls is not None else load_controls(path)
    if not isinstance(controls, dict):
        return None, None
    book = controls.get(portfolio_id)
    if not isinstance(book, dict) or book.get("halt_clear") is None:
        return None, None
    clear = book["halt_clear"]
    if not isinstance(clear, dict):
        return None, "halt_clear is not an object — ignored"
    if not (clear.get("clears_halt_set_at") or clear.get("halt_reason_match")):
        return None, "halt_clear has neither clears_halt_set_at nor halt_reason_match — ignored"
    missing = [k for k in HALT_CLEAR_REQUIRED if not clear.get(k)]
    if missing:
        return None, f"halt_clear missing provenance field(s) {missing} — ignored"
    return dict(clear), None


def halt_clear_key(clear):
    """Stable identity of a clear request, used to make it single-use."""
    return (f"set_at={clear.get('clears_halt_set_at') or ''}"
            f"|reason={clear.get('halt_reason_match') or ''}"
            f"|changed_at={clear.get('changed_at') or ''}")


def halt_clear_matches(clear, state):
    """(matches, why). Pure. A clear targets exactly one halt:

    * ``clears_halt_set_at`` must equal the halt's ``halt_set_at``; or
    * for a LEGACY halt that carries no ``halt_set_at`` (latched before halts
      were stamped), ``halt_reason_match`` must equal ``halt_reason`` exactly.
      Every halt latched by current code is stamped, so a reason match can never
      clear a future halt. When both keys are given, both must match.
    A clear whose key was already consumed never matches again (single-use).
    """
    if not isinstance(clear, dict) or not isinstance(state, dict):
        return False, "no clear/state"
    if not state.get("halted"):
        return False, "not halted"
    if halt_clear_key(clear) in (state.get("halt_clears_consumed") or []):
        return False, "halt_clear already consumed (single-use)"
    set_at = state.get("halt_set_at")
    want_set_at = clear.get("clears_halt_set_at")
    want_reason = clear.get("halt_reason_match")
    if want_set_at:
        if want_set_at != set_at:
            return False, f"clears_halt_set_at={want_set_at!r} != halt_set_at={set_at!r}"
    elif set_at:
        return False, ("halt is stamped (halt_set_at present) — a reason-only clear "
                       "applies to legacy unstamped halts only")
    if want_reason and want_reason != state.get("halt_reason"):
        return False, f"halt_reason_match={want_reason!r} != halt_reason={state.get('halt_reason')!r}"
    return True, "matches"
