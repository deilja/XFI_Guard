"""Принудительная переустановка XFI Guard из origin/main с сохранением локальных изменений."""
from __future__ import annotations

import subprocess

from . import updater


def apply_force_update() -> int:
    if not updater.acquire_lock():
        updater.notify("⚠️ Обновление XFI Guard уже выполняется.")
        return 2

    old = ""
    stash = ""
    try:
        old = updater.local_head()
        stash = updater.preserve_local_changes()
        updater._write_status("принудительно", f"Начинаю принудительное обновление: {old[:8]}", old)
        updater.notify(
            "⚡ Принудительное обновление XFI Guard\n\n"
            f"Текущая версия: {old[:8]}\n"
            "Локальные изменения будут автоматически сохранены и восстановлены."
        )

        updater.run("git", "fetch", "--prune", "origin", "main", timeout=120)
        remote = updater.run("git", "rev-parse", "origin/main").stdout.strip()
        updater._install(remote, old)
        updater.restore_local_changes(stash)

        updater.clear_notified()
        updater._write_status("успешно", "XFI Guard принудительно переустановлен, локальные изменения восстановлены.", old, remote)
        updater.notify(
            "⚡✅ Принудительное обновление XFI Guard завершено\n\n"
            f"Было: {old[:8]}\n"
            f"Установлено: {remote[:8]}\n\n"
            "Локальные изменения сохранены. Бот работает."
        )
        return 0

    except Exception as exc:
        rollback_ok = False
        try:
            if old:
                updater.run("git", "reset", "--hard", old, timeout=120)
                if stash:
                    try:
                        updater.restore_local_changes(stash)
                    except Exception as restore_exc:
                        print(f"Local change restore after rollback failed: {restore_exc}")
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
            f"Автоматический откат: {'✅ выполнен' if rollback_ok else '❌ НЕ выполнен'}\n"
            "Локальные изменения не удалены."
        )
        return 1
    finally:
        updater.release_lock()


if __name__ == "__main__":
    raise SystemExit(apply_force_update())
