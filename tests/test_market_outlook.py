from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from stock_ai.market_outlook import MarketDataSnapshot, build_market_outlook_message, send_market_outlook
from stock_ai.notifier import ReliableWeChatSender


class MarketOutlookTest(unittest.TestCase):
    def test_build_market_outlook_message_contains_view_and_drivers(self) -> None:
        snapshot = MarketDataSnapshot(
            as_of="2026-06-03",
            index_rows=[
                {"name": "上证指数", "close": 3100.0, "pct_chg": 0.8},
                {"name": "深证成指", "close": 10000.0, "pct_chg": 0.5},
                {"name": "创业板指", "close": 2000.0, "pct_chg": -0.2},
            ],
            news_titles=["央行开展逆回购操作维护流动性", "AI芯片板块成交活跃", "外围市场风险偏好改善"],
            northbound_text="北向资金净流入 35 亿元",
        )

        message = build_market_outlook_message(snapshot)

        self.assertIn("明日大盘预测观点", message)
        self.assertIn("观点：", message)
        self.assertIn("上证指数", message)
        self.assertIn("央行开展逆回购", message)
        self.assertIn("不构成投资建议", message)

    def test_send_market_outlook_saves_and_sends_message(self) -> None:
        snapshot = MarketDataSnapshot(
            as_of="2026-06-03",
            index_rows=[{"name": "上证指数", "close": 3100.0, "pct_chg": 0.8}],
            news_titles=["政策预期升温"],
            northbound_text="资金面中性",
        )
        with tempfile.TemporaryDirectory() as tmp:
            sender = ReliableWeChatSender(
                cc_connect=Path("/usr/local/bin/cc-connect"),
                project="daily-market-news",
                session="weixin:dm:test@im.wechat",
                outbox_dir=Path(tmp) / "outbox",
                retries=1,
            )
            with patch("stock_ai.notifier.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stderr = ""
                run.return_value.stdout = ""
                ok = send_market_outlook(snapshot, sender=sender, output_dir=Path(tmp))

            self.assertTrue(ok)
            saved = Path(tmp) / "market_outlook_2026-06-03.txt"
            self.assertTrue(saved.exists())
            self.assertIn("政策预期升温", saved.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
