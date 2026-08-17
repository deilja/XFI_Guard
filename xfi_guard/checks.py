"""Safe, read-only system checks used by XFI Guard."""

from __future__ import annotations

import os
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
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def check_disk(path: str = "/", warning_percent: int = 85) -> CheckResult:
    usage = shutil.disk_usage(path)
    percent = round((usage.used / usage.total) * 100, 1) if usage.total else 0.0
    status = "warning" if percent >= warning_percent else "ok"
    return CheckResult(
        name="disk",
        status=status,
        message=f"Disk usage is {percent}% on {path}",
        details={"path": path, "percent": percent, "free_bytes": usage.free},
    )


def check_memory(warning_percent: int = 90) -> CheckResult:
    total = available = None
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            values = {}
            for line in handle:
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0]) * 1024
            total = values.get("MemTotal")
            available = values.get("MemAvailable")
    except (FileNotFoundError, ValueError):
        return CheckResult("memory", "unknown", "Memory information unavailable", {})

    if not total or available is None:
        return CheckResult("memory", "unknown", "Memory information incomplete", {})

    used_percent = round(((total - available) / total) * 100, 1)
    status = "warning" if used_percent >= warning_percent else "ok"
    return CheckResult(
        "memory",
        status,
        f"Memory usage is {used_percent}%",
        {"percent": used_percent, "total_bytes": total, "available_bytes": available},
    )


def check_service(service: str) -> CheckResult:
    if not service.replace("-", "").isalnum():
        raise ValueError("Invalid service name")
    code, stdout, stderr = _run(["systemctl", "is-active", service])
    if code == 0 and stdout == "active":
        return CheckResult("service", "ok", f"Service {service} is active", {"service": service})
    return CheckResult(
        "service",
        "critical",
        f"Service {service} is not active",
        {"service": service, "output": stdout or stderr},
    )


def check_command_available(command: str) -> CheckResult:
    available = shutil.which(command) is not None
    return CheckResult(
        name="command",
        status="ok" if available else "warning",
        message=f"Command {command} is {'available' if available else 'not available'}",
        details={"command": command, "available": available},
    )


def collect_basic_checks() -> list[CheckResult]:
    results = [check_disk(), check_memory()]
    for command in ("ufw", "fail2ban-client", "systemctl"):
        results.append(check_command_available(command))
    return results
