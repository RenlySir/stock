from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4


class WeChatSendError(RuntimeError):
    pass


@dataclass(frozen=True)
class FlushResult:
    sent: int
    failed: int
    skipped: int = 0
    quarantined: int = 0


def send_wechat(
    message: str,
    *,
    cc_connect: Path,
    project: str,
    session: str,
    retries: int = 2,
) -> None:
    last_error = ""
    for attempt in range(1, retries + 1):
        subprocess.run([str(cc_connect), "daemon", "status"], check=False, capture_output=True, text=True)
        proc = subprocess.run(
            [str(cc_connect), "send", "-p", project, "-s", session, "--stdin"],
            input=message,
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return
        last_error = (proc.stderr or proc.stdout or f"cc-connect failed: {proc.returncode}").strip()
        if attempt < retries:
            subprocess.run([str(cc_connect), "daemon", "restart"], check=False, capture_output=True, text=True)
            time.sleep(1)
    raise WeChatSendError(last_error)


class ReliableWeChatSender:
    def __init__(
        self,
        *,
        cc_connect: Path,
        project: str,
        session: str,
        outbox_dir: Path,
        retries: int = 3,
        retry_sleep_sec: float = 2.0,
        max_outbox_attempts: int = 12,
        outbox_cooldown_sec: int = 1800,
    ) -> None:
        self.cc_connect = cc_connect
        self.project = project
        self.session = session
        self.outbox_dir = outbox_dir
        self.retries = retries
        self.retry_sleep_sec = retry_sleep_sec
        self.max_outbox_attempts = max_outbox_attempts
        self.outbox_cooldown_sec = outbox_cooldown_sec

    def send_or_queue(self, message: str, *, kind: str) -> bool:
        try:
            self.send(message)
            return True
        except WeChatSendError as exc:
            self.queue(message, kind=kind, error=str(exc))
            return False

    def send(self, message: str) -> None:
        last_error = ""
        for attempt in range(1, self.retries + 1):
            try:
                subprocess.run([str(self.cc_connect), "daemon", "status"], check=False, capture_output=True, text=True)
                proc = subprocess.run(
                    [str(self.cc_connect), "send", "-p", self.project, "-s", self.session, "--stdin"],
                    input=message,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except OSError as exc:
                last_error = str(exc)
                if attempt < self.retries:
                    time.sleep(self.retry_sleep_sec)
                    continue
                raise WeChatSendError(last_error) from exc
            if proc.returncode == 0:
                return
            last_error = (proc.stderr or proc.stdout or f"cc-connect failed: {proc.returncode}").strip()
            if _is_unrecoverable_wechat_error(last_error):
                raise WeChatSendError(last_error)
            if attempt < self.retries:
                self._restart_if_needed(last_error)
                time.sleep(self.retry_sleep_sec)
        raise WeChatSendError(last_error)

    def flush_outbox(self) -> FlushResult:
        sent = 0
        failed = 0
        skipped = 0
        quarantined = 0
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.outbox_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if int(payload.get("attempts", 0)) >= self.max_outbox_attempts:
                self._quarantine(path)
                quarantined += 1
                continue
            if self._in_cooldown(payload):
                skipped += 1
                continue
            try:
                self.send(str(payload["message"]))
            except WeChatSendError as exc:
                payload["attempts"] = int(payload.get("attempts", 0)) + 1
                payload["last_error"] = str(exc)
                payload["last_attempt_at"] = datetime.now().isoformat(timespec="seconds")
                if int(payload["attempts"]) >= self.max_outbox_attempts:
                    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    self._quarantine(path)
                    quarantined += 1
                else:
                    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    failed += 1
                continue
            path.unlink()
            sent += 1
        return FlushResult(sent=sent, failed=failed, skipped=skipped, quarantined=quarantined)

    def queue(self, message: str, *, kind: str, error: str) -> Path:
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        path = self.outbox_dir / f"{now.strftime('%Y%m%d_%H%M%S')}_{kind}_{uuid4().hex[:8]}.json"
        payload = {
            "kind": kind,
            "message": message,
            "project": self.project,
            "session": self.session,
            "created_at": now.isoformat(timespec="seconds"),
            "attempts": 0,
            "last_error": error,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _restart_if_needed(self, error: str) -> None:
        lower = error.lower()
        if any(
            token in lower
            for token in (
                "api.sock",
                "connection refused",
                "failed to connect",
                "another cc-connect instance",
            )
        ):
            subprocess.run([str(self.cc_connect), "daemon", "restart"], check=False, capture_output=True, text=True)

    def _in_cooldown(self, payload: dict[str, object]) -> bool:
        last_attempt = payload.get("last_attempt_at")
        if not last_attempt:
            return False
        try:
            last_dt = datetime.fromisoformat(str(last_attempt))
        except ValueError:
            return False
        return (datetime.now() - last_dt).total_seconds() < self.outbox_cooldown_sec

    def _quarantine(self, path: Path) -> Path:
        dead_letter = self.outbox_dir / "dead_letter"
        dead_letter.mkdir(parents=True, exist_ok=True)
        target = dead_letter / path.name
        shutil.move(str(path), str(target))
        return target


def _is_unrecoverable_wechat_error(error: str) -> bool:
    lower = error.lower()
    return "weixin:" in lower and "ret=-2" in lower
