#!/usr/bin/env python3
"""Official House Clerk disclosure feed — P2's Capitol-Trades fallback.

The Capitol Trades MCP feed has been WAF-blocked from GitHub Actions IPs since
2026-05-29 (audit 2026-07-04, defect D3: "rate-limited after 5 attempts" on
14/14 fetches, every run). This module sources the SAME signal from the
primary source instead: the House Clerk's public financial-disclosure index
(https://disclosures-clerk.house.gov) — one ZIP fetch per scan, no API key,
no rate limit — and parses each new Periodic Transaction Report PDF with the
stdlib-only extractor in ``ptr_pdf_text`` (parity-validated 467/467 docs,
4,932/4,932 rows against the research lane's pdfplumber ground truth).

Output trades are shaped EXACTLY like the MCP feed's so the whole downstream
pipeline (fingerprint dedup, freshness gate, bond/private filters, technical
confirmation, sizing) applies unchanged. Senate members (e.g. Tuberville) are
not in the House index and are simply absent — the MCP feed remains the only
source for them.

Cloud-path pure: requests + stdlib only.
"""
import io
import json
import logging
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

import requests

from ptr_pdf_text import looks_like_bond_or_private, parse_pdf_bytes

log = logging.getLogger("politician_bot")

BASE_DIR = Path(__file__).resolve().parent.parent
SEEN_PATH = BASE_DIR / "data" / "house_fd_seen.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
INDEX_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
PDF_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc}.pdf"


def _name_keys(politicians):
    """{(last_lower, first_prefix_lower): full_name} from config names."""
    keys = {}
    for name in politicians or []:
        parts = str(name).split()
        if len(parts) >= 2:
            keys[(parts[-1].lower(), parts[0].lower())] = name
    return keys


def _match_member(name_keys, last, first):
    last = (last or "").strip().lower()
    first = (first or "").strip().lower()
    for (kl, kf), full in name_keys.items():
        if last == kl and first.startswith(kf):
            return full
    return None


def fetch_index(year, fetch_bytes):
    """PTR filings [{member_last, member_first, filing_date, doc_id}] for a year."""
    blob = fetch_bytes(INDEX_URL.format(year=year))
    if not blob:
        return []
    z = zipfile.ZipFile(io.BytesIO(blob))
    xml_name = next((n for n in z.namelist() if n.lower().endswith(".xml")), None)
    if not xml_name:
        return []
    xml_text = z.read(xml_name).decode("utf-8", "ignore")
    # XXE / billion-laughs hardening without leaving the requests-only runtime
    # (defusedxml is banned from the cloud path): the official index carries no
    # DTD, so any entity/doctype declaration is hostile — refuse to parse it.
    lowered = xml_text[:4096].lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        log.error("house_fd: index XML contains DTD/entity declarations — refusing to parse")
        return []
    root = ET.fromstring(xml_text)
    filings = []
    for m in root.findall("Member"):
        if (m.findtext("FilingType") or "").strip() != "P":
            continue
        filings.append({
            "last": (m.findtext("Last") or "").strip(),
            "first": (m.findtext("First") or "").strip(),
            "filing_date": (m.findtext("FilingDate") or "").strip(),
            "doc_id": (m.findtext("DocID") or "").strip(),
            "year": year,
        })
    return filings


def _parse_filing_date(s):
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except (TypeError, ValueError):
            continue
    return None


def rows_to_trades(rows, politician, filing_date):
    """PTR rows -> MCP-shaped trades (the schema the whole P2 pipeline speaks).

    Conservative by design: only P (buy) / S (sell) rows with an EXPLICIT
    ticker survive; bonds/private assets are dropped with the same filter the
    5y backtest used. No name->ticker guessing on the live path.
    """
    trades = []
    for r in rows:
        code = (r.get("code") or "").upper()
        if code not in ("P", "S"):
            continue
        ticker = r.get("ticker_paren")
        if not ticker:
            continue
        if looks_like_bond_or_private(r.get("asset_name") or "", r.get("asset_code")):
            continue
        trades.append({
            "politician": {"name": politician},
            "issuer": {"name": r.get("asset_name") or "", "ticker": ticker.upper()},
            "transaction": {"type": "BUY" if code == "P" else "SELL",
                            "size": r.get("size_bucket") or ""},
            "dates": {"trade": r.get("txn_date") or "",
                      "disclosed": filing_date},
            "_feed": "house_fd",
        })
    return trades


# A PTR whose PDF downloads but will not parse is retried on later scans, at
# most this many times, before it is given up on (logged loudly) so one corrupt
# filing can never consume the per-scan PDF budget forever (audit 2026-10-23 D9).
MAX_PARSE_ATTEMPTS = 3


def _load_cache():
    """{"doc_ids": set, "parse_failures": {doc_id: n}} from the seen-cache."""
    try:
        raw = json.loads(SEEN_PATH.read_text())
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    failures = raw.get("parse_failures")
    return {"doc_ids": set(raw.get("doc_ids", []) or []),
            "parse_failures": dict(failures) if isinstance(failures, dict) else {}}


def _save_cache(cache):
    try:
        SEEN_PATH.write_text(json.dumps(
            {"updated": datetime.now().isoformat(),
             "doc_ids": sorted(cache["doc_ids"])[-2000:],
             "parse_failures": cache.get("parse_failures", {})}, indent=1))
    except OSError as e:
        log.warning(f"house_fd: could not persist seen-cache: {e}")


def _load_seen():
    return _load_cache()["doc_ids"]


