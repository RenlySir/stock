# Stock AI

面向 A 股固定股票池的本地量化研究、模拟交易、策略自更新和微信通知程序。

当前程序为了适配低配云服务器，交易和推荐范围固定为三只股票：

- `600498` 烽火通信
- `688820` 盛合晶微
- `300803` 指南针

程序只做本地模拟交易和研究分析，不连接券商实盘，不构成投资建议。

## 核心功能

- 固定股票池实时监控：盘中只拉取三只股票行情，每秒刷新一次，触发模拟买入/卖出后微信通知。
- 每日盘后推荐：休市后基于本地 SQLite、技术因子、演进算子和轻量 RL 启发信号推荐一只股票。
- 明日大盘观点：综合主要指数、新闻舆情、A 股情感分析、资金线索生成次日观点。
- 算子演进：评估 MACD、RSI、KDJ、BOLL、动量、量价、突破、低波动等技术算子。
- 策略自动更新：每天盘后用 walk-forward 样本外验证选择策略参数，目标是提高盈利并控制过拟合。
- SQLite 存储：保存三只股票日线、推荐记录、算子权重、情绪指标和策略配置。
- 微信可靠发送：发送失败会进入 outbox，定时重试。

## 项目结构

```text
stock_ai/
  auto_update.py       # walk-forward 策略自更新
  backtest.py          # 回测引擎和交易成本模型
  cli.py               # 命令行入口
  history.py           # 历史行情拉取
  market_outlook.py    # 明日大盘观点
  operators.py         # 技术指标算子和算子演进
  realtime.py          # 盘中实时行情和模拟买卖
  recommendation.py    # 每日股票推荐
  rl_policy.py         # StockRL 启发的轻量动作评分
  sentiment.py         # A 股新闻情感分析
  storage.py           # SQLite 存储层
scripts/
  run_stock_ai_*_server.sh
tests/
  test_*.py
```

## 安装

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

主入口：

```bash
python3 run_stock_ai.py --help
```

## 常用命令

同步固定股票池日线到 SQLite：

```bash
python3 run_stock_ai.py sync-history \
  --codes 600498,688820,300803 \
  --start-date 2025-01-01 \
  --end-date 2026-06-03 \
  --db-path data/stock_ai.sqlite
```

盘后推荐一只股票：

```bash
python3 run_stock_ai.py recommend-daily \
  --csv profile_input_20260508.csv \
  --as-of 2026-06-03 \
  --codes 600498,688820,300803 \
  --db-path data/stock_ai.sqlite \
  --operator-weights output/stock_ai/operators/operator_weights.json
```

生成明日大盘观点：

```bash
python3 run_stock_ai.py market-outlook \
  --as-of 2026-06-03 \
  --db-path data/stock_ai.sqlite
```

演进技术指标算子：

```bash
python3 run_stock_ai.py evolve-operators \
  --csv profile_input_20260508.csv \
  --as-of 2026-06-03 \
  --codes 600498,688820,300803 \
  --db-path data/stock_ai.sqlite \
  --output-dir output/stock_ai/operators
```

自动更新策略参数：

```bash
python3 run_stock_ai.py auto-update-strategy \
  --codes 600498,688820,300803 \
  --start-date 2025-01-01 \
  --end-date 2026-06-03 \
  --lookback-days 180 \
  --db-path data/stock_ai.sqlite \
  --output-dir output/stock_ai/strategy_auto_update
```

启动盘中实时模拟监控：

```bash
python3 run_stock_ai.py realtime-monitor \
  --codes 600498,688820,300803 \
  --poll-seconds 1
```

## 服务器定时任务

当前服务器使用 cron 按 A 股交易日执行脚本。脚本内部会再次检查交易日，非交易日自动跳过。

```cron
0 15 * * 1-5    /opt/stock/scripts/run_stock_ai_daily_server.sh
10 15 * * 1-5   /opt/stock/scripts/run_stock_ai_market_outlook_server.sh
20 15 * * 1-5   /opt/stock/scripts/run_stock_ai_sync_history_server.sh
35 15 * * 1-5   /opt/stock/scripts/run_stock_ai_recommend_server.sh
30 16 * * 1-5   /opt/stock/scripts/run_stock_ai_evolve_server.sh
0 17 * * 1-5    /opt/stock/scripts/run_stock_ai_auto_update_server.sh
*/10 * * * *    /opt/stock/scripts/run_stock_ai_flush_wechat_server.sh
```

