from pathlib import Path

from xfi_guard import ai
from xfi_guard import ai_runtime


class DummyAnalyzer:
    def __init__(self):
        self.provider = "gemini"
        self.last_provider = "groq"
        self.last_model = "groq-test"
        self.last_error = "Gemini unavailable"

    def analyze(self, event, allow_fallback=True):
        return "fallback response"


def test_runtime_failover_is_audited(monkeypatch, tmp_path):
    path = tmp_path / "ai-events.jsonl"
    monkeypatch.setenv("XFI_GUARD_AI_EVENTS_PATH", str(path))
    ai_runtime.install(DummyAnalyzer)

    analyzer = DummyAnalyzer()
    result = analyzer.analyze({"event_type": "health_check"})

    assert result == "fallback response"
    line = Path(path).read_text(encoding="utf-8").strip()
    assert '"event":"ai_failover"' in line
    assert '"from_provider":"gemini"' in line
    assert '"to_provider":"groq"' in line
    assert '"model":"groq-test"' in line


def test_runtime_failed_analysis_is_audited(monkeypatch, tmp_path):
    path = tmp_path / "ai-events.jsonl"
    monkeypatch.setenv("XFI_GUARD_AI_EVENTS_PATH", str(path))

    class FailedAnalyzer:
        provider = "gemini"
        last_provider = ""
        last_model = "gemini-test"
        last_error = "all providers failed"

        def analyze(self, event, allow_fallback=True):
            return None

    ai_runtime.install(FailedAnalyzer)
    FailedAnalyzer().analyze({"event_type": "health_check"})

    line = Path(path).read_text(encoding="utf-8").strip()
    assert '"event":"ai_analysis_failed"' in line
    assert '"success":false' in line
