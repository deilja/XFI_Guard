"""Multi-VPS synchronization of XFI Guard bans through SSH."""
from __future__ import annotations

import concurrent.futures
import ipaddress
import os
import subprocess
from pathlib import Path

from .nodes import load_nodes


def _ban_node(node, ip: str, timeout: int = 12) -> dict:
    target = f"{node.user}@{node.host}"
    identity = Path(os.path.expanduser(node.identity_file))
    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=7", "-o", "StrictHostKeyChecking=yes",
    ]
    if identity.is_file():
        cmd += ["-i", str(identity)]
    cmd += ["-p", str(node.port), target, "sudo", "fail2ban-client", "set", "xfi-guard", "banip", ip]
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
        if p.returncode == 0:
            return {"node": node.name, "host": node.host, "status": "blocked"}
        return {"node": node.name, "host": node.host, "status": "failed", "error": (p.stderr or p.stdout or "remote command failed").strip()[:300]}
    except Exception as exc:
        return {"node": node.name, "host": node.host, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def sync_ban(ip: str, config_path: str | Path = "/opt/xfi-guard/config.toml") -> list[dict]:
    """Apply an approved local ban to every configured remote VPS.

    Authentication uses the configured per-node identity file and strict
    known_hosts verification. No passwords are stored by XFI Guard.
    """
    try:
        parsed = ipaddress.ip_address(str(ip).strip())
        if parsed.version != 4 or not parsed.is_global:
            return []
        normalized = parsed.compressed
    except ValueError:
        return []
    nodes = load_nodes(config_path)
    if not nodes:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(nodes))) as pool:
        futures = [pool.submit(_ban_node, node, normalized) for node in nodes]
        return [future.result() for future in futures]
