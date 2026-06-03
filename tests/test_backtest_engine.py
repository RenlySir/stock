from __future__ import annotations

import pandas as pd
import unittest

from stock_ai.backtest import BacktestConfig, run_backtest
from stock_ai.optimizer import optimize_strategy
from stock_ai.reports import format_wechat_summary


def sample_bars() -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2026-01-01", periods=80)
    for idx, date in enumerate(dates):
        day = date.strftime("%Y-%m-%d")
        strong_close = 10 + idx * 0.22
        weak_close = 20 - idx * 0.05
        rows.extend(
            [
                {
                    "date": day,
                    "code": "000001",
                    "name": "强势股",
                    "open": strong_close - 0.1,
                    "high": strong_close + 0.3,
                    "low": strong_close - 0.3,
                    "close": strong_close,
                    "volume": 1_000_000 + idx * 30_000,
                    "amount": strong_close * (1_000_000 + idx * 30_000),
                    "pe": 15,
                    "pb": 2,
                    "roe": 18,
                    "turnover_rate": 3,
                    "is_st": 0,
                    "delisting_risk": 0,
                    "negative_news": 0,
                },
                {
                    "date": day,
                    "code": "000002",
                    "name": "弱势股",
                    "open": weak_close + 0.1,
                    "high": weak_close + 0.2,
                    "low": weak_close - 0.4,
                    "close": weak_close,
                    "volume": 800_000,
                    "amount": weak_close * 800_000,
                    "pe": 30,
                    "pb": 5,
                    "roe": 6,
                    "turnover_rate": 1,
                    "is_st": 0,
                    "delisting_risk": 0,
                    "negative_news": 0,
                },
            ]
        )
    return pd.DataFrame(rows)


class BacktestEngineTest(unittest.TestCase):
    def test_backtest_records_trades_and_profit_summary(self) -> None:
        result = run_backtest(
            sample_bars(),
            BacktestConfig(
                start_date="2026-02-02",
                end_date="2026-04-15",
                initial_cash=1_000_000,
                top_n=1,
                position_pct=0.20,
                min_score=30,
                max_hold_days=20,
                stop_loss_pct=0.08,
                take_profit_pct=0.18,
                trailing_stop_pct=0.10,
                fee_rate=0,
                tax_rate=0,
                slippage_bps=0,
            ),
        )

        self.assertFalse(result.trades.empty)
        self.assertTrue({"BUY", "SELL"}.issubset(set(result.trades["side"])))
        self.assertEqual(result.summary["initial_cash"], 1_000_000)
        self.assertGreater(result.summary["gross_profit"], 0)
        self.assertEqual(result.summary["realized_pnl"], result.summary["gross_profit"] - result.summary["gross_loss"])
        self.assertAlmostEqual(result.summary["total_pnl"], result.summary["ending_equity"] - result.summary["initial_cash"], places=2)
        self.assertGreater(result.summary["ending_equity"], result.summary["initial_cash"])

    def test_optimizer_returns_best_parameter_set(self) -> None:
        result = optimize_strategy(
            sample_bars(),
            start_date="2026-02-02",
            end_date="2026-04-15",
            initial_cash=1_000_000,
            top_n_options=[1, 2],
            min_score_options=[20, 60],
            max_hold_day_options=[10, 20],
        )

        self.assertIsNotNone(result.best)
        assert result.best is not None
        self.assertGreaterEqual(result.best.summary["ending_equity"], 1_000_000)
        self.assertEqual(len(result.runs), 8)

    def test_wechat_summary_includes_trade_side_stock_and_price(self) -> None:
        result = run_backtest(
            sample_bars(),
            BacktestConfig(
                start_date="2026-02-02",
                end_date="2026-04-15",
                initial_cash=1_000_000,
                top_n=1,
                min_score=30,
                max_hold_days=20,
                fee_rate=0,
                tax_rate=0,
                slippage_bps=0,
            ),
        )

        message = format_wechat_summary(result)

        self.assertIn("初始资金：1,000,000", message)
        self.assertIn("买入：", message)
        self.assertIn("卖出：", message)
        self.assertIn("买入价：", message)
        self.assertIn("卖出价：", message)
        self.assertIn("强势股", message)

    def test_backtest_records_oskhquant_style_costs_and_annual_metrics(self) -> None:
        result = run_backtest(
            sample_bars().assign(code=lambda df: df["code"].replace({"000001": "600001"})),
            BacktestConfig(
                start_date="2026-02-02",
                end_date="2026-04-15",
                initial_cash=1_000_000,
                top_n=1,
                min_score=30,
                max_hold_days=20,
                fee_rate=0.0003,
                tax_rate=0.001,
                min_commission=5.0,
                transfer_fee_rate=0.00001,
                flow_fee=0.1,
                slippage_bps=10,
            ),
        )

        self.assertFalse(result.trades.empty)
        for column in ["commission", "stamp_tax", "transfer_fee", "flow_fee", "total_cost"]:
            self.assertIn(column, result.trades.columns)
        sells = result.trades[result.trades["side"] == "SELL"]
        buys = result.trades[result.trades["side"] == "BUY"]
        self.assertGreater(float(sells["stamp_tax"].sum()), 0)
        self.assertGreater(float(buys["transfer_fee"].sum()), 0)
        self.assertGreaterEqual(float(result.trades["commission"].min()), 5.0)
        self.assertIn("annual_return_pct", result.summary)
        self.assertIn("trade_days", result.summary)
        self.assertGreater(result.summary["trade_days"], 0)


if __name__ == "__main__":
    unittest.main()
