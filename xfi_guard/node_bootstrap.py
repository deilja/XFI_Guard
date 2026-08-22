"""Safe remote VPS bootstrap via the local SSH identity/agent."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def bootstrap(
    host: str,
    user: str = "root",
    port: int = 22,
    timeout: int = 30,
    identity_file: str | None = None,
) -> tuple[bool, str]:
    """Install/repair XFI Guard on a trusted node using its configured identity."""
    if not host or any(c.isspace() for c in host):
        return False, "invalid host"
    target = f"{user}@{host}"
    remote = r'''set -eu
command -v systemctl >/dev/null
command -v fail2ban-client >/dev/null || { echo FAIL2BAN_MISSING; exit 20; }
if [ -d /opt/xfi-guard/.git ]; then
  cd /opt/xfi-guard
  git pull --ff-only origin main
else
  echo XFI_GUARD_NOT_INSTALLED
  exit 21
fi
systemctl enable --now xfi-guard.service
systemctl enable --now xfi-guard-bot.service 2>/dev/null || true
systemctl enable --now fail2ban
fail2ban-client status xfi-guard >/dev/null
printf 'XFI_GUARD_BOOTSTRAP_OK\n'
'''
    cmd = ["ssh"]
    if identity_file:
        identity = Path(os.path.expanduser(identity_file))
        if not identity.exists():
            return False, f"SSH identity file not found: {identity}"
        cmd += ["-i", str(identity)]
    cmd += [
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes" if identity_file else "-o",
    ]
    if identity_file:
        # Replace the compact pair above with the actual SSH option/value.
        cmd = ["ssh", "-i", str(Path(os.path.expanduser(identity_file))),
               "-o", "IdentitiesOnly=yes"]
    cmd += [
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"ConnectTimeout={int(timeout)}",
        "-p", str(int(port)), target,
        "bash", "-s",
    ]
    try:
        p = subprocess.run(cmd, input=remote, text=True, capture_output=True, timeout=timeout + 15)
    except Exception as exc:
        return False, f"SSH error: {type(exc).__name__}: {exc}"
    output = (p.stdout + "\n" + p.stderr).strip()
    if p.returncode:
        return False, output[-2500:]
    return True, output[-2500:]
