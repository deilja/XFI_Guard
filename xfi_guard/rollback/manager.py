"""Rollback primitives for XFI Guard remediation.

Backups are created before mutation. Network changes can be protected by an
`at` timer so a lost SSH session has a bounded recovery path.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BACKUP_ROOT = Path("/var/lib/xfi-guard/backups")
NETWORK_BACKUP = Path("/root/net-backup")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def create_backup(paths: list[str], label: str = "remediation") -> Path:
    destination = BACKUP_ROOT / f"{_stamp()}-{label}"
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "paths": []}
    for raw in paths:
        source = Path(raw)
        item = destination / source.name
        if source.is_dir():
            shutil.copytree(source, item, symlinks=True)
        elif source.exists():
            shutil.copy2(source, item)
        else:
            continue
        manifest["paths"].append(str(source))
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.chmod(destination / "manifest.json", 0o600)
    return destination


def snapshot_network() -> Path:
    """Capture the network state used by the documented emergency rollback."""
    NETWORK_BACKUP.mkdir(parents=True, mode=0o700, exist_ok=True)
    commands = {
        "ip-rule.txt": ["ip", "rule", "show"],
        "routes.txt": ["ip", "route", "show", "table", "all"],
        "nft.bak": ["nft", "list", "ruleset"],
    }
    for filename, command in commands.items():
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        (NETWORK_BACKUP / filename).write_text(result.stdout, encoding="utf-8")
    subprocess.run(["iptables-save"], stdout=(NETWORK_BACKUP / "iptables.bak").open("w"), check=False)
    return NETWORK_BACKUP


def schedule_network_rollback(minutes: int = 15) -> str:
    if minutes < 1:
        raise ValueError("rollback delay must be at least one minute")
    script = NETWORK_BACKUP / "xfi-rollback.sh"
    script.write_text(
        "#!/bin/sh\n"
        "set +e\n"
        "[ -s /root/net-backup/nft.bak ] && nft -f /root/net-backup/nft.bak\n"
        "[ -s /root/net-backup/iptables.bak ] && iptables-restore < /root/net-backup/iptables.bak\n"
        "systemctl restart ssh 2>/dev/null || true\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    result = subprocess.run(["at", "now", "+", f"{minutes}", "minutes"], input=f"{script}\n", text=True, capture_output=True, check=False)
    return (result.stdout or result.stderr).strip()
