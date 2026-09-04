"""Сравнение снимков состояния текущего VPS без удалённых узлов."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
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
    """Чистый локальный монитор: сравнивает снимки и ничего не выполняет."""
    def __init__(self) -> None:
        self._previous: dict[str, NodeSnapshot] = {}

    def update(self, snapshot: NodeSnapshot) -> list[HealthIncident]:
        previous = self._previous.get(snapshot.node_id)
        self._previous[snapshot.node_id] = snapshot
        if previous is None:
            return []
        incidents: list[HealthIncident] = []
        now = datetime.now(timezone.utc)
        if previous.awg_handshake is True and snapshot.awg_handshake is False:
            incidents.append(HealthIncident(snapshot.node_id, IncidentLevel.HIGH,
                "Потеряно рукопожатие AWG", "Туннель AWG перестал подтверждаться.", now))
        if previous.internet_reachable is True and snapshot.internet_reachable is False:
            incidents.append(HealthIncident(snapshot.node_id, IncidentLevel.HIGH,
                "Потерян выход в Интернет", "Текущий VPS больше не подтверждает доступность выхода.", now))
        for service, old_state in previous.services.items():
            new_state = snapshot.services.get(service)
            if old_state.value == "работает" and new_state is not None and new_state.value == "остановлен":
                incidents.append(HealthIncident(snapshot.node_id, IncidentLevel.HIGH,
                    f"Остановлена служба: {service}",
                    f"Служба {service} перешла из состояния «работает» в «остановлен».", now))
        return incidents
