#!/usr/bin/env python3
"""Readiness Engine v2 — per-sleeve live-readiness report (CLI).

Reads the human-owned ``config/strategy_registry.json`` and, for every
sleeve-version, scores its evidence since ``start_date`` with the pre-registered
gates in ``shared/readiness.py``. Writes ``data/readiness_report.json`` (with an
embedded input fingerprint) for the dashboard and docs/LIVE_READINESS.md §6.

READ-ONLY: it places no orders and never writes config. Network is GET-only and
optional — Alpaca (portfolio history, calendar, daily bars; explicit start),
Supabase REST (read), GitHub Actions run history. Every missing input degrades
a gate to ``insufficient`` / ``not_measured``; nothing here can crash a run or
pass a gate by default.

Usage:
  python3 scripts/readiness_engine.py [--as-of YYYY-MM-DD] [--offline]
                                      [--out data/readiness_report.json]
                                      [--skip-non-session]
Env (all optional): P{1,2,3}_API_KEY / P{1,2,3}_API_SECRET, SUPABASE_URL +
SUPABASE_ANON_KEY, GITHUB_TOKEN + GITHUB_REPOSITORY.
"""
import argparse
import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared import readiness as R  # noqa: E402
from shared.alpaca_http import resilient_request  # noqa: E402
from shared.research_provenance import data_fingerprint  # noqa: E402
from performance_tracker import is_partial_trim, whole_trades  # noqa: E402
import heartbeat  # noqa: E402

ET = ZoneInfo("America/New_York")
PAPER_API = "https://paper-api.alpaca.markets"
DATA_API = "https://data.alpaca.markets"
SESSION_COMPLETE_ET = (16, 15)   # after the close + EOD snapshot
HISTORY_START = "2026-05-01"     # books went live 2026-05-27

REGISTRY_PATH = os.path.join(REPO_ROOT, "config", "strategy_registry.json")
CONTROLS_PATH = os.path.join(REPO_ROOT, "config", "strategy_controls.json")
OUT_PATH = os.path.join(REPO_ROOT, "data", "readiness_report.json")

BOOKS = {
    "portfolio_1": {"label": "P1 Self Improving Brain", "env": "P1", "dir": "data",
                    "journal": "journal",
                    "workflows": ["p1-trading.yml", "p1-monitor.yml", "p1-eod.yml",
                                  "p1-weekly.yml", "guardian.yml"]},
    "portfolio_2": {"label": "P2 Capitol Shadow", "env": "P2", "dir": "political-copy-bot/data",
                    "journal": "political-copy-bot/journal",
                    "workflows": ["p2-trading.yml", "p2-monitor.yml", "guardian.yml"]},
    "portfolio_3": {"label": "P3 Cautious Sniper", "env": "P3", "dir": "event-driven-bot/data",
                    "journal": "event-driven-bot/journal",
                    "workflows": ["p3-trading.yml", "p3-monitor.yml", "p3-eod.yml", "guardian.yml"]},
}


def _load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _rel(*parts):
    return os.path.join(REPO_ROOT, *parts)


def _stamp_date(ts):
    """ET session date of an Alpaca daily stamp. Portfolio-history 1D points are
    stamped 00:00Z of the NEXT calendar day (= 20:00 ET of the session they
    close); daily bars are stamped 04:00/05:00Z (= 00:00 ET of the session).
    Converting to America/New_York maps both to the right session."""
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).date().isoformat()


# ---------------------------------------------------------------------------
# Fetchers (GET only; each returns (data_or_None, note))
# ---------------------------------------------------------------------------

def _next_day(d):
    """Portfolio-history points are stamped 00:00Z of the next day, so the
    request must end one day after the as-of session to include its close."""
    return (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).date().isoformat()


