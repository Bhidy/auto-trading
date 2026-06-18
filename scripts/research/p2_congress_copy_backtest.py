#!/usr/bin/env python3
"""P2 "Capitol Shadow" — the FIRST real, no-look-ahead backtest of the congress
copy-trade thesis: does copying disclosed congressional BUYs at the REAL
disclosure lag (i.e. entering only AFTER the public filing date) produce edge?

OFFLINE RESEARCH (T2). Never runs on the cloud trading path. Heavier libs
(pdfplumber, requests) allowed here; the trading path stays requests-only.

Pipeline
--------
STAGE 1 (already done): data/p2_disclosure_index.json = 631 PTR filings for P2's
  tracked House members, 2020-2026, each with member, filing_date (the DISCLOSURE
  date, point-in-time), doc_id, pdf_url.

STAGE 2 (this script): download + pdfplumber-parse each PTR PDF -> transaction
  rows (asset name, P/S/E code, transaction date, amount bracket). Map free-text
  asset names -> tickers (parenthetical ticker first, then a curated name map vs.
  the price universe). DROP non-equities (treasuries, muni/agency bonds, corporate
  bonds [CS]/[GS], money-market, private LPs/funds) — mirroring P2's live filters.
  Keep equity PURCHASES. PDFs + parsed rows are cached to avoid refetching.

STAGE 3 (this script): NO-LOOK-AHEAD backtest. For each equity BUY, the signal is
  KNOWN at close of the FILING date t (NOT the transaction date — that is private
  until disclosed). Enter at the OPEN of t+1 (next trading day). Friction >= 5 bps
  EACH side (reuses scripts/backtest/friction.load_friction, floored at 5/5).
  Test fixed hold horizons (21/63/126 trading days) AND P2's live exit rules
  (8% trailing stop / 25% take-profit / 180d max hold). Each trade's return is
  measured AND its alpha vs SPY over the identical window. Results split OOS by
  filing year. Disclosure-lag decay is quantified by bucketing the gap between the
  politician's transaction date and the filing date.

Honesty: real numbers only. Parse success rate, ticker-mapping coverage, and the
#BUY events are reported exactly as observed. If price coverage or sample is thin,
that is stated, not smoothed over.
"""
import io
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.backtest import metrics as M  # noqa: E402
from scripts.backtest.friction import load_friction  # noqa: E402

try:
    import pdfplumber  # noqa: E402
except ImportError:
    print("pdfplumber is required for STAGE 2 (offline research lane).")
    raise

INDEX = REPO / "data" / "p2_disclosure_index.json"
PDF_CACHE = REPO / "data" / "p2_ptr_cache"
PARSE_CACHE = REPO / "data" / "p2_ptr_parsed.json"
PRICE_DIR = REPO / "data" / "deep_wide5"
EXTRA_PRICE = REPO / "data" / "p2_extra_bars.json"
PORTFOLIOS = REPO / "config" / "portfolios.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ---------------------------------------------------------------------------
# STAGE 2 — PTR PDF parse
# ---------------------------------------------------------------------------

# Anchor on the structural backbone of every transaction line:
#   <asset text ...> [P|S|E] <txn MM/DD/YYYY> <notif MM/DD/YYYY> $<amount>
# (the asset-type code [ST]/[GS]/[CS] may sit inside or AFTER the asset text, and
#  may wrap to the next physical line, so we do not rely on it for anchoring).
ROW_RE = re.compile(
    r"(?P<asset>.+?)\s\[?(?P<code>[PSE])\]?\s+"
    r"(?P<txdate>\d{1,2}/\d{1,2}/\d{4})\s+"
    r"(?P<notif>\d{1,2}/\d{1,2}/\d{4})\s+"
    r"\$[\d,]+"
)
TICKER_RE = re.compile(r"\(([A-Z][A-Z\.]{0,5})\)")
# Asset-type code if present anywhere on the (possibly multi-line) asset blob.
ASSETCODE_RE = re.compile(r"\[([A-Za-z]{2})\]")

