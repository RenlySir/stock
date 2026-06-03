from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from stock_ai.operators import add_operator_columns, evolve_operators, save_operator_evolution
from stock_ai.recommendation import recommend_one_stock


def operator_sample_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=90)
    rows = []
    for idx, date in enumerate(dates):
        day = date.strftime("%Y-%m-%d")
        for code, base, drift, roe in [
            ("600498", 10, 0.18, 16),
            ("688820", 30, 0.02, 9),
            ("300803", 18, -0.03, 12),
        ]:
            close = base + idx * drift
            rows.append(
                {
                    "date": day,
                    "code": code,
                    "name": f"股票{code}",
                    "open": close - 0.05,
                    "high": close + 0.2,
                    "low": close - 0.2,
                    "close": close,
                    "volume": 1_000_000 + idx * 20_000,
                    "amount": close * (1_000_000 + idx * 20_000),
                    "pe": 15,
                    "pb": 2,
                    "roe": roe,
                }
            )
    return pd.DataFrame(rows)


class OperatorEvolutionTest(unittest.TestCase):
    def test_add_operator_columns_includes_common_tonghuashun_style_indicators(self) -> None:
        frame = add_operator_columns(operator_sample_bars())

        for column in [
            "macd_dif",
            "macd_dea",
            "macd_hist",
            "rsi6",
            "kdj_k",
            "kdj_d",
            "kdj_j",
            "boll_mid",
            "boll_upper",
            "boll_lower",
            "op_momentum_20",
        ]:
            self.assertIn(column, frame.columns)

        latest = frame[frame["code"] == "600498"].tail(1).iloc[0]
        self.assertGreater(latest["op_momentum_20"], 0)
        self.assertGreater(latest["boll_upper"], latest["boll_mid"])

    def test_evolve_operators_ranks_predictive_operator_and_saves_weights(self) -> None:
        result = evolve_operators(operator_sample_bars(), as_of="2026-04-30", horizon=5, top_n=5)

        self.assertGreaterEqual(len(result.scores), 1)
        self.assertIn("op_momentum_20", result.weights)
        self.assertGreater(result.weights["op_momentum_20"], 0)
        self.assertAlmostEqual(sum(result.weights.values()), 1.0, places=6)

        with tempfile.TemporaryDirectory() as tmp:
            saved = save_operator_evolution(result, Path(tmp))
            payload = json.loads((saved["weights"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["horizon"], 5)
            self.assertIn("op_momentum_20", payload["weights"])
            self.assertTrue(saved["scores"].exists())

    def test_recommendation_uses_evolved_operator_weights_when_available(self) -> None:
        bars = operator_sample_bars()
        result = evolve_operators(bars, as_of="2026-04-30", horizon=5, top_n=5)

        with tempfile.TemporaryDirectory() as tmp:
            saved = save_operator_evolution(result, Path(tmp))
            rec = recommend_one_stock(
                bars,
                ["600498", "688820", "300803"],
                as_of="2026-04-30",
                operator_weights_path=saved["weights"],
            )

        self.assertEqual(rec.code, "600498")
        self.assertIn("演进算子评分", rec.message)
        self.assertIn("600498", rec.message)


if __name__ == "__main__":
    unittest.main()
