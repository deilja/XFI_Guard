"""Безопасные read-only проверки системы."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run(command: list[str]) -> tuple[int, str, str]:
    """Run a fixed argv command without allowing an OS failure to escape."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"command timed out: {exc}"
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return 126 if isinstance(exc, PermissionError) else 127, "", f"command failed: {exc}"
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def check_disk(path: str = "/", warning_percent: int = 85) -> CheckResult:
    try:
        usage = shutil.disk_usage(path)
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return CheckResult("disk", "unknown", f"Диск недоступен: {exc}", {"path": path})
    percent = round((usage.used / usage.total) * 100, 1) if usage.total else 0.0
    return CheckResult(
        "disk",
        "warning" if percent >= warning_percent else "ok",
        f"Использование диска: {percent}% на {path}",
        {"path": path, "percent": percent, "free_bytes": usage.free},
    )


def check_memory(warning_percent: int = 90) -> CheckResult:
    try:
        values: dict[str, int] = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0]) * 1024
        total = values.get("MemTotal")
        available = values.get("MemAvailable")
    except (FileNotFoundError, PermissionError, OSError, ValueError):
        return CheckResult("memory", "unknown", "Информация о памяти недоступна", {})
    if not total or available is None:
        return CheckResult("memory", "unknown", "Информация о памяти неполная", {})
    used = round(((total - available) / total) * 100, 1)
    return CheckResult(
        "memory",
        "warning" if used >= warning_percent else "ok",
        f"Использование памяти: {used}%",
        {"percent": used, "total_bytes": total, "available_bytes": available},
    )


def check_service(service: str) -> CheckResult:
    if not service.replace("-", "").isalnum():
        raise ValueError("Invalid service name")
    code, stdout, stderr = _run(["systemctl", "is-active", service])
    if code == 0 and stdout == "active":
        return CheckResult("service", "ok", f"Сервис {service} активен", {"service": service})
    return CheckResult(
        "service",
        "critical",
        f"Сервис {service} неактивен",
        {"service": service, "output": stdout or stderr},
    )


def check_command_available(command: str) -> CheckResult:
    available = shutil.which(command) is not None
    return CheckResult(
        "command",
        "ok" if available else "warning",
        f"Команда {command} {'доступна' if available else 'недоступна'}",
        {"command": command, "available": available},
    )


def collect_basic_checks() -> list[CheckResult]:
    results = [check_disk(), check_memory()]
    for command in ("ufw", "fail2ban-client", "systemctl"):
        results.append(check_command_available(command))
    return results
