"""Authenticated Master/Entry/Exit node gateway primitives.

The gateway is deliberately policy-first: a caller must present a trusted
client certificate and its node identity must be allow-listed. This module
contains no shell execution and never stores private keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Iterable


class NodeAuthError(PermissionError):
    """Raised when a node cannot be authenticated or authorized."""


@dataclass(frozen=True)
class NodeIdentity:
    node_id: str
    role: str
    address: str | None = None


@dataclass(frozen=True)
class GatewayPolicy:
    """Allow-list for management-plane access.

    Public management exposure is never implied by this policy. The caller
    must also be on an explicitly trusted network when ``trusted_networks``
    is non-empty.
    """

    trusted_nodes: frozenset[str]
    trusted_roles: frozenset[str] = frozenset({"MASTER", "ENTRY", "EXIT"})
    trusted_networks: tuple[str, ...] = ()

    def authorize(self, identity: NodeIdentity, source_ip: str | None = None) -> None:
        if identity.node_id not in self.trusted_nodes:
            raise NodeAuthError("узел отсутствует в списке доверенных")
        if identity.role.upper() not in self.trusted_roles:
            raise NodeAuthError("роль узла запрещена политикой")
        if self.trusted_networks and source_ip is not None:
            source = ip_address(source_ip)
            if not any(source in ip_network(net, strict=False) for net in self.trusted_networks):
                raise NodeAuthError("источник находится вне доверенной сети")


def build_tls_server_context(cert_file: str, key_file: str, ca_file: str):
    """Build a TLS context requiring client certificates (mTLS)."""
    import ssl

    for value in (cert_file, key_file, ca_file):
        if not Path(value).is_file():
            raise FileNotFoundError(value)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    context.load_verify_locations(cafile=ca_file)
    return context


def identity_from_certificate(cert: dict) -> NodeIdentity:
    """Extract node identity from a peer certificate subject CN.

    The CN is an identifier only; authorization is performed separately by
    ``GatewayPolicy``. This keeps certificate parsing and authorization
    concerns separate.
    """
    common_name = None
    for item in cert.get("subject", ()):
        for key, value in item:
            if key == "commonName":
                common_name = value
                break
    if not common_name or not common_name.startswith("xfi-node:"):
        raise NodeAuthError("сертификат не содержит идентификатор XFI Guard")

    parts = common_name.split(":", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        raise NodeAuthError("некорректный идентификатор узла")
    return NodeIdentity(node_id=parts[1], role=parts[2].upper())


def load_allowlist(lines: Iterable[str]) -> GatewayPolicy:
    """Parse ``node_id=ROLE`` entries while ignoring comments and blanks."""
    nodes: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            node_id, role = line.split("=", 1)
        except ValueError as exc:
            raise ValueError(f"некорректная строка списка узлов: {line!r}") from exc
        node_id, role = node_id.strip(), role.strip().upper()
        if not node_id or not role:
            raise ValueError("пустой идентификатор или роль узла")
        nodes[node_id] = role
    return GatewayPolicy(
        trusted_nodes=frozenset(nodes),
        trusted_roles=frozenset(nodes.values()) or frozenset({"MASTER", "ENTRY", "EXIT"}),
    )
