from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .factors import add_factor_columns
from .strategy import StrategyConfig, select_candidates


@dataclass(frozen=True)
class BacktestConfig:
    start_date: str
    end_date: str
    initial_cash: float = 1_000_000
    top_n: int = 3
    position_pct: float = 0.20
    min_score: float = 45.0
    max_hold_days: int = 20
    stop_loss_pct: float = 0.08
    take_profit_pct: float = 0.20
    trailing_stop_pct: float = 0.12
    fee_rate: float = 0.0003
    tax_rate: float = 0.001
    slippage_bps: float = 5


@dataclass
class BacktestResult:
    summary: dict[str, float | int | str]
    trades: pd.DataFrame
    daily: pd.DataFrame
    positions: pd.DataFrame
    candidates: pd.DataFrame


def run_backtest(raw_bars: pd.DataFrame, config: BacktestConfig) -> BacktestResult:
    bars = add_factor_columns(raw_bars)
    dates = sorted(d for d in bars["date"].unique() if config.start_date <= d <= config.end_date)
    cash = float(config.initial_cash)
    positions: dict[str, dict[str, object]] = {}
    trade_rows: list[dict[str, object]] = []
    daily_rows: list[dict[str, object]] = []
    candidate_rows: list[dict[str, object]] = []
    realized_pnl = 0.0
    gross_profit = 0.0
    gross_loss = 0.0

    for date in dates:
        day_rows = bars[bars["date"] == date].set_index("code")
        for code, pos in list(positions.items()):
            if code not in day_rows.index:
                continue
            row = day_rows.loc[code]
            close = float(row["close"])
            pos["highest_close"] = max(float(pos["highest_close"]), close)
            hold_days = int(pos["hold_days"]) + 1
            pos["hold_days"] = hold_days
            ret = close / float(pos["buy_price"]) - 1
            trail = close / float(pos["highest_close"]) - 1
            sell_reason = None
            if ret <= -config.stop_loss_pct:
                sell_reason = "stop_loss"
            elif ret >= config.take_profit_pct:
                sell_reason = "take_profit"
            elif trail <= -config.trailing_stop_pct:
                sell_reason = "trailing_stop"
            elif hold_days >= config.max_hold_days:
                sell_reason = "max_hold_days"
            if sell_reason:
                sell_price = close * (1 - config.slippage_bps / 10000)
                shares = int(pos["shares"])
                proceeds = sell_price * shares
                fee = proceeds * (config.fee_rate + config.tax_rate)
                pnl = proceeds - fee - float(pos["cost"])
                cash += proceeds - fee
                realized_pnl += pnl
                gross_profit += max(pnl, 0)
                gross_loss += max(-pnl, 0)
                trade_rows.append(
                    {
                        "date": date,
                        "side": "SELL",
                        "code": code,
                        "name": pos["name"],
                        "shares": shares,
                        "price": round(sell_price, 4),
                        "amount": round(proceeds, 2),
                        "fee": round(fee, 2),
                        "pnl": round(pnl, 2),
                        "return_pct": round(pnl / float(pos["cost"]), 6),
                        "reason": sell_reason,
                    }
                )
                del positions[code]

        picks = select_candidates(bars, date, StrategyConfig(config.top_n, config.min_score))
        for pick in picks.to_dict("records"):
            candidate_rows.append(
                {
                    "date": date,
                    "code": pick["code"],
                    "name": pick.get("name", ""),
                    "combined_score": pick["combined_score"],
                    "reasons": pick.get("reasons", ""),
                    "risks": pick.get("risks", ""),
                }
            )
        for pick in picks.to_dict("records"):
            code = pick["code"]
            if code in positions or code not in day_rows.index:
                continue
            price = float(day_rows.loc[code, "close"]) * (1 + config.slippage_bps / 10000)
            budget = min(cash, config.initial_cash * config.position_pct)
            shares = int(budget // price // 100) * 100
            if shares <= 0:
                continue
            amount = price * shares
            fee = amount * config.fee_rate
            if amount + fee > cash:
                continue
            cash -= amount + fee
            positions[code] = {
                "code": code,
                "name": pick.get("name", ""),
                "shares": shares,
                "buy_date": date,
                "buy_price": price,
                "cost": amount + fee,
                "highest_close": float(day_rows.loc[code, "close"]),
                "hold_days": 0,
                "combined_score": pick["combined_score"],
            }
            trade_rows.append(
                {
                    "date": date,
                    "side": "BUY",
                    "code": code,
                    "name": pick.get("name", ""),
                    "shares": shares,
                    "price": round(price, 4),
                    "amount": round(amount, 2),
                    "fee": round(fee, 2),
                    "pnl": 0.0,
                    "return_pct": 0.0,
                    "reason": f"score={pick['combined_score']}",
                }
            )

        market_value = 0.0
        unrealized = 0.0
        for code, pos in positions.items():
            if code not in day_rows.index:
                continue
            close = float(day_rows.loc[code, "close"])
            value = close * int(pos["shares"])
            market_value += value
            unrealized += value - float(pos["cost"])
        equity = cash + market_value
        daily_rows.append(
            {
                "date": date,
                "cash": round(cash, 2),
                "market_value": round(market_value, 2),
                "equity": round(equity, 2),
                "realized_pnl": round(realized_pnl, 2),
                "unrealized_pnl": round(unrealized, 2),
                "open_positions": len(positions),
            }
        )

    trades = pd.DataFrame(trade_rows)
    daily = pd.DataFrame(daily_rows)
    position_df = pd.DataFrame(list(positions.values()))
    candidates = pd.DataFrame(candidate_rows)
    ending_equity = float(daily.iloc[-1]["equity"]) if not daily.empty else config.initial_cash
    max_drawdown = _max_drawdown(daily["equity"]) if not daily.empty else 0.0
    summary = {
        "initial_cash": round(config.initial_cash, 2),
        "ending_equity": round(ending_equity, 2),
        "total_pnl": round(ending_equity - config.initial_cash, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "realized_pnl": round(realized_pnl, 2),
        "open_positions": len(positions),
        "trade_count": len(trades),
        "buy_count": int((trades["side"] == "BUY").sum()) if not trades.empty else 0,
        "sell_count": int((trades["side"] == "SELL").sum()) if not trades.empty else 0,
        "max_drawdown_pct": round(max_drawdown, 6),
        "return_pct": round(ending_equity / config.initial_cash - 1, 6),
        "top_n": config.top_n,
        "min_score": config.min_score,
        "max_hold_days": config.max_hold_days,
    }
    return BacktestResult(summary, trades, daily, position_df, candidates)


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    drawdown = equity / peak - 1
    return float(drawdown.min())