# Non-equity asset classes to DROP (mirrors P2's live copy_filters intent).
BOND_CODES = {"GS", "CS", "MF", "MA", "HN", "RP", "AB", "OL", "BA"}  # govt/corp/muni/MF/etc
BOND_KW = ("TREAS", "T-BILL", "T BILL", "TREASURY BILL", "MUNI", "MUNICIPAL",
           "SCHOOL DIST", "WATER DIST", "% DUE", "%/", "% /", "NOTE DUE",
           "BOND", " UST ", "UST BOND", "AGENCY", "CERTIFICATE OF DEPOSIT",
           "MONEY MARKET", "100% US TREAS", "FANNIE MAE", "FREDDIE MAC")
PRIVATE_KW = (" LLC", " L.L.C", " LP", " L.P", " LTD", "TRUST", " FUND",
              "CITY OF", "COUNTY", "STATE OF", "AUTHORITY", " DISTRICT",
              "PARTNERS", "HOLDINGS LLC")


def looks_like_bond_or_private(asset, code):
    up = asset.upper()
    if code and code.upper() in BOND_CODES:
        return True
    if any(k in up for k in BOND_KW):
        return True
    # A coupon like "2.2%25" / "4.5% 11/33" without a stock ticker -> bond.
    if re.search(r"\d\.\d+\s?%", up):
        return True
    if any(k in up for k in PRIVATE_KW):
        return True
    return False


def clean_asset_name(asset):
    # Strip the owner prefix (SP/JT/DC/self codes) and the asset-type bracket.
    a = re.sub(r"^\s*(SP|JT|DC|S P|J T)\s+", "", asset, flags=re.I)
    a = ASSETCODE_RE.sub("", a)
    a = TICKER_RE.sub("", a)
    a = re.sub(r"\s+", " ", a).strip(" .,-")
    return a


def parse_pdf_bytes(content):
    """Return list of {code, ticker_paren, asset_name, asset_code, txn_date}."""
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        txt = "\n".join((p.extract_text() or "") for p in pdf.pages)
    rows = []
    for line in txt.splitlines():
        m = ROW_RE.search(line)
        if not m:
            continue
        asset = m.group("asset")
        tk = TICKER_RE.search(asset)
        ac = ASSETCODE_RE.search(asset)
        rows.append({
            "code": m.group("code"),
            "ticker_paren": tk.group(1).replace(".", "") if tk else None,
            "asset_name": clean_asset_name(asset),
            "asset_code": ac.group(1).upper() if ac else None,
            "txn_date": m.group("txdate"),
        })
    return rows, len(txt.strip())


def stage2_parse(filings, limit=None):
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    cache = {}
    if PARSE_CACHE.exists():
        cache = json.loads(PARSE_CACHE.read_text())

    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})
    n_ok = n_fail = n_empty = 0
    todo = filings if limit is None else filings[:limit]
    for i, f in enumerate(todo):
        did = f["doc_id"]
        if did in cache:
            continue
        url = f["pdf_url"]
        pdf_path = PDF_CACHE / f"{did}.pdf"
        try:
            if pdf_path.exists():
                content = pdf_path.read_bytes()
            else:
                r = sess.get(url, timeout=60)
                if r.status_code != 200:
                    cache[did] = {"status": "http_%d" % r.status_code, "rows": []}
                    n_fail += 1
                    continue
                content = r.content
                pdf_path.write_bytes(content)
                time.sleep(0.15)  # be polite to the House server
            rows, nchars = parse_pdf_bytes(content)
            status = "ok" if rows else ("empty_text" if nchars < 300 else "no_rows")
            cache[did] = {"status": status, "nchars": nchars, "rows": rows}
            if rows:
                n_ok += 1
            else:
                n_empty += 1
        except Exception as e:  # noqa: BLE001 - research; record and continue
            cache[did] = {"status": "parse_err:%s" % type(e).__name__, "rows": []}
            n_fail += 1
        if (i + 1) % 50 == 0:
            PARSE_CACHE.write_text(json.dumps(cache))
            print("  parsed %d/%d (ok=%d empty=%d fail=%d)" % (i + 1, len(todo), n_ok, n_empty, n_fail))
    PARSE_CACHE.write_text(json.dumps(cache))
    return cache


