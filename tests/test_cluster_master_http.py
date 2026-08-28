from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from xfi_guard.cluster_auth import sign_heartbeat


def _request(host, port, method, path, body=None, token="test-token"):
    conn = HTTPConnection(host, port, timeout=2)
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        raw = json.dumps(body).encode()
        conn.request(method, path, body=raw, headers=headers)
    else:
        conn.request(method, path, headers=headers)
    response = conn.getresponse()
    payload = json.loads(response.read())
    conn.close()
    return response.status, payload


def test_cluster_master_health_and_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("XFI_GUARD_CLUSTER_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("XFI_GUARD_CLUSTER_TOKEN", "test-token")
    monkeypatch.setenv("XFI_GUARD_CLUSTER_SECRET", "test-secret")

    from xfi_guard import cluster_master as cm

    cm.NODES.clear()
    cm.COMMANDS.clear()
    cm.BLOCKS.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), cm.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address

        status, _ = _request(host, port, "GET", "/health", token="wrong-token")
        assert status == 401

        status, payload = _request(host, port, "GET", "/health")
        assert status == 200
        assert payload["ok"] is True
        assert payload["nodes"] == 0

        heartbeat = {
            "node": "node-1",
            "node_id": "node_test",
            "hostname": "test-host",
            "blocked": ["203.0.113.10"],
            "timestamp": time.time(),
            "nonce": "nonce-test-1",
        }
        heartbeat["signature"] = sign_heartbeat(heartbeat, "test-secret")
        status, payload = _request(host, port, "POST", "/heartbeat", heartbeat)
        assert status == 200
        assert payload["ok"] is True
        assert payload["commands"] == []

        status, payload = _request(host, port, "GET", "/nodes")
        assert status == 200
        assert payload["nodes"][0]["name"] == "node-1"
        assert payload["nodes"][0]["online"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_cluster_master_rejects_stale_heartbeat(monkeypatch, tmp_path):
    monkeypatch.setenv("XFI_GUARD_CLUSTER_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("XFI_GUARD_CLUSTER_TOKEN", "test-token")
    monkeypatch.setenv("XFI_GUARD_CLUSTER_SECRET", "test-secret")

    from xfi_guard import cluster_master as cm

    cm.NODES.clear()
    cm.COMMANDS.clear()
    cm.BLOCKS.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), cm.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        heartbeat = {
            "node": "node-stale",
            "node_id": "node_test",
            "hostname": "stale-host",
            "blocked": [],
            "timestamp": time.time() - 121,
            "nonce": "nonce-stale-1",
        }
        heartbeat["signature"] = sign_heartbeat(heartbeat, "test-secret")
        status, payload = _request(host, port, "POST", "/heartbeat", heartbeat)
        assert status == 401
        assert payload["error"] == "invalid node heartbeat"
        assert "node-stale" not in cm.NODES
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
