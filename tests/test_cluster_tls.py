from __future__ import annotations

import ssl


def test_cluster_agent_uses_ca_bundle_before_insecure(monkeypatch, tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("dummy")
    monkeypatch.setenv("XFI_GUARD_CLUSTER_TLS_CA_FILE", str(ca))
    monkeypatch.setenv("XFI_GUARD_CLUSTER_TLS_INSECURE", "1")
    from xfi_guard import cluster_agent
    calls = {}

    def fake_default_context(*, cafile):
        calls["cafile"] = cafile
        return "ca-context"

    monkeypatch.setattr(ssl, "create_default_context", fake_default_context)
    assert cluster_agent._ssl_context() == "ca-context"
    assert calls["cafile"] == str(ca)


def test_cluster_agent_does_not_disable_tls_by_default(monkeypatch):
    monkeypatch.delenv("XFI_GUARD_CLUSTER_TLS_CA_FILE", raising=False)
    monkeypatch.delenv("XFI_GUARD_CLUSTER_TLS_INSECURE", raising=False)
    from xfi_guard import cluster_agent
    assert cluster_agent._ssl_context() is None


def test_cluster_agent_explicit_insecure_mode(monkeypatch):
    monkeypatch.delenv("XFI_GUARD_CLUSTER_TLS_CA_FILE", raising=False)
    monkeypatch.setenv("XFI_GUARD_CLUSTER_TLS_INSECURE", "1")
    from xfi_guard import cluster_agent
    context = cluster_agent._ssl_context()
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_NONE
