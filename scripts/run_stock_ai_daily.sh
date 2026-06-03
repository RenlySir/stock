#!/usr/bin/env bash
set -euo pipefail

cd "/Users/lan/Documents/New project 3"
if ! python3 - <<'PY'
from stock_ai.market_calendar import is_a_share_trading_day
if not is_a_share_trading_day():
    print("skip: non A-share trading day")
    raise SystemExit(1)
PY
then
  exit 0
fi
python3 run_stock_ai.py daily-summary \
  --csv "profile_input_20260508.csv" \
  --start-date "2025-01-07" \
  --end-date "$(date +%Y-%m-%d)" \
  --output-dir "output/stock_ai/daily"
