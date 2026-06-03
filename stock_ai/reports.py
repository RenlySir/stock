from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .backtest import BacktestResult
from .optimizer import OptimizationResult


def save_backtest_outputs(result: BacktestResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(result.summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result.trades.to_csv(output_dir / "trades.csv", index=False)
    result.daily.to_csv(output_dir / "daily_equity.csv", index=False)
    result.positions.to_csv(output_dir / "open_positions.csv", index=False)
    result.candidates.to_csv(output_dir / "candidates.csv", index=False)
    build_summary_message(result).to_csv(output_dir / "profit_summary.csv", index=False)


def save_optimization_outputs(result: OptimizationResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [run.summary for run in result.runs]
    pd.DataFrame(rows).to_csv(output_dir / "optimization_runs.csv", index=False)
    if result.best is not None:
        save_backtest_outputs(result.best, output_dir / "best")


def build_summary_message(result: BacktestResult) -> pd.DataFrame:
    trades = result.trades
    if trades.empty:
        return pd.DataFrame([{"metric": "message", "value": "暂无交易记录"}])
    sells = trades[trades["side"] == "SELL"].copy()
    rows = [
        {"metric": "初始资金", "value": result.summary["initial_cash"]},
        {"metric": "期末权益", "value": result.summary["ending_equity"]},
        {"metric": "合计盈利", "value": result.summary["gross_profit"]},
        {"metric": "合计亏损", "value": result.summary["gross_loss"]},
        {"metric": "总盈亏", "value": result.summary["total_pnl"]},
        {"metric": "收益率", "value": result.summary["return_pct"]},
        {"metric": "最大回撤", "value": result.summary["max_drawdown_pct"]},
        {"metric": "交易次数", "value": result.summary["trade_count"]},
    ]
    if not sells.empty:
        winners = int((sells["pnl"] > 0).sum())
        rows.append({"metric": "卖出胜率", "value": round(winners / len(sells), 4)})
    return pd.DataFrame(rows)


def format_wechat_summary(result: BacktestResult) -> str:
    summary = result.summary
    lines = [
        "【A股AI策略模拟交易】",
        "仅用于本地量化研究和模拟交易，不构成投资建议。",
        f"初始资金：{float(summary['initial_cash']):,.0f}",
        f"期末权益：{float(summary['ending_equity']):,.0f}",
        f"合计盈利：{float(summary['gross_profit']):,.0f}",
        f"合计亏损：{float(summary['gross_loss']):,.0f}",
        f"总盈亏：{float(summary['total_pnl']):,.0f}",
        f"收益率：{float(summary['return_pct']) * 100:.2f}%",
        f"最大回撤：{float(summary['max_drawdown_pct']) * 100:.2f}%",
        f"买入/卖出：{summary['buy_count']}/{summary['sell_count']}",
        f"当前持仓：{summary['open_positions']}",
    ]
    if not result.trades.empty:
        latest = result.trades.tail(5)
        lines.append("最近交易：")
        for row in latest.to_dict("records"):
            side = str(row["side"])
            if side == "BUY":
                lines.append(
                    f"- {row['date']} 买入：{row['code']} {row.get('name', '')}，"
                    f"买入价：{float(row['price']):.2f}，数量：{int(row['shares'])}股，"
                    f"金额：{float(row['amount']):,.0f}"
                )
            else:
                lines.append(
                    f"- {row['date']} 卖出：{row['code']} {row.get('name', '')}，"
                    f"卖出价：{float(row['price']):.2f}，数量：{int(row['shares'])}股，"
                    f"本笔盈亏：{float(row.get('pnl', 0)):,.0f}，"
                    f"收益率：{float(row.get('return_pct', 0)) * 100:.2f}%"
                )
    return "\n".join(lines)


def format_trade_alerts(result: BacktestResult, date: str | None = None) -> list[str]:
    if result.trades.empty:
        return []
    trades = result.trades.copy()
    if date is not None:
        trades = trades[trades["date"] == date]
    alerts = []
    for row in trades.to_dict("records"):
        side = "买入" if row["side"] == "BUY" else "卖出"
        lines = [
            f"【A股模拟交易{side}提醒】",
            "仅为本地模拟交易，不构成投资建议。",
            f"日期：{row['date']}",
            f"股票：{row['code']} {row.get('name', '')}",
            f"数量：{int(row['shares'])}股",
            f"价格：{float(row['price']):.2f}",
            f"金额：{float(row['amount']):,.0f}",
            f"原因：{row.get('reason', '')}",
        ]
        if row["side"] == "SELL":
            lines.append(f"本笔盈亏：{float(row.get('pnl', 0)):,.0f}")
            lines.append(f"收益率：{float(row.get('return_pct', 0)) * 100:.2f}%")
        alerts.append("\n".join(lines))
    return alerts
