from __future__ import annotations

import tempfile
import unittest
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from stock_ai.notifier import ReliableWeChatSender, WeChatSendError


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

    def test_ret_minus_two_does_not_restart_cc_connect_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sender = ReliableWeChatSender(
                cc_connect=Path("/usr/local/bin/cc-connect"),
                project="daily-market-news",
                session="weixin:dm:test@im.wechat",
                outbox_dir=Path(tmp) / "outbox",
                retries=2,
                retry_sleep_sec=0,
            )
            commands: list[list[str]] = []

            def fake_run(command: list[str], **kwargs: object) -> object:
                commands.append(command)

                class Result:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                if command[1] == "send":
                    Result.returncode = 1
                    Result.stderr = "weixin: sendMessage: ret=-2 errcode=0 errmsg="
                return Result()

            with patch("stock_ai.notifier.subprocess.run", side_effect=fake_run):
                with self.assertRaises(WeChatSendError):
                    sender.send("微信暂时拒绝的消息")

            self.assertNotIn(["/usr/local/bin/cc-connect", "daemon", "restart"], commands)

    def test_ret_minus_two_fails_fast_without_repeating_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sender = ReliableWeChatSender(
                cc_connect=Path("/usr/local/bin/cc-connect"),
                project="daily-market-news",
                session="weixin:dm:test@im.wechat",
                outbox_dir=Path(tmp) / "outbox",
                retries=3,
                retry_sleep_sec=0,
            )
            commands: list[list[str]] = []

            def fake_run(command: list[str], **kwargs: object) -> object:
                commands.append(command)

                class Result:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                if command[1] == "send":
                    Result.returncode = 1
                    Result.stderr = "weixin: sendMessage: ret=-2 errcode=0 errmsg="
                return Result()

            with patch("stock_ai.notifier.subprocess.run", side_effect=fake_run):
                with self.assertRaises(WeChatSendError):
                    sender.send("微信登录态失效")

            send_calls = [command for command in commands if command[1] == "send"]
            self.assertEqual(len(send_calls), 1)

    def test_flush_outbox_skips_cooldown_and_quarantines_exhausted_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outbox = Path(tmp) / "outbox"
            outbox.mkdir()
            cooldown_message = outbox / "cooldown.json"
            exhausted_message = outbox / "exhausted.json"
            cooldown_message.write_text(
                json.dumps(
                    {
                        "kind": "summary",
                        "message": "刚失败过，先冷却",
                        "attempts": 1,
                        "last_attempt_at": datetime.now().isoformat(timespec="seconds"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            exhausted_message.write_text(
                json.dumps(
                    {
                        "kind": "summary",
                        "message": "失败太多次，进入隔离",
                        "attempts": 12,
                        "last_attempt_at": (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            sender = ReliableWeChatSender(
                cc_connect=Path("/usr/local/bin/cc-connect"),
                project="daily-market-news",
                session="weixin:dm:test@im.wechat",
                outbox_dir=outbox,
                retries=1,
                max_outbox_attempts=12,
                outbox_cooldown_sec=3600,
            )

            with patch("stock_ai.notifier.subprocess.run") as run:
                flushed = sender.flush_outbox()

            self.assertEqual(flushed.sent, 0)
            self.assertEqual(flushed.failed, 0)
            self.assertEqual(flushed.skipped, 1)
            self.assertEqual(flushed.quarantined, 1)
            self.assertTrue(cooldown_message.exists())
            self.assertFalse(exhausted_message.exists())
            self.assertTrue((outbox / "dead_letter" / "exhausted.json").exists())
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
