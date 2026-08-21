"""Multi-VPS synchronization of XFI Guard bans through SSH."""
from __future__ import annotations

import concurrent.futures
import ipaddress
import subprocess
from pathlib import Path

from .nodes import load_nodes


def _ban_node(node, ip: str, timeout: int = 12) -> dict:
    target = f"{node.user}@{node.host}"
    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=7",
        "-o", "StrictHostKeyChecking=yes", "-p", str(node.port), target,
        "sudo", "fail2ban-client", "set", "xfi-guard", "banip", ip,
    ]
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
        if p.returncode == 0:
            return {"node": node.name, "host": node.host, "status": "blocked"}
        return {"node": node.name, "host": node.host, "status": "failed", "error": (p.stderr or p.stdout or "remote command failed").strip()[:300]}
    except Exception as exc:
        return {"node": node.name, "host": node.host, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def sync_ban(ip: str, config_path: str | Path = "/opt/xfi-guard/config.toml") -> list[dict]:
    """Apply an already-approved local ban to every configured remote VPS.

    Authentication is delegated to the system SSH agent/known_hosts. No keys or
    passwords are stored by XFI Guard. The remote xfi-guard jail controls the
    seven-day bantime.
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
