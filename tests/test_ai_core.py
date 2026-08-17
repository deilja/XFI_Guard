from xfi_guard import ai


class DummyGemini:
    model = "gemini-test"
    last_error = ""

    def __init__(self, enabled=True):
        self._enabled = enabled
        self.calls = 0

    def enabled(self):
        return self._enabled

    def analyze(self, event):
        self.calls += 1
        self.last_error = "Gemini недоступен"
        return None


def test_ai_status_reports_available_providers(monkeypatch, tmp_path):
    monkeypatch.setattr(ai, "load", lambda: {
        "provider": "gemini",
        "gemini_key": "gemini-key",
        "groq_key": "groq-key",
        "gemini_model": "gemini-test",
        "groq_model": "groq-test",
    })
    analyzer = ai.AIAnalyzer()
    assert analyzer.enabled() is True
    assert analyzer.available_providers() == ["gemini", "groq"]
    status = analyzer.status()
    assert status["ready"] is True
    assert status["selected_provider"] == "gemini"


def test_analyze_falls_back_to_groq(monkeypatch):
    monkeypatch.setattr(ai, "load", lambda: {
        "provider": "gemini",
        "gemini_key": "gemini-key",
        "groq_key": "groq-key",
        "gemini_model": "gemini-test",
        "groq_model": "groq-test",
    })
    analyzer = ai.AIAnalyzer()
    analyzer.gemini = DummyGemini()
    monkeypatch.setattr(analyzer, "_analyze_groq", lambda event: "ответ Groq")

    result = analyzer.analyze({"event_type": "health_check"})

    assert result == "ответ Groq"
    assert analyzer.last_provider == "groq"
    assert analyzer.last_model == "groq-test"


def test_analyze_without_any_provider_returns_clear_error(monkeypatch):
    monkeypatch.setattr(ai, "load", lambda: {
        "provider": "gemini",
        "gemini_key": "",
        "groq_key": "",
        "gemini_model": "gemini-test",
        "groq_model": "groq-test",
    })
    analyzer = ai.AIAnalyzer()
    assert analyzer.analyze({"event_type": "health_check"}) is None
    assert "не настроен" in analyzer.last_error.lower()
