#!/bin/bash
# Vercel build script — CRITICAL: validates all data files are present before deploy.
# DO NOT reduce this to a no-op. These checks prevent silent production failures.
set -e

echo "=== BUILD: Validating deployment data files ==="

REQUIRED_FILES=(
    "data/trade_log.json"
    "data/signals.json"
    "data/portfolio_state.json"
    "data/strategy_params.json"
    "data/learning_report.json"
    "event-driven-bot/data/trade_log.json"
    "event-driven-bot/data/signals.json"
    "political-copy-bot/data/trade_log.json"
    "political-copy-bot/data/portfolio_state.json"
    "journal"
    "config/risk_limits.json"
    "config/watchlist.json"
)

MISSING=0
for file in "${REQUIRED_FILES[@]}"; do
    if [ -e "$file" ]; then
        if [ -f "$file" ]; then
            SIZE=$(wc -c < "$file" | tr -d ' ')
            echo "  OK  $file (${SIZE} bytes)"
        else
            echo "  OK  $file/ (directory)"
        fi
    else
        echo "  FAIL  $file — MISSING!"
        MISSING=$((MISSING + 1))
    fi
done

# Verify vercel.json includeFiles syntax (brace expansion, not comma-separated)
if [ -f vercel.json ]; then
    if grep -q '"includeFiles"' vercel.json; then
        PATTERN=$(python3 -c "import json; f=json.load(open('vercel.json')); print(f.get('functions',{}).get('api/index.js',{}).get('includeFiles',''))")
        if echo "$PATTERN" | grep -q ','; then
            echo "  FAIL  vercel.json includeFiles contains commas — must use brace expansion {a,b}/**"
            MISSING=$((MISSING + 1))
        else
            echo "  OK  vercel.json includeFiles: $PATTERN"
        fi
    fi
fi

echo ""
if [ $MISSING -gt 0 ]; then
    echo "BUILD FAILED: $MISSING required files/directories are missing."
    echo "Ensure GitHub Actions workflows have synced data files before deploy."
    echo "Run: python3 scripts/autonomous_runner.py morning-research (to regenerate)"
    exit 1
fi

echo "BUILD PASSED: All required data files present."
echo "Dashboard data directories ready for deployment"
