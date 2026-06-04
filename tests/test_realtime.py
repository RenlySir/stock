from __future__ import annotations

import unittest
import unittest.mock
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from stock_ai.realtime import CombinedQuoteProvider, EastMoneyQuoteProvider, Quote, RealtimeDecisionEngine, is_a_share_market_time, poll_realtime_once
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

    def test_poll_realtime_once_keeps_service_alive_when_quote_provider_fails(self) -> None:
        class FailingProvider:
            def fetch(self, codes: list[str]) -> list[Quote]:
                raise RuntimeError("network down")

        class RecordingSender:
            def __init__(self) -> None:
                self.messages: list[str] = []

            def send_or_queue(self, message: str, *, kind: str) -> None:
                self.messages.append(message)

        with TemporaryDirectory() as tmp:
            state_log = Path(tmp) / "realtime.log"

            poll_realtime_once(
                codes=["600498", "688820", "300803"],
                provider=FailingProvider(),
                sender=RecordingSender(),
                engine=RealtimeDecisionEngine(),
                state_log=state_log,
            )

            self.assertIn("quote fetch error", state_log.read_text(encoding="utf-8"))
            self.assertIn("network down", state_log.read_text(encoding="utf-8"))

    def test_combined_quote_provider_falls_back_when_primary_fails(self) -> None:
        class FailingProvider:
            name = "sina"

            def fetch(self, codes: list[str]) -> list[Quote]:
                raise RuntimeError("sina down")

        class WorkingProvider:
            name = "eastmoney"

            def fetch(self, codes: list[str]) -> list[Quote]:
                return [
                    Quote(
                        code="600498",
                        name="烽火通信",
                        price=52.97,
                        open=51.1,
                        previous_close=52.02,
                        high=53.99,
                        low=50.98,
                        volume=68132920,
                        amount=3608661942,
                        timestamp="2026-06-04 11:30:00",
                    )
                ]

        with TemporaryDirectory() as tmp:
            provider = CombinedQuoteProvider([FailingProvider(), WorkingProvider()])
            quotes = provider.fetch(["600498"], state_log=Path(tmp) / "provider.log")

            self.assertEqual(len(quotes), 1)
            self.assertEqual(quotes[0].code, "600498")
            log_text = (Path(tmp) / "provider.log").read_text(encoding="utf-8")
            self.assertIn("quote provider failed provider=sina", log_text)
            self.assertIn("quote provider ok provider=eastmoney count=1", log_text)

    def test_combined_quote_provider_fills_missing_codes_from_backup_provider(self) -> None:
        class PartialProvider:
            name = "sina"

            def fetch(self, codes: list[str]) -> list[Quote]:
                return [
                    Quote(
                        code="600498",
                        name="烽火通信",
                        price=52.97,
                        open=51.1,
                        previous_close=52.02,
                        high=53.99,
                        low=50.98,
                        volume=68132920,
                        amount=3608661942,
                        timestamp="2026-06-04 11:30:00",
                    )
                ]

        class BackupProvider:
            name = "eastmoney"

            def fetch(self, codes: list[str]) -> list[Quote]:
                return [
                    Quote(
                        code=code,
                        name=f"股票{code}",
                        price=10.0,
                        open=9.8,
                        previous_close=9.9,
                        high=10.2,
                        low=9.7,
                        volume=1000,
                        amount=10_000,
                        timestamp="2026-06-04 11:30:00",
                    )
                    for code in codes
                ]

        with TemporaryDirectory() as tmp:
            provider = CombinedQuoteProvider([PartialProvider(), BackupProvider()])
            quotes = provider.fetch(["600498", "688820", "300803"], state_log=Path(tmp) / "provider.log")

            self.assertEqual([quote.code for quote in quotes], ["600498", "688820", "300803"])
            log_text = (Path(tmp) / "provider.log").read_text(encoding="utf-8")
            self.assertIn("quote provider partial provider=sina count=1 missing=688820,300803", log_text)
            self.assertIn("quote provider filled provider=eastmoney count=2 total=3", log_text)

    def test_poll_realtime_once_logs_missing_codes_when_provider_returns_partial_data(self) -> None:
        class PartialProvider:
            def fetch(self, codes: list[str]) -> list[Quote]:
                return [
                    Quote(
                        code="600498",
                        name="烽火通信",
                        price=52.97,
                        open=51.1,
                        previous_close=52.02,
                        high=53.99,
                        low=50.98,
                        volume=68132920,
                        amount=3608661942,
                        timestamp="2026-06-04 11:30:00",
                    )
                ]

        class RecordingSender:
            def send_or_queue(self, message: str, *, kind: str) -> bool:
                return True

        with TemporaryDirectory() as tmp:
            state_log = Path(tmp) / "realtime.log"
            poll_realtime_once(
                codes=["600498", "688820", "300803"],
                provider=PartialProvider(),
                sender=RecordingSender(),
                engine=RealtimeDecisionEngine(),
                state_log=state_log,
            )

            log_text = state_log.read_text(encoding="utf-8")
            self.assertIn("quote fetch partial count=1 expected=3 missing=688820,300803", log_text)

    def test_eastmoney_provider_parses_ulist_response(self) -> None:
        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "rc": 0,
                    "data": {
                        "diff": [
                            {
                                "f2": 52.97,
                                "f5": 681329,
                                "f6": 3608661942.0,
                                "f12": "600498",
                                "f13": 1,
                                "f14": "烽火通信",
                                "f15": 53.99,
                                "f16": 50.98,
                                "f17": 51.1,
                                "f18": 52.02,
                                "f124": 1780547511,
                            }
                        ]
                    },
                }

        def fake_get(*args: object, **kwargs: object) -> FakeResponse:
            return FakeResponse()

        with unittest.mock.patch("stock_ai.realtime.requests.get", side_effect=fake_get):
            quotes = EastMoneyQuoteProvider().fetch(["600498"])

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].code, "600498")
        self.assertEqual(quotes[0].name, "烽火通信")
        self.assertEqual(quotes[0].price, 52.97)
        self.assertEqual(quotes[0].volume, 68132900)

    def test_eastmoney_provider_reports_malformed_json_cleanly(self) -> None:
        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> list[str]:
                return ["bad payload"]

        with unittest.mock.patch("stock_ai.realtime.requests.get", return_value=FakeResponse()):
            with self.assertRaisesRegex(RuntimeError, "eastmoney malformed response"):
                EastMoneyQuoteProvider().fetch(["600498"])


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
                        "industry": "通信设备" if code == "600498" else "电子",
                        "concepts": "算力;5G;光通信" if code == "600498" else "芯片",
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
        self.assertIn("名称：股票600498", rec.message)
        self.assertIn("行业：通信设备", rec.message)
        self.assertIn("概念题材：算力、5G、光通信", rec.message)
        self.assertIn("近5日交易量", rec.message)
        self.assertIn("近5日成交额", rec.message)
        self.assertIn("强化学习启发动作", rec.message)

    def test_recommendation_uses_fixed_metadata_fallback(self) -> None:
        dates = pd.bdate_range("2026-01-01", periods=70)
        rows = []
        for idx, date in enumerate(dates):
            close = 30 + idx * 0.2
            rows.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "code": "688820",
                    "name": "688820",
                    "open": close - 0.1,
                    "high": close + 0.2,
                    "low": close - 0.2,
                    "close": close,
                    "volume": 1_000_000 + idx * 10_000,
                    "amount": close * 1_000_000,
                    "pe": 15,
                    "pb": 2,
                    "roe": 16,
                }
            )

        rec = recommend_one_stock(pd.DataFrame(rows), ["688820"], as_of=dates[-1].strftime("%Y-%m-%d"))

        self.assertIn("名称：盛合晶微", rec.message)
        self.assertIn("行业：半导体", rec.message)
        self.assertIn("概念题材：先进封装、集成电路", rec.message)
        self.assertNotIn("行业：数据源未提供", rec.message)


if __name__ == "__main__":
    unittest.main()
