#!/usr/bin/env python3
"""Pure-stdlib text extraction + transaction parsing for US House PTR PDFs.

Cloud-path-safe fallback for the Capitol Trades feed (audit 2026-07-04, defect
D3: the feed has been WAF-blocked from GitHub Actions IPs since 2026-05-29).
House Periodic Transaction Reports are machine-generated, single-column,
FlateDecode PDFs; extracting their text needs only ``zlib`` + a small content-
stream scanner — no pdfplumber, keeping the trading path ``requests``-only
(tests/test_trading_path_purity.py).

Parity-validated against the research lane's pdfplumber ground truth
(data/p2_ptr_parsed.json, 467 docs) before adoption; the regex layer below is
the same one the 5y backtest used (scripts/research/p2_congress_copy_backtest.py).
"""
import hashlib
import re
import struct
import zlib

# --------------------------------------------------------------------------
# Standard security handler (V2/R3, RC4-128, empty user password).
# Every encrypted House PTR in the 631-doc research cache is V2R3; the "key"
# is derived from the EMPTY password exactly as any PDF viewer does on open —
# these are public documents, the flags only restrict printing/copying.
# --------------------------------------------------------------------------

_PAD = bytes([0x28, 0xBF, 0x4E, 0x5E, 0x4E, 0x75, 0x8A, 0x41, 0x64, 0x00,
              0x4E, 0x56, 0xFF, 0xFA, 0x01, 0x08, 0x2E, 0x2E, 0x00, 0xB6,
              0xD0, 0x68, 0x3E, 0x80, 0x2F, 0x0C, 0xA9, 0xFE, 0x64, 0x53,
              0x69, 0x7A])


def _rc4(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) & 0xFF
        S[i], S[j] = S[j], S[i]
    out = bytearray()
    i = j = 0
    for c in data:
        i = (i + 1) & 0xFF
        j = (j + S[i]) & 0xFF
        S[i], S[j] = S[j], S[i]
        out.append(c ^ S[(S[i] + S[j]) & 0xFF])
    return bytes(out)


def _hexbytes(tok):
    return bytes.fromhex(re.sub(rb"\s", b"", tok).decode())


def _encryption_key(pdf):
    """Document RC4 key for the empty user password, or None if unencrypted."""
    if b"/Encrypt" not in pdf:
        return None
    enc_ref = re.search(rb"/Encrypt\s+(\d+)\s+(\d+)\s+R", pdf)
    if enc_ref:
        obj = re.search(rb"(?<![\d])%s\s+%s\s+obj(.*?)endobj"
                        % (enc_ref.group(1), enc_ref.group(2)), pdf, re.S)
        enc = obj.group(1) if obj else b""
    else:
        enc = pdf
    o_m = re.search(rb"/O\s*<([0-9A-Fa-f\s]+)>", enc)
    p_m = re.search(rb"/P\s+(-?\d+)", enc)
    len_m = re.search(rb"/Length\s+(\d+)", enc)
    id_m = re.search(rb"/ID\s*\[\s*<([0-9A-Fa-f\s]*)>", pdf)
    r_m = re.search(rb"/R\s+(\d+)", enc)
    if not (o_m and p_m):
        return None
    keylen = (int(len_m.group(1)) // 8) if len_m else 5
    rev = int(r_m.group(1)) if r_m else 3
    h = hashlib.md5()
    h.update(_PAD)                                       # empty user password
    h.update(_hexbytes(o_m.group(1))[:32])
    h.update(struct.pack("<i", int(p_m.group(1))))
    h.update(_hexbytes(id_m.group(1)) if id_m else b"")
    key = h.digest()
    if rev >= 3:
        for _ in range(50):
            key = hashlib.md5(key[:keylen]).digest()
    return key[:keylen]


def _object_key(doc_key, num, gen):
    h = hashlib.md5(doc_key + struct.pack("<i", num)[:3]
                    + struct.pack("<i", gen)[:2]).digest()
    return h[:min(len(doc_key) + 5, 16)]


# --------------------------------------------------------------------------
# PDF content-stream text extraction (FlateDecode + Tj/TJ/'/" show ops)
# --------------------------------------------------------------------------

_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)endobj", re.S)
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_ESC = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}


