"""Локальная телеметрия текущего VPS XFI Guard.

Совместимый контейнер для снимка состояния. Никакого обнаружения,
подключения или управления удалёнными VPS здесь нет.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

class ServiceState(str, Enum):
    UNKNOWN = "неизвестно"
    RUNNING = "работает"
    DEGRADED = "есть проблемы"
    STOPPED = "остановлен"

@dataclass(frozen=True)
class NodeSnapshot:
    """Снимок только локального VPS; node_id — идентификатор этого сервера."""
    node_id: str
    role: str
    services: Mapping[str, ServiceState]
    awg_handshake: bool | None = None
    internet_reachable: bool | None = None
    cpu_percent: float | None = None
    memory_percent: float | None = None
    disk_percent: float | None = None

    def health_score(self) -> int:
        checks = [state is ServiceState.RUNNING for state in self.services.values()]
        checks.extend(value for value in (self.awg_handshake, self.internet_reachable) if value is not None)
        return round(100 * sum(checks) / len(checks)) if checks else 0

class DiscoveryPolicy:
    """Белый список полей локальной телеметрии."""
    ALLOWED_FIELDS = frozenset({
        "node_id", "role", "services", "awg_handshake", "internet_reachable",
        "cpu_percent", "memory_percent", "disk_percent",
    })

    @classmethod
    def sanitize(cls, payload: Mapping[str, object]) -> dict[str, object]:
        return {key: value for key, value in payload.items() if key in cls.ALLOWED_FIELDS}
