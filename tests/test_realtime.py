from __future__ import annotations

import unittest
from datetime import datetime

import pandas as pd

from stock_ai.realtime import Quote, RealtimeDecisionEngine, is_a_share_market_time
from stock_ai.recommendation import recommend_one_stock


class RealtimeTradingTest(unittest.TestCase):
    def test_market_time_matches_a_share_sessions(self) -> None:
        self.assertTrue(is_a_share_market_time(datetime(2026, 6, 3, 9, 45)))
        self.assertTrue(is_a_share_market_time(datetime(2026, 6, 3, 14, 59)))
        self.assertFalse(is_a_share_market_time(datetime(2026, 6, 3, 11, 45)))
        self.assertFalse(is_a_share_market_time(datetime(2026, 6, 6, 10, 0)))

    def test_engine_generates_buy_and_sell_decisions(self) -> None:
        engine = RealtimeDecisionEngine(initial_cash=100_000, max_position_pct=0.20, lot_size=100)
        code = "600498"
        for idx in range(5):
            engine.on_quote(Quote(code=code, name="烽火通信", price=10 + idx * 0.04, open=10, previous_close=10, high=10.3, low=9.9, volume=1000 + idx * 100, amount=10_000, timestamp=f"09:30:0{idx}"))

        buy = engine.on_quote(Quote(code=code, name="烽火通信", price=10.35, open=10, previous_close=10, high=10.4, low=9.9, volume=3000, amount=31_000, timestamp="09:30:05"))

        self.assertIsNotNone(buy)
        assert buy is not None
        self.assertEqual(buy.side, "BUY")
        self.assertEqual(buy.code, code)
        self.assertGreaterEqual(buy.shares, 100)

        sell = engine.on_quote(Quote(code=code, name="烽火通信", price=9.75, open=10, previous_close=10, high=10.4, low=9.7, volume=4000, amount=39_000, timestamp="10:00:00"))

        self.assertIsNotNone(sell)
        assert sell is not None
        self.assertEqual(sell.side, "SELL")
        self.assertEqual(sell.code, code)


class RecommendationTest(unittest.TestCase):
    def test_recommend_one_stock_from_fixed_universe(self) -> None:
        dates = pd.bdate_range("2026-01-01", periods=70)
        rows = []
        for idx, date in enumerate(dates):
            for code, base, step, roe in [
                ("600498", 20, 0.10, 16),
                ("688820", 30, 0.02, 8),
                ("300803", 15, -0.01, 12),
            ]:
                close = base + idx * step
                rows.append(
                    {
                        "date": date.strftime("%Y-%m-%d"),
                        "code": code,
                        "name": f"股票{code}",
                        "open": close - 0.1,
                        "high": close + 0.2,
                        "low": close - 0.2,
                        "close": close,
                        "volume": 1_000_000 + idx * 10_000,
                        "amount": close * 1_000_000,
                        "pe": 15,
                        "pb": 2,
                        "roe": roe,
                    }
                )

        rec = recommend_one_stock(pd.DataFrame(rows), ["600498", "688820", "300803"], as_of=dates[-1].strftime("%Y-%m-%d"))

        self.assertEqual(rec.code, "600498")
        self.assertIn("推荐理由", rec.message)
        self.assertIn("600498", rec.message)


if __name__ == "__main__":
    unittest.main()
