"""Validated monitor configuration loaded from TOML."""
from __future__ import annotations

import tomllib
from pathlib import Path

from .ai_config import MonitorSettings

MonitorConfig = MonitorSettings


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
    telegram = data.get("telegram", {})
    ai = data.get("ai", {})
    defense = data.get("auto_block", {})
    return MonitorConfig.model_validate({
        "interval_seconds": monitor.get("interval_seconds", 60),
        "log_level": str(monitor.get("log_level", "INFO")).upper(),
        "output_file": monitor.get("output_file", "/var/log/xfi-guard/monitor.jsonl"),
        "state_file": monitor.get("state_file", "/var/lib/xfi-guard/state.json"),
        "disk_warning_percent": thresholds.get("disk_warning_percent", 85),
        "memory_warning_percent": thresholds.get("memory_warning_percent", 90),
        "vpn_services": vpn.get("services", ["xray", "x-ui", "3x-ui"]),
        "vpn_ports": vpn.get("ports", [22, 80, 443, 2053, 2083, 2087, 2096]),
        "ssh_log": events.get("ssh_log", "/var/log/auth.log"),
        "fail2ban_log": events.get("fail2ban_log", "/var/log/fail2ban.log"),
        "max_events_per_cycle": events.get("max_events_per_cycle", 100),
        "telegram_enabled": telegram.get("enabled", False),
        "telegram_cooldown_seconds": telegram.get("cooldown_seconds", 300),
        "ai_provider": str(ai.get("provider", "gemini")).lower(),
        "ai_max_events_per_cycle": ai.get("max_events_per_cycle", 10),
        "auto_block_enabled": defense.get("enabled", False),
        "auto_block_confidence": defense.get("confidence", 0.90),
        "auto_block_min_attempts": defense.get("min_attempts", 5),
        "auto_block_db": defense.get("db", "/var/lib/xfi-guard/security.db"),
    })
