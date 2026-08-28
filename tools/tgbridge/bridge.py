#!/usr/bin/env python3
"""Telegram allowlist bridge for the fixed Delta update command.

Secrets and runtime state live outside this repository. The bridge accepts only
STATUS and UPDATE from the configured Telegram chat; it never passes message
text through as a shell command.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(os.environ.get("DELTA_REPO", Path(__file__).resolve().parents[2]))
STATE_DIR = Path(os.environ.get("TG_BRIDGE_STATE_DIR", Path.home() / "tgbridge"))
TOKEN_FILE = Path(os.environ.get("TG_BRIDGE_TOKEN_FILE", STATE_DIR / "token"))
CHAT_ID_FILE = Path(os.environ.get("TG_BRIDGE_CHAT_ID_FILE", STATE_DIR / "chat_id"))
POLL_TIMEOUT_SECONDS = 45
UPDATE_TIMEOUT_SECONDS = 6 * 60 * 60
MAX_REPLY_CHARS = 3500


class BridgeError(RuntimeError):
    """Raised when bridge configuration is unavailable."""


def read_secret(path: Path, label: str) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BridgeError(f"Không đọc được {label}: {path}") from exc
    if not value:
        raise BridgeError(f"{label} đang trống: {path}")
    return value


def load_config() -> tuple[str, str]:
    token = read_secret(TOKEN_FILE, "token Telegram")
    chat_id = read_secret(CHAT_ID_FILE, "chat_id Telegram")
    if any(char.isspace() for char in token):
        raise BridgeError("Token Telegram không hợp lệ")
    if not chat_id.lstrip("-").isdigit():
        raise BridgeError("chat_id Telegram không hợp lệ")
    return token, chat_id


def telegram_api(token: str, method: str, **data: str) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=body, method="POST"
    )
    with urllib.request.urlopen(request, timeout=POLL_TIMEOUT_SECONDS + 15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise BridgeError(f"Telegram API lỗi: {payload.get('description', 'không rõ')}")
    return payload


def run_checked(args: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout, check=False
    )


def status_text() -> str:
    root = run_checked(["su", "-c", "id -u"], timeout=10)
    branch = run_checked(["git", "branch", "--show-current"])
    head = run_checked(["git", "log", "-1", "--oneline"])
    return "\n".join(
        (
            f"ROOT_RC={root.returncode}",
            f"ROOT_UID={(root.stdout or '').strip() or 'N/A'}",
            f"BRANCH={(branch.stdout or '').strip() or 'N/A'}",
            f"HEAD={(head.stdout or '').strip() or 'N/A'}",
        )
    )


def update_text() -> str:
    """Run the exact fixed updater, with no Telegram-provided arguments."""
    result = run_checked([sys.executable, "delta/delta_updater.py"], timeout=UPDATE_TIMEOUT_SECONDS)
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if len(output) > MAX_REPLY_CHARS:
        output = "…\n" + output[-MAX_REPLY_CHARS:]
    return f"UPDATE_RC={result.returncode}\n{output or '(không có output)'}"


def send(token: str, chat_id: str, text: str) -> None:
    telegram_api(token, "sendMessage", chat_id=chat_id, text=text[:3900])


def handle_message(token: str, allowed_chat_id: str, message: dict[str, Any]) -> None:
    chat_id = str((message.get("chat") or {}).get("id") or "")
    text = str(message.get("text") or "").strip().upper()
    if chat_id != allowed_chat_id:
        return
    if text == "STATUS":
        send(token, chat_id, status_text())
    elif text == "UPDATE":
        send(token, chat_id, "UPDATE đang chạy: tải → xác minh → giải nén → cài.")
        send(token, chat_id, update_text())
    else:
        send(token, chat_id, "Lệnh hợp lệ: STATUS hoặc UPDATE")


def main() -> int:
    token, allowed_chat_id = load_config()
    offset: int | None = None
    print("[bridge] ONLINE — chỉ nhận STATUS, UPDATE", flush=True)
    while True:
        try:
            params = {"timeout": str(POLL_TIMEOUT_SECONDS)}
            if offset is not None:
                params["offset"] = str(offset)
            updates = telegram_api(token, "getUpdates", **params).get("result", [])
            for item in updates:
                offset = int(item["update_id"]) + 1
                message = item.get("message")
                if isinstance(message, dict):
                    handle_message(token, allowed_chat_id, message)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"[bridge-error] {exc}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