def _keys(env_prefix):
    k, s = os.environ.get(f"{env_prefix}_API_KEY", ""), os.environ.get(f"{env_prefix}_API_SECRET", "")
    return ({"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s} if k and s else None)


def _any_keys():
    for b in BOOKS.values():
        h = _keys(b["env"])
        if h:
            return h
    return None


def fetch_calendar(headers, start, end):
    if not headers:
        return None, "no Alpaca keys"
    try:
        rows = resilient_request("GET", f"{PAPER_API}/v2/calendar", headers,
                                 params={"start": start, "end": end}, timeout=20)
        return [r["date"] for r in rows if r.get("date")], "alpaca calendar"
    except Exception as e:  # network/HTTP: fall back to the NYSE rules
        return None, f"alpaca calendar failed ({type(e).__name__})"


def fetch_equity_alpaca(headers, start, end):
    if not headers:
        return None, "no Alpaca keys"
    try:
        d = resilient_request("GET", f"{PAPER_API}/v2/account/portfolio/history", headers,
                              params={"timeframe": "1D", "start": start, "end": end}, timeout=30)
        out = {}
        for ts, eq in zip(d.get("timestamp") or [], d.get("equity") or []):
            if eq:
                out[_stamp_date(ts)] = float(eq)
        return (out or None), "alpaca portfolio history (1D)"
    except Exception as e:
        return None, f"alpaca portfolio history failed ({type(e).__name__})"


def fetch_equity_supabase(pid, start):
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        return None, "no Supabase read key"
    try:
        rows = resilient_request(
            "GET", f"{url.rstrip('/')}/rest/v1/portfolio_equity_history",
            {"apikey": key, "Authorization": f"Bearer {key}"},
            params={"portfolio_id": f"eq.{pid}", "date": f"gte.{start}",
                    "select": "date,equity", "order": "date.asc", "limit": 2000}, timeout=20)
        # Exactly-$100,000 rows are inception anchors, not measurements (honest data rule).
        out = {r["date"][:10]: float(r["equity"]) for r in rows or []
               if r.get("equity") and float(r["equity"]) != 100000.0}
        return (out or None), "supabase portfolio_equity_history"
    except Exception as e:
        return None, f"supabase read failed ({type(e).__name__})"


def equity_from_journals(journal_dir):
    """Equity per ET session from committed journals (last resort).

    P1 entries carry a ``mode`` — only ``end-of-day`` rows count (its other rows
    are intraday). P2 (``account_snapshot``) and P3 (``audit``) rows have no
    mode: the LATEST row per ET session is used, which for P2 is an intraday
    snapshot (flagged). Rows are dated by the ET session of their timestamp, so
    a journal written at 00:00Z belongs to the previous ET day."""
    best = {}
    for fp in sorted(glob.glob(os.path.join(journal_dir, "2*.json"))):
        entries = _load(fp, [])
        entries = [entries] if isinstance(entries, dict) else (entries or [])
        has_mode = any(isinstance(e, dict) and e.get("mode") for e in entries)
        for e in entries:
            if not isinstance(e, dict) or (has_mode and e.get("mode") != "end-of-day"):
                continue
            eq = None
            for blk in ("account", "audit", "account_snapshot"):
                v = (e.get(blk) or {}).get("equity") if isinstance(e.get(blk), dict) else None
                if v is not None:
                    eq = v
                    break
            try:
                eq = float(eq)
            except (TypeError, ValueError):
                continue
            ts = str(e.get("timestamp") or "")
            d = R.iso_date_et(ts) or os.path.basename(fp)[:10]
            if eq > 0 and (d not in best or ts >= best[d][0]):
                best[d] = (ts, eq)
    out = {d: v for d, (_ts, v) in best.items()}
    return (out or None), "committed journals (latest snapshot per session; P2 rows are intraday)"


def fetch_bars(headers, symbols, start, end):
    """Daily adjusted closes {sym: {date: close}} — SIP first, IEX fallback."""
    if not headers:
        return None, "no Alpaca keys"
    for feed in ("sip", "iex"):
        try:
            out, token = {}, None
            for _ in range(20):
                params = {"symbols": ",".join(symbols), "timeframe": "1Day", "start": start,
                          "end": end, "adjustment": "all", "feed": feed, "limit": 10000}
                if token:
                    params["page_token"] = token
                d = resilient_request("GET", f"{DATA_API}/v2/stocks/bars", headers, params=params, timeout=30)
                for sym, bars in (d.get("bars") or {}).items():
                    for b in bars or []:
                        out.setdefault(sym, {})[_stamp_date(b["t"])] = float(b["c"])
                token = d.get("next_page_token")
                if not token:
                    break
            if all(out.get(s) for s in symbols):
                return out, f"alpaca daily bars ({feed}, adjustment=all)"
        except Exception:
            continue
    return None, "alpaca bars failed"


def bars_from_committed():
    """Offline fallback: morning-research bar caches (SPY in core_equity.json,
    BIL in defensive.json). Raw (unadjusted) closes — flagged in the report."""
    out = {}
    for fname, sym in (("core_equity.json", "SPY"), ("defensive.json", "BIL")):
        bars = ((_load(_rel("data", fname), {}) or {}).get("bars") or {}).get(sym) or []
        for b in bars:
            try:
                out.setdefault(sym, {})[_stamp_date(b["t"])] = float(b["c"])
            except (KeyError, TypeError, ValueError):
                continue
    return (out if out.get("SPY") else None), "committed bar caches (raw closes)"


_WF_CACHE = {}


def _workflow_failures(wf, since, hdr, repo):
    """{ET session: failed-run count} for one workflow file (cached per run)."""
    if wf in _WF_CACHE:
        return _WF_CACHE[wf]
    counts = {}
    for conclusion in ("failure", "timed_out", "startup_failure"):   # server-side filter
        for page in range(1, 11):
            d = resilient_request(
                "GET", f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs", hdr,
                params={"created": f">={since}", "status": conclusion, "per_page": 100, "page": page},
                timeout=20)
            runs = d.get("workflow_runs") or []
            for run in runs:
                s = R.iso_date_et(run.get("created_at"))
                counts[s] = counts.get(s, 0) + 1
            if len(runs) < 100:
                break
    _WF_CACHE[wf] = counts
    return counts


def fetch_workflow_failures(workflows, sessions, as_of, horizon=45):
    """{session: failed_run_count} over the last ``horizon`` sessions for a
    book's workflows, or None if the run history cannot be read completely
    (never a silent pass). A failed run is the observable proxy for an
    unhandled exception (it also counts e.g. a push conflict — conservative)."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None, "GITHUB_TOKEN/GITHUB_REPOSITORY not set"
    window = [s for s in sessions if s <= as_of][-horizon:]
    if not window:
        return None, "no sessions"
    counts = {s: 0 for s in window}
    hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        for wf in workflows:
            for s, c in _workflow_failures(wf, window[0], hdr, repo).items():
                if s in counts:
                    counts[s] += c
    except Exception as e:
        return None, f"github run history failed ({type(e).__name__})"
    return counts, "github actions run history"


# ---------------------------------------------------------------------------
# Trade-row selection per sleeve (code knows the log schemas; registry does not)
# ---------------------------------------------------------------------------

def _text(t):
    r = t.get("reasons", t.get("reason"))
    return " ".join(map(str, r)) if isinstance(r, list) else str(r or "")


def _is_momentum(t):
    return (t.get("bucket") == "momentum" or t.get("order_class") == "momentum_sleeve"
            or "momentum top" in _text(t))


SLEEVE_ROWS = {
    "p1-momentum-v1": _is_momentum,
    "p1-multifactor-satellite-v2": lambda t: (not _is_momentum(t) and "passive_core" not in _text(t)
                                              and "reconciled from broker" not in _text(t)),
    "p2-copy-v2": lambda t: (t.get("politician") != "BENCHMARK_SLEEVE"
                             and t.get("source") != "benchmark_sleeve"),
    "p2-benchmark-etf-v1": lambda t: (t.get("politician") == "BENCHMARK_SLEEVE"
                                      or t.get("source") == "benchmark_sleeve"),
    "p3-event-driven-legacy": lambda t: not str(t.get("strategy") or "").startswith("crisis_core"),
    "p3-crisis-core-v1-forward": lambda t: str(t.get("strategy") or "").startswith("crisis_core"),
}


def sleeve_rows(sleeve_id, log, start, end):
    pred = SLEEVE_ROWS.get(sleeve_id)
    if pred is None:
        return None
    out = []
    for t in log or []:
        if not isinstance(t, dict) or not pred(t):
            continue
        d = R.iso_date_et(t.get("timestamp")) or ""
        if start <= d <= end:
            out.append(t)
    return out


def _is_entry(t):
    return not is_partial_trim(t) and t.get("status") != "exit_marker"


def _engine_placed(t):
    """Rows written by reconciliation (unlogged broker lots) are not orders the
    engine placed, so they cannot be duplicate orders."""
    return (str(t.get("status") or "") != "closed_reconciled"
            and "reconciled from broker" not in _text(t))


def duplicate_entries(rows):
    """Count symbol/side/session groups holding more than one DISTINCT order
    (the engines place at most one per symbol/side/session; lot splits share an
    order id and are not duplicates). Returns (duplicates, entries_checked)."""
    groups = {}
    for t in rows:
        if not _is_entry(t) or not _engine_placed(t):
            continue
        ident = t.get("order_id") or t.get("client_order_id") or t.get("id")
        key = (t.get("symbol"), str(t.get("side")).lower(), R.iso_date_et(t.get("timestamp")))
        groups.setdefault(key, set()).add(str(ident))
    return sum(len(v) - 1 for v in groups.values() if len(v) > 1), len(groups)


def adverse_slippage_bps(rows):
    """Adverse slippage (bps, + = cost) vs each row's recorded reference price,
    ONE sample per order (lot-split rows share an order id and would otherwise
    be counted several times). Buys: fill above reference is adverse; sells:
    below."""
    out, seen = [], set()
    for t in rows:
        sp = t.get("slippage_pct")
        if sp is None or not _is_entry(t):
            continue
        ident = t.get("order_id") or t.get("client_order_id") or t.get("id")
        if ident is not None:
            if ident in seen:
                continue
            seen.add(ident)
        try:
            sign = -1.0 if str(t.get("side")).lower() == "sell" else 1.0
            out.append(float(sp) * 100.0 * sign)
        except (TypeError, ValueError):
            continue
    return out


def trade_pnls(sleeve_id, rows, start):
    """Whole round-trip P&Ls for trade-based sleeves, or (None, why)."""
    if sleeve_id == "p2-copy-v2":
        sc = _load(_rel("data", "p2_scorecard.json"))
        post = ((sc or {}).get("cohorts") or {}).get("post") or {}
        rts = post.get("round_trips")
        if rts is None:
            return None, "data/p2_scorecard.json post cohort unavailable"
        pnls = [float(rt["pnl"]) for rt in rts if rt.get("pnl") is not None and (rt.get("entry_date") or "") >= start]
        return pnls, f"pre-registered P2 scorecard post cohort (generated {str(sc.get('generated_at'))[:10]})"
    if rows is None:
        return None, "no trade selector for this sleeve"
    completed, _partial = whole_trades(rows)
    return [float(w["pnl"]) for w in completed], "whole trades (slices aggregated per lot) from the book trade log"


# ---------------------------------------------------------------------------
# Regime tags
# ---------------------------------------------------------------------------

def regime_labels(sessions):
    """{session: label} from weekly journals (ISO week -> its sessions) plus the
    latest signals.json regime for sessions after the last weekly tag."""
    labels = {}
    last_tag_day = ""
    for fp in sorted(glob.glob(_rel("journal", "weekly-*.json"))):
        d = _load(fp, {}) or {}
        lab, wk = d.get("market_regime") or d.get("regime"), d.get("week")
        if not lab or not wk:
            continue
        try:
            y, w = wk.split("-W")
            monday = datetime.strptime(f"{y}-W{int(w):02d}-1", "%G-W%V-%u").date()
        except ValueError:
            continue
        for i in range(5):
            day = (monday + timedelta(days=i)).isoformat()
            if day in sessions:
                labels[day] = lab
                last_tag_day = max(last_tag_day, day)
    sig = _load(_rel("data", "signals.json"), {}) or {}
    lab, d = sig.get("market_regime"), R.iso_date_et(sig.get("timestamp"))
    if lab and d:
        for s in sessions:
            if last_tag_day < s <= d:
                labels[s] = lab
    return labels


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _edge_summary(edge, eta_edge):
    def rd(x, nd=6):
        return round(x, nd) if isinstance(x, float) else x
    return {
        "alpha": rd(edge.get("alpha_annual")),           # annualized (x252), arithmetic
        "alpha_daily": rd(edge.get("alpha_daily"), 8),
        "beta": rd(edge.get("beta"), 4),
        "t_hac": rd(edge.get("t_hac"), 4),
        "ir": rd(edge.get("ir_annual"), 4),              # appraisal ratio, annualized
        "psr": rd(edge.get("psr"), 4),
        "dsr": rd(edge.get("dsr"), 4),
        "n": edge.get("n"),
        "trial_count": edge.get("trial_count"),
        "z_required": edge.get("z_required"),
        "rf_source": edge.get("rf_source"),
        "status": edge.get("status"),
        "eta_state": eta_edge.get("state"),
    }


def resolve_as_of(sessions, now_utc):
    now_et = now_utc.astimezone(ET)
    today = now_et.date().isoformat()
    if today in sessions and (now_et.hour, now_et.minute) >= SESSION_COMPLETE_ET:
        return today
    return R.previous_session(sessions, today)


def controls_warnings(registry, controls):
    """Registry status must agree with the human-owned strategy controls."""
    w = []
    for s in registry:
        c = (controls or {}).get(s["book"]) or {}
        if s["status"] in ("active", "forward_test") and s["sleeve"] != "crisis_core_allocator" \
                and c.get("new_entries_enabled") is False:
            w.append(f"{s['id']}: registry says {s['status']} but {s['book']}.new_entries_enabled=false")
        if s["sleeve"] == "crisis_core_allocator":
            al = c.get("allocator") or {}
            if s["status"] == "forward_test" and not al.get("enabled"):
                w.append(f"{s['id']}: registry forward_test but {s['book']}.allocator.enabled is not true")
    return w


def build_report(registry_doc, *, as_of=None, offline=False, now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    warnings = []
    registry = registry_doc.get("sleeves") or []
    hdr = None if offline else _any_keys()
    horizon_end = (now_utc.date() + timedelta(days=366 * 12)).isoformat()

    broker_days, cal_note = (None, "offline") if offline else fetch_calendar(
        hdr, HISTORY_START, (now_utc.date() + timedelta(days=365)).isoformat())
    if broker_days is None:
        warnings.append(f"session calendar from standing NYSE rules ({cal_note})")
    sessions = R.nyse_sessions(HISTORY_START, horizon_end, broker_days)
    as_of = as_of or resolve_as_of(sessions, now_utc)

    # Books: equity series (one source per book, in priority order)
    books, equity = {}, {}
    for pid, b in BOOKS.items():
        series, note, tried = None, None, []
        sources = [] if offline else [lambda: fetch_equity_alpaca(_keys(b["env"]), HISTORY_START, _next_day(as_of)),
                                      lambda: fetch_equity_supabase(pid, HISTORY_START)]
        sources.append(lambda: equity_from_journals(_rel(b["journal"])))
        for fn in sources:
            series, note = fn()
            tried.append(note)
            if series:
                break
        series = {d: v for d, v in (series or {}).items() if d <= as_of}
        equity[pid] = series
        books[pid] = {"label": b["label"], "equity_source": note if series else None,
                      "equity_sources_tried": tried, "equity_points": len(series),
                      "first_date": min(series) if series else None,
                      "last_date": max(series) if series else None,
                      "last_equity": series[max(series)] if series else None, "sleeves": []}

    # Benchmark + risk-free (BIL) closes
    bars, bars_note = (None, "offline") if offline else fetch_bars(hdr, ["SPY", "BIL"], HISTORY_START, as_of)
    if not bars:
        bars, bars_note = bars_from_committed()
        warnings.append(f"benchmark bars from {bars_note}")
    bars = bars or {}

    labels = regime_labels(set(sessions))
    freshness = heartbeat.read_freshness(Path(REPO_ROOT))
    fresh_by_book = {pid: freshness.get(b["label"]) for pid, b in BOOKS.items()}
    controls = _load(CONTROLS_PATH, {})
    warnings.extend(controls_warnings(registry, controls))

    wf_cache = {}
    sleeves_out = []
    for s in registry:
        pid, b = s["book"], BOOKS.get(s["book"])
        if b is None:
            warnings.append(f"{s.get('id')}: unknown book {pid}")
            continue
        start = s["start_date"]
        end = min(s.get("end_date") or as_of, as_of)
        n_sessions = R.count_sessions(sessions, start, end) if start <= end else 0
        th = R.THRESHOLDS

        book_w = R.window_returns(equity[pid], sessions, start, end)
        spy_w = R.window_returns(bars.get("SPY", {}), sessions, start, end)
        bil_w = R.window_returns(bars.get("BIL", {}), sessions, start, end)
        spy_by, bil_by = dict(zip(spy_w["dates"], spy_w["returns"])), dict(zip(bil_w["dates"], bil_w["returns"]))
        rf_const = th["rf_fallback_annual"] / R.PERIODS_PER_YEAR
        use_bil = bool(book_w["dates"]) and sum(1 for d in book_w["dates"] if d in bil_by) >= 0.9 * len(book_w["dates"])
        aligned = [(d, r) for d, r in zip(book_w["dates"], book_w["returns"]) if d in spy_by]
        y = [r for _, r in aligned]
        x = [spy_by[d] for d, _ in aligned]
        rf = [(bil_by.get(d, rf_const) if use_bil else rf_const) for d, _ in aligned]
        edge = R.edge_test(y, x, rf, s["trial_count"])
        edge["rf_source"] = "BIL daily total return" if use_bil else \
            f"constant {th['rf_fallback_annual']:.0%}/yr (BIL returns unavailable)"
        eta_edge = R.edge_eta(edge)

        gates = [R.track_record_gate(n_sessions), R.edge_gate(edge, eta_edge)]
        gates += R.risk_gates(book_w["returns"])

        log = _load(_rel(b["dir"], "trade_log.json"), [])
        rows = sleeve_rows(s["id"], log, start, end)
        if s["evidence_basis"] in ("trades", "both"):
            pnls, why = trade_pnls(s["id"], rows, start)
            gates += R.trade_gates(pnls, n_sessions, why)
        else:
            for gid, name in (("sample", "Closed round trips (whole trades)"), ("profit_factor", "Profit factor")):
                gates.append(R.gate(gid, name, "trade-based sleeves only", None, "not_applicable",
                                    "evidence basis is daily returns", hard=False))

        gates.append(R.regime_gate(book_w["dates"], book_w["returns"], labels))
        gates.append(R.reconciliation_gate(_load(_rel(b["dir"], "reconciliation_report.json")), as_of, sessions))
        dup_extra = ""
        if s["sleeve"] == "crisis_core_allocator":
            conc = ((_load(_rel(b["dir"], "allocator_state.json"), {}) or {}).get("concurrency") or {})
            if conc.get("count"):
                dup_extra = f"allocator race detector count={conc.get('count')} (stale runs placed nothing)"
        if rows is None:
            gates.append(R.duplicate_gate(None, 0, "no row selector for this sleeve"))
            gates.append(R.slippage_gate(None))
        else:
            dups, checked = duplicate_entries(rows)
            gates.append(R.duplicate_gate(dups, checked, dup_extra))
            sg = R.slippage_gate(adverse_slippage_bps(rows))
            if pid == "portfolio_2" and sg["value"] is not None:
                sg["detail"] += ("; P2 reference = its limit price (house convention), so a negative value "
                                 "is headroom under the limit, not price improvement vs arrival")
            gates.append(sg)
        gates.append(R.freshness_gate(fresh_by_book.get(pid), as_of, sessions))
        if pid not in wf_cache:
            wf_cache[pid] = (None, "offline") if offline else fetch_workflow_failures(b["workflows"], sessions, as_of)
        fails, _wf_note = wf_cache[pid]
        gates.append(R.exception_gate(fails, as_of, sessions))

        v = R.verdict(s["status"], gates, sessions, as_of)
        entry = {k: s.get(k) for k in ("id", "book", "sleeve", "version", "start_date", "end_date", "status",
                                       "evidence_basis", "benchmark", "trial_count", "spec")}
        entry.update({
            "window": {"start": start, "end": end, "trading_days": n_sessions,
                       "daily_returns": len(book_w["returns"]), "aligned_with_spy": len(aligned),
                       "missing_sessions": book_w["missing"][:20]},
            "attribution": "book_level",
            "attribution_note": f"no clean sleeve-level series; returns are the whole {pid} account "
                                f"({books[pid]['equity_source'] or 'no equity source'})",
            "gates": gates,
            "edge": _edge_summary(edge, eta_edge),
            "eta": {"edge": eta_edge, "overall": v["eta"]},
            "verdict": v["verdict"], "binding_gate": v["binding_gate"],
            "gates_passed": v["gates_passed"], "gates_total": v["gates_total"],
            "measurement_gaps": v["measurement_gaps"],
        })
        entry["narrative"] = R.narrative({**entry, "edge": edge, "eta": v["eta"]})
        sleeves_out.append(entry)
        books[pid]["sleeves"].append(s["id"])

    for pid in books:
        mine = [e for e in sleeves_out if e["book"] == pid]
        books[pid]["verdicts"] = {e["id"]: e["verdict"] for e in mine}
        books[pid]["any_go"] = any(e["verdict"] == "GO" for e in mine)

    inputs = [REGISTRY_PATH, CONTROLS_PATH, _rel("data", "p2_scorecard.json")] + \
        [_rel(b["dir"], f) for b in BOOKS.values() for f in ("trade_log.json", "reconciliation_report.json")]
    return {
        "generated_at": now_utc.isoformat(),
        "as_of_session": as_of,
        "methodology_version": R.METHODOLOGY_VERSION,
        "methodology_doc": "docs/LIVE_READINESS.md §2 (v2)",
        "thresholds": dict(R.THRESHOLDS),
        "verdict_rule": "GO only if every hard gate passes; NOT_ELIGIBLE for exits_only/quarantined; "
                        "no percentage score. Real capital remains a human decision.",
        "sleeves": sleeves_out,
        "books": books,
        "data_sources": {"calendar": "alpaca" if broker_days else "nyse_rules", "bars": bars_note,
                         "workflow_history": {pid: note for pid, (_f, note) in wf_cache.items()}},
        "warnings": warnings,
        "provenance": data_fingerprint(inputs, extra={"engine": "scripts/readiness_engine.py"}),
        "disclosure": "Paper-trading evidence for internal model-risk use — not investment advice. PAPER ONLY.",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--as-of")
    ap.add_argument("--offline", action="store_true", help="no network; committed artifacts only")
    ap.add_argument("--out", default=OUT_PATH)
    ap.add_argument("--skip-non-session", action="store_true",
                    help="exit 0 without writing when today (ET) is not a trading session")
    ap.add_argument("--skip-if-current", action="store_true",
                    help="exit 0 without writing when --out already holds this session's report "
                         "under the same methodology (dedups the staggered cron)")
    a = ap.parse_args(argv)

    registry = _load(REGISTRY_PATH)
    if not isinstance(registry, dict) or not registry.get("sleeves"):
        print("[readiness] config/strategy_registry.json missing or empty — nothing written")
        return 1
    if a.skip_non_session and not a.offline:
        today = datetime.now(timezone.utc).astimezone(ET).date().isoformat()
        days, _ = fetch_calendar(_any_keys(), today, today)
        if days is not None and today not in days:
            print(f"[readiness] {today} is not a trading session — report unchanged.")
            return 0
    if a.skip_if_current and not a.as_of:
        prev = _load(a.out, {}) or {}
        now = datetime.now(timezone.utc)
        cal, _ = (None, "offline") if a.offline else fetch_calendar(
            _any_keys(), HISTORY_START, (now.date() + timedelta(days=7)).isoformat())
        cur = resolve_as_of(R.nyse_sessions(HISTORY_START, (now.date() + timedelta(days=7)).isoformat(), cal), now)
        if (prev.get("as_of_session") == cur and prev.get("methodology_version") == R.METHODOLOGY_VERSION
                and (R.iso_date_et(prev.get("generated_at")) or "") >= cur):
            print(f"[readiness] report for session {cur} already current — unchanged.")
            return 0
    report = build_report(registry, as_of=a.as_of, offline=a.offline)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    for e in report["sleeves"]:
        print(f"[readiness] {e['id']:<30} {e['verdict']:<13} {e['gates_passed']}/{e['gates_total']} "
              f"binding={e['binding_gate']}")
    for w in report["warnings"]:
        print(f"[readiness] warning: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
