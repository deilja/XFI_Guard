from xfi_guard import ai


def test_ai_analyzer_sync_reloads_provider_and_openrouter_model(monkeypatch):
    settings = {
        "provider": "gemini",
        "gemini_key": "gemini-key",
        "gemini_model": "gemini-test",
        "groq_key": "",
        "groq_model": "openai/gpt-oss-20b",
        "openrouter_key": "or-key",
        "openrouter_model": "openrouter/free",
        "openrouter_models": ("openrouter/free",),
    }
    monkeypatch.setattr(ai, "load", lambda: dict(settings))
    analyzer = ai.AIAnalyzer()
    assert analyzer.status()["selected_provider"] == "gemini"

    settings["provider"] = "openrouter"
    settings["openrouter_model"] = "openrouter/auto"
    settings["openrouter_models"] = ("openrouter/auto", "openrouter/free")
    analyzer.sync()

    status = analyzer.status()
    assert status["selected_provider"] == "openrouter"
    assert status["openrouter_model"] == "openrouter/auto"
    assert status["openrouter_models"] == ["openrouter/auto", "openrouter/free"]
    assert "openrouter" in status["available_providers"]
