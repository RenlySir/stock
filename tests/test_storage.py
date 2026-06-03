from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from stock_ai.operators import OperatorEvolutionResult, OperatorScore
from stock_ai.recommendation import StockRecommendation
from stock_ai.storage import StockDatabase


class StockDatabaseTest(unittest.TestCase):
    def test_upserts_and_loads_daily_bars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StockDatabase(Path(tmp) / "stock_ai.sqlite")
            bars = pd.DataFrame(
                [
                    {
                        "date": "2026-06-01",
                        "code": "600498",
                        "name": "烽火通信",
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10.5,
                        "volume": 1_000_000,
                        "amount": 10_500_000,
                        "pe": 12,
                        "pb": 1.5,
                        "roe": 15,
                    }
                ]
            )

            db.upsert_daily_bars(bars)
            db.upsert_daily_bars(bars.assign(close=10.8))
            loaded = db.load_daily_bars(["600498"], start_date="2026-06-01", end_date="2026-06-02")

            self.assertEqual(len(loaded), 1)
            self.assertEqual(float(loaded.iloc[0]["close"]), 10.8)

    def test_saves_recommendation_and_operator_evolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StockDatabase(Path(tmp) / "stock_ai.sqlite")
            rec = StockRecommendation(
                code="600498",
                name="烽火通信",
                score=66.5,
                message="推荐消息",
            )
            result = OperatorEvolutionResult(
                as_of="2026-06-03",
                horizon=5,
                codes=["600498", "688820", "300803"],
                weights={"op_momentum_20": 1.0},
                scores=[
                    OperatorScore(
                        name="op_momentum_20",
                        ic=0.12,
                        top_quantile_return=0.03,
                        hit_rate=0.6,
                        sample_size=100,
                        weight=1.0,
                    )
                ],
            )

            db.save_recommendation(as_of="2026-06-03", recommendation=rec)
            db.save_operator_evolution(result)

            recommendations = db.load_recommendations()
            weights = db.load_latest_operator_weights()

            self.assertEqual(recommendations.iloc[0]["code"], "600498")
            self.assertEqual(recommendations.iloc[0]["message"], "推荐消息")
            self.assertEqual(weights, {"op_momentum_20": 1.0})


if __name__ == "__main__":
    unittest.main()