def _literal_string(buf, i):
    """Parse a PDF literal string starting at buf[i] == '(' -> (text, next_i)."""
    out = bytearray()
    depth = 1
    i += 1
    n = len(buf)
    while i < n and depth:
        c = buf[i]
        if c == 0x5C and i + 1 < n:                     # backslash escape
            nxt = buf[i + 1]
            if nxt in _ESC:
                out.append(_ESC[nxt]); i += 2
            elif nxt in (0x28, 0x29, 0x5C):             # \( \) \\
                out.append(nxt); i += 2
            elif 0x30 <= nxt <= 0x37:                   # octal \ddd
                j = i + 1
                digits = bytearray()
                while j < n and len(digits) < 3 and 0x30 <= buf[j] <= 0x37:
                    digits.append(buf[j]); j += 1
                out.append(int(digits.decode(), 8) & 0xFF)
                i = j
            elif nxt == 0x0A:                           # line continuation
                i += 2
            else:
                out.append(nxt); i += 2
        elif c == 0x28:                                 # nested (
            depth += 1; out.append(c); i += 1
        elif c == 0x29:                                 # )
            depth -= 1
            if depth:
                out.append(c)
            i += 1
        else:
            out.append(c); i += 1
    return out.decode("latin-1", errors="replace"), i


def _hex_string(buf, i):
    """Parse <hex> string starting at buf[i] == '<' -> (text, next_i)."""
    j = buf.find(b">", i + 1)
    if j < 0:
        return "", len(buf)
    hx = re.sub(rb"\s", b"", buf[i + 1:j])
    if len(hx) % 2:
        hx += b"0"
    try:
        return bytes.fromhex(hx.decode()).decode("latin-1", errors="replace"), j + 1
    except ValueError:
        return "", j + 1


_NUM_RE = re.compile(rb"[-+]?\d*\.?\d+")
_OP_RE = re.compile(rb"[A-Za-z'\"*]{1,3}")
_BFCHAR_RE = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE_RE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
_HEXPAIR_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_HEXTRIPLE_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")


def _tounicode_map(cmap_bytes):
    """{code: unicode_str} from ONE ToUnicode CMap stream."""
    out = {}
    for m in _BFCHAR_RE.finditer(cmap_bytes):
        for src, dst in _HEXPAIR_RE.findall(m.group(1)):
            code = int(src, 16)
            uni = bytes.fromhex(dst.decode()).decode("utf-16-be", errors="replace")
            out[code] = uni
    for m in _BFRANGE_RE.finditer(cmap_bytes):
        for lo, hi, dst in _HEXTRIPLE_RE.findall(m.group(1)):
            lo_i, hi_i = int(lo, 16), int(hi, 16)
            base = int(dst, 16)
            for k in range(hi_i - lo_i + 1):
                out[lo_i + k] = chr(base + k)
    return out


def _decode_codes(s, cmap):
    """Map a shown string's codes through the merged ToUnicode CMap.

    Identity-H (CID) fonts — what the House PTR generator emits — use 2-byte
    codes, visible as a NUL high byte on every even position; simple fonts use
    1-byte codes. Detect per string and decode accordingly.
    """
    if not cmap:
        return s
    if (len(s) >= 2 and len(s) % 2 == 0
            and all(s[i] == "\x00" for i in range(0, len(s), 2))):
        codes = [(ord(s[i]) << 8) | ord(s[i + 1]) for i in range(0, len(s), 2)]
    else:
        codes = [ord(ch) for ch in s]
    return "".join(cmap.get(c, chr(c)) for c in codes)


