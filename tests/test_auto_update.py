from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from stock_ai.auto_update import auto_update_strategy
from stock_ai.storage import StockDatabase


def auto_update_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=90)
    rows = []
    for idx, date in enumerate(dates):
        close = 10 + idx * 0.18
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "code": "600498",
                "name": "烽火通信",
                "open": close - 0.1,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": 1_000_000 + idx * 10_000,
                "amount": close * 1_000_000,
                "pe": 15,
                "pb": 2,
                "roe": 18,
            }
        )
    return pd.DataFrame(rows)


class AutoUpdateTest(unittest.TestCase):
    def test_auto_update_strategy_saves_best_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StockDatabase(Path(tmp) / "stock_ai.sqlite")
            db.upsert_daily_bars(auto_update_bars())

            result = auto_update_strategy(
                db,
                codes=["600498"],
                start_date="2026-02-01",
                end_date="2026-04-30",
                output_dir=Path(tmp),
                top_n_options=[1],
                min_score_options=[20, 40],
                max_hold_day_options=[10, 20],
            )

            saved = db.load_latest_strategy_config()
            self.assertIsNotNone(result.best)
            self.assertEqual(saved["as_of"], "2026-04-30")
            self.assertIn("score", saved)
            self.assertEqual(saved["validation"], "walk_forward")
            self.assertIn("out_of_sample_score", saved)
            self.assertGreaterEqual(saved["fold_count"], 1)
            self.assertGreater(saved["trade_count"], 0)
            self.assertTrue((Path(tmp) / "strategy_config.json").exists())


if __name__ == "__main__":
    unittest.main()
