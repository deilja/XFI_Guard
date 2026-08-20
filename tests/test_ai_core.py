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
    calls = []

    def fake_call(provider, model, prompt):
        calls.append((provider, model))
        if provider == "groq":
            analyzer.last_provider = provider
            analyzer.last_model = model
            return "ответ Groq"
        return None

    monkeypatch.setattr(analyzer, "_call", fake_call)

    result = analyzer.analyze("health check")

    assert result == "ответ Groq"
    assert analyzer.last_provider == "groq"
    assert analyzer.last_model == "groq-test"
    assert calls == [("gemini", "gemini-test"), ("groq", "groq-test")]


def test_analyze_without_any_provider_returns_clear_error(monkeypatch):
    monkeypatch.setattr(ai, "load", lambda: {
        "provider": "gemini",
        "gemini_key": "",
        "groq_key": "",
        "gemini_model": "gemini-test",
        "groq_model": "groq-test",
    })
    analyzer = ai.AIAnalyzer()
    assert analyzer.analyze("health check") is None
    assert "не настроен" in analyzer.last_error.lower()
