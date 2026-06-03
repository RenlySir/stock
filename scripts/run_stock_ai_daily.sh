#!/usr/bin/env bash
set -euo pipefail

cd "/Users/lan/Documents/New project 3"
python3 run_stock_ai.py daily-summary \
  --csv "profile_input_20260508.csv" \
  --start-date "2025-01-07" \
  --end-date "$(date +%Y-%m-%d)" \
  --output-dir "output/stock_ai/daily"
