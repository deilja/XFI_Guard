"""Regression tests for XFI Guard Cluster Master/Node authentication."""

import importlib
import time

import pytest

from xfi_guard.cluster_auth import sign_heartbeat, verify_heartbeat


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


def test_heartbeat_requires_nonce_and_rejects_replay():
    payload = {"node": "ger", "node_id": "node-1", "timestamp": time.time(), "nonce": "nonce-1"}
    signature = sign_heartbeat(payload, "secret")
    assert verify_heartbeat(payload, signature, "secret") is True
    assert verify_heartbeat(payload, signature, "secret") is False


def test_heartbeat_rejects_stale_timestamp():
    payload = {"node": "ger", "node_id": "node-1", "timestamp": time.time() - 1000, "nonce": "nonce-stale"}
    assert verify_heartbeat(payload, sign_heartbeat(payload, "secret"), "secret", max_age=120) is False


def test_heartbeat_rejects_invalid_signature():
    payload = {"node": "ger", "node_id": "node-1", "timestamp": time.time(), "nonce": "nonce-invalid"}
    assert verify_heartbeat(payload, "bad", "secret") is False


def test_node_module_requires_secret(monkeypatch):
    monkeypatch.setenv("XFI_GUARD_CLUSTER_SECRET", "")
    import xfi_guard.cluster_node as node
    node = importlib.reload(node)
    with pytest.raises(RuntimeError, match="SECRET is not configured"):
        node.heartbeat()


def test_node_module_builds_authenticated_heartbeat(monkeypatch):
    monkeypatch.setenv("XFI_GUARD_CLUSTER_SECRET", "test-secret")
    monkeypatch.setenv("XFI_GUARD_CLUSTER_TOKEN", "test-token")
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
    assert payload["nonce"]
    assert payload["signature"] == sign_heartbeat(
        {k: v for k, v in payload.items() if k != "signature"},
        "test-secret",
    )


def test_legacy_cluster_agent_builds_master_compatible_heartbeat(monkeypatch):
    monkeypatch.setenv("XFI_GUARD_CLUSTER_TLS_INSECURE", "true")
    import xfi_guard.cluster_agent as agent
    agent = importlib.reload(agent)
    captured = {}

    monkeypatch.setattr(agent, "list_blocked_ips", lambda: ["1.2.3.4"])

    def fake_post(url, payload, token=""):
        captured.update(url=url, payload=payload, token=token)
        return {"ok": True, "commands": []}

    monkeypatch.setattr(agent, "_post", fake_post)
    result = agent.heartbeat("https://master.example", "node-1", "test-secret", "test-token")

    assert result["ok"] is True
    assert captured["url"] == "https://master.example/heartbeat"
    assert captured["token"] == "test-token"
    payload = captured["payload"]
    assert payload["node"] == "node-1"
    assert payload["node_id"] == "node-1"
    assert payload["hostname"]
    assert payload["nonce"]
    assert payload["blocked"] == ["1.2.3.4"]
    assert payload["signature"] == sign_heartbeat(
        {k: v for k, v in payload.items() if k != "signature"},
        "test-secret",
    )


def test_cluster_agent_supports_self_signed_master(monkeypatch):
    monkeypatch.setenv("XFI_GUARD_CLUSTER_TLS_INSECURE", "true")
    import xfi_guard.cluster_agent as agent
    agent = importlib.reload(agent)
    assert agent._ssl_context() is not None


def test_cluster_ui_default_master_url_is_local(monkeypatch):
    monkeypatch.delenv("XFI_GUARD_CLUSTER_MASTER_URL", raising=False)
    import xfi_guard.cluster_ui as ui
    ui = importlib.reload(ui)
    assert ui._master_url() == "http://127.0.0.1:8765"


def test_cluster_ui_uses_configured_master_url(monkeypatch):
    monkeypatch.setenv("XFI_GUARD_CLUSTER_MASTER_URL", "http://10.70.0.1:8765/")
    import xfi_guard.cluster_ui as ui
    ui = importlib.reload(ui)
    assert ui._master_url() == "http://10.70.0.1:8765"
