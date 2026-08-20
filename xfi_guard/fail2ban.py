"""Fail2Ban integration for timed XFI Guard threat bans."""
from __future__ import annotations

import ipaddress
import re
from pathlib import Path

from .checks import _run

JAIL = "xfi-guard"
BAN_SECONDS = 7 * 24 * 60 * 60
SYNC_LOG = Path("/var/log/xfi-guard/fail2ban-sync.log")


def _valid_ip(value: str) -> str:
    ip = ipaddress.ip_address(str(value).strip())
    if ip.version != 4 or not ip.is_global:
        raise ValueError("Only public IPv4 addresses can be blocked")
    return ip.compressed


def available() -> bool:
    code, _, _ = _run(["fail2ban-client", "ping"])
    return code == 0


def jail_active() -> bool:
    if not available():
        return False
    code, _, _ = _run(["fail2ban-client", "status", JAIL])
    return code == 0


def ban(ip: str, seconds: int = BAN_SECONDS) -> tuple[bool, str]:
    """Ban an IP through the dedicated XFI Guard Fail2Ban jail."""
    ip = _valid_ip(ip)
    seconds = max(60, int(seconds))
    if not jail_active():
        return False, f"Fail2Ban jail '{JAIL}' is not active"

    code, stdout, stderr = _run(
        ["fail2ban-client", "set", JAIL, "banip", ip, str(seconds)]
    )
    output = (stdout or stderr).strip()
    if code == 0:
        _write_sync_log(ip)
        return True, f"IP {ip} заблокирован Fail2Ban на {seconds // 86400} дн."
    if "already banned" in output.lower():
        _write_sync_log(ip)
        return True, f"IP {ip} уже заблокирован Fail2Ban."
    return False, f"Fail2Ban не смог заблокировать {ip}: {output[-500:]}"


def unban(ip: str) -> tuple[bool, str]:
    ip = _valid_ip(ip)
    if not jail_active():
        return False, f"Fail2Ban jail '{JAIL}' is not active"
    code, stdout, stderr = _run(["fail2ban-client", "set", JAIL, "unbanip", ip])
    output = (stdout or stderr).strip()
    if code == 0:
        return True, f"Блокировка Fail2Ban для {ip} снята."
    return False, f"Fail2Ban не смог снять блокировку {ip}: {output[-500:]}"


def banned_ips() -> list[str]:
    if not jail_active():
        return []
    code, stdout, _ = _run(["fail2ban-client", "status", JAIL])
    if code != 0:
        return []
    match = re.search(r"Banned IP list:\s*(.*)", stdout or "")
    if not match:
        return []
    result: list[str] = []
    for value in match.group(1).split():
        try:
            ip = _valid_ip(value)
        except ValueError:
            continue
        if ip not in result:
            result.append(ip)
    return result


def _write_sync_log(ip: str) -> None:
    try:
        SYNC_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SYNC_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"XFI-GUARD-BAN {ip}\n")
    except OSError:
        pass
