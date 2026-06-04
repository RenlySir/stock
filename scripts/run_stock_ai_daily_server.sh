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
python run_stock_ai.py backtest \
  --csv profile_input_20260508.csv \
  --start-date 2025-01-07 \
  --end-date 2026-05-08 \
  --initial-cash 1000000 \
  --top-n 3 \
  --min-score 45 \
  --max-hold-days 20 \
  --output-dir output/stock_ai/daily \
  --wechat \
  --cc-connect /usr/local/bin/cc-connect \
  --wechat-project daily-market-news \
  --wechat-session weixin:dm:o9cq808Zm6pkjw0mJxDT8kaN4pKo@im.wechat \
  --wechat-outbox output/stock_ai/wechat_outbox