def _mat_mul(m1, m2):
    """PDF matrix concatenation: apply m1, then m2 (both (a,b,c,d,e,f))."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _mat_apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _stream_segments(data):
    """(y, x, size, font_name, raw_string) DEVICE-space text segments.

    The House PTR generator draws every text run inside its own
    ``q <matrix> cm BT ... ET Q`` block — position lives in the GRAPHICS
    matrix (with a 1/32 page scale), not in Tm. So the scanner tracks the full
    CTM (q/Q stack + cm concatenation) and emits device coordinates; lines are
    then rebuilt by device Y and word gaps inferred from device X advances —
    the same reconstruction pdfplumber performs. The active font (Tf) travels
    with each segment because subset fonts carry CONFLICTING code->unicode
    maps (the bold header font and the body font reuse the same codes).
    """
    segs = []
    x = y = 0.0                                          # text-space position
    size = 10.0
    tc = 0.0                                             # char spacing (Tc)
    leading = 0.0
    font = None
    ctm = _IDENTITY
    stack = []
    pending = []
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        if c in b" \t\r\n\x00":
            i += 1
            continue
        if c == 0x28:                                    # ( literal string
            s, i = _literal_string(data, i)
            pending.append(("str", s))
            continue
        if c == 0x3C:                                    # < hex or << dict
            if i + 1 < n and data[i + 1] == 0x3C:
                i += 2
                continue
            s, i = _hex_string(data, i)
            pending.append(("str", s))
            continue
        if c in b"[]/":
            if c == 0x2F:                                # /Name operand
                m = re.compile(rb"/([^\s\[\]()<>/]*)").match(data, i)
                if m:
                    pending.append(("name", m.group(1).decode("latin-1")))
                    i = m.end()
                else:
                    i += 1
            else:
                i += 1
            continue
        m = _NUM_RE.match(data, i)
        if m and (chr(c).isdigit() or c in b"+-."):
            pending.append(("num", float(m.group()))); i = m.end()
            continue
        m = _OP_RE.match(data, i)
        if not m:
            i += 1
            continue
        op = m.group().decode("latin-1")
        i = m.end()
        strs = [v for k, v in pending if k == "str"]
        nums = [v for k, v in pending if k == "num"]
        names = [v for k, v in pending if k == "name"]
        if op in ("Tj", "'", '"', "TJ"):
            if op in ("'", '"'):
                y -= leading or size * 1.2
            txt = "".join(strs)
            if txt:
                dx, dy = _mat_apply(ctm, x, y)
                scale = abs(ctm[0]) or abs(ctm[2]) or 1.0
                segs.append((dy, dx, size * scale, font, txt))
                x += (0.5 * size + tc) * len(txt)        # rough advance
        elif op == "Tm" and len(nums) >= 6:
            x, y = nums[-2], nums[-1]
        elif op in ("Td", "TD") and len(nums) >= 2:
            x += nums[-2]
            y += nums[-1]
            if op == "TD":
                leading = -nums[-1]
        elif op == "TL" and nums:
            leading = nums[-1]
        elif op == "Tc" and nums:
            tc = nums[-1]
        elif op == "T*":
            y -= leading or size * 1.2
        elif op == "Tf":
            if names:
                font = names[-1]
            if nums and nums[-1]:
                size = nums[-1]
        elif op == "BT":
            x = y = 0.0
        elif op == "q":
            stack.append(ctm)
        elif op == "Q":
            if stack:
                ctm = stack.pop()
        elif op == "cm" and len(nums) >= 6:
            ctm = _mat_mul(tuple(nums[-6:]), ctm)
        pending = []
    return segs


def _segments_to_text(segs):
    """Group segments into lines by device Y, order by X, join with spaces.

    Segments are whole table CELLS in these generated PDFs, so a single space
    between adjacent segments reconstructs the column separation the row regex
    needs. Gap-size heuristics were measurably WORSE (79.6% vs 83.4% row
    recall on the 467-doc ground-truth corpus): estimated glyph widths eat the
    real column gap on long asset names ("...Inc.P 12/10/2019").
    """
    lines = {}
    for y, x, size, txt in segs:
        key = round(y / 2.5)                             # ~2.5pt line tolerance
        lines.setdefault(key, []).append((x, txt))
    out = []
    for key in sorted(lines, reverse=True):              # PDF y grows upward
        parts = sorted(lines[key], key=lambda p: p[0])
        line = " ".join(txt for _, txt in parts)
        if line.strip():
            out.append(line)
    return "\n".join(out)


def _decoded_streams(pdf_bytes, doc_key):
    """{object_number: decrypted (and inflated when Flate) stream bytes}."""
    streams = {}
    for om in _OBJ_RE.finditer(pdf_bytes):
        num, gen, body = int(om.group(1)), int(om.group(2)), om.group(3)
        sm = _STREAM_RE.search(body)
        if not sm:
            continue
        raw = sm.group(1)
        if doc_key is not None:
            raw = _rc4(_object_key(doc_key, num, gen), raw)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass                                         # uncompressed stream
        streams[num] = raw
    return streams


def _page_fonts(pdf_bytes, streams):
    """{content_obj_num: {font_resource_name: cmap}} — PAGE-scoped.

    Every page redefines /F0, /F1, ... against DIFFERENT subset font objects
    with conflicting code maps, so font names must be resolved per page, never
    globally (the global merge decoded body text with the header font's map).
    """
    bodies = {int(m.group(1)): m.group(3) for m in _OBJ_RE.finditer(pdf_bytes)}
    # font object -> cmap
    font_obj_cmap = {}
    for num, body in bodies.items():
        tu = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
        if tu and (b"/Font" in body or b"/BaseFont" in body):
            data = streams.get(int(tu.group(1)))
            if data:
                font_obj_cmap[num] = _tounicode_map(data)

    def font_dict(src):
        m = re.search(rb"/Font\s*<<(.*?)>>", src, re.S)
        if not m:
            return None
        out = {}
        for name, ref in re.findall(rb"/([^\s/<>\[\]()]+)\s+(\d+)\s+\d+\s+R",
                                    m.group(1)):
            cm = font_obj_cmap.get(int(ref))
            if cm:
                out[name.decode("latin-1")] = cm
        return out or None

    def resolve_fonts(head, full_body):
        fonts = font_dict(head)
        if fonts is None:                                # /Resources indirect
            rm = re.search(rb"/Resources\s+(\d+)\s+\d+\s+R", head)
            if rm and int(rm.group(1)) in bodies:
                fonts = font_dict(bodies[int(rm.group(1))])
        if fonts is None and head is not full_body:
            fonts = font_dict(full_body)
        return fonts or {}

    page_fonts = {}
    for num, body in bodies.items():
        head = body.split(b"stream", 1)[0]               # dict only, not data
        if re.search(rb"/Type\s*/Page\b", head):
            cm = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", head)
            if cm:
                page_fonts[int(cm.group(1))] = resolve_fonts(head, body)
        elif re.search(rb"/Subtype\s*/Form\b", head):
            # 2022+ generator: page content is `q /XOBJ0 Do Q`; the real text
            # lives in a Form XObject carrying its OWN font resources.
            page_fonts[num] = resolve_fonts(head, head)
    return page_fonts


def extract_text(pdf_bytes):
    """Plain text of a machine-generated PDF (FlateDecode streams, RC4-aware,
    subset-font codes resolved through each PAGE's own font ToUnicode CMaps)."""
    doc_key = _encryption_key(pdf_bytes)
    streams = _decoded_streams(pdf_bytes, doc_key)
    page_fonts = _page_fonts(pdf_bytes, streams)
    chunks = []
    for num, data in sorted(streams.items()):
        if num not in page_fonts:
            continue                                     # not a page content stream
        if b"BT" not in data and b"Tj" not in data and b"TJ" not in data:
            continue
        fonts = page_fonts[num]
        merged = {}
        for cm in fonts.values():
            merged.update(cm)
        segs = [(y, x, size, _decode_codes(txt, fonts.get(font) or merged))
                for y, x, size, font, txt in _stream_segments(data)]
        txt = _segments_to_text(segs)
        if txt:
            chunks.append(txt)
    return "\n".join(chunks)


# --------------------------------------------------------------------------
# PTR transaction-row parsing (same regex layer as the 5y research backtest)
# --------------------------------------------------------------------------

ROW_RE = re.compile(
    r"(?P<asset>.+?)\s\[?(?P<code>[PSE])\]?\s+"
    r"(?P<txdate>\d{1,2}/\d{1,2}/\d{4})\s+"
    r"(?P<notif>\d{1,2}/\d{1,2}/\d{4})\s+"
    r"\$(?P<amount_low>[\d,]+)"
)

# STOCK Act reporting bands, keyed by each band's LOWER bound — the only part
# of "$50,001 - $100,000" guaranteed to sit on the row's first line (ranges
# wrap). Values are P2's config bucket strings (size_bucket_multiplier keys).
AMOUNT_BUCKETS = {
    1_001: "1K–15K",
    15_001: "15K–50K",
    50_001: "50K–100K",
    100_001: "100K–250K",
    250_001: "250K–500K",
    500_001: "500K–1M",
    1_000_001: "1M–5M",
    5_000_001: "5M–25M",
    25_000_001: "25M–50M",
}


def size_bucket_from_low(amount_low):
    """Config-format size bucket ("15K–50K") from a band's lower bound."""
    try:
        low = int(str(amount_low).replace(",", ""))
    except (TypeError, ValueError):
        return None
    best = None
    for bound, bucket in sorted(AMOUNT_BUCKETS.items()):
        if low >= bound:
            best = bucket
    return best
TICKER_RE = re.compile(r"\(([A-Z][A-Z\.]{0,5})\)")
ASSETCODE_RE = re.compile(r"\[([A-Za-z]{2})\]")

BOND_CODES = {"GS", "CS", "MF", "MA", "HN", "RP", "AB", "OL", "BA"}
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
    if re.search(r"\d\.\d+\s?%", up):
        return True
    if any(k in up for k in PRIVATE_KW):
        return True
    return False


def clean_asset_name(asset):
    a = re.sub(r"^\s*(SP|JT|DC|S P|J T)\s+", "", asset, flags=re.I)
    a = ASSETCODE_RE.sub("", a)
    a = TICKER_RE.sub("", a)
    return re.sub(r"\s+", " ", a).strip(" .,-")


def parse_ptr_rows(text):
    """Transaction rows from extracted PTR text.

    Returns [{code, ticker_paren, asset_name, asset_code, txn_date}] — the
    exact schema of the research parser, so downstream mapping is shared.
    """
    rows = []
    for line in text.splitlines():
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
            "size_bucket": size_bucket_from_low(m.group("amount_low")),
        })
    return rows


def parse_pdf_bytes(content):
    """(rows, n_text_chars) — signature-compatible with the research parser."""
    txt = extract_text(content)
    return parse_ptr_rows(txt), len(txt.strip())
