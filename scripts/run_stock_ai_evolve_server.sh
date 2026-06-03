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
AS_OF="$(date +%F)"
python run_stock_ai.py evolve-operators \
  --csv profile_input_20260508.csv \
  --as-of "$AS_OF" \
  --horizon 5 \
  --top-n 5 \
  --output-dir output/stock_ai/operators