# ---------------------------------------------------------------------------
# Name -> ticker mapping (curated, vs. the price universe + common congress names)
# ---------------------------------------------------------------------------
# Built from the actual asset names that appear in the parsed PTRs. Only equities
# we can price. Free-text -> ticker. Keyed by a normalized substring.
NAME_MAP = {
    "APPLE": "AAPL", "MICROSOFT": "MSFT", "ALPHABET": "GOOGL", "AMAZON": "AMZN",
    "NVIDIA": "NVDA", "TESLA": "TSLA", "META PLATFORMS": "META", "FACEBOOK": "META",
    "NETFLIX": "NFLX", "ADVANCED MICRO": "AMD", "BROADCOM": "AVGO", "QUALCOMM": "QCOM",
    "INTEL": "INTC", "CISCO": "CSCO", "ORACLE": "ORCL", "SALESFORCE": "CRM",
    "ADOBE": "ADBE", "INTERNATIONAL BUSINESS MACHINES": "IBM", "TEXAS INSTRUMENT": "TXN",
    "MICRON": "MU", "APPLIED MATERIALS": "AMAT", "LAM RESEARCH": "LRCX",
    "PALO ALTO": "PANW", "SERVICENOW": "NOW", "INTUIT": "INTU", "ACCENTURE": "ACN",
    "ANALOG DEVICES": "ADI", "KLA CORP": "KLAC", "CADENCE": "CDNS", "SYNOPSYS": "SNPS",
    "ARISTA": None, "PAYPAL": None, "MASTERCARD": "MA", "VISA INC": "V",
    "JPMORGAN": "JPM", "BANK OF AMERICA": "BAC", "WELLS FARGO": "WFC",
    "GOLDMAN SACHS": "GS", "MORGAN STANLEY": "MS", "CITIGROUP": "C",
    "AMERICAN EXPRESS": "AXP", "BLACKROCK": "BLK", "SCHWAB": "SCHW",
    "S&P GLOBAL": "SPGI", "PROGRESSIVE": "PGR", "CHUBB": "CB", "MARSH": "MMC",
    "JOHNSON & JOHNSON": "JNJ", "ABBVIE": "ABBV", "MERCK": "MRK", "PFIZER": "PFE",
    "ELI LILLY": "LLY", "LILLY": "LLY", "THERMO FISHER": "TMO", "ABBOTT": "ABT",
    "MEDTRONIC": "MDT", "DANAHER": "DHR", "AMGEN": "AMGN", "GILEAD": "GILD",
    "BRISTOL": "BMY", "VERTEX": "VRTX", "REGENERON": "REGN", "INTUITIVE SURGICAL": "ISRG",
    "UNITEDHEALTH": "UNH", "EXXON": "XOM", "CHEVRON": "CVX", "CONOCOPHILLIPS": "COP",
    "EOG RESOURCES": "EOG", "SCHLUMBERGER": "SLB", "MARATHON PETROLEUM": "MPC",
    "PHILLIPS 66": "PSX", "PROCTER": "PG", "COCA-COLA": "KO", "COCA COLA": "KO",
    "PEPSICO": "PEP", "WALMART": "WMT", "COSTCO": "COST", "MCDONALD": "MCD",
    "STARBUCKS": "SBUX", "NIKE": "NKE", "HOME DEPOT": "HD", "LOWE": "LOW",
    "TARGET CORP": "TGT", "TJX": "TJX", "CHIPOTLE": "CMG", "BOOKING": "BKNG",
    "MARRIOTT": "MAR", "O'REILLY": "ORLY", "OREILLY": "ORLY", "MONDELEZ": "MDLZ",
    "COLGATE": "CL", "PHILIP MORRIS": "PM", "ALTRIA": "MO", "ESTEE": None,
    "BOEING": "BA", "CATERPILLAR": "CAT", "DEERE": "DE", "HONEYWELL": "HON",
    "GENERAL ELECTRIC": "GE", "GE AEROSPACE": "GE", "EMERSON": "EMR", "EATON": "ETN",
    "3M COMPANY": "MMM", "3M ": "MMM", "RAYTHEON": "RTX", "RTX CORP": "RTX",
    "LOCKHEED": "LMT", "UNION PACIFIC": "UNP", "UNITED PARCEL": "UPS", "UPS ": "UPS",
    "CINTAS": "CTAS", "WALT DISNEY": "DIS", "DISNEY": "DIS", "COMCAST": "CMCSA",
    "CHARTER": "CHTR", "AT&T": "T", "VERIZON": "VZ", "T-MOBILE": "TMUS",
    "TMOBILE": "TMUS", "NEXTERA": "NEE", "DUKE ENERGY": "DUK", "SOUTHERN CO": "SO",
    "SOUTHERN COMPANY": "SO", "AMERICAN TOWER": "AMT", "PROLOGIS": "PLD",
    "EQUINIX": "EQIX", "LINDE": "LIN", "AIR PRODUCTS": "APD", "SHERWIN": "SHW",
    "SPDR S&P 500": "SPY", "SPDR S&P500": "SPY", "ISHARES RUSSELL 2000": "IWM",
    "INVESCO QQQ": "QQQ", "SPDR DOW": "DIA", "ISHARES 20": "TLT", "GOLD": "GLD",
    "AUTOMATIC DATA": "ADP",
}
NAME_MAP = {k: v for k, v in NAME_MAP.items() if v is not None}


