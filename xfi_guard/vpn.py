"""Проверка фактического состояния 3X-UI/Xray и сетевых портов."""
from __future__ import annotations
import re
from typing import Any
from .checks import CheckResult, _run


def _process_active(name: str) -> bool:
    code, stdout, _ = _run(["pgrep", "-x", name])
    return code == 0 and bool(stdout.strip())


def check_xray_runtime() -> CheckResult:
    """Проверяет реально запущенный Xray, включая Xray, запущенный 3X-UI."""
    if _process_active("xray"):
        code, stdout, _ = _run(["pgrep", "-a", "-x", "xray"])
        return CheckResult("xray_runtime", "ok", "Xray реально запущен и работает как процесс", {"processes": stdout.splitlines() if code == 0 else []})

    code, stdout, _ = _run(["ps", "-eo", "pid=,comm=,args="])
    matches = []
    if code == 0:
        for line in stdout.splitlines():
            if re.search(r"(?:^|/)xray(?:\s|$)", line, re.IGNORECASE):
                matches.append(line.strip())
    if matches:
        return CheckResult("xray_runtime", "ok", "Xray реально запущен и найден среди процессов", {"processes": matches})
    return CheckResult("xray_runtime", "critical", "Процесс Xray не запущен", {})


def check_panel_service(services: tuple[str, ...] = ("x-ui", "3x-ui")) -> CheckResult:
    states = []
    for service in services:
        code, stdout, _ = _run(["systemctl", "is-active", service])
        if code == 0 and stdout.strip() == "active":
            states.append(service)
    if states:
        return CheckResult("xui_panel", "ok", f"Панель управления активна: {', '.join(states)}", {"services": states})
    return CheckResult("xui_panel", "warning", "Служба 3X-UI/x-ui не найдена среди активных systemd-сервисов", {})


def check_service_candidates(services: tuple[str, ...] = ("xray", "x-ui", "3x-ui")) -> list[CheckResult]:
    raw = []
    for service in services:
        code, stdout, stderr = _run(["systemctl", "is-active", service])
        state = stdout.strip()
        if code == 0 and state == "active":
            raw.append((service, "ok", state))
        elif state in {"inactive", "failed"}:
            raw.append((service, "critical", state))
        else:
            raw.append((service, "unknown", state or stderr.strip()))

    xray_runtime = _process_active("xray")
    results = []
    for service, status, output in raw:
        if service == "xray" and xray_runtime:
            status = "ok"
            message = "Xray работает (фактический процесс активен)"
        elif status == "ok":
            message = f"Сервис {service} активен"
        elif status == "critical":
            message = f"Сервис {service} неактивен"
        else:
            message = f"Состояние сервиса {service} недоступно"
        results.append(CheckResult("vpn_service", status, message, {"service": service, "output": output}))
    return results


def check_listening_ports(ports: tuple[int, ...] = (22, 80, 443, 2053, 2083, 2087, 2096)) -> CheckResult:
    code, stdout, stderr = _run(["ss", "-lntup"])
    if code != 0:
        return CheckResult("network", "unknown", "Не удалось проверить открытые сетевые порты", {"output": stdout or stderr})
    listeners: list[dict[str, Any]] = []
    for line in stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 5:
            continue
        local = fields[4]
        port_text = local.rsplit(":", 1)[-1].strip("[]")
        if port_text.isdigit() and int(port_text) in ports:
            match = re.search(r'users:\(\("([^"]+)"', line)
            process = match.group(1) if match else ""
            listeners.append({"port": int(port_text), "process": process, "line": line})
    return CheckResult("network", "ok", f"Обнаружено {len(listeners)} отслеживаемых открытых портов", {"listeners": listeners, "monitored_ports": list(ports)})


def collect_vpn_checks() -> list[CheckResult]:
    return [check_panel_service(), check_xray_runtime()] + check_service_candidates() + [check_listening_ports()]
