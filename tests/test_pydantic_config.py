import pytest
from pydantic import ValidationError

from xfi_guard.ai_config import AISettings, MonitorSettings


def test_monitor_settings_clamps_are_now_validation_errors():
    with pytest.raises(ValidationError):
        MonitorSettings(interval_seconds=2)
    with pytest.raises(ValidationError):
        MonitorSettings(memory_warning_percent=101)


def test_ai_provider_and_consensus_validation():
    assert AISettings(provider="groq", ai_min_consensus=0.85).provider == "groq"
    with pytest.raises(ValidationError):
        AISettings(provider="unknown")
    with pytest.raises(ValidationError):
        AISettings(ai_min_consensus=1.1)
    with pytest.raises(ValidationError):
        AISettings(ai_weights={"groq": 0})
