"""Minimal stdlib HTTP master for XFI Guard Multi-VPS synchronization."""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .cluster import accept_event
from .cluster_notify import notify_global_block_sync
from .cluster_policy import evaluate
from .threat_intel import active

NODES: dict[str, dict] = {}
COMMANDS: dict[str, list[dict]] = {}
LOCK = threading.Lock()


def _json(handler, code: int, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


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
        if not expected:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {expected}"

    def do_POST(self):
        if not self._auth():
            return _json(self, 401, {"error": "unauthorized"})
        try:
            payload = self._body()
            if self.path == "/heartbeat":
                node = str(payload.get("node", ""))[:128]
                if not node:
                    raise ValueError("missing node")
                with LOCK:
                    NODES[node] = {"last_seen": time.time(), "status": "online"}
                    commands = COMMANDS.pop(node, [])
                return _json(self, 200, {"ok": True, "commands": commands})
            if self.path == "/threat":
                secret = os.getenv("XFI_GUARD_CLUSTER_SECRET", "")
                if not secret:
                    raise ValueError("master secret is not configured")
                signature = str(payload.get("signature", ""))
                signed_payload = dict(payload)
                signed_payload.pop("signature", None)
                item = accept_event(signed_payload, signature, secret)
                source_node = str(signed_payload.get("node", "unknown"))
                nodes = len(item.get("origin_nodes", []))
                decision = evaluate(item.get("score", 0), item.get("risk", "low"), nodes, require_two_nodes=False)
                blocked_nodes = []
                until = None
                if decision.allowed:
                    until = time.time() + 604800
                    with LOCK:
                        for node, state in NODES.items():
                            if node != source_node and time.time() - state["last_seen"] <= 90:
                                COMMANDS.setdefault(node, []).append({"action":"block","ip":item["ip"],"until":until,"source_node":source_node})
                                blocked_nodes.append(node)
                    event = dict(item)
                    event.update({"source_node": source_node, "until": until, "confidence": signed_payload.get("confidence", "-"), "providers": signed_payload.get("providers", "-")})
                    try:
                        notify_global_block_sync(event, blocked_nodes)
                    except Exception:
                        pass
                return _json(self, 200, {"ok": True, "threat": item, "global_block": decision.allowed, "blocked_nodes": blocked_nodes})
            return _json(self, 404, {"error": "not found"})
        except Exception as exc:
            return _json(self, 400, {"error": str(exc)})

    def do_GET(self):
        if not self._auth():
            return _json(self, 401, {"error": "unauthorized"})
        if self.path == "/health":
            now = time.time()
            with LOCK:
                online = sum(1 for n in NODES.values() if now - n["last_seen"] <= 90)
            return _json(self, 200, {"ok": True, "nodes": len(NODES), "online": online, "threats": len(active(500))})
        return _json(self, 404, {"error": "not found"})


def main():
    host = os.getenv("XFI_GUARD_CLUSTER_HOST", "127.0.0.1")
    port = int(os.getenv("XFI_GUARD_CLUSTER_PORT", "8765"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
