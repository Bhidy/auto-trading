"""P2 official House-Clerk disclosure fallback (audit 2026-07-04, defect D3).

The Capitol Trades MCP feed was WAF-blocked from GitHub Actions IPs for 5+
weeks (14/14 fetches rate-limited every run) — P2's copy engine was dead while
runs stayed green. The fallback sources the SAME signal from the primary
source: the House Clerk index (one ZIP per scan) + a stdlib-only PTR-PDF
parser, parity-validated 467/467 docs / 4,932/4,932 rows against the research
lane's pdfplumber ground truth. These tests pin:
  * the full extractor chain (RC4 decrypt -> CTM text layout -> ToUnicode
    fonts -> row regex) on a real committed PTR fixture,
  * the STOCK-Act amount-band -> config-bucket mapping,
  * MCP-shape conversion (only explicit-ticker equity rows survive),
  * the index fetch: member matching, seen-cache, staleness, PDF budget,
    and the DTD/XXE refusal guard.
"""
import io
import os
import sys
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P2_SCRIPTS = os.path.join(REPO_ROOT, "political-copy-bot", "scripts")
for _p in (REPO_ROOT, P2_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from house_fd_feed import (fetch_index, fetch_tracked_ptr_trades,  # noqa: E402
                           rows_to_trades)
from ptr_pdf_text import parse_pdf_bytes, size_bucket_from_low  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "house_ptr_20013901.pdf")


# --------------------------------------------------------------------------
# Extractor parity on a real (RC4-encrypted, CID-font) House PTR
# --------------------------------------------------------------------------

def test_fixture_pdf_parses_to_ground_truth_rows():
    rows, nchars = parse_pdf_bytes(open(FIXTURE, "rb").read())
    keys = [(r["code"], r["ticker_paren"], r["txn_date"]) for r in rows]
    # pdfplumber ground truth for doc 20013901 (data/p2_ptr_parsed.json)
    assert keys == [
        ("E", "CBS", "12/05/2019"),
        ("P", None, "12/23/2019"),
        ("S", None, "12/23/2019"),
        ("E", None, "12/05/2019"),
    ]
    assert rows[0]["asset_name"] == "CBS Corporation Class B"
    assert rows[1]["asset_code"] == "GS"                 # treasury -> filtered later
    assert rows[0]["size_bucket"] == "1K–15K"
    assert nchars > 300


# --------------------------------------------------------------------------
# Amount-band mapping
# --------------------------------------------------------------------------

def test_size_bucket_from_low_bands():
    assert size_bucket_from_low("1,001") == "1K–15K"
    assert size_bucket_from_low("15,001") == "15K–50K"
    assert size_bucket_from_low("50,001") == "50K–100K"
    assert size_bucket_from_low("250,001") == "250K–500K"
    assert size_bucket_from_low("1,000,001") == "1M–5M"
    assert size_bucket_from_low("junk") is None


# --------------------------------------------------------------------------
# Row -> MCP-shaped trade conversion
# --------------------------------------------------------------------------

def test_rows_to_trades_is_conservative_and_mcp_shaped():
    rows = [
        {"code": "P", "ticker_paren": "AMD", "asset_name": "Advanced Micro Devices",
         "asset_code": "ST", "txn_date": "05/05/2026", "size_bucket": "1K–15K"},
        {"code": "S", "ticker_paren": "ABBV", "asset_name": "AbbVie Inc",
         "asset_code": "ST", "txn_date": "05/05/2026", "size_bucket": "1K–15K"},
        # no explicit ticker -> dropped (no name->ticker guessing live)
        {"code": "P", "ticker_paren": None, "asset_name": "Northwest Natural",
         "asset_code": None, "txn_date": "05/05/2026", "size_bucket": "1K–15K"},
        # treasury -> dropped
        {"code": "P", "ticker_paren": "X", "asset_name": "uS TREaSuR 2.375% 05/29",
         "asset_code": "GS", "txn_date": "05/05/2026", "size_bucket": "50K–100K"},
        # exchange (E) rows are not copyable transactions
        {"code": "E", "ticker_paren": "CBS", "asset_name": "CBS Corp",
         "asset_code": "ST", "txn_date": "05/05/2026", "size_bucket": "1K–15K"},
    ]
    trades = rows_to_trades(rows, "Josh Gottheimer", "6/3/2026")
    assert [t["issuer"]["ticker"] for t in trades] == ["AMD", "ABBV"]
    buy = trades[0]
    assert buy["transaction"] == {"type": "BUY", "size": "1K–15K"}
    assert buy["politician"] == {"name": "Josh Gottheimer"}
    assert buy["dates"] == {"trade": "05/05/2026", "disclosed": "6/3/2026"}
    assert buy["_feed"] == "house_fd"
    assert trades[1]["transaction"]["type"] == "SELL"


