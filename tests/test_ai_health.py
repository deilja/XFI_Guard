from xfi_guard import ai_health


class DummyAnalyzer:
    def __init__(self):
        self.gemini = type("Gemini", (), {"model": "gemini-test"})()
        self.groq_model = "groq-test"
        self.openrouter_models = ["router-test"]
        self.calls = []

    def available_providers(self):
        return ["groq"]

    def _chat_model(self, provider, model, prompt, json_mode=False, force=False):
        self.calls.append((provider, model, json_mode, force))
        return "{}"

    last_error = ""


def test_health_check_bypasses_provider_cooldown(monkeypatch):
    analyzer = DummyAnalyzer()
    monkeypatch.setattr(ai_health, "AIAnalyzer", lambda: analyzer)
    monkeypatch.setattr(ai_health, "record", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_health, "adapt_weights", lambda: {})

    result = ai_health.run_health_check()
    groq = next(item for item in result["results"] if item["provider"] == "groq")

    assert groq["ok"] is True
    assert analyzer.calls == [("groq", "groq-test", True, True)]
