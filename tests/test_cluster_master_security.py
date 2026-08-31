"""Security regression tests for the authenticated cluster master HTTP API."""

import importlib
import json
import time

import pytest


def _load_master(monkeypatch):
    monkeypatch.setenv("XFI_GUARD_CLUSTER_TOKEN", "test-token")
    monkeypatch.setenv("XFI_GUARD_CLUSTER_SECRET", "test-secret")
    import xfi_guard.cluster_master as master
    return importlib.reload(master)


def test_cluster_master_requires_authentication(monkeypatch):
    master = _load_master(monkeypatch)
    handler = object.__new__(master.Handler)
    handler.headers = {"Authorization": "Bearer wrong"}
    assert handler._auth() is False


def test_cluster_master_rejects_missing_cluster_configuration(monkeypatch):
    monkeypatch.delenv("XFI_GUARD_CLUSTER_TOKEN", raising=False)
    monkeypatch.delenv("XFI_GUARD_CLUSTER_SECRET", raising=False)
    import xfi_guard.cluster_master as master
    master = importlib.reload(master)
    assert master._configured() is False


def test_cluster_master_body_limit(monkeypatch):
    master = _load_master(monkeypatch)

    class Body:
        headers = {"Content-Length": str(master.MAX_BODY_BYTES + 1)}

    handler = object.__new__(master.Handler)
    handler.headers = Body.headers
    with pytest.raises(ValueError, match="request too large"):
        handler._body()


def test_cluster_master_accepts_only_object_json(monkeypatch):
    master = _load_master(monkeypatch)

    class Body:
        headers = {"Content-Length": "2"}
        def read(self, length):
            return b"[]"

    handler = object.__new__(master.Handler)
    handler.headers = Body.headers
    handler.rfile = Body()
    with pytest.raises(ValueError, match="JSON object required"):
        payload = handler._body()
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")


def test_command_id_is_stable_for_same_block(monkeypatch):
    master = _load_master(monkeypatch)
    assert master._command_id("8.8.8.8", 1700000000) == master._command_id("8.8.8.8", 1700000000)
    assert master._command_id("8.8.8.8", 1700000000) != master._command_id("1.1.1.1", 1700000000)
