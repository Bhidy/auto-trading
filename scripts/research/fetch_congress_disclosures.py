#!/usr/bin/env python3
"""Source point-in-time US House disclosure FILINGS for the P2 (Capitol Shadow)
backtest — STAGE 1: the filing index (DocID + FilingDate per Periodic Transaction
Report) for the members P2 tracks, across all available years.

This is OFFLINE RESEARCH (T2) — it never runs on the cloud trading path. It only
establishes WHAT data exists and HOW MUCH (the sample size that decides whether a
faithful P2 backtest is meaningful). The transaction-level PDF parse + name->ticker
mapping is a later stage; see memory/reference_p2_disclosure_data.md.

Source: https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{YEAR}FD.zip
        -> {YEAR}FD.xml  (FilingType 'P' = Periodic Transaction Report = trades)
Output: data/p2_disclosure_index.json
"""
import io
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "p2_disclosure_index.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# P2's tracked HOUSE members as (last, first-prefix) so common surnames
# (Green/Taylor) don't false-match other representatives. Tuberville is SENATE
# (separate eFD source) and is intentionally excluded here.
TRACKED = [
    ("McCaul", "Michael"), ("Pelosi", "Nancy"), ("Greene", "Marjorie"),
    ("Crenshaw", "Dan"), ("Gottheimer", "Josh"), ("Khanna", "Ro"),
    ("Curtis", "John"), ("Hern", "Kevin"), ("Green", "Mark"),
    ("Fallon", "Pat"), ("Blumenauer", "Earl"), ("Taylor", "David"),
]
YEARS = range(2020, 2027)


def _match(last, first):
    last = (last or "").strip()
    first = (first or "").strip()
    for tl, tf in TRACKED:
        if last.lower() == tl.lower() and first.lower().startswith(tf.lower()):
            return f"{first} {last}"
    return None


def fetch_year(year):
    url = f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
    if r.status_code != 200:
        print(f"  {year}: HTTP {r.status_code} — skipped")
        return []
    z = zipfile.ZipFile(io.BytesIO(r.content))
    xml_name = next((n for n in z.namelist() if n.lower().endswith(".xml")), None)
    if not xml_name:
        print(f"  {year}: no XML in zip")
        return []
    root = ET.fromstring(z.read(xml_name).decode("utf-8", "ignore"))
    rows = []
    for m in root.findall("Member"):
        if (m.findtext("FilingType") or "").strip() != "P":
            continue  # P = Periodic Transaction Report (the trades)
        who = _match(m.findtext("Last"), m.findtext("First"))
        if not who:
            continue
        doc = (m.findtext("DocID") or "").strip()
        rows.append({
            "member": who,
            "filing_date": (m.findtext("FilingDate") or "").strip(),  # the DISCLOSURE date (point-in-time)
            "year": year,
            "doc_id": doc,
            "pdf_url": f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc}.pdf",
        })
    print(f"  {year}: {len(rows)} PTR filings for tracked members")
    return rows


def main():
    print("Sourcing House PTR filing index for P2 tracked members...")
    all_rows = []
    for y in YEARS:
        try:
            all_rows.extend(fetch_year(y))
        except Exception as e:  # noqa: BLE001 - research script, log and continue
            print(f"  {y}: error {e}")
    OUT.write_text(json.dumps(all_rows, indent=2))

    # Summary — the sample size that decides backtest viability.
    by_member = {}
    for r in all_rows:
        by_member[r["member"]] = by_member.get(r["member"], 0) + 1
    print("\n=== PTR filings per tracked member (all years) ===")
    for who in sorted(by_member, key=lambda k: -by_member[k]):
        print(f"  {by_member[who]:>4}  {who}")
    print(f"\nTOTAL PTR filings: {len(all_rows)} across {len(by_member)} members "
          f"-> {OUT.relative_to(REPO)}")
    print("NOTE: each filing contains 1..N transactions; equity-BUY count (after "
          "dropping treasuries/munis/MMF) is established in the PDF-parse stage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
