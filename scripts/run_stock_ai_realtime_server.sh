#!/usr/bin/env bash
set -euo pipefail

cd /opt/stock
. .venv/bin/activate
python run_stock_ai.py realtime-monitor \
  --codes 600498,688820,300803 \
  --poll-seconds 1 \
  --cc-connect /usr/local/bin/cc-connect \
  --wechat-project daily-market-news \
  --wechat-session weixin:dm:o9cq808Zm6pkjw0mJxDT8kaN4pKo@im.wechat \
  --wechat-outbox output/stock_ai/wechat_outbox \
  --state-log output/stock_ai/realtime_monitor.log
