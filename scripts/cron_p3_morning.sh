#!/bin/bash
# P3 Cautious Sniper — Full Morning Pipeline
set -e
cd /Users/home/Documents/Auto\ Trading/event-driven-bot

LOG="logs/cron_p3_$(date +%Y-%m-%d).log"
echo "[$(date)] P3 morning pipeline starting" >> "$LOG"

# Weekly screen on Mondays only
if [ "$(date +%u)" = "1" ]; then
    echo "[$(date)] Running weekly screen (Monday)" >> "$LOG"
    python3 scripts/event_driven_bot.py weekly-screen >> "$LOG" 2>&1
fi

python3 scripts/event_driven_bot.py morning-scan >> "$LOG" 2>&1
python3 scripts/event_driven_bot.py trading-session >> "$LOG" 2>&1
python3 scripts/event_driven_bot.py news-scan >> "$LOG" 2>&1 || true

echo "[$(date)] P3 morning pipeline complete" >> "$LOG"
