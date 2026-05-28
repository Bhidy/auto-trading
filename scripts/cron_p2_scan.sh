#!/bin/bash
# P2 Capitol Shadow — Scan & Trade
set -e
cd /Users/home/Documents/Auto\ Trading/political-copy-bot

LOG="logs/cron_p2_$(date +%Y-%m-%d).log"
echo "[$(date)] P2 scan starting" >> "$LOG"
python3 scripts/politician_bot.py scan >> "$LOG" 2>&1
echo "[$(date)] P2 scan complete" >> "$LOG"
