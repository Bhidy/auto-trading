#!/bin/bash
# Cron runner for the Politician Copy Trading Bot
# Ensures proper PATH and environment for cron execution

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="/Users/home/Documents/Auto Trading/political-copy-bot/scripts"

BOT_DIR="/Users/home/Documents/Auto Trading/political-copy-bot"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
LOG_DIR="$BOT_DIR/logs"

mkdir -p "$LOG_DIR"

MODE="${1:-scan}"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)

echo "[$TIMESTAMP] Running politician_bot.py in '$MODE' mode" >> "$LOG_DIR/cron.log"

$PYTHON "$BOT_DIR/scripts/politician_bot.py" "$MODE" >> "$LOG_DIR/cron_${MODE}_${TIMESTAMP}.log" 2>&1
EXIT_CODE=$?

echo "[$TIMESTAMP] Completed with exit code $EXIT_CODE" >> "$LOG_DIR/cron.log"
