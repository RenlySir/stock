from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .backtest import BacktestConfig, BacktestResult, run_backtest


@dataclass
class OptimizationResult:
    best: BacktestResult | None
    runs: list[BacktestResult]


def optimize_strategy(
    bars: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    initial_cash: float = 1_000_000,
    top_n_options: list[int] | None = None,
    min_score_options: list[float] | None = None,
    max_hold_day_options: list[int] | None = None,
) -> OptimizationResult:
    top_n_options = top_n_options or [1, 3, 5]
    min_score_options = min_score_options or [35, 45, 55]
    max_hold_day_options = max_hold_day_options or [10, 20, 40]
    runs: list[BacktestResult] = []
    for top_n in top_n_options:
        for min_score in min_score_options:
            for max_hold_days in max_hold_day_options:
                config = BacktestConfig(
                    start_date=start_date,
                    end_date=end_date,
                    initial_cash=initial_cash,
                    top_n=top_n,
                    min_score=min_score,
                    max_hold_days=max_hold_days,
                )
                runs.append(run_backtest(bars, config))
    best = max(
        runs,
        key=lambda result: (
            float(result.summary["ending_equity"]),
            -abs(float(result.summary["max_drawdown_pct"])),
            -int(result.summary["trade_count"]),
        ),
        default=None,
    )
    return OptimizationResult(best=best, runs=runs)
