from __future__ import annotations

import json
import os
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer


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

        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/health")
        response = conn.getresponse()
        assert response.status == 401
        conn.close()

        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/health", headers={"Authorization": "Bearer test-token"})
        response = conn.getresponse()
        assert response.status == 200
        payload = json.loads(response.read())
        assert payload["ok"] is True
        assert payload["nodes"] == 0
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
