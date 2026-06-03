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
                    score = _objective_score(result)
                    run_rows.append(
                        {
                            "top_n": top_n,
                            "min_score": min_score,
                            "max_hold_days": max_hold_days,
                            "position_pct": position_pct,
                            "objective_score": round(score, 6),
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
        "objective": "ending_equity - drawdown_penalty - overtrade_penalty",
        **best_row,
    }
    config_payload["score"] = config_payload["objective_score"]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "strategy_config.json").write_text(json.dumps(config_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(run_rows).sort_values("objective_score", ascending=False).to_csv(output_dir / "strategy_runs.csv", index=False)
    db.save_strategy_config(config_payload)
    return StrategyUpdateResult(as_of=end_date, best=best, runs=run_rows, config=config_payload)


def _objective_score(result: BacktestResult) -> float:
    ending_equity = float(result.summary["ending_equity"])
    initial_cash = float(result.summary["initial_cash"])
    drawdown = abs(float(result.summary["max_drawdown_pct"]))
    trade_count = int(result.summary["trade_count"])
    drawdown_penalty = initial_cash * drawdown * 0.35
    overtrade_penalty = max(trade_count - 30, 0) * 500
    return ending_equity - drawdown_penalty - overtrade_penalty
