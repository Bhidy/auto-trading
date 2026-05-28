#!/bin/bash
# Cron runner for Portfolio 1 — Quantitative Multi-Factor System
# Ensures proper PATH and environment for cron execution

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="/Users/home/Documents/Auto Trading/scripts"

BOT_DIR="/Users/home/Documents/Auto Trading"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
LOG_DIR="$BOT_DIR/logs"

mkdir -p "$LOG_DIR"

MODE="${1:-intraday-monitor}"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)

echo "[$TIMESTAMP] Running autonomous_runner.py in '$MODE' mode" >> "$LOG_DIR/cron.log"

$PYTHON "$BOT_DIR/scripts/autonomous_runner.py" "$MODE" >> "$LOG_DIR/cron_${MODE}_${TIMESTAMP}.log" 2>&1
EXIT_CODE=$?

echo "[$TIMESTAMP] Completed '$MODE' with exit code $EXIT_CODE" >> "$LOG_DIR/cron.log"
