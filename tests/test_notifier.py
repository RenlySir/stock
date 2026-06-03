from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_ai.notifier import ReliableWeChatSender


class ReliableWeChatSenderTest(unittest.TestCase):
    def test_failed_message_is_queued_and_later_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outbox = Path(tmp) / "outbox"
            sender = ReliableWeChatSender(
                cc_connect=Path("/usr/local/bin/cc-connect"),
                project="daily-market-news",
                session="weixin:dm:test@im.wechat",
                outbox_dir=outbox,
                retries=1,
            )

            with patch("stock_ai.notifier.subprocess.run") as run:
                run.return_value.returncode = 1
                run.return_value.stderr = "gateway error"
                run.return_value.stdout = ""

                sent = sender.send_or_queue("测试消息", kind="summary")

            self.assertFalse(sent)
            queued = list(outbox.glob("*.json"))
            self.assertEqual(len(queued), 1)
            self.assertIn("测试消息", queued[0].read_text(encoding="utf-8"))

            with patch("stock_ai.notifier.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stderr = ""
                run.return_value.stdout = ""

                flushed = sender.flush_outbox()

            self.assertEqual(flushed.sent, 1)
            self.assertEqual(flushed.failed, 0)
            self.assertFalse(list(outbox.glob("*.json")))

    def test_missing_cc_connect_binary_is_queued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sender = ReliableWeChatSender(
                cc_connect=Path("/path/that/does/not/exist"),
                project="daily-market-news",
                session="weixin:dm:test@im.wechat",
                outbox_dir=Path(tmp) / "outbox",
                retries=1,
            )

            sent = sender.send_or_queue("缺少命令也要入队", kind="summary")

            self.assertFalse(sent)
            self.assertEqual(len(list((Path(tmp) / "outbox").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
