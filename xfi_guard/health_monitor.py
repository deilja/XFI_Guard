"""Состояние узлов, изменение состояния и безопасные инциденты."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone
from .discovery import NodeSnapshot


class IncidentLevel(str, Enum):
    INFO = "информация"
    WARNING = "предупреждение"
    HIGH = "высокий"
    CRITICAL = "критический"


@dataclass(frozen=True)
class HealthIncident:
    node_id: str
    level: IncidentLevel
    title: str
    details: str
    created_at: datetime


class HealthMonitor:
    """Pure monitor: compares snapshots, executes nothing."""

    def __init__(self) -> None:
        self._previous: dict[str, NodeSnapshot] = {}

    def update(self, snapshot: NodeSnapshot) -> list[HealthIncident]:
        previous = self._previous.get(snapshot.node_id)
        self._previous[snapshot.node_id] = snapshot
        if previous is None:
            return []

        incidents: list[HealthIncident] = []
        if previous.awg_handshake is True and snapshot.awg_handshake is False:
            incidents.append(HealthIncident(
                snapshot.node_id, IncidentLevel.HIGH,
                "Потеряно рукопожатие AWG",
                "Туннель AWG перестал подтверждаться.",
                datetime.now(timezone.utc),
            ))
        if previous.internet_reachable is True and snapshot.internet_reachable is False:
            incidents.append(HealthIncident(
                snapshot.node_id, IncidentLevel.HIGH,
                "Потерян выход в Интернет",
                "Узел больше не подтверждает доступность выхода.",
                datetime.now(timezone.utc),
            ))

        for service, old_state in previous.services.items():
            new_state = snapshot.services.get(service)
            if old_state.value == "работает" and new_state is not None and new_state.value == "остановлен":
                incidents.append(HealthIncident(
                    snapshot.node_id, IncidentLevel.HIGH,
                    f"Остановлена служба: {service}",
                    f"Служба {service} перешла из состояния «работает» в «остановлен».",
                    datetime.now(timezone.utc),
                ))
        return incidents
