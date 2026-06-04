from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import requests

from stock_ai.history import fetch_sina_daily, load_or_fetch_histories


class HistoryFetchTest(unittest.TestCase):
    def test_fetch_daily_uses_eastmoney_when_akshare_and_sina_have_no_rows(self) -> None:
        class FakeResponse:
            text = "no usable sina rows"

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "rc": 0,
                    "data": {
                        "klines": [
                            "2026-06-03,50.00,52.00,53.00,49.50,12345,6543210.00,3.0,4.0,2.0,1.2",
                            "2026-06-04,52.00,53.00,54.00,51.00,23456,7654321.00,3.0,1.9,1.0,1.5",
                        ]
                    },
                }

        calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            calls.append(url)
            return FakeResponse()

        with patch("stock_ai.history._fetch_akshare_daily", return_value=pd.DataFrame()):
            with patch("stock_ai.history.requests.get", side_effect=fake_get):
                frame = fetch_sina_daily("600498", start_date="2026-06-01", end_date="2026-06-04")

        self.assertEqual(len(frame), 2)
        self.assertEqual(frame.iloc[-1]["code"], "600498")
        self.assertEqual(float(frame.iloc[-1]["close"]), 53.0)
        self.assertEqual(float(frame.iloc[-1]["volume"]), 2_345_600)
        self.assertTrue(any("push2his.eastmoney.com" in url for url in calls))

    def test_fetch_daily_uses_eastmoney_when_sina_disconnects(self) -> None:
        class FakeEastMoneyResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "rc": 0,
                    "data": {
                        "name": "烽火通信",
                        "klines": ["2026-06-04,52.00,53.00,54.00,51.00,23456,7654321.00,3.0,1.9,1.0,1.5"]
                    },
                }

        def fake_get(url: str, **kwargs: object) -> FakeEastMoneyResponse:
            if "finance.sina.com.cn" in url:
                raise requests.ConnectionError("Remote end closed connection without response")
            return FakeEastMoneyResponse()

        with patch("stock_ai.history._fetch_akshare_daily", return_value=pd.DataFrame()):
            with patch("stock_ai.history.requests.get", side_effect=fake_get):
                frame = fetch_sina_daily("600498", start_date="2026-06-01", end_date="2026-06-04")

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["name"], "烽火通信")
        self.assertEqual(float(frame.iloc[0]["close"]), 53.0)

    def test_load_or_fetch_histories_keeps_available_codes_when_one_code_fails(self) -> None:
        def fake_fetch(code: str, *, start_date: str, end_date: str) -> pd.DataFrame:
            if code == "688820":
                raise ValueError("temporary source failure")
            return pd.DataFrame(
                [
                    {
                        "date": "2026-06-04",
                        "code": code,
                        "name": code,
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10.5,
                        "volume": 1000,
                        "amount": 10500,
                        "pe": 0,
                        "pb": 0,
                        "roe": 0,
                    }
                ]
            )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("stock_ai.history.fetch_sina_daily", side_effect=fake_fetch):
                frame = load_or_fetch_histories(
                    ["600498", "688820", "300803"],
                    start_date="2026-06-01",
                    end_date="2026-06-04",
                    cache_dir=Path(tmp),
                )

        self.assertEqual(sorted(frame["code"].astype(str).tolist()), ["300803", "600498"])
        self.assertIn("688820: temporary source failure", frame.attrs["fetch_errors"])


if __name__ == "__main__":
    unittest.main()