def map_to_ticker(row, priceable):
    """Resolve a parsed transaction row to a priceable ticker, or None.

    1. parenthetical ticker if it is in the price universe;
    2. curated company-name substring match (vs price universe);
    returns None if neither resolves to a ticker we hold prices for.
    """
    tp = row.get("ticker_paren")
    if tp and tp in priceable:
        return tp
    up = (row.get("asset_name") or "").upper()
    for kw, tk in NAME_MAP.items():
        if kw in up and tk in priceable:
            return tk
    return None


# ---------------------------------------------------------------------------
# STAGE 3 — price data + no-look-ahead backtest
# ---------------------------------------------------------------------------

def load_universe_bars():
    """Load deep_wide5 bars -> {ticker: [(date, open, close), ...] sorted asc}."""
    bars = {}
    for fp in sorted(PRICE_DIR.glob("*.json")):
        data = json.loads(fp.read_text())
        for tk, rows in (data.get("bars") or {}).items():
            series = []
            for b in rows:
                d = b["t"][:10]
                series.append((d, float(b["o"]), float(b["c"])))
            series.sort()
            bars[tk] = series
    return bars


def _creds():
    if PORTFOLIOS.exists():
        cfg = json.loads(PORTFOLIOS.read_text())
        p = cfg.get("portfolio_2") or cfg.get("portfolio_1") or {}
        return p.get("api_key"), p.get("api_secret"), p.get("data_url", "https://data.alpaca.markets")
    return (os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY"),
            "https://data.alpaca.markets")


def fetch_extra_bars(tickers, start="2019-06-01"):
    """Fetch daily bars for tickers not in deep_wide5 (cached)."""
    cache = {}
    if EXTRA_PRICE.exists():
        cache = json.loads(EXTRA_PRICE.read_text())
    need = [t for t in tickers if t not in cache]
    if not need:
        return cache
    key, sec, data_url = _creds()
    if not key:
        print("  no Alpaca creds -> cannot fetch extra bars for %d tickers" % len(need))
        return cache
    hdr = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    for t in need:
        try:
            allbars, token = [], None
            for _ in range(20):
                params = {"timeframe": "1Day", "start": start, "limit": 10000,
                          "feed": "iex", "adjustment": "split", "sort": "asc"}
                if token:
                    params["page_token"] = token
                r = requests.get(f"{data_url}/v2/stocks/{t}/bars", params=params,
                                 headers=hdr, timeout=30)
                if r.status_code != 200:
                    break
                d = r.json()
                allbars.extend(d.get("bars") or [])
                token = d.get("next_page_token")
                if not token:
                    break
            cache[t] = [{"t": b["t"], "o": b["o"], "c": b["c"]} for b in allbars]
            time.sleep(0.1)
        except Exception:  # noqa: BLE001
            cache[t] = []
    EXTRA_PRICE.write_text(json.dumps(cache))
    return cache


def parse_mdy(s):
    return datetime.strptime(s, "%m/%d/%Y").date()


# Verifier fix (2026-06-18): if the price series doesn't start until long after a
# filing (deep_wide5 begins ~2021-06), next_open_index would fill a 2020 filing in
# mid-2021 — a phantom cohort buying the mega-cap melt-up a year late, which
# mislabelled the by-year OOS. Require the entry bar to be within this many calendar
# days of the filing; otherwise SKIP the trade (no stale fill).
MAX_FILL_GAP_DAYS = 7


def _iso_gap_days(d1, d2):
    """Absolute calendar-day gap between two 'YYYY-MM-DD' strings."""
    from datetime import date
    a = date(int(d1[:4]), int(d1[5:7]), int(d1[8:10]))
    b = date(int(d2[:4]), int(d2[5:7]), int(d2[8:10]))
    return abs((b - a).days)


