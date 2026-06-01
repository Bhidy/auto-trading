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

# Portfolios that run the EOD broker-vs-ledger reconciliation audit (P1 + P3;
# P2 uses a working-orders report, not drift). If a report says in_sync=false,
# the broker and the trade log have diverged — a money-correctness signal that
# must never sit silent. P2 has no drift report, so it's intentionally absent.
RECONCILE_SOURCES = {
    "P1 Self Improving Brain": "data/reconciliation_report.json",
    "P3 Cautious Sniper": "event-driven-bot/data/reconciliation_report.json",
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


def read_reconciliation(root: Path):
    """Return {label: report_dict_or_None} for each portfolio that reconciles."""
    out = {}
    for label, rel in RECONCILE_SOURCES.items():
        path = root / rel
        try:
            with open(path) as f:
                out[label] = json.load(f)
        except Exception:
            out[label] = None
    return out


def assess_reconciliation(reports: dict):
    """Pure decision logic (unit-tested). Returns (alert: bool, summary: str).

    Flags any portfolio whose latest reconciliation shows OPEN drift
    (`in_sync` is False) — a broker-vs-ledger divergence (orphan open trades,
    unlogged positions, or qty/cost-basis drift) that must not stay silent.
    A missing report is not drift (returns no alert for it).
    """
    drifting = []
    for label, rep in reports.items():
        if not isinstance(rep, dict) or rep.get("in_sync") is not False:
            continue
        parts = []
        for key, human in (
            ("orphan_open_trades", "orphan open trades"),
            ("unlogged_positions", "unlogged positions"),
            ("qty_drift", "qty drift"),
            ("cost_basis_drift", "cost-basis drift"),
        ):
            vals = rep.get(key) or []
            if vals:
                parts.append(f"{human}: {', '.join(str(v) for v in vals)}")
        drifting.append(f"{label} — {'; '.join(parts) if parts else 'in_sync=false'}")
    if drifting:
        return True, (
            "RECONCILIATION DRIFT — broker vs ledger out of sync:\n"
            + "\n".join(f"  - {d}" for d in drifting)
        )
    return False, "Reconciliation: all books in sync."


# Each portfolio's data dir, where the trading session writes the execution-
# integrity, strategy-conformance, and preflight reports (Phases C/D/E).
PORTFOLIO_DATA_DIRS = {
    "P1 Self Improving Brain": "data",
    "P2 Capitol Shadow": "political-copy-bot/data",
    "P3 Cautious Sniper": "event-driven-bot/data",
}


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def read_integrity(root: Path):
    """Return {label: {integrity, conformance, preflight}} for each portfolio."""
    out = {}
    for label, d in PORTFOLIO_DATA_DIRS.items():
        base = root / d
        out[label] = {
            "integrity": _read_json(base / "execution_integrity.json"),
            "conformance": _read_json(base / "strategy_conformance.json"),
            "preflight": _read_json(base / "preflight_report.json"),
        }
    return out


def assess_integrity(reports: dict, today=None):
    """Pure decision logic (unit-tested). Returns (alert: bool, summary: str).

    Flags, per portfolio: an execution anomaly (approved>0 & placed==0 with no
    benign reason — the 2026-06-01 silent no-op), a preflight HARD failure (trading
    was refused), or a strategy-conformance violation. Today-dated reports only for
    integrity/conformance (a stale file must not alert forever); a failed preflight
    is surfaced regardless since it is overwritten on the next successful run. A
    missing report is never an alert.
    """
    issues = []
    for label, rep in reports.items():
        integ, conf, pre = rep.get("integrity"), rep.get("conformance"), rep.get("preflight")
        if (isinstance(integ, dict) and integ.get("anomalous")
                and (today is None or _date_of(integ.get("timestamp")) == today)):
            issues.append(f"{label} — EXECUTION ANOMALY: {integ.get('anomaly_reason')}")
        if isinstance(pre, dict) and pre.get("ok") is False:
            hard = pre.get("hard_failures") or []
            issues.append(f"{label} — PREFLIGHT FAILED: {'; '.join(hard) or 'see report'}")
        if (isinstance(conf, dict) and conf.get("conformant") is False
                and (today is None or _date_of(conf.get("timestamp")) == today)):
            viol = [v.get("name") for v in (conf.get("violations") or [])]
            issues.append(f"{label} — CONFORMANCE: {', '.join(viol)}")
    if issues:
        return True, ("EXECUTION INTEGRITY / CONFORMANCE issues:\n"
                      + "\n".join(f"  - {i}" for i in issues))
    return False, "Execution integrity & conformance: all clear."


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

    # Operational drift check (M1): broker-vs-ledger divergence on P1/P3.
    recon_alert, recon_summary = assess_reconciliation(read_reconciliation(REPO_ROOT))
    if recon_alert:
        alert = True
        summary = f"{summary}\n\n{recon_summary}"

    # Execution integrity / conformance / preflight surfacing (Phase F): the
    # 2026-06-01 silent no-op, a refused preflight, or a mandate violation.
    integ_alert, integ_summary = assess_integrity(read_integrity(REPO_ROOT), today)
    if integ_alert:
        alert = True
        summary = f"{summary}\n\n{integ_summary}"

    print(f"[heartbeat] {summary}")
    _emit_output(alert, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
