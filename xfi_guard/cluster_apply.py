"""Apply trusted cluster block commands through the existing XFI Guard Fail2Ban jail."""
from __future__ import annotations

import subprocess


def fail2ban_block(ip: str, jail: str = "xfi-guard") -> tuple[bool, str]:
    """Ban an already-validated public IPv4 for the configured jail.

    The jail's bantime remains authoritative (currently 7 days on deployed nodes).
    """
    result = subprocess.run(
        ["fail2ban-client", "set", jail, "banip", ip],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode == 0:
        return True, (result.stdout or "ok").strip()
    return False, (result.stderr or result.stdout or "fail2ban error").strip()