推荐执行顺序：

1. `15:10` 发送明日大盘观点和 A 股情感分析。
2. `15:20` 同步三只股票日线到 SQLite。
3. `15:35` 基于本地数据推荐一只股票。
4. `16:30` 演进技术指标算子。
5. `17:00` walk-forward 自动更新策略参数。
6. 每 10 分钟重试微信 outbox。

## SQLite 数据库

默认数据库路径：

```text
data/stock_ai.sqlite
```

主要表：

- `daily_bars`：固定三只股票日线。
- `recommendations`：每日推荐记录和完整消息。
- `operator_weights`：演进后的算子权重。
- `operator_scores`：算子 IC、命中率、前分位收益。
- `market_sentiment`：A 股新闻情感分析结果。
- `strategy_configs`：每日自动更新出的策略参数。

## 策略自更新逻辑

自更新不是简单选择历史收益最高参数，而是使用 walk-forward 样本外验证：

- 在最近 `lookback-days` 窗口内划分多个样本外验证区间。
- 每组参数在多个验证折上独立回测。
- 目标函数偏向盈利，同时惩罚回撤、收益不稳定、过度交易和不交易。

目标函数摘要：

```text
2 * 平均样本外收益
+ 0.5 * 最差折收益
- 0.7 * 平均样本外回撤
- 稳定性惩罚
- 过度交易惩罚
- 无交易/低收益惩罚
```

这会降低过拟合风险，但不能保证未来盈利。

## 情感分析

`sentiment.py` 参考股市情绪指数思路，对 A 股新闻标题做轻量词典分类：

```text
BI = log((1 + 正向条数) / (1 + 负向条数))
SI = (正向条数 - 负向条数) / (正向条数 + 负向条数)
```

该结果会写入 SQLite，并出现在每日 `15:10` 的大盘观点消息中。

## 微信通知

程序通过 `cc-connect` 发送微信消息。发送失败时会写入：

```text
output/stock_ai/wechat_outbox/
```

`run_stock_ai_flush_wechat_server.sh` 每 10 分钟自动重试。若看到 `ret=-2`，通常是微信端临时拒发或登录态问题，不代表量化程序主体失败。

## 输出文件

- `output/stock_ai/recommendation/`：每日推荐消息。
- `output/stock_ai/market_outlook/`：明日大盘观点。
- `output/stock_ai/operators/operator_weights.json`：算子权重。
- `output/stock_ai/operators/operator_scores.csv`：算子评分。
- `output/stock_ai/strategy_auto_update/strategy_config.json`：最新策略参数。
- `output/stock_ai/strategy_auto_update/strategy_runs.csv`：参数搜索结果。
- `output/stock_ai/backtest/`：回测摘要、交易流水、权益曲线。

## 测试

本地运行：

```bash
python3 -m unittest discover -s tests
```

服务器部署后也应运行同样命令确认：

```bash
cd /opt/stock
. .venv/bin/activate
python -m unittest discover -s tests
```

## 风险边界

- 当前仅模拟交易，不会向券商下实盘单。
- 当前股票池固定为三只股票，样本很小，策略稳定性有限。
- A 股新闻和行情接口可能断连，程序会降级并记录提示。
- 历史回测、walk-forward 和情绪分析都不能保证未来收益。
- 若要进入实盘，需要补充券商接口、风控审批、限价单/成交约束、异常熔断和人工确认。

## 参考思路

- 多因子选股：估值、质量、动量、风险控制。
- 动量效应：短中期收益、均线、量能确认。
- 技术指标：MACD、RSI、KDJ、BOLL、突破、低波动。
- 情感分析：正负新闻聚合、BI/SI 情绪指数。
- 强化学习启发：状态、动作、收益-回撤奖励代理。
- Walk-forward 验证：用样本外结果约束参数选择，降低过拟合。
