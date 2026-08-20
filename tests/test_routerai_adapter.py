from unittest.mock import patch

from xfi_guard.routerai import RouterAIAdapter


def test_non_chat_model_markers_are_rejected():
    rejected = [
        "google/gemini-3.1-flash-image",
        "openai/sora-2-pro",
        "x-ai/grok-imagine-video",
        "alibaba/happyhorse-1.0",
        "cohere/rerank-4-pro",
        "runway/gen-4.5",
    ]
    for model in rejected:
        assert RouterAIAdapter._is_chat_model(model) is False


def test_chat_model_is_allowed():
    assert RouterAIAdapter._is_chat_model("provider/free-chat") is True
    assert RouterAIAdapter._is_chat_model("google/gemma-4-31b-it:free") is True


def test_endpoint_capabilities_accept_chat_completions():
    endpoint = {
        "supported_apis": ["chat/completions"],
        "output_modalities": ["text"],
    }
    assert RouterAIAdapter._is_chat_endpoint(endpoint) is True


def test_endpoint_capabilities_reject_image_only():
    endpoint = {
        "supported_apis": ["images/generations"],
        "output_modalities": ["image"],
    }
    assert RouterAIAdapter._is_chat_endpoint(endpoint) is False


def test_free_models_require_zero_price_chat_endpoint():
    adapter = RouterAIAdapter("test-key")
    adapter._models_cache = ["provider/free-chat", "provider/image-model"]
    with patch.object(adapter, "_endpoint_info", side_effect=[
        [{"status": 0, "supported_apis": ["chat/completions"], "output_modalities": ["text"], "pricing": {"prompt": "0", "completion": "0"}}],
        [{"status": 0, "supported_apis": ["images/generations"], "output_modalities": ["image"], "pricing": {"prompt": "0", "completion": "0"}}],
    ]):
        result = adapter.free_models(force=True)
    assert result == ["provider/free-chat"]


def test_ordered_models_prioritizes_free_and_hides_paid_when_disabled():
    adapter = RouterAIAdapter("test-key")
    with patch.object(adapter, "models", return_value=["provider/paid-chat", "provider/free-chat"]), \
         patch.object(adapter, "free_models", return_value=["provider/free-chat"]):
        assert adapter.ordered_models(allow_paid=False, preferred="provider/paid-chat") == ["provider/free-chat"]
        assert adapter.ordered_models(allow_paid=True, preferred="provider/paid-chat") == ["provider/free-chat", "provider/paid-chat"]
