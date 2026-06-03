#!/usr/bin/env bash
set -euo pipefail

cd /opt/stock
. .venv/bin/activate
python run_stock_ai.py recommend-daily \
  --csv profile_input_20260508.csv \
  --as-of 2026-05-08 \
  --codes 600498,688820,300803 \
  --output-dir output/stock_ai/recommendation \
  --cc-connect /usr/local/bin/cc-connect \
  --wechat-project daily-market-news \
  --wechat-session weixin:dm:o9cq808Zm6pkjw0mJxDT8kaN4pKo@im.wechat \
  --wechat-outbox output/stock_ai/wechat_outbox