def mark_docs_seen(doc_ids):
    """Mark filings as fully processed in the persisted seen-cache.

    Called by the bot ONLY after every trade from these filings has gone
    through the copy pipeline (executed, rejected by a gate, or recorded as
    processed) in a market-open scan. Marking a filing seen at download time
    (the old behaviour) lost its trades whenever the run then crashed, timed
    out, or ran with the market closed (audit 2026-10-23 D9).
    """
    doc_ids = {d for d in (doc_ids or []) if d}
    if not doc_ids:
        return
    cache = _load_cache()
    cache["doc_ids"] |= doc_ids
    for d in doc_ids:
        cache["parse_failures"].pop(d, None)
    _save_cache(cache)


def fetch_tracked_ptr_trades(politicians, max_age_days=45, fetch_bytes=None,
                             now=None, seen=None, max_pdfs=12, pending=None,
                             status=None):
    """MCP-shaped trades for tracked House members from the official index.

    * one index ZIP per relevant year (2 near a year boundary),
    * only NEW filings (doc_id not in the persisted seen-cache) filed within
      ``max_age_days`` are downloaded — bounded by ``max_pdfs`` per scan so a
      backlog can never stampede the House server (politeness pause between
      PDFs),
    * fail-open: any network/parse error returns what was gathered so far.

    Seen-cache semantics (D9): a filing is marked seen here only when there is
    nothing left to act on — it is older than the copy window, or it parsed
    cleanly to ZERO tradeable rows, or it failed to parse ``MAX_PARSE_ATTEMPTS``
    times. A filing that yielded trades is NOT marked seen; its doc_id is added
    to ``pending`` (and stamped on each trade as ``_doc_id``) and the caller
    marks it via ``mark_docs_seen`` once the trades were processed. Re-fetching
    a pending filing is harmless: the bot's fingerprint dedup drops trades it
    already processed. A download or parse failure is retried next scan.

    ``status`` (optional dict) receives ``index_ok`` — True only if at least
    one year's index was actually downloaded. The feed is fail-open, so an
    empty result alone cannot distinguish "no new filings" from "House server
    unreachable"; the bot uses this for its feed-reachable conformance check.

    ``fetch_bytes(url) -> bytes|None`` is injectable for tests.
    """
    now = now or datetime.now()
    if status is None:
        status = {}
    status["index_ok"] = False
    if fetch_bytes is None:
        sess = requests.Session()
        sess.headers.update({"User-Agent": UA})

        def fetch_bytes(url):
            try:
                resp = sess.get(url, timeout=60)
                return resp.content if resp.status_code == 200 else None
            except requests.RequestException as e:
                log.warning(f"house_fd: fetch failed {url}: {e}")
                return None

    raw_fetch = fetch_bytes

    def fetch_bytes(url):
        blob = raw_fetch(url)
        if blob and url.endswith(".zip"):
            status["index_ok"] = True
        return blob

    name_keys = _name_keys(politicians)
    years = {now.year}
    if now.month == 1:
        years.add(now.year - 1)

    persistent = seen is None
    cache = _load_cache() if persistent else {"doc_ids": set(seen), "parse_failures": {}}
    seen = cache["doc_ids"]
    failures = cache["parse_failures"]
    if pending is None:
        pending = set()
    trades = []
    fetched = 0
    for year in sorted(years):
        try:
            filings = fetch_index(year, fetch_bytes)
        except Exception as e:
            log.warning(f"house_fd: index fetch failed for {year}: {e}")
            continue
        for f in filings:
            member = _match_member(name_keys, f["last"], f["first"])
            if not member or not f["doc_id"] or f["doc_id"] in seen:
                continue
            fd = _parse_filing_date(f["filing_date"])
            if fd is None or (now - fd).days > max_age_days:
                # older than the copy window -> mark seen, never fetch
                seen.add(f["doc_id"])
                continue
            if fetched >= max_pdfs:
                log.info("house_fd: per-scan PDF budget reached; rest next scan")
                break
            pdf = fetch_bytes(PDF_URL.format(year=f["year"], doc=f["doc_id"]))
            fetched += 1
            time.sleep(0.5)                       # be polite to the House server
            if not pdf:
                continue                          # retry next scan (not seen)
            try:
                rows, _ = parse_pdf_bytes(pdf)
            except Exception as e:
                n = int(failures.get(f["doc_id"], 0)) + 1
                failures[f["doc_id"]] = n
                if n >= MAX_PARSE_ATTEMPTS:
                    log.error(f"::error::house_fd: doc {f['doc_id']} ({member}) failed to "
                              f"parse {n} times ({e}) — giving up; review it manually")
                    seen.add(f["doc_id"])
                    failures.pop(f["doc_id"], None)
                else:
                    log.warning(f"house_fd: parse failed doc {f['doc_id']} "
                                f"(attempt {n}/{MAX_PARSE_ATTEMPTS}): {e} — retrying next scan")
                continue
            failures.pop(f["doc_id"], None)
            new = rows_to_trades(rows, member, f["filing_date"])
            if not new:
                seen.add(f["doc_id"])             # nothing to act on -> processed
                continue
            log.info(f"house_fd: {member} filing {f['doc_id']} "
                     f"({f['filing_date']}) -> {len(new)} tradeable row(s)")
            for t in new:
                t["_doc_id"] = f["doc_id"]
            pending.add(f["doc_id"])
            trades.extend(new)
    if persistent:
        _save_cache(cache)
    return trades
