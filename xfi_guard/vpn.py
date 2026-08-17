"""Проверка фактического состояния 3X-UI/Xray и сетевых портов."""
from __future__ import annotations
import re
from typing import Any
from .checks import CheckResult, _run

XRAY_RE = re.compile(r"(?:^|[\s/])(xray|xray-linux(?:-amd64|-arm64|-arm)?)(?:$|[\s])", re.IGNORECASE)


def _xray_processes() -> list[str]:
    """Возвращает реальные процессы Xray, в том числе запущенные 3X-UI."""
    code, stdout, _ = _run(["ps", "-eo", "pid=,comm=,args="])
    if code != 0:
        return []
    matches: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        comm = parts[1] if len(parts) > 1 else ""
        args = parts[2] if len(parts) > 2 else ""
        if comm.lower() in {"xray", "xray-linux-amd64", "xray-linux-arm64", "xray-linux-arm"} or XRAY_RE.search(args):
            matches.append(line)
    return matches


def _process_active(name: str) -> bool:
    code, stdout, _ = _run(["pgrep", "-x", name])
    return code == 0 and bool(stdout.strip())


def check_xray_runtime() -> CheckResult:
    matches = _xray_processes()
    if matches:
        return CheckResult("xray_runtime", "ok", "Xray реально запущен и работает как процесс", {"processes": matches})
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

    xray_runtime = bool(_xray_processes())
    panel_active = any(service in {"x-ui", "3x-ui"} and status == "ok" for service, status, _ in raw)
    results = []
    for service, status, output in raw:
        if service == "xray" and xray_runtime:
            status = "ok"
            message = "Xray работает (фактический процесс активен)"
        elif service == "xray" and panel_active and status == "critical":
            status = "warning"
            message = "Отдельный systemd-сервис Xray неактивен, но панель 3X-UI/x-ui работает; проверяйте фактический процесс выше"
        elif service == "3x-ui" and panel_active and status == "critical":
            status = "warning"
            message = "Сервис 3x-ui неактивен, но активна панель x-ui"
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
        # Формат ss -lntup: State Recv-Q Send-Q Local Address:Port Peer Address:Port Process
        # Local Address находится в fields[3], а не fields[4].
        local = fields[3]
        port_text = local.rsplit(":", 1)[-1].strip("[]")
        if port_text.isdigit() and int(port_text) in ports:
            match = re.search(r'users:\(\("([^"]+)"', line)
            process = match.group(1) if match else ""
            listeners.append({"port": int(port_text), "process": process, "line": line})
    return CheckResult("network", "ok", f"Обнаружено {len(listeners)} отслеживаемых открытых портов", {"listeners": listeners, "monitored_ports": list(ports)})


def collect_vpn_checks() -> list[CheckResult]:
    return [check_panel_service(), check_xray_runtime()] + check_service_candidates() + [check_listening_ports()]