def next_open_index(series, after_date):
    """First bar index with date strictly AFTER after_date (the t+1 fill bar)."""
    lo, hi = 0, len(series)
    while lo < hi:
        mid = (lo + hi) // 2
        if series[mid][0] <= after_date:
            lo = mid + 1
        else:
            hi = mid
    return lo if lo < len(series) else None


def backtest_buys(buys, bars, spy, cost_bps, slip_bps):
    """Each buy: fill at OPEN of first bar AFTER filing_date. For every strategy we
    store per-trade (stock_ret, matched_spy_ret_over_same_window) PAIRS, so alpha
    is a strict matched-pair difference (never two unaligned lists). one-side
    friction = (cost+slip) bps applied on BOTH entry and exit."""
    fr = (cost_bps + slip_bps) / 10000.0  # per side, as fraction
    HORIZONS = [21, 63, 126]
    # each strategy: {"pairs":[(ret, spy_ret_or_None)], "by_year":{}, "by_lag":{}}
    out = {f"hold_{h}d": {"pairs": [], "by_year": {}, "by_lag": {}} for h in HORIZONS}
    out["p2_rules"] = {"pairs": [], "by_year": {}, "by_lag": {}}
    # Candidate fix: a WIDER trailing stop + longer max-hold keeps real downside
    # protection but stops churning winners out the way the 8%/180d rules do.
    out["p2_rules_wide"] = {"pairs": [], "by_year": {}, "by_lag": {}}
    n_filled = 0
    n_no_price = 0
    n_no_future = 0
    n_stale = 0

    for bz in buys:
        tk = bz["ticker"]
        series = bars.get(tk)
        if not series:
            n_no_price += 1
            continue
        fdate = bz["filing_date"]
        ei = next_open_index(series, fdate)
        if ei is None:
            n_no_future += 1
            continue
        # Verifier fix: reject stale fills — the entry bar must be within
        # MAX_FILL_GAP_DAYS of the filing, else the series has no real bar near
        # the disclosure and we'd buy a year late.
        if _iso_gap_days(fdate, series[ei][0]) > MAX_FILL_GAP_DAYS:
            n_stale += 1
            continue
        entry_open = series[ei][1]
        if entry_open <= 0:
            continue
        entry_px = entry_open * (1 + fr)  # pay friction on entry
        n_filled += 1
        yr = str(bz["filing_year"])
        lag = bz.get("disclosure_lag_days")
        lag_bucket = lag_bucket_of(lag)

        # SPY matched entry (same filing date -> same t+1 fill)
        spy_ei = next_open_index(spy, fdate) if spy else None

        # Fixed horizons
        for h in HORIZONS:
            xi = ei + h
            if xi >= len(series):
                continue
            exit_px = series[xi][2] * (1 - fr)
            ret = exit_px / entry_px - 1.0
            sret = spy_ret(spy, spy_ei, h, fr)
            d = out[f"hold_{h}d"]
            d["pairs"].append((ret, sret))
            d["by_year"].setdefault(yr, []).append((ret, sret))
            if lag_bucket:
                d["by_lag"].setdefault(lag_bucket, []).append((ret, sret))

        # P2 live exit rules: 8% trailing stop / 25% TP / 180d max hold
        ret, hold_used = p2_exit(series, ei, entry_px, fr, stop=0.08, tp=0.25, maxhold=180)
        sret = spy_ret(spy, spy_ei, hold_used, fr)
        d = out["p2_rules"]
        d["pairs"].append((ret, sret))
        d["by_year"].setdefault(yr, []).append((ret, sret))
        if lag_bucket:
            d["by_lag"].setdefault(lag_bucket, []).append((ret, sret))

        # Candidate WIDER exit: 18% trailing stop / 25% TP / 252d (~1y) max hold —
        # still a real stop, but patient enough to let the signal play out.
        retw, holdw = p2_exit(series, ei, entry_px, fr, stop=0.18, tp=0.25, maxhold=252)
        sretw = spy_ret(spy, spy_ei, holdw, fr)
        dw = out["p2_rules_wide"]
        dw["pairs"].append((retw, sretw))
        dw["by_year"].setdefault(yr, []).append((retw, sretw))
        if lag_bucket:
            dw["by_lag"].setdefault(lag_bucket, []).append((retw, sretw))

    return out, {"filled": n_filled, "no_price": n_no_price,
                 "no_future_bar": n_no_future, "stale_skipped": n_stale}


