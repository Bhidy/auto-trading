"""Regression tests for the 2026-10-23 audit defects on P2/P3 + the shared
state-commit path (D1, D2, D3, D4, D6, D7, D9, D10, D11, D12).

Every test is hermetic: no network, no broker, no keys. Workflow YAML is
checked textually (PyYAML is not a CI dependency) and the commit script is
exercised end-to-end against throw-away local git repositories.
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P2_SCRIPTS = os.path.join(REPO_ROOT, "political-copy-bot", "scripts")
P3_SCRIPTS = os.path.join(REPO_ROOT, "event-driven-bot", "scripts")
WF = os.path.join(REPO_ROOT, ".github", "workflows")
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts"), P2_SCRIPTS, P3_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import heartbeat  # noqa: E402
import house_fd_feed  # noqa: E402
import politician_bot as pb  # noqa: E402


def _read(name):
    with open(os.path.join(WF, name)) as f:
        return f.read()


# ===========================================================================
# Shared P2 stubs
# ===========================================================================

class StubAlpaca:
    def __init__(self, positions=None, is_open=True):
        self._positions = positions or []
        self._is_open = is_open
        self.orders = []

    def get_account(self):
        return {"equity": "100000", "cash": "50000", "last_equity": "100000"}

    def get_clock(self):
        return {"is_open": self._is_open}

    def get_positions(self):
        return self._positions

    def get_position(self, sym):
        return next((p for p in self._positions if p["symbol"] == sym), None)

    def get_latest_quote(self, sym):
        return {"quote": {"ap": 100.0, "bp": 99.0}}

    def get_latest_trade(self, sym):
        return {"trade": {"p": 100.0}}

    def get_order(self, oid):
        return {"status": "filled", "filled_qty": self.orders[-1]["qty"],
                "filled_avg_price": "99.0"}

    def place_order(self, **kw):
        o = {"id": f"ord-{len(self.orders)}", "status": "accepted", **kw}
        self.orders.append(o)
        return o


WATCHLIST = {
    "primary_politician": "David Taylor",
    "backup_politicians": ["Kevin Hern", "Josh Gottheimer"],
    "check_intervals": {"primary_scan_days": 30},
    "copy_filters": {"transaction_types": ["BUY"], "max_transaction_age_days": 45},
    "sell_logic": {"copy_politician_sells": True},
}


def _bot(tmp_path, monkeypatch, alpaca=None, trade_log=None):
    monkeypatch.setattr(pb, "BASE_DIR", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "risk_limits.json").write_text(json.dumps({
        "limit_offset_pct": 0.15, "max_daily_trades": 10,
        "kill_switch_drawdown_pct": 18, "max_daily_loss_pct": 4}))
    bot = pb.PoliticianBot.__new__(pb.PoliticianBot)
    bot.alpaca = alpaca or StubAlpaca()
    bot.risk = pb.RiskManager(tmp_path / "config" / "risk_limits.json",
                              tmp_path / "data" / "trade_log.json")
    bot.risk.trade_log = list(trade_log or [])
    bot.watchlist_cfg = json.loads(json.dumps(WATCHLIST))
    bot.processed_trades_path = tmp_path / "data" / "processed_trades.json"
    bot.portfolio_state_path = tmp_path / "data" / "portfolio_state.json"
    bot.processed_trades = set()
    bot._freshness_evaluated = 0
    bot._unparseable_dates = 0
    return bot


def _recent(days=5, fmt="%m/%d/%Y"):
    from datetime import timedelta
    return (datetime.now() - timedelta(days=days)).strftime(fmt)


def _trade(pol, ticker, tx="BUY", date=None, size="1K–15K"):
    return {"politician": {"name": pol}, "issuer": {"name": ticker + " Inc", "ticker": ticker},
            "transaction": {"type": tx, "size": size},
            "dates": {"trade": date or _recent()}}


# ===========================================================================
# D2 — House index first; Capitol Trades probed once behind a breaker
# ===========================================================================

def test_d2_house_feed_runs_first_and_failed_probe_skips_all_mcp(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    order, mcp_calls, sleeps = [], [], []

    def fake_house(pols, max_age_days=45, pending=None, status=None, **kw):
        order.append("house")
        status["index_ok"] = True
        return [_trade("David Taylor", "AMD")]

    def fake_mcp(tool, args, timeout=120, max_attempts=5):
        order.append("mcp")
        mcp_calls.append((args["politician"], timeout, max_attempts))
        raise RuntimeError("Capitol Trades rate-limited (WAF)")

    monkeypatch.setattr(house_fd_feed, "fetch_tracked_ptr_trades", fake_house)
    monkeypatch.setattr(pb, "call_mcp_tool", fake_mcp)
    monkeypatch.setattr(pb.time, "sleep", lambda s: sleeps.append(s))

    trades = bot.scan_politician_trades()

    assert order[0] == "house"
    assert len(mcp_calls) == 1, "a failed probe must short-circuit every other MCP fetch"
    assert mcp_calls[0][2] == 1 and mcp_calls[0][1] <= 30
    assert sleeps == []
    assert [t["issuer"]["ticker"] for t in trades] == ["AMD"]
    assert bot._feed_dark is True and bot._fallback_ok is True
    assert bot._mcp_circuit_open is True


def test_d2_breaker_opens_after_consecutive_failures(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    calls = []

    def fake_mcp(tool, args, timeout=120, max_attempts=5):
        calls.append(args["politician"])
        if len(calls) == 1:
            return {"trades": []}            # probe OK
        raise RuntimeError("down")

    monkeypatch.setattr(house_fd_feed, "fetch_tracked_ptr_trades",
                        lambda *a, status=None, **k: status.update(index_ok=True) or [])
    monkeypatch.setattr(pb, "call_mcp_tool", fake_mcp)
    monkeypatch.setattr(pb.time, "sleep", lambda s: None)
    bot.scan_politician_trades()
    # probe + primary SELL (fail 1) + first backup (fail 2) -> circuit open
    assert len(calls) == 1 + pb.MCP_BREAKER_THRESHOLD
    assert bot._mcp_circuit_open is True


def test_d2_same_filing_from_both_feeds_is_copied_once(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    house = _trade("Josh Gottheimer", "NVDA", date=_recent(5, "%m/%d/%Y"))
    mcp = _trade("Josh Gottheimer", "NVDA", date=_recent(5, "%d %b %Y"), size="1K-15K")
    monkeypatch.setattr(house_fd_feed, "fetch_tracked_ptr_trades",
                        lambda *a, status=None, **k: status.update(index_ok=True) or [house])
    monkeypatch.setattr(pb, "call_mcp_tool",
                        lambda tool, args, **k: {"trades": [mcp] if args["politician"]
                                                 == "Josh Gottheimer" else []})
    monkeypatch.setattr(pb.time, "sleep", lambda s: None)
    trades = bot.scan_politician_trades()
    assert [t["issuer"]["ticker"] for t in trades] == ["NVDA"]


def test_d2_p2_trading_timeout_is_25_minutes():
    text = _read("p2-trading.yml")
    assert "timeout-minutes: 25" in text and "timeout-minutes: 15" not in text


def test_d2_mcp_client_exposes_attempt_budget():
    import inspect
    import mcp_client
    assert "max_attempts" in inspect.signature(mcp_client.call_mcp_tool).parameters


# ===========================================================================
# D6 — every P2 exit carries a client_order_id; processed state per order
# ===========================================================================

def test_d6_exit_client_order_ids_are_deterministic_and_distinct():
    a = pb.exit_client_order_id("cs", "HD", politician="David Taylor")
    b = pb.exit_client_order_id("cs", "HD", politician="Kevin Hern")
    assert a == pb.exit_client_order_id("cs", "HD", politician="david  taylor")
    assert a != b                                         # different politicians
    assert pb.exit_client_order_id("ts", "HD") != pb.exit_client_order_id("tx", "HD")
    assert a.endswith("-HD-sell") and len(a) <= 128


def test_d6_trailing_stop_order_sends_client_order_id(tmp_path, monkeypatch):
    alpaca = StubAlpaca(positions=[{"symbol": "CB", "unrealized_plpc": "-0.30", "qty": "10"}])
    bot = _bot(tmp_path, monkeypatch, alpaca=alpaca)
    bot.watchlist_cfg["sell_logic"].update({"trailing_stop_pct": 8.0})
    (tmp_path / "data" / "trailing_peaks.json").write_text(json.dumps({"CB": 5.0}))
    monkeypatch.setattr(pb, "confirm_fill", lambda c, oid: ("filled", 10, 99.0))
    bot.check_stops()
    assert alpaca.orders and alpaca.orders[0]["client_order_id"] == \
        pb.exit_client_order_id("ts", "CB")


def test_d6_duplicate_exit_is_an_idempotent_skip():
    class Resp:
        status_code = 422
        text = '{"message":"client_order_id must be unique"}'

    import requests
    assert pb.is_duplicate_client_order_id(requests.HTTPError(response=Resp()))
    assert not pb.is_duplicate_client_order_id(RuntimeError("x"))


def _scan_harness(tmp_path, monkeypatch, is_open=True):
    bot = _bot(tmp_path, monkeypatch, alpaca=StubAlpaca(is_open=is_open))
    import shared.preflight as pf
    monkeypatch.setattr(pf, "run_preflight", lambda **k: (True, {"hard_failures": []}))
    monkeypatch.setattr(pb.time, "sleep", lambda s: None)
    return bot


def test_d6_processed_state_is_persisted_after_each_order(tmp_path, monkeypatch):
    bot = _scan_harness(tmp_path, monkeypatch)
    t1, t2 = _trade("David Taylor", "AMD"), _trade("David Taylor", "MSFT")
    monkeypatch.setattr(bot, "scan_politician_trades", lambda: [t1, t2])
    calls = []

    def execute(trade, cluster_counts=None):
        calls.append(trade["issuer"]["ticker"])
        if len(calls) == 2:
            raise RuntimeError("job killed mid-loop")
        return None

    monkeypatch.setattr(bot, "execute_trade", execute)
    with pytest.raises(RuntimeError):
        bot.run_scan_and_trade()
    saved = json.loads(bot.processed_trades_path.read_text())
    assert bot._trade_fingerprint(t1) in saved


# ===========================================================================
# D7 — a politician's SELL only closes that politician's lots
# ===========================================================================

def _lot(pol, qty, ts="2026-10-01T15:00:00"):
    return {"symbol": "HD", "side": "buy", "qty": qty, "entry_price": 400.0,
            "status": "open", "politician": pol, "timestamp": ts, "order_status": "filled",
            "filled_qty": qty}


def test_d7_attributable_qty_is_per_politician():
    log = [_lot("David Taylor", 10), _lot("Kevin Hern", 4),
           {**_lot("Kevin Hern", 6), "status": "closed"},
           {**_lot("BENCHMARK_SLEEVE", 50)},
           {**_lot("Kevin Hern", 3), "order_status": "canceled", "filled_qty": 0}]
    assert pb.politician_open_lot_qty(log, "HD", "Kevin Hern") == 4
    assert pb.politician_open_lot_qty(log, "HD", "David Taylor") == 10
    assert pb.politician_open_lot_qty(log, "HD", "Nancy Pelosi") == 0


def test_d7_hern_sell_cannot_close_taylor_lot(tmp_path, monkeypatch):
    alpaca = StubAlpaca(positions=[{"symbol": "HD", "qty": "10"}])
    bot = _bot(tmp_path, monkeypatch, alpaca=alpaca, trade_log=[_lot("David Taylor", 10)])
    assert bot._execute_sell(_trade("Kevin Hern", "HD", "SELL"), "HD") is None
    assert alpaca.orders == []
    assert bot.risk.trade_log[0]["status"] == "open"
    assert bot._is_sell_candidate(_trade("Kevin Hern", "HD", "SELL")) is False


def test_d7_own_sell_closes_only_own_lots(tmp_path, monkeypatch):
    alpaca = StubAlpaca(positions=[{"symbol": "HD", "qty": "14"}])
    bot = _bot(tmp_path, monkeypatch, alpaca=alpaca,
               trade_log=[_lot("David Taylor", 10, "2026-09-01T15:00:00"),
                          _lot("Kevin Hern", 4, "2026-10-01T15:00:00")])
    monkeypatch.setattr(pb, "confirm_fill", lambda c, oid: ("filled", 2, 99.0))
    rec = bot._execute_sell(_trade("Kevin Hern", "HD", "SELL"), "HD")
    assert rec is not None and alpaca.orders[0]["qty"] == 2          # half of Hern's 4
    assert alpaca.orders[0]["client_order_id"] == \
        pb.exit_client_order_id("cs", "HD", politician="Kevin Hern")
    taylor = [t for t in bot.risk.trade_log if t.get("politician") == "David Taylor"]
    assert all(t["status"] == "open" and t["qty"] == 10 for t in taylor)
    hern_closed = [t for t in bot.risk.trade_log
                   if t.get("politician") == "Kevin Hern" and t.get("status") == "closed"]
    assert sum(t["qty"] for t in hern_closed) == 2


# ===========================================================================
# D9 — House filings are marked seen only after processing
# ===========================================================================

def _fd_zip(doc):
    import io
    import zipfile
    xml = (f"<FinancialDisclosure><Member><Last>Taylor</Last><First>David</First>"
           f"<FilingType>P</FilingType><FilingDate>{_recent(3)}</FilingDate>"
           f"<DocID>{doc}</DocID></Member></FinancialDisclosure>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("2026FD.xml", xml)
    return buf.getvalue()


def _house_env(tmp_path, monkeypatch, rows_or_exc):
    monkeypatch.setattr(house_fd_feed, "SEEN_PATH", tmp_path / "house_fd_seen.json")
    monkeypatch.setattr(house_fd_feed.time, "sleep", lambda s: None)

    def parse(pdf):
        if isinstance(rows_or_exc, Exception):
            raise rows_or_exc
        return rows_or_exc, 1000
    monkeypatch.setattr(house_fd_feed, "parse_pdf_bytes", parse)
    blob = _fd_zip("D100")
    return lambda url: blob if url.endswith(".zip") else b"%PDF"


ROW = {"code": "P", "ticker_paren": "AMD", "asset_name": "Advanced Micro Devices",
       "asset_code": "ST", "txn_date": _recent(5), "size_bucket": "1K–15K"}


def test_d9_filing_with_trades_is_pending_not_seen(tmp_path, monkeypatch):
    fetch = _house_env(tmp_path, monkeypatch, [ROW])
    pending, status = set(), {}
    trades = house_fd_feed.fetch_tracked_ptr_trades(
        ["David Taylor"], fetch_bytes=fetch, pending=pending, status=status)
    assert [t["_doc_id"] for t in trades] == ["D100"] and pending == {"D100"}
    assert status["index_ok"] is True
    assert "D100" not in house_fd_feed._load_seen()
    house_fd_feed.mark_docs_seen(pending)
    assert "D100" in house_fd_feed._load_seen()


def test_d9_parse_failure_is_retried_then_given_up(tmp_path, monkeypatch):
    fetch = _house_env(tmp_path, monkeypatch, ValueError("corrupt PDF"))
    for attempt in range(1, house_fd_feed.MAX_PARSE_ATTEMPTS + 1):
        house_fd_feed.fetch_tracked_ptr_trades(["David Taylor"], fetch_bytes=fetch)
        seen = house_fd_feed._load_seen()
        if attempt < house_fd_feed.MAX_PARSE_ATTEMPTS:
            assert "D100" not in seen, "a parse failure must be retried, not marked seen"
    assert "D100" in house_fd_feed._load_seen()


def test_d9_index_outage_reports_not_ok(tmp_path, monkeypatch):
    _house_env(tmp_path, monkeypatch, [ROW])
    status = {}
    assert house_fd_feed.fetch_tracked_ptr_trades(
        ["David Taylor"], fetch_bytes=lambda url: None, status=status) == []
    assert status["index_ok"] is False


# ===========================================================================
# D10 — market closed: disclosures are NOT marked processed
# ===========================================================================

def test_d10_closed_market_leaves_disclosures_unprocessed(tmp_path, monkeypatch):
    bot = _scan_harness(tmp_path, monkeypatch, is_open=False)
    called = []
    monkeypatch.setattr(bot, "scan_politician_trades",
                        lambda: called.append(1) or [_trade("David Taylor", "AMD")])
    bot.run_scan_and_trade()
    assert bot.processed_trades == set()
    assert not bot.processed_trades_path.exists()


# ===========================================================================
# D11 / D12 — P3 day-start equity + ET session date
# ===========================================================================

def test_d11_day_start_is_anchored_once_per_session():
    import event_driven_bot as edb
    state = {}
    ds, changed = edb.resolve_day_start_equity(state, 100_000, "2026-10-23")
    assert (ds, changed) == (100_000.0, True) and state["day_start_date"] == "2026-10-23"
    # a later (bogus) last_equity read cannot move the session reference
    ds, changed = edb.resolve_day_start_equity(state, 140_000, "2026-10-23")
    assert (ds, changed) == (100_000.0, False)
    ds, changed = edb.resolve_day_start_equity(state, 101_000, "2026-10-26")
    assert (ds, changed) == (101_000.0, True)


def test_d11_monitor_kill_switch_uses_day_start_not_last_equity(tmp_path, monkeypatch):
    import event_driven_bot as edb
    monkeypatch.setattr(edb, "DATA_DIR", tmp_path)
    monkeypatch.setattr(edb, "CONFIG_DIR", tmp_path)
    (tmp_path / "risk_limits.json").write_text(json.dumps(
        {"kill_switch_daily_loss_pct": 2.5, "kill_switch_halt_hours": 24}))
    (tmp_path / "bot_state.json").write_text(json.dumps(
        {"day_start_equity": 97_500, "day_start_date": edb.session_date_et(), "halted": False}))
    monkeypatch.setattr(edb, "_enforce_catalyst_decay", lambda *a, **k: set())
    monkeypatch.setattr(edb, "_rearm_protective_stops", lambda *a, **k: None)
    monkeypatch.setattr(edb, "_sync_state", lambda a: None)
    import shared.order_hygiene as oh
    monkeypatch.setattr(oh, "enforce_exit_hygiene", lambda *a, **k: None)

    class A:
        liquidated = False

        def is_market_open(self):
            return True

        def get_account(self):          # last_equity says -3%; the session says -0.5%
            return {"equity": "97000", "last_equity": "100000", "cash": "97000"}

        def get_positions(self):
            return []

        def cancel_all_orders(self):
            A.liquidated = True

        def close_all_positions(self):
            A.liquidated = True

    edb.run_intraday_monitor(A())
    assert A.liquidated is False
    assert json.loads((tmp_path / "bot_state.json").read_text())["halted"] is False


def test_d12_session_date_is_new_york():
    import event_driven_bot as edb
    # 01:30 UTC Oct-23 is 21:30 EDT Oct-22 — the journal belongs to Oct-22.
    assert edb.session_date_et(datetime(2026, 10, 23, 1, 30, tzinfo=timezone.utc)) == "2026-10-22"
    assert edb.session_date_et(datetime(2026, 10, 22, 20, 20, tzinfo=timezone.utc)) == "2026-10-22"


# ===========================================================================
# D4 — heartbeat: >= semantics, ET session date, scan-only P2 freshness
# ===========================================================================

def test_d4_newer_activity_is_not_stale():
    alert, _ = heartbeat.assess("2026-10-22", {
        "P1 Self Improving Brain": "2026-10-23",   # ran again after the verified session
        "P2 Capitol Shadow": "2026-10-22",
        "P3 Cautious Sniper": "2026-10-23"})
    assert alert is False
    alert, summary = heartbeat.assess("2026-10-22", {"P2 Capitol Shadow": "2026-10-21"})
    assert alert is True and "P2 Capitol Shadow" in summary


def test_d4_p2_freshness_comes_from_scan_only_artifact():
    path, _field = heartbeat.FRESHNESS_SOURCES["P2 Capitol Shadow"]
    assert path.endswith("strategy_conformance.json")


def test_d4_reference_session_is_dst_correct():
    utc = timezone.utc
    # Winter (EST): 21:30 UTC = 16:30 ET, session not yet complete -> previous day
    assert heartbeat.reference_session_date(datetime(2026, 1, 6, 21, 30, tzinfo=utc)) == "2026-01-05"
    assert heartbeat.reference_session_date(datetime(2026, 1, 6, 22, 30, tzinfo=utc)) == "2026-01-06"
    # ET conversion of state stamps: 01:00 UTC is still the previous ET session
    assert heartbeat._et_date_of("2026-10-23T01:00:00+00:00") == "2026-10-22"
    assert heartbeat._et_date_of("2026-10-22T19:20:28.5") == "2026-10-22"


# ===========================================================================
# D3 — failure watchdog covers cancelled / timed_out, CI and deploy
# ===========================================================================

def test_d3_failure_alert_covers_cancelled_timed_out_and_ci_deploy():
    text = _read("failure-alert.yml")
    for conclusion in ("'failure'", "'cancelled'", "'timed_out'"):
        assert f"conclusion == {conclusion}" in text
    for wf_file in ("ci.yml", "smoke-test.yml"):
        name_line = next(ln for ln in _read(wf_file).splitlines() if ln.startswith("name:"))
        name = name_line.split(":", 1)[1].strip().strip('"')
        assert f'- "{name}"' in text, f"{name} must be watched"


# ===========================================================================
# D1 — Guardian syncs before gating; commit never clobbers newer state
# ===========================================================================

def test_d1_guardian_syncs_to_origin_main_before_any_freshness_gate():
    text = _read("guardian.yml")
    sync = text.index("git reset --hard origin/main")
    assert sync < text.index("id: assess")
    for pid in ("p1", "p2", "p3"):
        step = text.index(f"id: {pid}catch")
        nxt = text.find("- name:", step)
        assert f'guardian_fresh.py" {pid}' in text[step:nxt], f"{pid} must re-check freshness"
    assert "strategy_conformance.json" in text


def _guardian_fresh_script():
    text = _read("guardian.yml")
    start = text.index("cat > \"$RUNNER_TEMP/guardian_fresh.py\" << 'PY'\n") + len(
        "cat > \"$RUNNER_TEMP/guardian_fresh.py\" << 'PY'\n")
    end = text.index("\n          PY\n", start)
    lines = text[start:end].splitlines()
    return "\n".join(ln[10:] if ln.startswith(" " * 10) else ln.strip() for ln in lines) + "\n"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _repo_pair(tmp_path, files):
    """bare origin + one clone at the seeded commit."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    _git(seed, "checkout", "-q", "-b", "main")
    for rel, content in files.items():
        p = seed / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(content, indent=2))
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", "origin", "main")
    return origin, seed


