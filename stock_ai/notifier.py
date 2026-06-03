from __future__ import annotations

import subprocess
import time
from pathlib import Path


class WeChatSendError(RuntimeError):
    pass


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
