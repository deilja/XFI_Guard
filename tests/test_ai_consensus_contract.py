from xfi_guard.ai import AIAnalyzer


def _analyzer(monkeypatch, verdicts):
    analyzer = object.__new__(AIAnalyzer)
    analyzer.min_consensus = 0.60
    analyzer.weights = {"gemini": 1.0, "groq": 1.0, "openrouter": 1.0, "routerai": 1.0}
    analyzer.last_provider_errors = {}
    analyzer._failures = {}
    analyzer.max_workers = 4
    analyzer._sync_config = lambda: None
    analyzer._jobs = lambda: [(p, f"{p}-model") for p, _ in verdicts]
    analyzer._prompt = lambda event: "test"
    analyzer._call = lambda provider, model, prompt: {"risk": next(v[1]["risk"] for v in verdicts if v[0] == provider), "confidence": next(v[1]["confidence"] for v in verdicts if v[0] == provider), "reason": "test"}
    analyzer._parse_verdict = lambda text: text
    analyzer.available_providers = lambda: [p for p, _ in verdicts]
    analyzer._models_for = lambda provider: [f"{provider}-model"]
    analyzer.configured_providers = analyzer.available_providers
    return analyzer


def test_single_provider_is_not_consensus(monkeypatch):
    analyzer = _analyzer(monkeypatch, [("gemini", {"risk": "critical", "confidence": 0.99})])
    result = analyzer.analyze_consensus({"event": "test"})
    assert result["providers_used"] == 1
    assert result["consensus"] is False
    assert result["degraded"] is False


def test_two_agreeing_providers_form_consensus(monkeypatch):
    analyzer = _analyzer(monkeypatch, [
        ("gemini", {"risk": "critical", "confidence": 0.95}),
        ("groq", {"risk": "critical", "confidence": 0.93}),
    ])
    result = analyzer.analyze_consensus({"event": "test"})
    assert result["providers_used"] == 2
    assert result["consensus"] is True
    assert result["degraded"] is False
    assert result["winner"] == "critical"


def test_conflicting_providers_do_not_form_consensus(monkeypatch):
    analyzer = _analyzer(monkeypatch, [
        ("gemini", {"risk": "critical", "confidence": 0.95}),
        ("groq", {"risk": "low", "confidence": 0.95}),
    ])
    result = analyzer.analyze_consensus({"event": "test"})
    assert result["providers_used"] == 2
    assert result["consensus"] is False
    assert result["conflict"] > 0


def test_partial_provider_failure_is_degraded(monkeypatch):
    analyzer = _analyzer(monkeypatch, [
        ("gemini", {"risk": "critical", "confidence": 0.95}),
        ("groq", {"risk": "critical", "confidence": 0.95}),
        ("openrouter", {"risk": "critical", "confidence": 0.95}),
    ])
    analyzer._jobs = lambda: [("gemini", "gemini-model"), ("groq", "groq-model"), ("openrouter", "openrouter-model")]
    original_call = analyzer._call
    def partial_call(provider, model, prompt):
        if provider == "openrouter":
            return None
        return original_call(provider, model, prompt)
    analyzer._call = partial_call
    result = analyzer.analyze_consensus({"event": "test"})
    assert result["consensus"] is True
    assert result["degraded"] is True
