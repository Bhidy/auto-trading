"""
save_to_supabase.py — Daily persistence for portfolio equity + market prices.

Run at EOD from each portfolio's workflow. Accumulates real historical data in
Supabase so charts don't depend on Alpaca subscription tiers or synthetic backfill.

Usage:
    python3 scripts/save_to_supabase.py \
        --portfolio-id portfolio_1 \
        --state-file data/portfolio_state.json \
        --api-key $ALPACA_API_KEY \
        --api-secret $ALPACA_API_SECRET

Required env vars:
    SUPABASE_URL              e.g. https://xxxx.supabase.co
    SUPABASE_SERVICE_ROLE_KEY service role key (write access)
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error
import ssl
import datetime

# ── CLI args ────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--portfolio-id', required=True, help='portfolio_1 | portfolio_2 | portfolio_3')
parser.add_argument('--state-file',   required=True, help='Path to portfolio_state.json')
parser.add_argument('--api-key',      default='', help='Alpaca API key for market data')
parser.add_argument('--api-secret',   default='', help='Alpaca API secret')
args = parser.parse_args()

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
DATA_URL     = 'https://data.alpaca.markets'
TODAY        = datetime.date.today().isoformat()

# Benchmarks + common holdings to track daily
MARKET_SYMBOLS = ['SPY', 'QQQ', 'DIA', 'IWM', 'GLD', 'TLT', 'BIL']

# ── SSL context (permissive for GitHub Actions) ──────────────────────────────
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def alpaca_get(path):
    if not args.api_key:
        return None
    url = DATA_URL + path
    req = urllib.request.Request(url, headers={
        'APCA-API-KEY-ID':     args.api_key,
        'APCA-API-SECRET-KEY': args.api_secret,
    })
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f'  Alpaca error {path}: {e}')
        return None


def supabase_upsert(table, rows):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print(f'  SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set — skipping {table}')
        return False
    if not rows:
        return True
    url  = f'{SUPABASE_URL}/rest/v1/{table}'
    body = json.dumps(rows).encode()
    req  = urllib.request.Request(url, data=body, method='POST', headers={
        'apikey':        SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type':  'application/json',
        'Prefer':        'resolution=merge-duplicates',
    })
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as r:
            print(f'  Upserted {len(rows)} row(s) into {table} — HTTP {r.status}')
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f'  Supabase error ({table}): {e.code} {body}')
        return False
    except Exception as e:
        print(f'  Supabase error ({table}): {e}')
        return False


# ── 1. Portfolio equity snapshot ─────────────────────────────────────────────
print(f'\n[{TODAY}] Saving {args.portfolio_id} equity snapshot...')
state = {}
try:
    with open(args.state_file) as f:
        state = json.load(f)
except Exception as e:
    print(f'  Could not read state file: {e}')

equity     = float(state.get('portfolio_value') or state.get('equity') or 100000)
cash       = float(state.get('cash') or 0)
pnl        = float(state.get('total_pl') or state.get('unrealized_pl') or 0)
pnl_pct    = float(state.get('total_pl_pct') or state.get('return_pct') or 0)
positions  = len(state.get('positions') or [])

supabase_upsert('portfolio_equity_history', [{
    'portfolio_id':    args.portfolio_id,
    'date':            TODAY,
    'equity':          round(equity, 2),
    'cash':            round(cash, 2),
    'pnl':             round(pnl, 2),
    'pnl_pct':         round(pnl_pct, 4),
    'positions_count': positions,
}])


# ── 2. Market daily prices ───────────────────────────────────────────────────
print(f'\n[{TODAY}] Saving market prices for {MARKET_SYMBOLS}...')
# Fetch latest bars for all symbols in one snapshot call
snap_url = f'/v2/stocks/snapshots?symbols={",".join(MARKET_SYMBOLS)}&feed=iex'
snaps = alpaca_get(snap_url) or {}

market_rows = []
for sym in MARKET_SYMBOLS:
    data = snaps.get(sym, {})
    bar  = data.get('dailyBar') or data.get('prevDailyBar') or {}
    if bar and bar.get('c'):
        market_rows.append({
            'symbol':      sym,
            'date':        TODAY,
            'close_price': round(float(bar['c']), 4),
            'open_price':  round(float(bar.get('o', bar['c'])), 4),
            'high_price':  round(float(bar.get('h', bar['c'])), 4),
            'low_price':   round(float(bar.get('l', bar['c'])), 4),
            'volume':      int(bar.get('v', 0)),
        })
        print(f'  {sym}: close={bar["c"]}')
    else:
        print(f'  {sym}: no bar data')

if market_rows:
    supabase_upsert('market_daily_history', market_rows)
else:
    print('  No market data to save')


# ── 3. Holdings prices (stocks currently in this portfolio) ──────────────────
# positions may be a list[dict] (P2) or a dict keyed by symbol (P1/P3) — handle both.
_positions = state.get('positions') or []
if isinstance(_positions, dict):
    _pos_items = []
    for sym, pos in _positions.items():
        if isinstance(pos, dict):
            pos = {**pos, 'symbol': pos.get('symbol') or pos.get('ticker') or sym}
        else:
            pos = {'symbol': sym}
        _pos_items.append(pos)
else:
    _pos_items = [p for p in _positions if isinstance(p, dict)]
held_symbols = list({
    pos.get('symbol') or pos.get('ticker') or ''
    for pos in _pos_items
    if pos.get('symbol') or pos.get('ticker')
})
held_symbols = [s for s in held_symbols if s and s not in MARKET_SYMBOLS]

if held_symbols:
    print(f'\n[{TODAY}] Saving holdings prices: {held_symbols}...')
    chunk_size = 50  # Alpaca snapshot limit
    all_snaps = {}
    for i in range(0, len(held_symbols), chunk_size):
        chunk = held_symbols[i:i+chunk_size]
        chunk_snaps = alpaca_get(f'/v2/stocks/snapshots?symbols={",".join(chunk)}&feed=iex') or {}
        all_snaps.update(chunk_snaps)

    holding_rows = []
    for sym in held_symbols:
        data = all_snaps.get(sym, {})
        bar  = data.get('dailyBar') or data.get('prevDailyBar') or {}
        if bar and bar.get('c'):
            holding_rows.append({
                'symbol':      sym,
                'date':        TODAY,
                'close_price': round(float(bar['c']), 4),
                'open_price':  round(float(bar.get('o', bar['c'])), 4),
                'high_price':  round(float(bar.get('h', bar['c'])), 4),
                'low_price':   round(float(bar.get('l', bar['c'])), 4),
                'volume':      int(bar.get('v', 0)),
            })
            print(f'  {sym}: {bar["c"]}')

    if holding_rows:
        supabase_upsert('market_daily_history', holding_rows)

print(f'\nDone. {args.portfolio_id} snapshot saved to Supabase.')
