from datetime import datetime, timezone

from xfi_guard.ai_analyzer import AIAnalyzer
from xfi_guard.health_monitor import HealthIncident, IncidentLevel
from xfi_guard.incident_correlator import CorrelatedIncident


def test_analysis_is_russian_and_requires_approval():
    source = HealthIncident("exit-01", IncidentLevel.HIGH, "AWG", "нет handshake", datetime.now(timezone.utc))
    incident = CorrelatedIncident(
        "exit-01", IncidentLevel.HIGH, "Корневая неисправность: exit-01",
        "Exit-01 определён как первичная точка отказа.", ("entry-01",), (source,),
    )
    result = AIAnalyzer().analyze(incident)
    assert result.risk == "высокий"
    assert result.requires_approval is True
    assert any("не удалять" in item for item in result.remediation)
