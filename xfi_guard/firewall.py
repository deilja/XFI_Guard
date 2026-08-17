"""Safe IP blocking helpers for the XFI Guard admin bot.

Blocking is never automatic: the bot only executes a firewall change after
an administrator explicitly presses a confirmation button.
"""
from __future__ import annotations

import ipaddress
import re
from .checks import _run


def validate_public_ip(value: str) -> str:
    value = value.strip()
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("Некорректный IP-адрес") from exc
    if ip.version != 4:
        raise ValueError("Сейчас поддерживается только IPv4")
    if not ip.is_global:
        raise ValueError("Разрешена блокировка только публичного IPv4")
    return str(ip)


def block_ip(ip: str) -> tuple[bool, str]:
    ip = validate_public_ip(ip)
    code, stdout, stderr = _run(["ufw", "insert", "1", "deny", "from", ip])
    output = (stdout or stderr).strip()
    if code == 0:
        return True, f"IP {ip} заблокирован в UFW."
    if "Skipping adding existing rule" in output or "already exists" in output.lower():
        return True, f"IP {ip} уже был заблокирован в UFW."
    return False, f"Не удалось заблокировать {ip}: {output[-500:]}"


def unblock_ip(ip: str) -> tuple[bool, str]:
    ip = validate_public_ip(ip)
    code, stdout, stderr = _run(["ufw", "delete", "deny", "from", ip])
    output = (stdout or stderr).strip()
    if code == 0:
        return True, f"Блокировка IP {ip} снята."
    return False, f"Не удалось снять блокировку {ip}: {output[-500:]}"


def _extract_public_ips(text: str) -> list[str]:
    ips: list[str] = []
    for candidate in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
        try:
            ip = ipaddress.ip_address(candidate)
            if ip.version == 4 and ip.is_global and ip.compressed not in ips:
                ips.append(ip.compressed)
        except ValueError:
            continue
    return ips


def list_blocked_ips() -> list[str]:
    """Read public deny/reject IPs using several UFW views.

    UFW output differs between versions/locales. ``ufw show added`` is the
    persistent-rule view, while ``status numbered`` is the human-facing view.
    We combine both and only return public IPv4 addresses from deny/reject
    rules. This function is read-only.
    """
    found: list[str] = []

    code, stdout, stderr = _run(["ufw", "show", "added"])
    if code == 0:
        for line in stdout.splitlines():
            upper = line.upper()
            if "DENY" not in upper and "REJECT" not in upper:
                continue
            for ip in _extract_public_ips(line):
                if ip not in found:
                    found.append(ip)

    code, stdout, stderr = _run(["ufw", "status", "number"])
    if code == 0:
        for line in stdout.splitlines():
            upper = line.upper()
            if "DENY" not in upper and "REJECT" not in upper:
                continue
            for ip in _extract_public_ips(line):
                if ip not in found:
                    found.append(ip)

    # Last-resort fallback for installations where UFW's status command is
    # unavailable but its persistent user rules are readable.
    if not found:
        code, stdout, stderr = _run(["grep", "-E", "^-A ufw-user-input.*(DROP|REJECT)", "/etc/ufw/user.rules"])
        if code in (0, 1):
            for ip in _extract_public_ips(stdout):
                if ip not in found:
                    found.append(ip)

    return found
