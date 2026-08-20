from unittest.mock import Mock, patch

from xfi_guard.ai import AIAnalyzer


def test_ai_analyzer_exposes_public_analyze():
    assert callable(getattr(AIAnalyzer, "analyze", None))


def test_routerai_public_analyze_passes_paid_policy():
    ai = AIAnalyzer(provider="routerai")
    ai.routerai_key = "test-key"
    ai.routerai_enabled = True
    ai.routerai_allow_paid = False
    ai.routerai_model = "free/provider-chat"
    ai.routerai_models = ["free/provider-chat"]
    ai.routerai = Mock()
    ai.routerai.analyze.return_value = "OK"

    with patch.object(ai, "_models_for", return_value=["free/provider-chat"]):
        result = ai.analyze("Reply with exactly OK")

    assert result == "OK"
    ai.routerai.analyze.assert_called_once_with(
        "free/provider-chat",
        "Reply with exactly OK",
        allow_paid=False,
    )
