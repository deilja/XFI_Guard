"""Regression tests for XFI Guard Cluster Master/Node authentication."""

import json
import time

import pytest

from xfi_guard.cluster_auth import sign_heartbeat


def test_heartbeat_signature_is_deterministic():
    payload = {
        "node": "ger",
        "node_id": "node-1",
        "timestamp": 1700000000,
        "hostname": "ger",
        "blocked": ["1.2.3.4"],
    }
    first = sign_heartbeat(payload, "secret")
    second = sign_heartbeat(payload, "secret")
    assert first == second
    assert len(first) >= 32


def test_heartbeat_signature_changes_when_payload_changes():
    payload = {
        "node": "ger",
        "node_id": "node-1",
        "timestamp": 1700000000,
        "hostname": "ger",
        "blocked": [],
    }
    first = sign_heartbeat(payload, "secret")
    payload["blocked"] = ["8.8.8.8"]
    second = sign_heartbeat(payload, "secret")
    assert first != second


def test_heartbeat_signature_changes_when_secret_changes():
    payload = {"node": "ger", "node_id": "node-1", "timestamp": 1700000000}
    assert sign_heartbeat(payload, "secret-a") != sign_heartbeat(payload, "secret-b")


def test_node_module_requires_secret(monkeypatch):
    monkeypatch.setenv("XFI_GUARD_CLUSTER_SECRET", "")
    import importlib
    import xfi_guard.cluster_node as node
    node = importlib.reload(node)
    with pytest.raises(RuntimeError, match="SECRET is not configured"):
        node.heartbeat()


def test_node_module_builds_authenticated_heartbeat(monkeypatch):
    monkeypatch.setenv("XFI_GUARD_CLUSTER_SECRET", "test-secret")
    monkeypatch.setenv("XFI_GUARD_CLUSTER_TOKEN", "test-token")
    import importlib
    import xfi_guard.cluster_node as node
    node = importlib.reload(node)

    captured = {}

    def fake_request(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"ok": True, "commands": []}

    monkeypatch.setattr(node, "_request", fake_request)
    monkeypatch.setattr(node, "_local_blocked", lambda: ["1.2.3.4"])
    result = node.heartbeat()

    assert result["ok"] is True
    assert captured["path"] == "/heartbeat"
    payload = captured["payload"]
    assert payload["node"]
    assert payload["node_id"]
    assert payload["blocked"] == ["1.2.3.4"]
    assert payload["signature"] == sign_heartbeat(
        {k: v for k, v in payload.items() if k != "signature"},
        "test-secret",
    )


def test_cluster_ui_default_master_url_is_local(monkeypatch):
    monkeypatch.delenv("XFI_GUARD_CLUSTER_MASTER_URL", raising=False)
    import importlib
    import xfi_guard.cluster_ui as ui
    ui = importlib.reload(ui)
    assert ui._master_url() == "http://127.0.0.1:8765"


def test_cluster_ui_uses_configured_master_url(monkeypatch):
    monkeypatch.setenv("XFI_GUARD_CLUSTER_MASTER_URL", "http://10.70.0.1:8765/")
    import importlib
    import xfi_guard.cluster_ui as ui
    ui = importlib.reload(ui)
    assert ui._master_url() == "http://10.70.0.1:8765"
