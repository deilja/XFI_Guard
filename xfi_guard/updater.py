"""Безопасное обновление XFI Guard."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time, urllib.request
from pathlib import Path
REPO = Path(os.getenv("XFI_GUARD_REPO", "/opt/xfi-guard"))
SERVICE = os.getenv("XFI_GUARD_SERVICE", "xfi-guard-bot")
GITHUB_API = "https://api.github.com/repos/deilja/XFI_Guard/commits/main"
LOCK_FILE = Path("/run/xfi-guard-update.lock")
ENV_FILE = Path("/etc/xfi-guard/bot.env")

# Existing updater implementation is kept below; the lock handling is intentionally
# isolated so stale locks from interrupted upgrades cannot block future updates.
def _pid_alive(pid: int) -> bool:
    if pid <= 0: return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _read_lock_pid() -> int | None:
    try:
        raw = LOCK_FILE.read_text(encoding="utf-8").strip()
        pid = int(raw)
        return pid if pid > 0 else None
    except (FileNotFoundError, ValueError, OSError):
        return None


def acquire_lock() -> bool:
    """Acquire update lock and remove only demonstrably stale locks."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return True
    except FileExistsError:
        pid = _read_lock_pid()
        if pid is not None and _pid_alive(pid):
            return False
        # Missing/corrupt/dead PID: remove stale lock and retry atomically.
        try:
            LOCK_FILE.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
            return True
        except FileExistsError:
            return False


def release_lock() -> None:
    """Remove the lock only when it belongs to this updater process."""
    pid = _read_lock_pid()
    if pid != os.getpid():
        return
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def test_lock_recovery() -> bool:
    """Self-test helper: a dead PID must not block acquisition."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text("2147483647\n", encoding="utf-8")
    acquired = acquire_lock()
    if acquired:
        release_lock()
    return acquired
