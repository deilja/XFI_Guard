"""Node registration and certificate lifecycle metadata.

This layer deliberately does not generate or persist private keys. A node
creates its own key/CSR; XFI Guard stores only the public certificate and
lifecycle metadata. Revocation is deny-by-default through the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum


class NodeStatus(str, Enum):
    PENDING = "ожидает подтверждения"
    ACTIVE = "активен"
    REVOKED = "отозван"
    EXPIRED = "истёк"


@dataclass(frozen=True)
class RegisteredNode:
    node_id: str
    role: str
    certificate_fingerprint: str
    issued_at: datetime
    expires_at: datetime
    status: NodeStatus = NodeStatus.PENDING

    def is_valid(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return self.status is NodeStatus.ACTIVE and self.issued_at <= now < self.expires_at


class NodeRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, RegisteredNode] = {}

    def register(
        self,
        node_id: str,
        role: str,
        certificate_fingerprint: str,
        ttl_days: int = 90,
        now: datetime | None = None,
    ) -> RegisteredNode:
        if not node_id or not certificate_fingerprint:
            raise ValueError("идентификатор и отпечаток сертификата обязательны")
        if ttl_days < 1:
            raise ValueError("срок сертификата должен быть не менее 1 дня")
        now = now or datetime.now(timezone.utc)
        node = RegisteredNode(
            node_id=node_id,
            role=role.upper(),
            certificate_fingerprint=certificate_fingerprint.lower(),
            issued_at=now,
            expires_at=now + timedelta(days=ttl_days),
        )
        self._nodes[node_id] = node
        return node

    def approve(self, node_id: str) -> RegisteredNode:
        node = self._nodes[node_id]
        updated = replace(node, status=NodeStatus.ACTIVE)
        self._nodes[node_id] = updated
        return updated

    def revoke(self, node_id: str) -> RegisteredNode:
        node = self._nodes[node_id]
        updated = replace(node, status=NodeStatus.REVOKED)
        self._nodes[node_id] = updated
        return updated

    def get(self, node_id: str) -> RegisteredNode | None:
        return self._nodes.get(node_id)

    def authorize(self, node_id: str, fingerprint: str, now: datetime | None = None) -> RegisteredNode:
        node = self._nodes.get(node_id)
        if node is None or node.certificate_fingerprint != fingerprint.lower():
            raise PermissionError("узел или сертификат не зарегистрирован")
        if not node.is_valid(now):
            raise PermissionError("сертификат узла неактивен или истёк")
        return node

    def expire(self, now: datetime | None = None) -> list[RegisteredNode]:
        now = now or datetime.now(timezone.utc)
        changed: list[RegisteredNode] = []
        for node_id, node in self._nodes.items():
            if node.status is NodeStatus.ACTIVE and now >= node.expires_at:
                updated = replace(node, status=NodeStatus.EXPIRED)
                self._nodes[node_id] = updated
                changed.append(updated)
        return changed
