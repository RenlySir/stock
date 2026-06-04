from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from stock_ai.cli import _refresh_or_keep_existing_histories


class CliHistoryFallbackTest(unittest.TestCase):
    def test_keeps_existing_history_when_remote_refresh_fails(self) -> None:
        existing = pd.DataFrame(
            [
                {
                    "date": "2026-05-08",
                    "code": "600498",
                    "name": "烽火通信",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                    "volume": 1000,
                    "amount": 10500,
                }
            ]
        )

        with patch("stock_ai.cli.load_or_fetch_histories", side_effect=ValueError("remote disconnected")):
            frame, note = _refresh_or_keep_existing_histories(
                ["600498"],
                existing_bars=existing,
                history_start="2025-01-01",
                as_of="2026-06-04",
                cache_dir=Path("data/cache"),
            )

        self.assertEqual(frame.iloc[0]["code"], "600498")
        self.assertIn("历史刷新失败，使用本地缓存", note)
        self.assertIn("remote disconnected", note)


if __name__ == "__main__":
    unittest.main()
