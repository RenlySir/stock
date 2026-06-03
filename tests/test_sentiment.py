from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stock_ai.sentiment import analyze_market_sentiment
from stock_ai.storage import StockDatabase


class MarketSentimentTest(unittest.TestCase):
    def test_analyze_market_sentiment_computes_bullish_index(self) -> None:
        result = analyze_market_sentiment(
            [
                "政策利好推动AI板块上涨",
                "北向资金流入，市场风险偏好改善",
                "地产板块承压，指数回落",
            ],
            as_of="2026-06-03",
        )

        self.assertEqual(result.positive_count, 2)
        self.assertEqual(result.negative_count, 1)
        self.assertGreater(result.bullish_index, 0)
        self.assertIn("BI", result.summary)

    def test_stock_database_saves_market_sentiment(self) -> None:
        result = analyze_market_sentiment(["利好上涨", "风险承压"], as_of="2026-06-03")
        with tempfile.TemporaryDirectory() as tmp:
            db = StockDatabase(Path(tmp) / "stock_ai.sqlite")
            db.save_market_sentiment(result)
            loaded = db.load_latest_market_sentiment()

        self.assertEqual(loaded["as_of"], "2026-06-03")
        self.assertEqual(int(loaded["positive_count"]), 1)
        self.assertIn("bullish_index", loaded)


if __name__ == "__main__":
    unittest.main()