def _clone(tmp_path, origin, name):
    d = tmp_path / name
    _git(tmp_path, "clone", "-q", "-b", "main", str(origin), str(d))
    return d


def _commit_push(repo, rel, content):
    (repo / rel).write_text(json.dumps(content, indent=2))
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "newer")
    _git(repo, "push", "-q", "origin", "main")


def _run_commit_script(repo):
    return subprocess.run(["bash", os.path.join(REPO_ROOT, "scripts", "commit_and_push.sh"),
                           "P2: test", "political-copy-bot/data"],
                          cwd=repo, capture_output=True, text=True)


def _remote_json(origin, tmp_path, rel):
    check = _clone(tmp_path, origin, f"check{len(list(tmp_path.iterdir()))}")
    return json.loads((check / rel).read_text())


TL = "political-copy-bot/data/trade_log.json"
PS = "political-copy-bot/data/portfolio_state.json"


@needs_git
def test_d1_stale_run_merges_instead_of_clobbering_newer_rows(tmp_path):
    origin, _ = _repo_pair(tmp_path, {TL: [{"id": 1}]})
    stale = _clone(tmp_path, origin, "stale")             # checked out BEFORE the newer run
    newer = _clone(tmp_path, origin, "newer")
    _commit_push(newer, TL, [{"id": 1}, {"id": 2, "by": "newer"}])
    (stale / TL).write_text(json.dumps([{"id": 1}, {"id": 3, "by": "stale"}], indent=2))
    r = _run_commit_script(stale)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _remote_json(origin, tmp_path, TL) == [{"id": 1}, {"id": 2, "by": "newer"},
                                                  {"id": 3, "by": "stale"}]


