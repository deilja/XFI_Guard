from xfi_guard import ai


def _config(**overrides):
    config = {
        "provider": "gemini",
        "gemini_key": "gemini-key",
        "groq_key": "groq-key",
        "gemini_model": "gemini-test",
        "groq_model": "groq-test",
        "openrouter_key": "",
        "routerai_key": "",
    }
    config.update(overrides)
    return config


def test_ai_status_reports_available_providers(monkeypatch):
    monkeypatch.setattr(ai, "load", lambda: _config())
    analyzer = ai.AIAnalyzer()
    monkeypatch.setattr(analyzer, "discover_models", lambda force=False: {
        "gemini": ["gemini-test"], "groq": ["groq-test"], "openrouter": [], "routerai": []
    })

    assert analyzer.enabled() is True
    assert analyzer.available_providers() == ["gemini", "groq"]
    status = analyzer.status()
    assert status["ready"] is True
    assert status["selected_provider"] == "gemini"


def test_consensus_uses_multiple_provider_verdicts(monkeypatch):
    monkeypatch.setattr(ai, "load", lambda: _config())
    analyzer = ai.AIAnalyzer()
    monkeypatch.setattr(analyzer, "discover_models", lambda force=False: {
        "gemini": ["gemini-test"], "groq": ["groq-test"], "openrouter": [], "routerai": []
    })
    monkeypatch.setattr(analyzer, "_call", lambda provider, model, prompt: (
        '{"risk":"high","confidence":0.9,"reason":"test"}'
        if provider == "gemini" else
        '{"risk":"high","confidence":0.8,"reason":"test"}'
    ))

    result = analyzer.analyze_consensus({"event_type": "health_check"})

    assert result["winner"] == "high"
    assert result["consensus"] is True
    assert result["providers_used"] == 2
    assert result["degraded"] is False


def test_consensus_returns_degraded_when_no_provider_responds(monkeypatch):
    monkeypatch.setattr(ai, "load", lambda: _config())
    analyzer = ai.AIAnalyzer()
    monkeypatch.setattr(analyzer, "discover_models", lambda force=False: {
        "gemini": ["gemini-test"], "groq": ["groq-test"], "openrouter": [], "routerai": []
    })
    monkeypatch.setattr(analyzer, "_call", lambda provider, model, prompt: None)

    result = analyzer.analyze_consensus({"event_type": "health_check"})

    assert result["winner"] == "unknown"
    assert result["consensus"] is False
    assert result["degraded"] is True
    assert result["providers_used"] == 0


def test_analyze_without_any_provider_returns_unknown(monkeypatch):
    monkeypatch.setattr(ai, "load", lambda: _config(gemini_key="", groq_key=""))
    analyzer = ai.AIAnalyzer()

    assert analyzer.analyze({"event_type": "health_check"}) == "unknown"
