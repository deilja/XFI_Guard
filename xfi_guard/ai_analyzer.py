"""Безопасный AI-анализ инцидентов без автоматического исполнения."""
from __future__ import annotations

from dataclasses import dataclass
from .incident_correlator import CorrelatedIncident
from .health_monitor import IncidentLevel


@dataclass(frozen=True)
class AnalysisResult:
    summary: str
    risk: str
    probable_cause: str
    checks: tuple[str, ...]
    remediation: tuple[str, ...]
    requires_approval: bool = True


class AIAnalyzer:
    """Deterministic fallback analyzer; an LLM can be plugged in later."""

    def analyze(self, incident: CorrelatedIncident) -> AnalysisResult:
        risk = {
            IncidentLevel.INFO: "низкий",
            IncidentLevel.WARNING: "средний",
            IncidentLevel.HIGH: "высокий",
            IncidentLevel.CRITICAL: "критический",
        }[incident.level]
        checks = (
            "проверить состояние AWG и время последнего handshake",
            "проверить доступность зависимого узла",
            "проверить маршрутизацию и policy routing",
            "проверить журналы Xray/системной службы без изменения конфигурации",
        )
        remediation = (
            f"проверить узел {incident.root_node_id} как первопричину",
            "подготовить обратимый план восстановления",
            "не удалять inbound, клиентов или узлы 3x-ui без подтверждения",
        )
        return AnalysisResult(
            summary=incident.title,
            risk=risk,
            probable_cause=incident.details,
            checks=checks,
            remediation=remediation,
            requires_approval=True,
        )
