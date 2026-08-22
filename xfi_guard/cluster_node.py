"""Lightweight node agent for XFI Guard Cluster Master."""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

from .cluster import _valid_ip

NODE_NAME = os.getenv("XFI_GUARD_CLUSTER_NODE_NAME", socket.gethostname())[:128]
MASTER_URL = os.getenv("XFI_GUARD_CLUSTER_MASTER_URL", "http://127.0.0.1:8765").rstrip("/")
TOKEN = os.getenv("XFI_GUARD_CLUSTER_TOKEN", "")
INTERVAL = max(10, int(os.getenv("XFI_GUARD_CLUSTER_HEARTBEAT_INTERVAL", "30")))
STATE = Path(os.getenv("XFI_GUARD_CLUSTER_NODE_STATE", "/var/lib/xfi-guard/node-state.json"))


def _request(path: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(
        MASTER_URL + path,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())


def _local_blocked() -> list[str]:
    """Best-effort Fail2Ban list; failure must not stop heartbeat."""
    try:
        import subprocess
        p = subprocess.run(
            ["fail2ban-client", "status", "xfi-guard"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if p.returncode != 0:
            return []
        # Prefer the compact JSON state if a local integration provides it.
        try:
            data = json.loads(STATE.read_text())
            return [x for x in data.get("blocked", []) if _valid_ip(x)][-500:]
        except (OSError, ValueError):
            pass
        return []
    except (OSError, subprocess.TimeoutExpired):
        return []


def heartbeat() -> dict:
    payload = {
        "node": NODE_NAME,
        "timestamp": time.time(),
        "hostname": socket.gethostname(),
        "blocked": _local_blocked(),
    }
    result = _request("/heartbeat", payload)
    for command in result.get("commands", []):
        if command.get("action") == "block" and _valid_ip(str(command.get("ip", ""))):
            apply_block(str(command["ip"]), int(command.get("until", 0)))
    return result


def apply_block(ip: str, until: int) -> bool:
    """Apply a global block locally through Fail2Ban's dedicated jail."""
    import subprocess
    bantime = max(60, until - int(time.time()))
    command = ["sudo", "fail2ban-client", "set", "xfi-guard", "banip", ip]
    p = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    if p.returncode != 0:
        return False
    subprocess.run(
        ["sudo", "fail2ban-client", "set", "xfi-guard", "bantime", str(bantime)],
        capture_output=True, text=True, timeout=15, check=False,
    )
    return True


def run() -> None:
    while True:
        try:
            result = heartbeat()
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps({"last_ok": time.time(), "commands": result.get("commands", [])}))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps({"last_error": f"{type(exc).__name__}: {exc}", "last_attempt": time.time()}))
        time.sleep(INTERVAL)


if __name__ == "__main__":
    run()
