"""Recover XFI Guard from a broken deployed revision."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path("/opt/xfi-guard")
SERVICE = "xfi-guard-bot"
BACKUP_BRANCH = "xfi-guard-pre-update"


def cmd(*args: str) -> str:
    return subprocess.run(args, cwd=REPO, text=True, capture_output=True).stdout.strip()


def notify(text: str) -> None:
    token = os.getenv("XFI_GUARD_BOT_TOKEN")
    admins = [x.strip() for x in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if x.strip().isdigit()]
    if not token:
        return
    for chat_id in admins:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps({"chat_id": int(chat_id), "text": text}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=10).close()
        except Exception as exc:
            print(f"notification failed: {exc}", file=sys.stderr)


def recent_polling() -> bool:
    return "polling запущен" in cmd("journalctl", "-u", SERVICE, "--since", "90 seconds ago", "--no-pager", "-o", "cat")


def main() -> int:
    try:
        restart_count = int(cmd("systemctl", "show", SERVICE, "-p", "NRestarts", "--value") or "0")
    except ValueError:
        return 0
    if restart_count < 3 or recent_polling():
        return 0
    backup = cmd("git", "rev-parse", BACKUP_BRANCH)
    if not backup:
        return 0
    current = cmd("git", "rev-parse", "HEAD")
    if current == backup:
        return 0
    notify(
        "🚨 XFI Guard не запустился после обновления\n\n"
        f"Текущая версия: {current[:8]}\n"
        f"Откат на: {backup[:8]}\n\n"
        "Выполняю автоматическое восстановление предыдущей версии."
    )
    subprocess.run(["git", "reset", "--hard", backup], cwd=REPO, check=False, timeout=120)
    subprocess.run(["systemctl", "daemon-reload"], check=False, timeout=30)
    subprocess.run(["systemctl", "restart", SERVICE], check=False, timeout=60)
    if cmd("systemctl", "is-active", SERVICE) == "active":
        notify(f"✅ XFI Guard восстановлен\n\nРабочая версия: {backup[:8]}")
        return 0
    notify("❌ Критическая ошибка: автоматическое восстановление XFI Guard не удалось.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
