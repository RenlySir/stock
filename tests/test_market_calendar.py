from __future__ import annotations

import unittest
from datetime import datetime

from stock_ai.market_calendar import is_a_share_trading_day, is_a_share_trading_time


class MarketCalendarTest(unittest.TestCase):
    def test_2026_exchange_holidays_are_closed(self) -> None:
        closed_days = [
            "2026-01-01",
            "2026-02-16",
            "2026-02-23",
            "2026-04-06",
            "2026-05-01",
            "2026-06-19",
            "2026-09-25",
            "2026-10-01",
            "2026-10-07",
        ]
        for day in closed_days:
            with self.subTest(day=day):
                self.assertFalse(is_a_share_trading_day(day))

    def test_weekend_makeup_days_remain_closed(self) -> None:
        self.assertFalse(is_a_share_trading_day("2026-02-28"))
        self.assertFalse(is_a_share_trading_day("2026-05-09"))
        self.assertFalse(is_a_share_trading_day("2026-10-10"))

    def test_open_weekdays_and_intraday_sessions(self) -> None:
        self.assertTrue(is_a_share_trading_day("2026-02-24"))
        self.assertTrue(is_a_share_trading_time(datetime(2026, 2, 24, 9, 45)))
        self.assertTrue(is_a_share_trading_time(datetime(2026, 2, 24, 14, 59)))
        self.assertFalse(is_a_share_trading_time(datetime(2026, 2, 24, 11, 45)))
        self.assertFalse(is_a_share_trading_time(datetime(2026, 10, 1, 10, 0)))


if __name__ == "__main__":
    unittest.main()