def p2_exit(series, ei, entry_px, fr, stop, tp, maxhold):
    """Walk forward bar-by-bar applying trailing-stop / TP / max-hold. Trailing
    stop tracks the peak CLOSE since entry (conservative single-series proxy).
    Returns (net_return, holding_bars)."""
    peak = series[ei][2]
    last_i = min(ei + maxhold, len(series) - 1)
    for i in range(ei + 1, last_i + 1):
        c = series[i][2]
        if c > peak:
            peak = c
        # trailing stop off the peak close
        if c <= peak * (1 - stop):
            exit_px = c * (1 - fr)
            return exit_px / entry_px - 1.0, i - ei
        # take profit vs entry (gross)
        if c / (entry_px / (1 + fr)) - 1.0 >= tp:
            exit_px = c * (1 - fr)
            return exit_px / entry_px - 1.0, i - ei
    exit_px = series[last_i][2] * (1 - fr)
    return exit_px / entry_px - 1.0, last_i - ei


def spy_ret(spy, spy_ei, holding, fr):
    if not spy or spy_ei is None:
        return None
    xi = spy_ei + holding
    if xi >= len(spy):
        return None
    entry = spy[spy_ei][1] * (1 + fr)
    exit_px = spy[xi][2] * (1 - fr)
    if entry <= 0:
        return None
    return exit_px / entry - 1.0


def lag_bucket_of(lag):
    if lag is None:
        return None
    if lag <= 14:
        return "0-14d"
    if lag <= 30:
        return "15-30d"
    if lag <= 45:
        return "31-45d"
    return "45d+"


