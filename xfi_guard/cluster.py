"""Signed cluster events and safe multi-VPS Fail2Ban synchronization."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .threat_intel import report, mark_blocked
from .nodes import Node, load_nodes

BANTIME = 604800


def sign_event(payload: dict, secret: str) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_event(payload: dict, signature: str, secret: str) -> bool:
    return hmac.compare_digest(sign_event(payload, secret), str(signature))


def accept_event(payload: dict, signature: str, secret: str) -> dict:
    if not verify_event(payload, signature, secret):
        raise ValueError("invalid cluster signature")
    if abs(time.time() - float(payload.get("timestamp", 0))) > 300:
        raise ValueError("stale cluster event")
    return report(payload["ip"], payload.get("node", "unknown"), payload.get("score", 0), payload.get("risk", "low"), payload.get("events", 1), payload.get("source", "cluster"))


def make_event(ip: str, node: str, score: int, risk: str, events: int, source: str, secret: str) -> dict:
    payload = {"ip": ip, "node": node, "score": int(score), "risk": risk, "events": int(events), "source": source, "timestamp": time.time()}
    payload["signature"] = sign_event(payload, secret)
    return payload


def register_global_block(ip: str, node: str, until: float) -> dict:
    return mark_blocked(ip, node, until, "cluster")


def _valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def _ssh(node: Node, command: str, timeout: int = 15) -> tuple[bool, str]:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=7", "-p", str(node.port), f"{node.user}@{node.host}", "--", command]
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
        return p.returncode == 0, (p.stdout or p.stderr or "").strip()[-1200:]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def ban_on_node(node: Node, ip: str, bantime: int = BANTIME) -> dict:
    if not _valid_ip(ip):
        return {"node": node.name, "ip": ip, "ok": False, "error": "invalid IP"}
    command = f"sudo fail2ban-client set xfi-guard banip {ip} && sudo fail2ban-client set xfi-guard bantime {int(bantime)}"
    ok, out = _ssh(node, command)
    return {"node": node.name, "ip": ip, "ok": ok, "output": out}


def sync_ban(ip: str, path: str = "config.toml", bantime: int = BANTIME) -> list[dict]:
    if not _valid_ip(ip):
        raise ValueError("Invalid IP address")
    nodes = load_nodes(path)
    results: list[dict] = []
    if not nodes:
        return results
    with ThreadPoolExecutor(max_workers=min(8, len(nodes))) as pool:
        futures = [pool.submit(ban_on_node, node, ip, bantime) for node in nodes]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda x: x["node"])
