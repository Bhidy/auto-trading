"""
backfill_equity_history.py — Repair the Supabase equity system-of-record from
Alpaca's broker daily portfolio history (the source of truth).

Why this exists: the daily EOD writer (save_to_supabase.py) previously read a
P1-shaped state file and wrote a literal $100,000 for P2/P3, fabricating their
equity curves. This one-off (idempotent) backfill overwrites every affected day
with the REAL closing equity Alpaca reports, so the dashboard chart's
system-of-record matches the broker. Merge-upsert keyed on (portfolio_id, date)
makes it safe to re-run.

Usage (run in CI where SUPABASE_SERVICE_ROLE_KEY is available):
    python3 scripts/backfill_equity_history.py \
        --portfolio-id portfolio_2 \
        --api-key $KEY --api-secret $SECRET \
        --base-url https://paper-api.alpaca.markets \
        --period 3M

Required env:
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (write access)
"""

import os
import json
import argparse
import urllib.request
import urllib.error
import ssl
import datetime

parser = argparse.ArgumentParser()
parser.add_argument('--portfolio-id', required=True)
parser.add_argument('--api-key', default='')
parser.add_argument('--api-secret', default='')
parser.add_argument('--base-url', default='https://paper-api.alpaca.markets')
parser.add_argument('--period', default='3M', help='Alpaca portfolio-history period (1M/3M/6M/1A)')
parser.add_argument('--dry-run', action='store_true', help='Print rows; do not write')
args = parser.parse_args()

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
TRADING_URL  = (args.base_url or 'https://paper-api.alpaca.markets').rstrip('/')
BASELINE     = 100000.0

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def alpaca_get(path):
    if not args.api_key:
        return None
    req = urllib.request.Request(TRADING_URL + path, headers={
        'APCA-API-KEY-ID':     args.api_key,
        'APCA-API-SECRET-KEY': args.api_secret,
    })
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as r:
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
    req = urllib.request.Request(f'{SUPABASE_URL}/rest/v1/{table}',
        data=json.dumps(rows).encode(), method='POST', headers={
            'apikey':        SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type':  'application/json',
            'Prefer':        'resolution=merge-duplicates',
        })
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as r:
            print(f'  Upserted {len(rows)} row(s) into {table} — HTTP {r.status}')
            return True
    except urllib.error.HTTPError as e:
        print(f'  Supabase error ({table}): {e.code} {e.read().decode()}')
        return False
    except Exception as e:
        print(f'  Supabase error ({table}): {e}')
        return False


print(f'\nBackfilling {args.portfolio_id} equity history (period={args.period})...')
hist = alpaca_get(
    f'/v2/account/portfolio/history?period={args.period}'
    f'&timeframe=1D&intraday_reporting=market_hours&pnl_reset=per_day'
) or {}

timestamps = hist.get('timestamp') or []
equities   = hist.get('equity') or []
rows = []
for ts, eq in zip(timestamps, equities):
    equity = float(eq or 0)
    if equity <= 0:
        continue  # market-closed gap day — skip, never fabricate
    date = datetime.datetime.utcfromtimestamp(ts).date().isoformat()
    pnl = equity - BASELINE
    rows.append({
        'portfolio_id': args.portfolio_id,
        'date':         date,
        'equity':       round(equity, 2),
        'pnl':          round(pnl, 2),
        'pnl_pct':      round((pnl / BASELINE) * 100, 4),
    })

print(f'  {len(rows)} real daily equity points from Alpaca:')
for r in rows:
    print(f"    {r['date']}  equity={r['equity']}  pnl={r['pnl']}")

if args.dry_run:
    print('  [dry-run] not writing')
else:
    supabase_upsert('portfolio_equity_history', rows)

print(f'Done. {args.portfolio_id} equity history repaired.')
