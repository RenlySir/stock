# Stock AI 模拟交易程序

本程序用于本地 A 股量化研究、因子选股、模拟交易、回测、参数搜索和微信通知。默认初始资金为 100 万元。

## 功能

- 因子选股：估值、ROE、动量、均线、成交额、放量、回撤、波动和风险字段综合评分。
- 策略优化：自动搜索 `top_n`、`min_score`、`max_hold_days`，按期末权益、回撤和交易次数选择最佳组合。
- 模拟交易：按评分买入，按止损、止盈、移动止损、最大持仓天数卖出。
- 自我算子演进：生成 MACD、RSI、KDJ、BOLL、动量、量价、突破、低波动等公开技术指标算子，按历史未来收益评估 IC、命中率和前分位收益，并把权重用于次日推荐。
- 回测报表：记录所有买入、卖出、已实现盈亏、浮盈浮亏、总盈利、总亏损和最大回撤。
- 微信通知：通过本机 `cc-connect` 向配置的微信会话发送买卖和日报摘要。
- 明日大盘预测：盘后综合主要指数、资金线索和市场新闻关键词，生成次日大盘观点并微信发送。
- SQLite 本地存储：固定股票池日线、每日推荐、算子权重和评分会写入本地轻量数据库，减少重复拉取。
- 每日 15:00：可用 `cron` 或 `launchd` 调用 `scripts/run_stock_ai_daily.sh`。

## 运行示例

筛选候选股：

```bash
python3 run_stock_ai.py screen --csv profile_input_20260508.csv --as-of 2026-05-08 --top-n 5 --min-score 45
```

回测：

```bash
python3 run_stock_ai.py backtest \
  --csv profile_input_20260508.csv \
  --start-date 2025-01-07 \
  --end-date 2026-05-08 \
  --initial-cash 1000000 \
  --output-dir output/stock_ai/backtest
```

自动寻找最佳参数：

```bash
python3 run_stock_ai.py optimize \
  --csv profile_input_20260508.csv \
  --start-date 2025-01-07 \
  --end-date 2026-05-08 \
  --initial-cash 1000000 \
  --output-dir output/stock_ai/optimization
```

演进技术指标算子：

```bash
python3 run_stock_ai.py evolve-operators \
  --csv profile_input_20260508.csv \
  --as-of 2026-05-08 \
  --horizon 5 \
  --top-n 5 \
  --codes 600498,688820,300803 \
  --output-dir output/stock_ai/operators
```

同步固定股票池日线到 SQLite：

```bash
python3 run_stock_ai.py sync-history \
  --codes 600498,688820,300803 \
  --start-date 2025-01-01 \
  --end-date 2026-06-03 \
  --db-path data/stock_ai.sqlite
```

发送微信日报：

```bash
python3 run_stock_ai.py daily-summary \
  --csv profile_input_20260508.csv \
  --start-date 2025-01-07 \
  --end-date 2026-05-08
```

发送明日大盘预测观点：

```bash
python3 run_stock_ai.py market-outlook --as-of 2026-06-03
```

## 每天下午 3 点发送

macOS/Linux cron 示例：

```cron
0 15 * * 1-5 /bin/bash "/Users/lan/Documents/New project 3/scripts/run_stock_ai_daily.sh" >> "/Users/lan/Documents/New project 3/output/stock_ai/daily_cron.log" 2>&1
```

## 输出文件

- `summary.json`：资金、收益、回撤、交易次数汇总。
- `trades.csv`：历史所有买入和卖出流水及每笔卖出盈亏。
- `daily_equity.csv`：每日现金、持仓市值、权益、已实现盈亏、浮盈浮亏。
- `open_positions.csv`：当前未平仓持仓。
- `candidates.csv`：每日候选股。
- `profit_summary.csv`：可读的盈亏摘要。
- `operator_weights.json`：自我演进选出的算子权重，用于每日 8:50 固定三只股票推荐。
- `operator_scores.csv`：每个候选算子的 IC、前分位未来收益、命中率和样本数。
- `market_outlook_YYYY-MM-DD.txt`：每日 15:10 发送的明日大盘预测观点。
- `data/stock_ai.sqlite`：SQLite 数据库，存储日线、推荐记录、算子权重和评分。

## 注意

这是研究和模拟交易程序，不连接券商实盘，不构成投资建议。真实使用前需要补充更完整的数据源、复权处理、交易日历、滑点模型、成交约束和风控审批。

## 参考依据

- Fama-French 多因子思想：使用估值、质量和风险因子做组合筛选。
- Jegadeesh-Titman 与 Carhart 动量思想：加入 5 日/20 日动量、均线和放量确认。
- Backtrader/同类开源回测框架实践：使用现金、持仓、交易流水、资产曲线和回撤指标拆分回测状态。本仓库为轻量自研实现，便于和现有 CSV、微信通知脚本集成。
