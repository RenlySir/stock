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
python run_stock_ai.py recommend-daily \
  --csv profile_input_20260508.csv \
  --as-of 2026-05-08 \
  --codes 600498,688820,300803 \
  --output-dir output/stock_ai/recommendation \
  --cc-connect /usr/local/bin/cc-connect \
  --wechat-project daily-market-news \
  --wechat-session weixin:dm:o9cq808Zm6pkjw0mJxDT8kaN4pKo@im.wechat \
  --wechat-outbox output/stock_ai/wechat_outbox