# --------------------------------------------------------------------------
# Index fetch: matching, staleness, seen-cache, budget, DTD guard
# --------------------------------------------------------------------------

def _fd_zip(members):
    rows = "".join(
        f"<Member><Prefix/><Last>{m['last']}</Last><First>{m['first']}</First>"
        f"<Suffix/><FilingType>{m.get('type', 'P')}</FilingType><StateDst>XX00</StateDst>"
        f"<Year>2026</Year><FilingDate>{m['date']}</FilingDate>"
        f"<DocID>{m['doc']}</DocID></Member>" for m in members)
    xml = f"<FinancialDisclosure>{rows}</FinancialDisclosure>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("2026FD.xml", xml)
    return buf.getvalue()


def test_fetch_tracked_ptr_trades_end_to_end_with_fake_index():
    from datetime import datetime
    now = datetime(2026, 7, 4)
    fixture_pdf = open(FIXTURE, "rb").read()
    zip_blob = _fd_zip([
        {"last": "Gottheimer", "first": "Josh", "date": "6/25/2026", "doc": "D1"},
        # Mark Green must NOT match Marjorie Taylor Greene (and vice versa)
        {"last": "Greene", "first": "Marjorie", "date": "6/25/2026", "doc": "D2"},
        # too old -> marked seen, never fetched
        {"last": "Gottheimer", "first": "Josh", "date": "1/05/2026", "doc": "D3"},
        # already seen -> skipped
        {"last": "Gottheimer", "first": "Josh", "date": "6/25/2026", "doc": "D4"},
        # untracked member -> ignored
        {"last": "Nobody", "first": "Someone", "date": "6/25/2026", "doc": "D5"},
        # annual report (type F) -> ignored
        {"last": "Gottheimer", "first": "Josh", "date": "6/25/2026",
         "doc": "D6", "type": "F"},
    ])
    fetched_urls = []

    def fake_fetch(url):
        fetched_urls.append(url)
        return zip_blob if url.endswith(".zip") else fixture_pdf

    trades = fetch_tracked_ptr_trades(
        ["Josh Gottheimer", "Mark Green"], max_age_days=45,
        fetch_bytes=fake_fetch, now=now, seen={"D4"})
    pdf_urls = [u for u in fetched_urls if u.endswith(".pdf")]
    assert len(pdf_urls) == 1 and "D1.pdf" in pdf_urls[0]   # only the fresh, unseen, tracked PTR
    # fixture yields 1 explicit-ticker row, but code E -> not copyable; the
    # P/S rows are bond/no-ticker -> conservative empty result is CORRECT here
    assert all(t["politician"]["name"] == "Josh Gottheimer" for t in trades)


def test_fetch_index_refuses_dtd():
    xml = b'<!DOCTYPE foo [<!ENTITY a "b">]><FinancialDisclosure/>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("2026FD.xml", xml.decode())
    blob = buf.getvalue()
    assert fetch_index(2026, lambda url: blob) == []


def test_fetch_index_parses_members():
    blob = _fd_zip([{"last": "Taylor", "first": "David", "date": "5/28/2026",
                     "doc": "20034650"}])
    filings = fetch_index(2026, lambda url: blob)
    assert filings == [{"last": "Taylor", "first": "David",
                        "filing_date": "5/28/2026", "doc_id": "20034650",
                        "year": 2026}]


def test_trade_dates_parse_with_bot_freshness_gate():
    """The fallback's date formats must be readable by the bot's _parse_date."""
    from politician_bot import disclosure_age_days
    from datetime import datetime
    trade = {"dates": {"trade": "05/05/2026", "disclosed": "6/3/2026"}}
    age = disclosure_age_days(trade, now=datetime(2026, 7, 4))
    assert age == 60
