"""Безопасный сбор состояния узлов XFI Guard.

Модуль принимает уже полученные метаданные и намеренно не выполняет shell-команды.
Он нормализует состояние служб, AWG и системных показателей для Health Monitor.
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
    node_id: str
    role: str
    services: Mapping[str, ServiceState]
    awg_handshake: bool | None = None
    internet_reachable: bool | None = None
    cpu_percent: float | None = None
    memory_percent: float | None = None
    disk_percent: float | None = None

    def health_score(self) -> int:
        """Консервативная оценка: неизвестное состояние не считается нормой."""
        checks: list[bool] = [state is ServiceState.RUNNING for state in self.services.values()]
        checks.extend(value for value in (self.awg_handshake, self.internet_reachable) if value is not None)
        if not checks:
            return 0
        return round(100 * sum(checks) / len(checks))


class DiscoveryPolicy:
    """Белый список безопасных телеметрических полей."""

    ALLOWED_FIELDS = frozenset({
        "node_id", "role", "services", "awg_handshake",
        "internet_reachable", "cpu_percent", "memory_percent", "disk_percent",
    })

    @classmethod
    def sanitize(cls, payload: Mapping[str, object]) -> dict[str, object]:
        return {key: value for key, value in payload.items() if key in cls.ALLOWED_FIELDS}
