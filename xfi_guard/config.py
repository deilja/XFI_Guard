"""Configuration loader using the Python standard library TOML parser."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MonitorConfig:
    interval_seconds: int = 60
    log_level: str = "INFO"
    output_file: str = "/var/log/xfi-guard/monitor.jsonl"
    state_file: str = "/var/lib/xfi-guard/state.json"
    disk_warning_percent: int = 85
    memory_warning_percent: int = 90
    vpn_services: tuple[str, ...] = ("xray", "x-ui", "3x-ui")
    vpn_ports: tuple[int, ...] = (22, 80, 443, 2053, 2083, 2087, 2096)
    ssh_log: str = "/var/log/auth.log"
    fail2ban_log: str = "/var/log/fail2ban.log"
    max_events_per_cycle: int = 100


def load_config(path: str | Path = "config.toml") -> MonitorConfig:
    config_path = Path(path)
    if not config_path.exists():
        return MonitorConfig()
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    monitor = data.get("monitor", {})
    thresholds = data.get("thresholds", {})
    vpn = data.get("vpn", {})
    events = data.get("events", {})
    return MonitorConfig(
        interval_seconds=max(5, int(monitor.get("interval_seconds", 60))),
        log_level=str(monitor.get("log_level", "INFO")).upper(),
        output_file=str(monitor.get("output_file", "/var/log/xfi-guard/monitor.jsonl")),
        state_file=str(monitor.get("state_file", "/var/lib/xfi-guard/state.json")),
        disk_warning_percent=int(thresholds.get("disk_warning_percent", 85)),
        memory_warning_percent=int(thresholds.get("memory_warning_percent", 90)),
        vpn_services=tuple(str(item) for item in vpn.get("services", ["xray", "x-ui", "3x-ui"])),
        vpn_ports=tuple(int(item) for item in vpn.get("ports", [22, 80, 443, 2053, 2083, 2087, 2096])),
        ssh_log=str(events.get("ssh_log", "/var/log/auth.log")),
        fail2ban_log=str(events.get("fail2ban_log", "/var/log/fail2ban.log")),
        max_events_per_cycle=max(1, int(events.get("max_events_per_cycle", 100))),
    )
