"""Lightweight authenticated node agent for XFI Guard Cluster Master."""
from __future__ import annotations

import json
import os
import secrets
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .cluster import _valid_ip
from .cluster_auth import new_node_id, sign_heartbeat
from .master_url import normalize_master_url

NODE_NAME = os.getenv("XFI_GUARD_CLUSTER_NODE_NAME", socket.gethostname())[:128]
NODE_ID_FILE = Path(os.getenv("XFI_GUARD_CLUSTER_NODE_ID_FILE", "/var/lib/xfi-guard/node-id"))
MASTER_URL = normalize_master_url(os.getenv("XFI_GUARD_CLUSTER_MASTER_URL", "http://127.0.0.1:8765"))
TOKEN = os.getenv("XFI_GUARD_CLUSTER_TOKEN", "")
SECRET = os.getenv("XFI_GUARD_CLUSTER_SECRET", "")
INTERVAL = max(10, int(os.getenv("XFI_GUARD_CLUSTER_HEARTBEAT_INTERVAL", "30")))


def _ssl_context() -> ssl.SSLContext | None:
    ca_file = os.getenv("XFI_GUARD_CLUSTER_TLS_CA_FILE", "").strip()
    if ca_file:
        return ssl.create_default_context(cafile=ca_file)
    if os.getenv("XFI_GUARD_CLUSTER_TLS_INSECURE", "").strip().lower() in {"1", "true", "yes"}:
        return ssl._create_unverified_context()
    return None


def _default_state_path() -> Path:
    configured = os.getenv("XFI_GUARD_CLUSTER_NODE_STATE")
    if configured:
        return Path(configured)
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        root = Path(tempfile.gettempdir()) / f"xfi-guard-{os.getuid()}"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        return root / "node-state.json"
    return Path("/var/lib/xfi-guard/node-state.json")


STATE = _default_state_path()


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
    context = _ssl_context() if MASTER_URL.startswith("https://") else None
    with urllib.request.urlopen(req, timeout=10, context=context) as response:
        return json.loads(response.read().decode())


def master_health(timeout: int = 10) -> dict:
    req = urllib.request.Request(MASTER_URL + "/health", method="GET")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    context = _ssl_context() if MASTER_URL.startswith("https://") else None
    with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
        result = json.loads(response.read().decode())
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Master /health returned unhealthy response")
    return result


def _local_blocked() -> list[str]:
    try:
        data = json.loads(STATE.read_text())
        return [x for x in data.get("blocked", []) if _valid_ip(x)][-500:]
    except (OSError, ValueError, TypeError):
        return []


def _save_state(**updates: object) -> None:
    current: dict = {}
    try:
        loaded = json.loads(STATE.read_text())
        if isinstance(loaded, dict):
            current = loaded
    except (OSError, ValueError, TypeError):
        pass
    current.update(updates)
    blocked = [x for x in current.get("blocked", []) if isinstance(x, str) and _valid_ip(x)]
    current["blocked"] = blocked[-500:]
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_name(f".{STATE.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(current, ensure_ascii=False))
        tmp.chmod(0o600)
        os.replace(tmp, STATE)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


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
    blocked = set(_local_blocked())
    for command in result.get("commands", []):
        if command.get("action") == "block" and _valid_ip(str(command.get("ip", ""))):
            ip = str(command["ip"])
            ok = apply_block(ip, int(command.get("until", 0)))
            applied.append({"ip": ip, "ok": ok})
            if ok:
                blocked.add(ip)
    _save_state(last_ok=time.time(), commands=result.get("commands", []), applied=applied, blocked=sorted(blocked), master_url=MASTER_URL)
    result["applied"] = applied
    result["master_url"] = MASTER_URL
    return result


def apply_block(ip: str, until: int) -> bool:
    bantime = max(60, until - int(time.time()))
    base = ["fail2ban-client", "set", "xfi-guard"]
    configure = subprocess.run(base + ["bantime", str(bantime)], capture_output=True, text=True, timeout=15, check=False)
    if configure.returncode != 0:
        return False
    p = subprocess.run(base + ["banip", ip], capture_output=True, text=True, timeout=15, check=False)
    return p.returncode == 0


def run() -> None:
    while True:
        try:
            heartbeat()
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            try:
                _save_state(last_error=f"{type(exc).__name__}: {exc}", last_attempt=time.time(), master_url=MASTER_URL)
            except OSError:
                pass
        time.sleep(INTERVAL)


if __name__ == "__main__":
    run()
