from xfi_guard.ai import AIAnalyzer
from xfi_guard.ai_config import AISettings
from xfi_guard.routerai import RouterAIAdapter


def test_ai_analyzer_keeps_legacy_analyze_api():
    assert hasattr(AIAnalyzer, "analyze")


def test_routerai_chat_endpoint_filter():
    assert RouterAIAdapter._is_chat_endpoint(
        {
            "supported_apis": ["chat", "responses"],
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
        }
    )
    assert not RouterAIAdapter._is_chat_endpoint(
        {
            "supported_apis": ["chat"],
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["image"],
            },
        }
    )


def test_paid_routerai_is_allowed_by_default():
    assert AISettings().routerai_allow_paid is True
