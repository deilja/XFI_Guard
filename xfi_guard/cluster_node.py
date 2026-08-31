"""Lightweight authenticated node agent for XFI Guard Cluster Master."""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .cluster import _valid_ip
from .cluster_auth import new_node_id, sign_heartbeat

NODE_NAME = os.getenv("XFI_GUARD_CLUSTER_NODE_NAME", socket.gethostname())[:128]
NODE_ID_FILE = Path(os.getenv("XFI_GUARD_CLUSTER_NODE_ID_FILE", "/var/lib/xfi-guard/node-id"))
MASTER_URL = os.getenv("XFI_GUARD_CLUSTER_MASTER_URL", "http://127.0.0.1:8765").rstrip("/")
TOKEN = os.getenv("XFI_GUARD_CLUSTER_TOKEN", "")
SECRET = os.getenv("XFI_GUARD_CLUSTER_SECRET", "")
INTERVAL = max(10, int(os.getenv("XFI_GUARD_CLUSTER_HEARTBEAT_INTERVAL", "30")))
STATE = Path(os.getenv("XFI_GUARD_CLUSTER_NODE_STATE", "/var/lib/xfi-guard/node-state.json"))


def _node_id() -> str:
    try:
        value = NODE_ID_FILE.read_text().strip()
        if value:
            return value[:128]
    except OSError:
        pass
    value = new_node_id()
    try:
        NODE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        NODE_ID_FILE.write_text(value)
        NODE_ID_FILE.chmod(0o600)
    except OSError:
        pass
    return value


def _request(path: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(MASTER_URL + path, data=body, method="POST", headers={"Content-Type": "application/json"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())


def _local_blocked() -> list[str]:
    """Read locally applied blocks without invoking external commands."""
    try:
        data = json.loads(STATE.read_text())
        return [x for x in data.get("blocked", []) if _valid_ip(x)][-500:]
    except (OSError, ValueError, TypeError):
        return []


def heartbeat() -> dict:
    payload = {
        "node": NODE_NAME,
        "node_id": _node_id(),
        "timestamp": time.time(),
        "nonce": secrets.token_urlsafe(24),
        "hostname": socket.gethostname(),
        "blocked": _local_blocked(),
    }
    if not SECRET:
        raise RuntimeError("XFI_GUARD_CLUSTER_SECRET is not configured")
    payload["signature"] = sign_heartbeat(payload, SECRET)
    result = _request("/heartbeat", payload)
    applied = []
    for command in result.get("commands", []):
        if command.get("action") == "block" and _valid_ip(str(command.get("ip", ""))):
            ip = str(command["ip"])
            ok = apply_block(ip, int(command.get("until", 0)))
            applied.append({"ip": ip, "ok": ok})
    result["applied"] = applied
    return result


def apply_block(ip: str, until: int) -> bool:
    bantime = max(60, until - int(time.time()))
    base = ["fail2ban-client", "set", "xfi-guard"]
    configure = subprocess.run(
        base + ["bantime", str(bantime)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if configure.returncode != 0:
        return False
    p = subprocess.run(
        base + ["banip", ip],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return p.returncode == 0


def run() -> None:
    while True:
        try:
            result = heartbeat()
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps({"last_ok": time.time(), "commands": result.get("commands", []), "applied": result.get("applied", [])}))
            try:
                STATE.chmod(0o600)
            except OSError:
                pass
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps({"last_error": f"{type(exc).__name__}: {exc}", "last_attempt": time.time()}))
            try:
                STATE.chmod(0o600)
            except OSError:
                pass
        time.sleep(INTERVAL)


if __name__ == "__main__":
    run()
