"""Read-only multi-VPS inventory for XFI Guard.

Nodes are configured in config.toml under [[nodes]]. Authentication is delegated
entirely to the host's SSH config/agent; no private keys or passwords are stored
by XFI Guard.
"""
from __future__ import annotations

import ipaddress
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Node:
    name: str
    host: str
    user: str = "root"
    port: int = 22
    enabled: bool = True


def load_nodes(path: str | Path = "config.toml") -> list[Node]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    result: list[Node] = []
    for raw in data.get("nodes", []) or []:
        if not isinstance(raw, dict) or not raw.get("enabled", True):
            continue
        name = str(raw.get("name", "")).strip()
        host = str(raw.get("host", "")).strip()
        user = str(raw.get("user", "root")).strip() or "root"
        try:
            port = int(raw.get("port", 22))
        except (TypeError, ValueError):
            continue
        if not name or not host or not (1 <= port <= 65535):
            continue
        try:
            ipaddress.ip_address(host)
        except ValueError:
            # DNS names are allowed; validation is performed by ssh.
            if any(c in host for c in " /\\\t\r\n"):
                continue
        result.append(Node(name=name, host=host, user=user, port=port))
    return result


def probe_node(node: Node, timeout: int = 8) -> dict:
    target = f"{node.user}@{node.host}"
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
        "-p", str(node.port), target,
        "python3 -c 'import json,platform,subprocess; "
        "print(json.dumps({\"hostname\":platform.node(),"
        "\"xfi_guard\":subprocess.run([\"systemctl\",\"is-active\",\"xfi-guard.service\"],capture_output=True,text=True).stdout.strip(),"
        "\"fail2ban\":subprocess.run([\"systemctl\",\"is-active\",\"fail2ban.service\"],capture_output=True,text=True).stdout.strip()},ensure_ascii=False))'",
    ]
    try:
        p = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
        if p.returncode != 0:
            return {"name": node.name, "host": node.host, "status": "offline", "error": (p.stderr or "ssh failed").strip()[:300]}
        import json
        payload = json.loads(p.stdout.strip().splitlines()[-1])
        return {"name": node.name, "host": node.host, "status": "online", **payload}
    except Exception as exc:
        return {"name": node.name, "host": node.host, "status": "offline", "error": f"{type(exc).__name__}: {exc}"}


def collect_nodes(path: str | Path = "config.toml") -> list[dict]:
    return [probe_node(node) for node in load_nodes(path)]
