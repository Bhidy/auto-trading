#!/bin/bash
# Pre-deployment validation — run before pushing to main.
# Verifies data files, vercel.json, and workflow configurations.
# Usage: bash dashboard/validate.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

FAILURES=0
echo "=== PRE-DEPLOY VALIDATION ==="
echo ""

# --- 1. Check required data files exist ---
echo "--- Data Files ---"
REQUIRED=(
    "data/trade_log.json"
    "data/signals.json"
    "data/portfolio_state.json"
    "data/strategy_params.json"
    "data/learning_report.json"
    "event-driven-bot/data/trade_log.json"
    "political-copy-bot/data/trade_log.json"
    "config/risk_limits.json"
    "config/watchlist.json"
)
for f in "${REQUIRED[@]}"; do
    if [ -f "$f" ]; then
        SIZE=$(wc -c < "$f" | tr -d ' ')
        if [ "$SIZE" -lt 10 ]; then
            echo "  WARN  $f exists but is tiny (${SIZE} bytes)"
        else
            echo "  OK    $f (${SIZE} bytes)"
        fi
    else
        echo "  FAIL  $f — MISSING!"
        FAILURES=$((FAILURES + 1))
    fi
done
echo ""

# --- 2. Verify vercel.json structure ---
echo "--- vercel.json ---"
if [ -f vercel.json ]; then
    # Check includeFiles uses brace expansion, not commas
    if python3 -c "
import json
with open('vercel.json') as f:
    cfg = json.load(f)
inc = cfg.get('functions',{}).get('api/index.js',{}).get('includeFiles','')
if ',' in inc and '{' not in inc:
    print('ERROR: includeFiles uses commas — must use brace expansion {a,b}/**')
    exit(1)
if not inc:
    print('ERROR: includeFiles is empty')
    exit(1)
print(f'OK: includeFiles = {inc}')
" 2>&1; then
        echo "  OK    vercel.json includeFiles format valid"
    else
        echo "  FAIL  vercel.json includeFiles format invalid"
        FAILURES=$((FAILURES + 1))
    fi
else
    echo "  FAIL  vercel.json not found"
    FAILURES=$((FAILURES + 1))
fi
echo ""

# --- 3. Verify data files are git-tracked (not gitignored) ---
echo "--- Git Tracking ---"
for f in data/trade_log.json data/signals.json data/portfolio_state.json; do
    if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
        echo "  OK    $f is git-tracked"
    else
        echo "  FAIL  $f is NOT tracked by git (check .gitignore)"
        FAILURES=$((FAILURES + 1))
    fi
done
echo ""

# --- 4. Verify data files have content (not just empty JSON) ---
echo "--- Data Integrity ---"
for f in data/trade_log.json data/signals.json data/portfolio_state.json; do
    if [ -f "$f" ]; then
        if python3 -c "
import json
with open('$f') as fh:
    data = json.load(fh)
if isinstance(data, list) and len(data) == 0:
    print('WARN: $f is empty array')
elif isinstance(data, dict) and len(data) == 0:
    print('WARN: $f is empty object')
else:
    print('OK: $f has content')
" 2>&1; then
            :
        else
            echo "  FAIL  $f has invalid JSON"
            FAILURES=$((FAILURES + 1))
        fi
    fi
done
echo ""

# --- Final ---
echo "=== VALIDATION COMPLETE: $FAILURES failures ==="
if [ $FAILURES -gt 0 ]; then
    echo ""
    echo "FIX THE FAILURES ABOVE BEFORE DEPLOYING."
    echo "Common fixes:"
    echo "  1. Missing data files: Run the trading pipeline to regenerate:"
    echo "     export PYTHONPATH=\"\$PWD/../scripts\""
    echo "     python3 ../scripts/autonomous_runner.py morning-research"
    echo "  2. Fix vercel.json: use brace expansion format:"
    echo "     \"includeFiles\": \"{data,event-driven-bot/data,political-copy-bot/data,journal,config}/**\""
    echo "  3. Data files not tracked: check .gitignore"
    exit 1
fi
echo "READY TO DEPLOY: cd dashboard && vercel --prod"
