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
    monkeypatch.setattr(ai_health, "select_best_provider", lambda results: "groq")

    result = ai_health.run_health_check()

    assert result["results"][0]["ok"] is True
    assert result["recommended_provider"] == "groq"
    assert analyzer.calls == [("groq", "groq-test", True, True)]


def test_select_best_provider_prefers_healthy_low_latency(monkeypatch):
    saved = {}
    monkeypatch.setattr(ai_health, "load", lambda: {"ai_weights": {"gemini": 1.0, "groq": 1.0, "openrouter": 1.0}})
    monkeypatch.setattr(ai_health, "save", lambda cfg: saved.update(cfg))

    result = ai_health.select_best_provider([
        {"provider": "gemini", "model": "g", "ok": True, "latency_ms": 900},
        {"provider": "groq", "model": "g", "ok": True, "latency_ms": 120},
        {"provider": "openrouter", "model": "r", "ok": False, "latency_ms": 40},
    ])

    assert result == "groq"
    assert saved["provider"] == "groq"
    assert saved["ai_auto_selected_provider"] == "groq"
