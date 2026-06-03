from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .backtest import BacktestConfig, BacktestResult, run_backtest
from .storage import StockDatabase


@dataclass(frozen=True)
class StrategyUpdateResult:
    as_of: str
    best: BacktestResult | None
    runs: list[dict[str, float | int]]
    config: dict[str, float | int | str]


def auto_update_strategy(
    db: StockDatabase,
    *,
    codes: list[str],
    start_date: str,
    end_date: str,
    output_dir: Path,
    initial_cash: float = 1_000_000,
    top_n_options: list[int] | None = None,
    min_score_options: list[float] | None = None,
    max_hold_day_options: list[int] | None = None,
    position_pct_options: list[float] | None = None,
) -> StrategyUpdateResult:
    bars = db.load_daily_bars(codes, start_date=start_date, end_date=end_date)
    if bars.empty:
        raise ValueError("no daily bars available for strategy auto update")
    top_n_options = top_n_options or [1]
    min_score_options = min_score_options or [20, 40, 60]
    max_hold_day_options = max_hold_day_options or [10, 20]
    position_pct_options = position_pct_options or [0.15, 0.25]
    best: BacktestResult | None = None
    best_score = float("-inf")
    run_rows: list[dict[str, float | int]] = []
    folds = _walk_forward_folds(bars, min_folds=3)
    for top_n in top_n_options:
        for min_score in min_score_options:
            for max_hold_days in max_hold_day_options:
                for position_pct in position_pct_options:
                    config = BacktestConfig(
                        start_date=start_date,
                        end_date=end_date,
                        initial_cash=initial_cash,
                        top_n=top_n,
                        min_score=min_score,
                        max_hold_days=max_hold_days,
                        position_pct=position_pct,
                    )
                    result = run_backtest(bars, config)
                    fold_metrics = _walk_forward_score(bars, config, folds)
                    score = fold_metrics["out_of_sample_score"]
                    run_rows.append(
                        {
                            "top_n": top_n,
                            "min_score": min_score,
                            "max_hold_days": max_hold_days,
                            "position_pct": position_pct,
                            "objective_score": round(score, 6),
                            "out_of_sample_score": round(fold_metrics["out_of_sample_score"], 6),
                            "avg_oos_return": round(fold_metrics["avg_oos_return"], 6),
                            "worst_oos_return": round(fold_metrics["worst_oos_return"], 6),
                            "avg_oos_drawdown": round(fold_metrics["avg_oos_drawdown"], 6),
                            "fold_count": int(fold_metrics["fold_count"]),
                            "ending_equity": float(result.summary["ending_equity"]),
                            "return_pct": float(result.summary["return_pct"]),
                            "max_drawdown_pct": float(result.summary["max_drawdown_pct"]),
                            "trade_count": int(result.summary["trade_count"]),
                        }
                    )
                    if score > best_score:
                        best_score = score
                        best = result
    if best is None:
        raise ValueError("auto update did not produce a strategy result")
    best_row = max(run_rows, key=lambda row: float(row["objective_score"]))
    config_payload: dict[str, float | int | str] = {
        "as_of": end_date,
        "codes": ",".join(str(code).zfill(6) for code in codes),
        "validation": "walk_forward",
        "objective": "out_of_sample_return + worst_fold_return - drawdown_penalty - overtrade_penalty",
        **best_row,
    }
    config_payload["score"] = config_payload["objective_score"]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "strategy_config.json").write_text(json.dumps(config_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(run_rows).sort_values("objective_score", ascending=False).to_csv(output_dir / "strategy_runs.csv", index=False)
    db.save_strategy_config(config_payload)
    return StrategyUpdateResult(as_of=end_date, best=best, runs=run_rows, config=config_payload)


def _walk_forward_folds(bars: pd.DataFrame, *, min_folds: int = 3) -> list[tuple[str, str]]:
    dates = sorted(str(date) for date in bars["date"].unique())
    if len(dates) < 30:
        return [(dates[0], dates[-1])] if dates else []
    fold_count = min(min_folds, max(1, len(dates) // 20))
    validation_size = max(10, len(dates) // (fold_count + 2))
    folds: list[tuple[str, str]] = []
    for idx in range(fold_count):
        end = len(dates) - idx * validation_size
        start = max(0, end - validation_size)
        if start >= end:
            continue
        folds.append((dates[start], dates[end - 1]))
    return list(reversed(folds))


def _walk_forward_score(bars: pd.DataFrame, base_config: BacktestConfig, folds: list[tuple[str, str]]) -> dict[str, float | int]:
    returns: list[float] = []
    drawdowns: list[float] = []
    trade_counts: list[int] = []
    for start_date, end_date in folds:
        config = BacktestConfig(
            start_date=start_date,
            end_date=end_date,
            initial_cash=base_config.initial_cash,
            top_n=base_config.top_n,
            position_pct=base_config.position_pct,
            min_score=base_config.min_score,
            max_hold_days=base_config.max_hold_days,
            stop_loss_pct=base_config.stop_loss_pct,
            take_profit_pct=base_config.take_profit_pct,
            trailing_stop_pct=base_config.trailing_stop_pct,
            fee_rate=base_config.fee_rate,
            tax_rate=base_config.tax_rate,
            slippage_bps=base_config.slippage_bps,
            min_commission=base_config.min_commission,
            transfer_fee_rate=base_config.transfer_fee_rate,
            flow_fee=base_config.flow_fee,
            trading_days_per_year=base_config.trading_days_per_year,
        )
        result = run_backtest(bars, config)
        returns.append(float(result.summary["return_pct"]))
        drawdowns.append(abs(float(result.summary["max_drawdown_pct"])))
        trade_counts.append(int(result.summary["trade_count"]))
    if not returns:
        return {
            "out_of_sample_score": float("-inf"),
            "avg_oos_return": 0.0,
            "worst_oos_return": 0.0,
            "avg_oos_drawdown": 0.0,
            "fold_count": 0,
        }
    avg_return = sum(returns) / len(returns)
    worst_return = min(returns)
    avg_drawdown = sum(drawdowns) / len(drawdowns)
    avg_trades = sum(trade_counts) / len(trade_counts)
    stability_penalty = _return_std(returns) * 0.5
    overtrade_penalty = max(avg_trades - 10, 0) * 0.002
    no_trade_penalty = 0.08 if sum(trade_counts) == 0 else 0.0
    low_profit_penalty = 0.03 if avg_return <= 0 else 0.0
    score = 2.0 * avg_return + 0.5 * worst_return - 0.7 * avg_drawdown - stability_penalty - overtrade_penalty - no_trade_penalty - low_profit_penalty
    return {
        "out_of_sample_score": score,
        "avg_oos_return": avg_return,
        "worst_oos_return": worst_return,
        "avg_oos_drawdown": avg_drawdown,
        "fold_count": len(returns),
    }


def _return_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return variance**0.5
