"""Безопасное обновление XFI Guard.

Локальные изменения администратора сохраняются во время обновления и
восстанавливаются после установки новой версии. Источник релизов — origin/main.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(os.getenv("XFI_GUARD_REPO", "/opt/xfi-guard"))
SERVICE = os.getenv("XFI_GUARD_SERVICE", "xfi-guard-bot")
GITHUB_API = "https://api.github.com/repos/deilja/XFI_Guard/commits/main"
LOCK_FILE = Path("/run/xfi-guard-update.lock")
NOTIFIED_FILE = Path("/var/lib/xfi-guard/update-notified")
STATUS_FILE = Path("/var/lib/xfi-guard/update-status.json")
ENV_FILE = Path("/etc/xfi-guard/bot.env")
ROLLBACK_BRANCH = "xfi-guard-pre-update"
LOCAL_STASH_PREFIX = "xfi-guard-auto-preserve"
GENERATED_DIRS = ("xfi_guard/__pycache__", "tests/__pycache__", ".pytest_cache", "xfi_guard.egg-info")


def _load_env_file() -> None:
    if not ENV_FILE.is_file(): return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        key, value = line.split("=", 1)
        key = key.strip(); value = value.strip().strip('"').strip("'")
        if key and key not in os.environ: os.environ[key] = value


_load_env_file()


def run(*args: str, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO, text=True, capture_output=True, timeout=timeout, check=check)


def _cleanup_generated() -> None:
    """Remove Python/build artefacts that must never be restored from Git stash."""
    for relative in GENERATED_DIRS:
        path = REPO / relative
        if path.is_dir(): shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            try: path.unlink()
            except OSError: pass
    for path in REPO.rglob("*.pyc"):
        try: path.unlink()
        except OSError: pass


def telegram_api_base() -> str:
    value = os.getenv("XFI_GUARD_TELEGRAM_API_URL", "").strip()
    if not value: return "https://api.telegram.org/"
    if value.startswith(("https://", "http://")): return value.rstrip("/") + "/"
    print("Некорректный XFI_GUARD_TELEGRAM_API_URL; используется https://api.telegram.org/", file=sys.stderr)
    return "https://api.telegram.org/"


def _write_status(status: str, message: str, old: str = "", new: str = "") -> None:
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps({"status": status, "message": message, "old": old, "new": new, "time": int(time.time())}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(STATUS_FILE, 0o600)
    except OSError as exc: print(f"Could not write update status: {exc}", file=sys.stderr)


def notify(text: str, keyboard: list[list[dict]] | None = None) -> bool:
    _load_env_file(); token = os.getenv("XFI_GUARD_BOT_TOKEN", "").strip(); admin_ids = [x.strip() for x in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if x.strip().isdigit()]
    if not token or not admin_ids:
        print("Telegram notification skipped: XFI_GUARD_BOT_TOKEN/XFI_GUARD_ADMIN_IDS not configured", file=sys.stderr); return False
    endpoint = f"{telegram_api_base().rstrip('/')}/bot{token}/sendMessage"; ok = True
    for chat_id in admin_ids:
        payload: dict[str, object] = {"chat_id": int(chat_id), "text": text}
        if keyboard: payload["reply_markup"] = {"inline_keyboard": keyboard}
        req = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json", "User-Agent": "XFI-Guard-Updater"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                body = json.loads(response.read().decode())
                if not body.get("ok"): raise RuntimeError(str(body))
        except Exception as exc:
            ok = False; print(f"Telegram notification failed for {chat_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return ok


def github_head() -> str:
    req = urllib.request.Request(GITHUB_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "XFI-Guard-Updater"})
    with urllib.request.urlopen(req, timeout=20) as response: data = json.loads(response.read().decode())
    sha = str(data.get("sha", "")).strip()
    if len(sha) != 40: raise RuntimeError("GitHub не вернул корректный SHA main")
    return sha


def local_head() -> str: return run("git", "rev-parse", "HEAD").stdout.strip()


def worktree_clean() -> bool:
    result = run("git", "status", "--porcelain", check=True).stdout.splitlines()
    ignored_untracked_prefixes = ("?? build/", "?? xfi_guard.egg-info/", "?? xfi_guard/__pycache__/", "?? backup/", "?? .pytest_cache/", "?? tests/__pycache__/")
    ignored_untracked_suffixes = (".bak", ".pyc")
    for line in result:
        if any(line.startswith(prefix) for prefix in ignored_untracked_prefixes): continue
        if line.startswith("?? ") and line[3:].endswith(ignored_untracked_suffixes): continue
        return False
    return True


def preserve_local_changes() -> str:
    _cleanup_generated()
    status = run("git", "status", "--porcelain").stdout.strip()
    if not status: return ""
    marker = f"{LOCAL_STASH_PREFIX}-{int(time.time())}"
    result = run("git", "stash", "push", "--include-untracked", "-m", marker, timeout=120)
    if result.returncode != 0: raise RuntimeError(f"Не удалось сохранить локальные изменения: {result.stderr.strip()[-500:]}")
    for line in run("git", "stash", "list", "--format=%H %gs").stdout.splitlines():
        if marker in line: return line.split(" ", 1)[0]
    raise RuntimeError("Git stash создан, но его идентификатор не найден")


def restore_local_changes(stash: str) -> None:
    if not stash: return
    _cleanup_generated()
    result = run("git", "stash", "apply", "--index", stash, check=False, timeout=120)
    if result.returncode != 0:
        _cleanup_generated()
        retry = run("git", "stash", "apply", stash, check=False, timeout=120)
        if retry.returncode != 0:
            raise RuntimeError(f"Локальные изменения сохранены в stash {stash}, но не применились автоматически: {retry.stderr.strip()[-700:]}")
    run("git", "stash", "drop", stash, check=False, timeout=30)


def acquire_lock() -> bool:
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.write(fd, str(os.getpid()).encode()); os.close(fd); return True
    except FileExistsError: return False


def release_lock() -> None:
    try: LOCK_FILE.unlink()
    except FileNotFoundError: pass


def read_notified() -> str:
    try: return NOTIFIED_FILE.read_text().strip()
    except FileNotFoundError: return ""


def write_notified(value: str) -> None:
    NOTIFIED_FILE.parent.mkdir(parents=True, exist_ok=True); NOTIFIED_FILE.write_text(value + "\n")


def clear_notified() -> None:
    try: NOTIFIED_FILE.unlink()
    except FileNotFoundError: pass


def bot_healthy(wait: int = 30) -> bool:
    deadline = time.time() + wait
    while time.time() < deadline:
        status = subprocess.run(["systemctl", "is-active", SERVICE], text=True, capture_output=True).stdout.strip()
        if status == "active":
            logs = subprocess.run(["journalctl", "-u", SERVICE, "-n", "80", "--no-pager", "-o", "cat"], text=True, capture_output=True).stdout
            if "polling запущен" in logs or "polling" in logs.lower(): return True
        time.sleep(2)
    return False


def validate() -> None:
    py = REPO / ".venv/bin/python"
    if not py.exists(): raise RuntimeError(f"Не найден Python venv: {py}")
    run(str(py), "-m", "compileall", "-q", "xfi_guard", timeout=120)
    probe = run(str(py), "-c", "import xfi_guard.bot; print('IMPORT_OK')", timeout=30)
    if "IMPORT_OK" not in probe.stdout: raise RuntimeError("Не удалось импортировать xfi_guard.bot")


def _install(remote: str, old: str) -> None:
    run("git", "branch", "-f", ROLLBACK_BRANCH, old); run("git", "reset", "--hard", remote)
    req = REPO / "requirements-bot.txt"
    if req.exists(): run(str(REPO / ".venv/bin/pip"), "install", "-r", str(req), timeout=300)
    validate(); subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=30); subprocess.run(["systemctl", "restart", SERVICE], check=True, timeout=60)
    if not bot_healthy(): raise RuntimeError("Новая версия не прошла проверку работоспособности")


def check_update() -> int:
    if not acquire_lock(): return 0
    try:
        current = local_head(); remote = github_head()
        if current == remote: clear_notified(); _write_status("актуально", "XFI Guard уже обновлён.", current, remote); return 0
        if read_notified() == remote: return 0
        text = f"🆕 Доступно обновление XFI Guard\n\nТекущая версия: {current[:8]}\nНовая версия: {remote[:8]}\n\nНажмите кнопку для установки."
        if notify(text, [[{"text": "⬆️ Обновить XFI Guard", "callback_data": "xfi_update"}]]): write_notified(remote)
        _write_status("доступно", text, current, remote); return 0
    except Exception as exc: _write_status("ошибка", str(exc)); print(f"Update check failed: {type(exc).__name__}: {exc}", file=sys.stderr); return 1
    finally: release_lock()


def apply_update() -> int:
    if not acquire_lock(): notify("⚠️ Обновление XFI Guard уже выполняется."); return 2
    old = ""; stash = ""
    try:
        old = local_head(); stash = preserve_local_changes(); _write_status("запущено", f"Начинаю обновление: {old[:8]}", old)
        notify(f"⏳ Начинаю обновление XFI Guard\n\nВерсия: {old[:8]}\nЛокальные изменения сохранены: {'да' if stash else 'нет'}")
        run("git", "fetch", "--prune", "origin", "main", timeout=120); remote = run("git", "rev-parse", "origin/main").stdout.strip()
        if old == remote and not stash: clear_notified(); _write_status("актуально", "Сервер уже на актуальном main.", old, remote); return 0
        _install(remote, old); restore_local_changes(stash); clear_notified(); _write_status("успешно", "XFI Guard успешно обновлён, локальные изменения восстановлены.", old, remote)
        notify(f"✅ XFI Guard обновлён\n\nБыло: {old[:8]}\nСтало: {remote[:8]}\n\nЛокальные изменения сохранены и восстановлены. Бот работает."); return 0
    except Exception as exc:
        rollback_ok = False
        try:
            if old:
                run("git", "reset", "--hard", old, timeout=120)
                if stash:
                    try: restore_local_changes(stash)
                    except Exception as restore_exc: print(f"Local change restore after rollback failed: {restore_exc}", file=sys.stderr)
                subprocess.run(["systemctl", "daemon-reload"], check=False, timeout=30); subprocess.run(["systemctl", "restart", SERVICE], check=False, timeout=60); rollback_ok = bot_healthy(); clear_notified()
        except Exception as rollback_exc: print(f"Rollback failed: {type(rollback_exc).__name__}: {rollback_exc}", file=sys.stderr)
        _write_status("ошибка", str(exc), old); notify(f"❌ Обновление XFI Guard не удалось\n\nОшибка: {type(exc).__name__}: {str(exc)[:650]}\n\nАвтоматический откат: {'✅ выполнен' if rollback_ok else '❌ НЕ выполнен'}\n\nЛокальные изменения не удалены."); return 1
    finally: release_lock()


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(apply_update() if command == "apply" else check_update())