@needs_git
def test_d1_conflicting_rewrite_withholds_and_fails_loudly(tmp_path):
    origin, _ = _repo_pair(tmp_path, {TL: [{"id": 1, "status": "open"}]})
    stale = _clone(tmp_path, origin, "stale")
    newer = _clone(tmp_path, origin, "newer")
    _commit_push(newer, TL, [{"id": 1, "status": "closed", "by": "newer"}])
    (stale / TL).write_text(json.dumps([{"id": 1, "status": "closed", "by": "stale"}]))
    r = _run_commit_script(stale)
    assert r.returncode == 1 and "withheld" in r.stdout
    assert _remote_json(origin, tmp_path, TL) == [{"id": 1, "status": "closed", "by": "newer"}]


@needs_git
def test_d1_older_snapshot_never_overwrites_newer_snapshot(tmp_path):
    origin, _ = _repo_pair(tmp_path, {PS: {"timestamp": "2026-10-23T14:00:00", "equity": 1}})
    stale = _clone(tmp_path, origin, "stale")
    newer = _clone(tmp_path, origin, "newer")
    _commit_push(newer, PS, {"timestamp": "2026-10-23T14:40:00", "equity": 3})
    (stale / PS).write_text(json.dumps({"timestamp": "2026-10-23T14:20:00", "equity": 2}))
    r = _run_commit_script(stale)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _remote_json(origin, tmp_path, PS)["equity"] == 3


