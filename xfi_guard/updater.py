"""Safe XFI Guard updater.

Checks GitHub main, notifies administrators, applies the update only after
explicit confirmation, validates the new code, restarts the bot and rolls
back automatically if the new version does not become healthy.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path("/opt/xfi-guard")
SERVICE = "xfi-guard-bot"
GITHUB_API = "https://api.github.com/repos/deilja/XFI_Guard/commits/main"
LOCK_FILE = Path("/run/xfi-guard-update.lock")


def run(*args: str, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO, text=True, capture_output=True, timeout=timeout, check=check)


def notify(text: str, keyboard: list[list[dict]] | None = None) -> bool:
    token = os.getenv("XFI_GUARD_BOT_TOKEN")
    admin_ids = [x.strip() for x in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if x.strip().isdigit()]
    if not token or not admin_ids:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chat_id in admin_ids:
        payload: dict[str, object] = {"chat_id": int(chat_id), "text": text}
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15):
                pass
        except Exception as exc:
            print(f"Telegram notification failed: {exc}", file=sys.stderr)
    return True


def github_head() -> str:
    req = urllib.request.Request(
        GITHUB_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "XFI-Guard-Updater"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return str(json.loads(response.read().decode())["sha"])


def local_head() -> str:
    return run("git", "rev-parse", "HEAD").stdout.strip()


def acquire_lock() -> bool:
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def bot_healthy(wait: int = 20) -> bool:
    deadline = time.time() + wait
    while time.time() < deadline:
        status = subprocess.run(
            ["systemctl", "is-active", SERVICE], text=True, capture_output=True
        ).stdout.strip()
        if status == "active":
            logs = subprocess.run(
                ["journalctl", "-u", SERVICE, "-n", "40", "--no-pager", "-o", "cat"],
                text=True, capture_output=True,
            ).stdout
            if "polling запущен" in logs:
                return True
        time.sleep(2)
    return False


def validate() -> None:
    py = REPO / ".venv/bin/python"
    if not py.exists():
        raise RuntimeError(f"Не найден Python venv: {py}")
    run(str(py), "-m", "compileall", "-q", "xfi_guard", timeout=120)
    probe = run(str(py), "-c", "import xfi_guard.bot; print('IMPORT_OK')", timeout=30)
    if "IMPORT_OK" not in probe.stdout:
        raise RuntimeError("Не удалось импортировать xfi_guard.bot")


def check_update() -> int:
    if not acquire_lock():
        return 0
    try:
        current = local_head()
        remote = github_head()
        if current == remote:
            return 0
        notify(
            "🆕 Доступно обновление XFI Guard\n\n"
            f"Текущая версия: {current[:8]}\n"
            f"Новая версия: {remote[:8]}\n\n"
            "Обновление выполнится только после подтверждения.",
            [[{"text": "⬆️ Обновить XFI Guard", "callback_data": "xfi_update"}]],
        )
        print(f"Update available: {current} -> {remote}")
        return 0
    except Exception as exc:
        print(f"Update check failed: {exc}", file=sys.stderr)
        return 1
    finally:
        release_lock()


def apply_update() -> int:
    if not acquire_lock():
        notify("⚠️ Обновление XFI Guard уже выполняется.")
        return 2
    old = ""
    try:
        old = local_head()
        notify(f"⏳ Начинаю обновление XFI Guard\n\nВерсия: {old[:8]}")
        run("git", "fetch", "origin", "main", timeout=120)
        remote = run("git", "rev-parse", "origin/main").stdout.strip()
        if old == remote:
            notify("ℹ️ Обновление уже не требуется. Сервер работает на актуальной версии.")
            return 0

        run("git", "branch", "-f", "xfi-guard-pre-update", old)
        run("git", "reset", "--hard", "origin/main")

        req = REPO / "requirements-bot.txt"
        if req.exists():
            run(str(REPO / ".venv/bin/pip"), "install", "-r", str(req), timeout=300)
        validate()
        subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=30)
        subprocess.run(["systemctl", "restart", SERVICE], check=True, timeout=60)

        if bot_healthy():
            notify(
                "✅ XFI Guard успешно обновлён\n\n"
                f"Было: {old[:8]}\n"
                f"Стало: {remote[:8]}\n\n"
                "Бот снова работает."
            )
            return 0
        raise RuntimeError("Новая версия не прошла проверку работоспособности")
    except Exception as exc:
        rollback_ok = False
        if old:
            try:
                run("git", "reset", "--hard", old, timeout=120)
                subprocess.run(["systemctl", "daemon-reload"], check=False, timeout=30)
                subprocess.run(["systemctl", "restart", SERVICE], check=False, timeout=60)
                rollback_ok = bot_healthy()
            except Exception:
                rollback_ok = False
        notify(
            "❌ Обновление XFI Guard не удалось\n\n"
            f"Ошибка: {str(exc)[:700]}\n\n"
            f"Автоматический откат: {'✅ выполнен' if rollback_ok else '❌ НЕ выполнен'}"
        )
        print(f"Update failed: {exc}; rollback={rollback_ok}", file=sys.stderr)
        return 1
    finally:
        release_lock()


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(apply_update() if command == "apply" else check_update())
