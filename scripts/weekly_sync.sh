#!/usr/bin/env bash
# Weekly scrape + embedding sync for CinePulse.
# Designed to be run via cron every Sunday.
#
# Usage (manual):
#   bash scripts/weekly_sync.sh
#
# Cron (every Sunday at 02:00):
#   0 2 * * 0 /path/to/CinePulse/scripts/weekly_sync.sh >> /path/to/CinePulse/logs/weekly_sync.log 2>&1

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"

echo "=== CinePulse weekly sync started at $(date) ==="

source "$REPO_DIR/venv/bin/activate"

cd "$REPO_DIR"
python scrapers/run_spider_and_embed.py

echo "=== CinePulse weekly sync finished at $(date) ==="