@needs_git
def test_d1_untouched_remote_takes_our_file(tmp_path):
    origin, _ = _repo_pair(tmp_path, {TL: [{"id": 1}]})
    run = _clone(tmp_path, origin, "run")
    (run / TL).write_text(json.dumps([{"id": 1}, {"id": 2}]))
    r = _run_commit_script(run)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _remote_json(origin, tmp_path, TL) == [{"id": 1}, {"id": 2}]


@needs_git
def test_d1_back_to_back_dispatch_sees_fresh_p2_on_origin_main(tmp_path):
    """The 2nd Guardian dispatch's working tree is stale, but origin/main
    already carries today's P2 scan artifact -> the gate says FRESH (skip)."""
    from zoneinfo import ZoneInfo
    today_ts = datetime.now(ZoneInfo("America/New_York")).isoformat()
    conf = "political-copy-bot/data/strategy_conformance.json"
    origin, _ = _repo_pair(tmp_path, {conf: {"timestamp": "2026-01-02T15:00:00+00:00"}})
    second = _clone(tmp_path, origin, "second")            # checked out at dispatch time
    first = _clone(tmp_path, origin, "first")
    _commit_push(first, conf, {"timestamp": today_ts})     # first Guardian committed
    script = tmp_path / "guardian_fresh.py"
    script.write_text(_guardian_fresh_script())
    r = subprocess.run([sys.executable, str(script), "p2"], cwd=second,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr          # FRESH -> skip
    r = subprocess.run([sys.executable, str(script), "p1"], cwd=second,
                       capture_output=True, text=True)
    assert r.returncode == 1                               # P1 artifact absent -> STALE


# ── Heartbeat: phantom-halt + stuck-exit visibility (follow-up 2026-10-23) ──────
def _hb():
    import importlib
    import heartbeat
    return importlib.reload(heartbeat)


def test_heartbeat_flags_halt_without_evidence_as_unverified():
    hb = _hb()
    alert, summary = hb.assess_safety_state({"P1 Self Improving Brain": {
        "state": {"halted": True, "halt_reason": "Kill switch: 73.94% drawdown"}, "recon": None}})
    assert alert is True
    assert "UNVERIFIED HALT" in summary and "halt_clear" in summary


def test_heartbeat_evidenced_halt_is_plain_halt_with_age():
    hb = _hb()
    alert, summary = hb.assess_safety_state({"P1 Self Improving Brain": {
        "state": {"halted": True, "halt_reason": "Kill switch: 19.0% drawdown",
                  "halt_set_at": "2026-01-02T15:00:00+00:00", "halt_verified": True,
                  "halt_evidence": {"equity": 81000, "independent_equity": 81010}},
        "recon": None}})
    assert alert is True
    assert "UNVERIFIED" not in summary and "d old" in summary


def test_heartbeat_flags_exits_unsettled_from_prior_session():
    hb = _hb()
    alert, summary = hb.assess_safety_state({"P1 Self Improving Brain": {
        "state": {"halted": False}, "recon": None,
        "pending_exits": [{"symbol": "CAT", "submitted_at": "2020-01-02T15:00:00+00:00"},
                          {"symbol": "C", "submitted_at": "2999-01-01T00:00:00+00:00"}]}})
    assert alert is True and "1 exit order(s)" in summary and summary.rstrip().endswith(": CAT")


def test_heartbeat_clean_book_no_alert():
    hb = _hb()
    alert, _ = hb.assess_safety_state({"P1 Self Improving Brain": {
        "state": {"halted": False}, "recon": None, "pending_exits": []}})
    assert alert is False


def test_heartbeat_partial_legacy_evidence_is_unverified():
    # Codex review on PR #95: a non-empty but partial evidence object (no
    # timestamp / no equity) must not count as verification.
    hb = _hb()
    for ev in ({"independent_equity": 97000}, {"at": "2026-07-07T14:24:00Z"}, {"equity": 26060.51}):
        alert, summary = hb.assess_safety_state({"P1 Self Improving Brain": {
            "state": {"halted": True, "halt_reason": "Kill switch: 73.94% drawdown",
                      "halt_evidence": ev}, "recon": None}})
        assert alert is True and "UNVERIFIED HALT" in summary, ev
    assert hb.halt_evidence_verified({"halt_evidence": {"at": "x", "equity": 1.0}}) is True
    assert hb.halt_evidence_verified({"halt_verified": False,
                                      "halt_evidence": {"at": "x", "equity": 1.0}}) is False
