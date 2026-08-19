"""Принудительное переустановочное обновление XFI Guard из origin/main."""
from __future__ import annotations

import subprocess

from . import updater


def apply_force_update() -> int:
    """Переустанавливает текущий origin/main даже если SHA не изменился."""
    if not updater.acquire_lock():
        updater.notify("⚠️ Обновление XFI Guard уже выполняется.")
        return 2

    old = ""
    try:
        if not updater.worktree_clean():
            raise RuntimeError(
                "Рабочее дерево Git содержит реальные локальные изменения. "
                "Принудительное обновление остановлено."
            )

        old = updater.local_head()
        updater._write_status("принудительно", f"Начинаю принудительное обновление: {old[:8]}", old)
        updater.notify(
            "⚡ Принудительное обновление XFI Guard\n\n"
            f"Текущая версия: {old[:8]}\n"
            "Даже при совпадающем SHA будет выполнена переустановка."
        )

        updater.run("git", "fetch", "--prune", "origin", "main", timeout=120)
        remote = updater.run("git", "rev-parse", "origin/main").stdout.strip()

        updater.run("git", "branch", "-f", updater.ROLLBACK_BRANCH, old)
        updater.run("git", "reset", "--hard", "origin/main")

        req = updater.REPO / "requirements-bot.txt"
        if req.exists():
            updater.run(
                str(updater.REPO / ".venv/bin/pip"),
                "install",
                "-r",
                str(req),
                timeout=300,
            )

        updater.validate()
        subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=30)
        subprocess.run(["systemctl", "restart", updater.SERVICE], check=True, timeout=60)

        if not updater.bot_healthy():
            raise RuntimeError("Принудительно установленная версия не прошла health-check бота")

        updater.clear_notified()
        updater._write_status("успешно", "XFI Guard принудительно переустановлен.", old, remote)
        updater.notify(
            "⚡✅ Принудительное обновление XFI Guard завершено\n\n"
            f"Было: {old[:8]}\n"
            f"Установлено: {remote[:8]}\n\n"
            "Бот снова работает."
        )
        return 0

    except Exception as exc:
        rollback_ok = False
        if old:
            try:
                updater.run("git", "reset", "--hard", old, timeout=120)
                subprocess.run(["systemctl", "daemon-reload"], check=False, timeout=30)
                subprocess.run(["systemctl", "restart", updater.SERVICE], check=False, timeout=60)
                rollback_ok = updater.bot_healthy()
                updater.clear_notified()
            except Exception as rollback_exc:
                print(f"Rollback failed: {type(rollback_exc).__name__}: {rollback_exc}")

        updater._write_status("ошибка", str(exc), old)
        updater.notify(
            "❌ Принудительное обновление XFI Guard не удалось\n\n"
            f"Ошибка: {type(exc).__name__}: {str(exc)[:650]}\n\n"
            f"Автоматический откат: {'✅ выполнен' if rollback_ok else '❌ НЕ выполнен'}"
        )
        return 1
    finally:
        updater.release_lock()


if __name__ == "__main__":
    raise SystemExit(apply_force_update())
