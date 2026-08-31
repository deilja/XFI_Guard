import pytest

from xfi_guard import cluster_ui


def test_request_rejects_missing_cluster_token(monkeypatch):
    monkeypatch.delenv("XFI_GUARD_CLUSTER_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="XFI_GUARD_CLUSTER_TOKEN не задан"):
        cluster_ui._request("/nodes")


def test_callback_secret_rejects_missing_cluster_token(monkeypatch):
    monkeypatch.delenv("XFI_GUARD_CLUSTER_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="XFI_GUARD_CLUSTER_TOKEN не задан"):
        cluster_ui._callback_secret()
