import ssl

import pytest

from xfi_guard.node_gateway import (
    GatewayPolicy,
    NodeAuthError,
    NodeIdentity,
    identity_from_certificate,
    load_allowlist,
)


def test_unknown_node_is_denied():
    policy = GatewayPolicy(frozenset({"master"}))
    with pytest.raises(NodeAuthError):
        policy.authorize(NodeIdentity("entry-01", "ENTRY"))


def test_public_source_is_denied_when_management_is_private_only():
    policy = GatewayPolicy(
        frozenset({"entry-01"}),
        trusted_networks=("10.70.0.0/16",),
    )
    with pytest.raises(NodeAuthError):
        policy.authorize(NodeIdentity("entry-01", "ENTRY"), "8.8.8.8")
    policy.authorize(NodeIdentity("entry-01", "ENTRY"), "10.70.1.11")


def test_certificate_identity_requires_xfi_prefix():
    cert = {"subject": ((("commonName", "xfi-node:entry-01:ENTRY"),),)}
    identity = identity_from_certificate(cert)
    assert identity == NodeIdentity("entry-01", "ENTRY")

    bad = {"subject": ((("commonName", "example.com"),),)}
    with pytest.raises(NodeAuthError):
        identity_from_certificate(bad)


def test_allowlist_is_russian_admin_friendly_format():
    policy = load_allowlist(["# узлы", "master=MASTER", "entry-01=ENTRY"])
    assert policy.trusted_nodes == frozenset({"master", "entry-01"})
    assert policy.trusted_roles == frozenset({"MASTER", "ENTRY"})


def test_tls_version_floor_is_supported():
    assert ssl.TLSVersion.TLSv1_2 < ssl.TLSVersion.TLSv1_3
