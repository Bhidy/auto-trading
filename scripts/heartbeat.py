#!/usr/bin/env python3
"""
Heartbeat watchdog — detects silent automation failures.

After the trading/EOD window, this verifies that each of the 3 portfolios
actually ran and committed fresh state TODAY (on trading days). If a portfolio
went stale, it surfaces an alert so a missed/crashed scheduled run can never go
unnoticed again — the exact failure mode that hid the 2026-05-29 outage.

Zero PC/Claude dependency: runs in GitHub Actions, opens a GitHub issue (and
optionally posts a Slack webhook) when a portfolio is stale.

Exit code is always 0; the workflow reads `alert`/`summary` from GITHUB_OUTPUT.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent

# Each portfolio's freshest "activity" timestamp lives in a state file written
# on every run. Map: label -> (relative path, timestamp field).
FRESHNESS_SOURCES = {
    "P1 Self Improving Brain": ("data/portfolio_state.json", "last_updated"),
    "P2 Capitol Shadow": ("political-copy-bot/data/portfolio_state.json", "timestamp"),
    "P3 Cautious Sniper": ("event-driven-bot/data/bot_state.json", "last_updated"),
}


def _date_of(ts):
    """Extract YYYY-MM-DD from an ISO timestamp string, or None."""
    if not ts or not isinstance(ts, str):
        return None
    return ts[:10]


def read_freshness(root: Path):
    """Return {label: date_string_or_None} for each portfolio."""
    out = {}
    for label, (rel, field) in FRESHNESS_SOURCES.items():
        path = root / rel
        date = None
        try:
            with open(path) as f:
                data = json.load(f)
            date = _date_of(data.get(field))
        except Exception:
            date = None
        out[label] = date
    return out


def assess(today: str, freshness: dict):
    """Pure decision logic (unit-tested). Returns (alert: bool, summary: str).

    A portfolio is STALE if its freshest state timestamp is not today.
    """
    stale, ok = [], []
    for label, date in freshness.items():
        if date == today:
            ok.append(label)
        else:
            stale.append(f"{label} (last activity: {date or 'never'})")
    if stale:
        summary = (
            f"STALE on {today} — {len(stale)} portfolio(s) did not run:\n"
            + "\n".join(f"  - {s}" for s in stale)
            + (f"\nHealthy: {', '.join(ok)}" if ok else "")
        )
        return True, summary
    return False, f"All 3 portfolios ran on {today}: {', '.join(ok)}"


def is_trading_day(api_key, api_secret, today: str) -> bool:
    """True if `today` is a market session day per Alpaca's calendar.
    Fails OPEN (returns True) on API error so we'd rather alert than miss."""
    if not api_key or not api_secret:
        return True
    try:
        r = requests.get(
            "https://paper-api.alpaca.markets/v2/calendar",
            headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret},
            params={"start": today, "end": today},
            timeout=15,
        )
        r.raise_for_status()
        return len(r.json()) > 0
    except Exception as e:
        print(f"[heartbeat] calendar check failed ({e}); assuming trading day")
        return True


def _emit_output(alert: bool, summary: str):
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if not gh_out:
        return
    with open(gh_out, "a") as f:
        f.write(f"alert={'true' if alert else 'false'}\n")
        # Multi-line output via heredoc-style delimiter
        f.write("summary<<HEARTBEAT_EOF\n")
        f.write(summary + "\n")
        f.write("HEARTBEAT_EOF\n")


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    api_key = os.environ.get("P1_API_KEY", "")
    api_secret = os.environ.get("P1_API_SECRET", "")

    if not is_trading_day(api_key, api_secret, today):
        print(f"[heartbeat] {today} is not a trading day — nothing expected. OK.")
        _emit_output(False, f"{today} is not a trading day; no run expected.")
        return 0

    freshness = read_freshness(REPO_ROOT)
    alert, summary = assess(today, freshness)
    print(f"[heartbeat] {summary}")
    _emit_output(alert, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
