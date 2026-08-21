"""Persistent, idempotent HTTP master for XFI Guard Multi-VPS synchronization."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .cluster import accept_event
from .cluster_notify import notify_global_block_sync
from .cluster_policy import evaluate
from .threat_intel import active

STATE_PATH = Path(os.getenv("XFI_GUARD_CLUSTER_STATE", "/var/lib/xfi-guard/cluster-state.json"))
NODES: dict[str, dict] = {}
COMMANDS: dict[str, list[dict]] = {}
BLOCKS: dict[str, dict] = {}
LOCK = threading.RLock()


def _load():
    try:
        data = json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, ValueError, OSError):
        return
    with LOCK:
        COMMANDS.update(data.get("commands", {}))
        BLOCKS.update(data.get("blocks", {}))


def _save():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps({"commands": COMMANDS, "blocks": BLOCKS}, ensure_ascii=False, indent=2))
    os.replace(tmp, STATE_PATH)


def _json(handler, code: int, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _command_id(ip: str, until: float) -> str:
    return hashlib.sha256(f"{ip}|{int(until)}".encode()).hexdigest()[:24]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 65536:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(length).decode())

    def _auth(self):
        expected = os.getenv("XFI_GUARD_CLUSTER_TOKEN", "")
        return not expected or self.headers.get("Authorization", "") == f"Bearer {expected}"

    def do_POST(self):
        if not self._auth(): return _json(self, 401, {"error": "unauthorized"})
        try:
            payload = self._body()
            if self.path == "/heartbeat":
                node = str(payload.get("node", ""))[:128]
                if not node: raise ValueError("missing node")
                now = time.time()
                with LOCK:
                    NODES[node] = {"last_seen": now, "status": "online", "blocked": payload.get("blocked", [])[:500]}
                    commands = [c for c in COMMANDS.get(node, []) if float(c.get("until", 0)) > now]
                    COMMANDS[node] = []
                    for c in commands:
                        b = BLOCKS.get(c["ip"])
                        if b: b.setdefault("nodes", {})[node] = "queued"
                    _save()
                return _json(self, 200, {"ok": True, "commands": commands})

            if self.path == "/threat":
                secret = os.getenv("XFI_GUARD_CLUSTER_SECRET", "")
                if not secret: raise ValueError("master secret is not configured")
                signature = str(payload.get("signature", ""))
                signed_payload = dict(payload); signed_payload.pop("signature", None)
                item = accept_event(signed_payload, signature, secret)
                source_node = str(signed_payload.get("node", "unknown"))
                decision = evaluate(item.get("score", 0), item.get("risk", "low"), len(item.get("origin_nodes", [])), require_two_nodes=False)
                blocked_nodes = []
                if decision.allowed:
                    until = time.time() + 604800
                    cid = _command_id(item["ip"], until)
                    with LOCK:
                        block = BLOCKS.setdefault(item["ip"], {"command_id": cid, "until": until, "source_node": source_node, "nodes": {}})
                        block["until"] = max(float(block.get("until", 0)), until)
                        block["command_id"] = cid
                        for node, state in NODES.items():
                            if time.time() - state["last_seen"] <= 90 and node != source_node:
                                if state.get("blocked") and item["ip"] in state["blocked"]:
                                    block["nodes"][node] = "blocked"
                                    continue
                                if not any(c.get("command_id") == cid for c in COMMANDS.setdefault(node, [])):
                                    COMMANDS[node].append({"action":"block","ip":item["ip"],"until":until,"source_node":source_node,"command_id":cid})
                                block["nodes"][node] = "queued"
                                blocked_nodes.append(node)
                        _save()
                    event = dict(item)
                    event.update({"source_node": source_node, "until": until, "confidence": signed_payload.get("confidence", "-"), "providers": signed_payload.get("providers", "-")})
                    try: notify_global_block_sync(event, blocked_nodes)
                    except Exception: pass
                return _json(self, 200, {"ok": True, "threat": item, "global_block": decision.allowed, "blocked_nodes": blocked_nodes})
            return _json(self, 404, {"error": "not found"})
        except Exception as exc:
            return _json(self, 400, {"error": str(exc)})

    def do_GET(self):
        if not self._auth(): return _json(self, 401, {"error": "unauthorized"})
        if self.path == "/health":
            now = time.time()
            with LOCK:
                online = sum(1 for n in NODES.values() if now - n["last_seen"] <= 90)
                return _json(self, 200, {"ok": True, "nodes": len(NODES), "online": online, "threats": len(active(500))})
        if self.path == "/nodes":
            now = time.time()
            with LOCK:
                return _json(self, 200, {"nodes": [{"name": n, **s, "online": now-s["last_seen"] <= 90} for n,s in NODES.items()]})
        if self.path.startswith("/block/"):
            ip = self.path.removeprefix("/block/")
            with LOCK: return _json(self, 200, BLOCKS.get(ip, {"ip": ip, "nodes": {}}))
        return _json(self, 404, {"error": "not found"})


def main():
    _load()
    host = os.getenv("XFI_GUARD_CLUSTER_HOST", "127.0.0.1")
    port = int(os.getenv("XFI_GUARD_CLUSTER_PORT", "8765"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__": main()
