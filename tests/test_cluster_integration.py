from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path


def test_fin_to_ger_heartbeat_registers_only_after_authenticated_heartbeat(monkeypatch):
    secret = "integration-secret"
    token = "integration-token"
    monkeypatch.setenv("XFI_GUARD_CLUSTER_SECRET", secret)
    monkeypatch.setenv("XFI_GUARD_CLUSTER_TOKEN", token)

    from xfi_guard import cluster_master
    from xfi_guard import cluster_node

    # cluster_node may already have been imported by another test; replace its
    # module-level credentials explicitly so this integration test is isolated.
    monkeypatch.setattr(cluster_node, "TOKEN", token)
    monkeypatch.setattr(cluster_node, "SECRET", secret)

    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "node-state.json"
        node_id = Path(tmp) / "node-id"
        monkeypatch.setattr(cluster_node, "STATE", state)
        monkeypatch.setattr(cluster_node, "NODE_ID_FILE", node_id)
        monkeypatch.setattr(cluster_node, "NODE_NAME", "ger")
        cluster_master.NODES.clear()
        cluster_master.COMMANDS.clear()
        cluster_master.BLOCKS.clear()

        server = cluster_master.SafeThreadingHTTPServer(("127.0.0.1", 0), cluster_master.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            monkeypatch.setattr(cluster_node, "MASTER_URL", f"http://127.0.0.1:{server.server_port}")
            assert "ger" not in cluster_master.NODES

            result = cluster_node.heartbeat()
            assert result["ok"] is True
            assert result["master_url"] == f"http://127.0.0.1:{server.server_port}"
            assert "ger" in cluster_master.NODES
            assert cluster_master.NODES["ger"]["status"] == "online"
            saved = json.loads(state.read_text())
            assert saved["master_url"] == result["master_url"]
            assert saved["last_ok"] > 0
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
