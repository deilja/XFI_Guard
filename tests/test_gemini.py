from xfi_guard.gemini import GeminiAnalyzer


def test_gemini_disabled_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    analyzer = GeminiAnalyzer()
    assert not analyzer.enabled()
    assert analyzer.analyze({"severity": "critical"}) is None


def test_gemini_model_default():
    analyzer = GeminiAnalyzer(api_key="test")
    assert analyzer.model == "gemini-2.5-pro"
