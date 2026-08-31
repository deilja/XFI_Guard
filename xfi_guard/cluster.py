"""Signed cluster events and safe multi-VPS Fail2Ban synchronization."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import shlex
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .threat_intel import report, mark_blocked
from .nodes import Node, load_nodes

BANTIME = 604800
_EVENT_LOCK = threading.Lock()
_SEEN_EVENTS: dict[str, float] = {}
_MAX_SEEN_EVENTS = 8192


def sign_event(payload: dict, secret: str) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_event(payload: dict, signature: str, secret: str) -> bool:
    return bool(secret) and hmac.compare_digest(sign_event(payload, secret), str(signature))


def accept_event(payload: dict, signature: str, secret: str) -> dict:
    if not verify_event(payload, signature, secret):
        raise ValueError("invalid cluster signature")
    try:
        timestamp = float(payload.get("timestamp", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid cluster timestamp") from exc
    now = time.time()
    if abs(now - timestamp) > 300:
        raise ValueError("stale cluster event")
    nonce = str(payload.get("nonce", "")).strip()
    if not nonce or len(nonce) > 128:
        raise ValueError("invalid cluster event nonce")
    try:
        parsed = ipaddress.ip_address(str(payload.get("ip", "")).strip())
    except ValueError as exc:
        raise ValueError("invalid cluster event IP") from exc
    if parsed.version != 4 or not parsed.is_global:
        raise ValueError("cluster events require a public IPv4")

    event_key = hashlib.sha256((secret + ":" + nonce).encode()).hexdigest()
    with _EVENT_LOCK:
        for key, seen_at in list(_SEEN_EVENTS.items()):
            if seen_at < now - 300:
                _SEEN_EVENTS.pop(key, None)
        if event_key in _SEEN_EVENTS:
            raise ValueError("replayed cluster event")
        if len(_SEEN_EVENTS) >= _MAX_SEEN_EVENTS:
            oldest = min(_SEEN_EVENTS, key=_SEEN_EVENTS.get)
            _SEEN_EVENTS.pop(oldest, None)
        _SEEN_EVENTS[event_key] = now

    try:
        score = max(0, min(100, int(payload.get("score", 0) or 0)))
        events = max(1, min(100000, int(payload.get("events", 1) or 1)))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid cluster event score/events") from exc
    return report(parsed.compressed, str(payload.get("node", "unknown"))[:128], score, str(payload.get("risk", "low"))[:32], events, str(payload.get("source", "cluster"))[:128])


def make_event(ip: str, node: str, score: int, risk: str, events: int, source: str, secret: str) -> dict:
    payload = {"ip": ip, "node": node, "score": int(score), "risk": risk, "events": int(events), "source": source, "timestamp": time.time(), "nonce": secrets.token_urlsafe(24)}
    payload["signature"] = sign_event(payload, secret)
    return payload


def register_global_block(ip: str, node: str, until: float) -> dict:
    return mark_blocked(ip, node, until, "cluster")


def _valid_ip(ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(ip)
        return parsed.version == 4 and parsed.is_global
    except ValueError:
        return False


def _ssh(node: Node, args: list[str], timeout: int = 15) -> tuple[bool, str]:
    """Run a fixed remote executable with shell-quoted arguments only."""
    if not args or any("\x00" in value for value in args):
        return False, "invalid remote command"
    remote = " ".join(shlex.quote(value) for value in args)
    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=7",
        "-p", str(node.port), f"{node.user}@{node.host}", "--", remote,
    ]
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
        return p.returncode == 0, (p.stdout or p.stderr or "").strip()[-1200:]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def ban_on_node(node: Node, ip: str, bantime: int = BANTIME) -> dict:
    if not _valid_ip(ip):
        return {"node": node.name, "ip": ip, "ok": False, "error": "invalid IP"}
    safe_bantime = max(60, min(int(bantime), BANTIME))
    base = ["sudo", "fail2ban-client", "set", "xfi-guard"]
    ok, out = _ssh(node, base + ["bantime", str(safe_bantime)])
    if not ok:
        return {"node": node.name, "ip": ip, "ok": False, "output": out}
    ok, out = _ssh(node, base + ["banip", ip])
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
