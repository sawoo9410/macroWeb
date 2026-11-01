"""Notifications: stdout always; macOS notification via osascript; Telegram when `TELEGRAM_BOT_TOKEN` and
`MACROWEB_TELEGRAM_CHAT_ID` are set in the environment (PLAN §11, §13.6). The bot token is only ever used
to build the request URL and is never logged; exceptions are reported by class name only."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

import httpx

from macroweb.paths import LOGS_DIR

TELEGRAM_LIMIT = 4000  # 4,096 hard limit; leave headroom


def _tail(job: str, n: int) -> str:
    log = LOGS_DIR / f"{job}.err.log"
    if n <= 0 or not log.exists():
        return ""
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    return "\n".join(lines)


def notify(
    level: str, job: str, message: str | None = None, tail: int = 0, rerun: str | None = None
) -> dict[str, str]:
    text = message or f"[macroweb/{job}] {level.upper()}"
    extra = _tail(job, tail)
    if extra:
        text += f"\n--- last {tail} lines of logs/{job}.err.log ---\n{extra}"
    if rerun:
        text += f"\n재실행: {rerun}"
    results: dict[str, str] = {"stdout": "ok"}
    print(text)

    if platform.system() == "Darwin":
        try:
            safe = text.splitlines()[0].replace('"', "'")[:120]
            subprocess.run(
                ["osascript", "-e", f'display notification "{safe}" with title "MacroWeb {job}"'],
                check=False,
                timeout=5,
                capture_output=True,
            )
            results["osascript"] = "ok"
        except (OSError, subprocess.SubprocessError) as exc:
            results["osascript"] = type(exc).__name__

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("MACROWEB_TELEGRAM_CHAT_ID")
    if token and chat_id:
        try:
            r = httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text[:TELEGRAM_LIMIT], "disable_web_page_preview": True},
                timeout=15,
            )
            results["telegram"] = str(r.status_code)
        except httpx.HTTPError as exc:
            results["telegram"] = type(exc).__name__
    else:
        results["telegram"] = "skipped (TELEGRAM_BOT_TOKEN / MACROWEB_TELEGRAM_CHAT_ID not set)"
    return results


def write_failure_note(job: str, note: str) -> Path:
    LOGS_DIR.mkdir(exist_ok=True)
    p = LOGS_DIR / f"{job}.last_failure.txt"
    p.write_text(note, encoding="utf-8")
    return p
