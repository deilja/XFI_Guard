"""VPN service and listening-port checks."""

from __future__ import annotations

from typing import Any

from .checks import CheckResult, _run


def check_service_candidates(services: tuple[str, ...] = ("xray", "x-ui", "3x-ui")) -> list[CheckResult]:
    results: list[CheckResult] = []
    for service in services:
        code, stdout, stderr = _run(["systemctl", "is-active", service])
        if code == 0 and stdout == "active":
            results.append(CheckResult("vpn_service", "ok", f"Service {service} is active", {"service": service}))
        elif stdout in {"inactive", "failed"}:
            results.append(CheckResult("vpn_service", "critical", f"Service {service} is {stdout}", {"service": service}))
        else:
            results.append(CheckResult("vpn_service", "unknown", f"Service {service} status unavailable", {"service": service, "output": stdout or stderr}))
    return results


def check_listening_ports(ports: tuple[int, ...] = (22, 80, 443, 2053, 2083, 2087, 2096)) -> CheckResult:
    code, stdout, stderr = _run(["ss", "-lntup"])
    if code != 0:
        return CheckResult("network", "unknown", "Unable to inspect listening sockets", {"output": stdout or stderr})
    listeners: list[dict[str, Any]] = []
    for line in stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 5:
            continue
        local = fields[4]
        port_text = local.rsplit(":", 1)[-1].strip("[]")
        if port_text.isdigit() and int(port_text) in ports:
            listeners.append({"port": int(port_text), "line": line})
    return CheckResult("network", "ok", f"Found {len(listeners)} monitored listening sockets", {"listeners": listeners, "monitored_ports": list(ports)})


def collect_vpn_checks() -> list[CheckResult]:
    return check_service_candidates() + [check_listening_ports()]
