#!/bin/bash
# P1 Self Improving Brain — Morning Research + Trading Session
# Cron backup: runs if Claude Code scheduled tasks didn't fire
set -e
cd /Users/home/Documents/Auto\ Trading

LOG="logs/cron_p1_$(date +%Y-%m-%d).log"
echo "[$(date)] P1 morning pipeline starting" >> "$LOG"

# Step 1: Fetch 220-day bars
python3 scripts/fetch_bars.py >> "$LOG" 2>&1

# Step 2: Run multi-factor analyst
python3 scripts/analyst_v2.py >> "$LOG" 2>&1

# Step 3: Run risk officer validation
if [ -f scripts/risk_officer.py ]; then
    python3 scripts/risk_officer.py >> "$LOG" 2>&1
fi

echo "[$(date)] P1 morning pipeline complete" >> "$LOG"
