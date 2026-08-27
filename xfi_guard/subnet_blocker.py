"""Safe IPv4 CIDR blocking helpers for XFI Guard.

This module deliberately keeps subnet blocking explicit. It validates public
CIDRs, protects broad/private/reserved networks, and delegates the actual
firewall mutation to UFW. Automatic subnet decisions belong to policy/AI
layers; this module only performs validated firewall operations.
"""
from __future__ import annotations

import ipaddress
from .checks import _run

# A single subnet rule should not accidentally block a large portion of the
# Internet. /24 is the broadest IPv4 network accepted by this safety layer.
MIN_PREFIXLEN_V4 = 24


def validate_public_subnet(value: str, *, min_prefixlen: int = MIN_PREFIXLEN_V4) -> str:
    """Return canonical public IPv4 CIDR or raise ValueError."""
    value = str(value).strip()
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError("Некорректная IPv4 подсеть в формате CIDR") from exc

    if network.version != 4:
        raise ValueError("Сейчас поддерживается только IPv4")
    if network.prefixlen < int(min_prefixlen):
        raise ValueError(f"Слишком широкая подсеть: разрешён минимум /{min_prefixlen}")
    if not network.is_global:
        raise ValueError("Разрешена блокировка только публичной IPv4 подсети")
    return network.with_prefixlen


def block_subnet(subnet: str) -> tuple[bool, str]:
    """Insert a UFW deny rule for a validated public IPv4 subnet."""
    subnet = validate_public_subnet(subnet)
    code, stdout, stderr = _run(["ufw", "insert", "1", "deny", "from", subnet])
    output = (stdout or stderr).strip()
    if code == 0:
        return True, f"Подсеть {subnet} заблокирована в UFW."
    if "Skipping adding existing rule" in output or "already exists" in output.lower():
        return True, f"Подсеть {subnet} уже была заблокирована в UFW."
    return False, f"Не удалось заблокировать {subnet}: {output[-500:]}"


def unblock_subnet(subnet: str) -> tuple[bool, str]:
    """Remove a UFW deny rule for a validated public IPv4 subnet."""
    subnet = validate_public_subnet(subnet)
    code, stdout, stderr = _run(["ufw", "delete", "deny", "from", subnet])
    output = (stdout or stderr).strip()
    if code == 0:
        return True, f"Блокировка подсети {subnet} снята."
    return False, f"Не удалось снять блокировку {subnet}: {output[-500:]}"


def list_blocked_subnets() -> list[str]:
    """Read public IPv4 CIDR deny/reject rules from UFW."""
    found: list[str] = []
    code, stdout, stderr = _run(["ufw", "show", "added"])
    if code != 0:
        return found

    for line in stdout.splitlines():
        upper = line.upper()
        if "DENY" not in upper and "REJECT" not in upper:
            continue
        # UFW's persistent rule format commonly contains "from CIDR".
        parts = line.split()
        for index, token in enumerate(parts[:-1]):
            if token.lower() != "from":
                continue
            candidate = parts[index + 1]
            try:
                subnet = validate_public_subnet(candidate)
            except ValueError:
                continue
            if subnet not in found:
                found.append(subnet)
    return found
