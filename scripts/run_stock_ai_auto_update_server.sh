#!/usr/bin/env bash
set -euo pipefail

cd /opt/stock
. .venv/bin/activate
if ! python - <<'PY'
from stock_ai.market_calendar import is_a_share_trading_day
if not is_a_share_trading_day():
    print("skip: non A-share trading day")
    raise SystemExit(1)
PY
then
  exit 0
fi
python run_stock_ai.py auto-update-strategy \
  --codes 600498,688820,300803 \
  --start-date 2025-01-01 \
  --end-date "$(date +%F)" \
  --lookback-days 180 \
  --db-path data/stock_ai.sqlite \
  --output-dir output/stock_ai/strategy_auto_update