def stats_block(pairs):
    """Per-trade equal-weight stats from (stock_ret, spy_ret_or_None) PAIRS. These
    are independent single-name copy trades (not a compounded curve), so we report
    the cross-sectional distribution + matched-pair alpha vs SPY (the decision
    metric). Two significance tests are reported:
      - t_stat_mean: is the mean trade return reliably != 0?
      - t_stat_alpha: is the mean (stock - SPY) per-trade EXCESS reliably > 0?
        (the one that actually decides 'edge over just buying SPY')
    Trades overlap in calendar time, so these t-stats overstate significance
    (no independence correction) — treated as directional, not gospel."""
    if not pairs:
        return None
    rets = [p[0] for p in pairs]
    n = len(rets)
    mean = M._mean(rets)
    sd = M._std(rets)
    wins = sum(1 for r in rets if r > 0)
    pf = M.profit_factor(rets)
    med = sorted(rets)[n // 2]
    tstat = (mean / (sd / (n ** 0.5))) if sd > 0 and n > 1 else 0.0

    # matched-pair alpha: only trades that HAVE a SPY window
    excess = [p[0] - p[1] for p in pairs if p[1] is not None]
    alpha = M._mean(excess) if excess else None
    alpha_sd = M._std(excess) if len(excess) > 1 else 0.0
    alpha_t = (alpha / (alpha_sd / (len(excess) ** 0.5))) if alpha_sd > 0 and len(excess) > 1 else 0.0
    alpha_win = (sum(1 for e in excess if e > 0) / len(excess)) if excess else None
    spy_mean = M._mean([p[1] for p in pairs if p[1] is not None]) if excess else None
    return {
        "n": n,
        "mean_ret_pct": round(mean * 100, 3),
        "median_ret_pct": round(med * 100, 3),
        "stdev_pct": round(sd * 100, 3),
        "win_rate_pct": round(100 * wins / n, 1),
        "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
        "mean_alpha_vs_spy_pct": round(alpha * 100, 3) if alpha is not None else None,
        "alpha_win_rate_pct": round(alpha_win * 100, 1) if alpha_win is not None else None,
        "t_stat_mean": round(tstat, 2),
        "t_stat_alpha": round(alpha_t, 2),
        "matched_n": len(excess),
        "spy_mean_pct": round(spy_mean * 100, 3) if spy_mean is not None else None,
    }


def main():
    print("=" * 70)
    print("P2 CAPITOL SHADOW — congress copy-trade backtest (no look-ahead)")
    print("=" * 70)

    filings = json.loads(INDEX.read_text())
    print("STAGE 1: %d PTR filings in index" % len(filings))

    # STAGE 2 ------------------------------------------------------------
    print("\nSTAGE 2: parsing PTR PDFs (cached) ...")
    cache = stage2_parse(filings)
    parsed_ok = sum(1 for f in filings if cache.get(f["doc_id"], {}).get("rows"))
    statuses = {}
    for f in filings:
        st = cache.get(f["doc_id"], {}).get("status", "missing")
        key = st.split(":")[0]
        statuses[key] = statuses.get(key, 0) + 1
    print("  parse status:", statuses)
    print("  files with >=1 parsed row: %d / %d (%.1f%%)"
          % (parsed_ok, len(filings), 100 * parsed_ok / len(filings)))

    # Flatten into transactions, attach filing metadata
    txns = []
    for f in filings:
        rec = cache.get(f["doc_id"], {})
        for row in rec.get("rows", []):
            txns.append({**row, "member": f["member"], "filing_date": f["filing_date"],
                         "filing_year": f["year"]})
    n_buys_raw = sum(1 for t in txns if t["code"] == "P")
    print("  parsed transactions: %d (purchases=%d, sales=%d, exchanges=%d)"
          % (len(txns), n_buys_raw,
             sum(1 for t in txns if t["code"] == "S"),
             sum(1 for t in txns if t["code"] == "E")))

    # Drop non-equities, keep BUYs
    equity_buys = []
    dropped_nonequity = 0
    for t in txns:
        if t["code"] != "P":
            continue
        if looks_like_bond_or_private(t["asset_name"], t["asset_code"]):
            dropped_nonequity += 1
            continue
        equity_buys.append(t)
    print("  equity-candidate BUYs (after dropping bonds/treasuries/private): %d "
          "(dropped %d non-equities)" % (len(equity_buys), dropped_nonequity))

    # STAGE 3: price universe + ticker mapping --------------------------
    print("\nSTAGE 3: price coverage + ticker mapping ...")
    bars = load_universe_bars()
    priceable = set(bars.keys())
    print("  deep_wide5 universe: %d tickers" % len(priceable))

    # First pass: which BUYs map to a priceable ticker?
    mapped = []
    unmapped_names = {}
    for b in equity_buys:
        tk = map_to_ticker(b, priceable)
        if tk:
            b2 = dict(b)
            b2["ticker"] = tk
            mapped.append(b2)
        else:
            # candidate parenthetical ticker not in universe -> try to fetch
            nm = b.get("ticker_paren") or b.get("asset_name", "")[:30]
            unmapped_names[nm] = unmapped_names.get(nm, 0) + 1

    # Try to extend coverage: parenthetical tickers we don't have prices for.
    extra_candidates = sorted({b["ticker_paren"] for b in equity_buys
                               if b.get("ticker_paren") and b["ticker_paren"] not in priceable
                               and re.fullmatch(r"[A-Z]{1,5}", b["ticker_paren"])})
    print("  BUYs mapped to deep_wide5: %d ; distinct unmapped paren-tickers: %d"
          % (len(mapped), len(extra_candidates)))
    extra = fetch_extra_bars(extra_candidates)
    for tk, rows in extra.items():
        if len(rows) >= 100:
            series = sorted((b["t"][:10], float(b["o"]), float(b["c"])) for b in rows)
            bars[tk] = series
            priceable.add(tk)
    # re-map with extended universe
    mapped = []
    for b in equity_buys:
        tk = map_to_ticker(b, priceable)
        if tk:
            b2 = dict(b)
            b2["ticker"] = tk
            mapped.append(b2)
    print("  total priceable universe now: %d tickers" % len(priceable))
    print("  equity BUYs mapped to a PRICEABLE ticker: %d / %d (%.1f%% of equity BUYs)"
          % (len(mapped), len(equity_buys),
             100 * len(mapped) / len(equity_buys) if equity_buys else 0))

    # Compute disclosure lag (filing_date - txn_date) and attach parsed dates
    final_buys = []
    for b in mapped:
        try:
            fd = parse_mdy(b["filing_date"])
            td = parse_mdy(b["txn_date"])
            lag = (fd - td).days
            if lag < 0 or lag > 400:
                lag = None  # bad/old amended filing
            b["filing_date"] = fd.isoformat()
            b["disclosure_lag_days"] = lag
            final_buys.append(b)
        except Exception:  # noqa: BLE001
            continue
    # de-dup identical (member,ticker,txn_date,filing_date) repeats within a filing
    seen = set()
    dedup = []
    for b in final_buys:
        k = (b["member"], b["ticker"], b["txn_date"], b["filing_date"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(b)
    final_buys = dedup
    print("  final distinct equity-BUY copy events: %d" % len(final_buys))
    uniq_tickers = sorted({b["ticker"] for b in final_buys})
    print("  unique tickers traded: %d" % len(uniq_tickers))
    lags = [b["disclosure_lag_days"] for b in final_buys if b["disclosure_lag_days"] is not None]
    if lags:
        lags.sort()
        print("  disclosure lag (txn->filing) days: median=%d mean=%.1f p90=%d max=%d"
              % (lags[len(lags) // 2], M._mean(lags), lags[int(0.9 * len(lags))], max(lags)))

    # Friction (floored at 5/5)
    cost_bps, slip_bps = load_friction("portfolio_2")
    print("  friction: cost=%.1fbps slippage=%.1fbps (each side)" % (cost_bps, slip_bps))

    # BACKTEST ----------------------------------------------------------
    print("\nBACKTEST (signal@close[filing t] -> fill@open[t+1], friction each side):")
    spy = bars.get("SPY")
    results, fill_stats = backtest_buys(final_buys, bars, spy, cost_bps, slip_bps)
    print("  fills: %s" % fill_stats)

    report = {
        "as_of": datetime.utcnow().isoformat(),
        "n_filings": len(filings),
        "parse_success_pct": round(100 * parsed_ok / len(filings), 1),
        "parse_status": statuses,
        "n_parsed_txns": len(txns),
        "n_equity_buys_candidate": len(equity_buys),
        "n_buys_mapped_priceable": len(final_buys),
        "ticker_coverage_pct_of_equity_buys": round(
            100 * len(mapped) / len(equity_buys), 1) if equity_buys else 0,
        "unique_tickers": len(uniq_tickers),
        "fill_stats": fill_stats,
        "friction_bps_each_side": {"cost": cost_bps, "slippage": slip_bps},
        "strategies": {},
    }

    for name, d in results.items():
        block = stats_block(d["pairs"])
        if not block:
            continue
        by_year = {y: stats_block(rs) for y, rs in sorted(d["by_year"].items())}
        by_lag = {lb: stats_block(rs) for lb, rs in sorted(d["by_lag"].items())}
        report["strategies"][name] = {"overall": block, "by_year": by_year, "by_lag_decay": by_lag}
        print("\n  --- %s ---" % name)
        print("    n=%d  mean=%.2f%%  median=%.2f%%  win=%.0f%%  PF=%s"
              % (block["n"], block["mean_ret_pct"], block["median_ret_pct"],
                 block["win_rate_pct"], block["profit_factor"]))
        print("    alpha_vs_SPY=%s%% (alpha_win=%s%%, t_alpha=%.2f)  |  SPY same-window mean=%s%%"
              % (block["mean_alpha_vs_spy_pct"], block["alpha_win_rate_pct"],
                 block["t_stat_alpha"], block["spy_mean_pct"]))
        for y, yb in by_year.items():
            if yb:
                print("      %s: n=%-4d mean=%6.2f%% win=%3.0f%% PF=%-5s alpha=%6.2f%%"
                      % (y, yb["n"], yb["mean_ret_pct"], yb["win_rate_pct"],
                         yb["profit_factor"], yb["mean_alpha_vs_spy_pct"] or 0.0))

    # lag-decay summary for the headline horizon (63d)
    print("\n  --- DISCLOSURE-LAG DECAY (hold_63d, by txn->filing gap) ---")
    for lb, blk in (report["strategies"].get("hold_63d", {}).get("by_lag_decay", {}) or {}).items():
        if blk:
            print("    %-8s n=%-4d mean=%6.2f%% win=%3.0f%%"
                  % (lb, blk["n"], blk["mean_ret_pct"], blk["win_rate_pct"]))

    out_path = REPO / "data" / "p2_congress_copy_backtest.json"
    out_path.write_text(json.dumps(report, indent=2))
    print("\nReport -> %s" % out_path)
    return report


if __name__ == "__main__":
    main()
