from unittest.mock import patch

from xfi_guard.routerai import RouterAIAdapter


def test_routerai_excludes_media_models_from_chat_pool():
    assert RouterAIAdapter._is_chat_model("qwen/qwen3.7-plus")
    assert not RouterAIAdapter._is_chat_model("alibaba/happyhorse-1.0")
    assert not RouterAIAdapter._is_chat_model("google/gemini-3.1-flash-image")
    assert not RouterAIAdapter._is_chat_model("openai/sora-2-pro")


def test_routerai_free_first_and_paid_policy():
    adapter = RouterAIAdapter("test-key")
    models = ["free/provider-chat", "paid/provider-chat", "alibaba/happyhorse-1.0"]

    with patch.object(adapter, "models", return_value=models), patch.object(
        adapter, "free_models", return_value=["free/provider-chat"]
    ):
        assert adapter.ordered_models(allow_paid=False) == ["free/provider-chat"]
        assert adapter.ordered_models(allow_paid=True) == [
            "free/provider-chat",
            "paid/provider-chat",
        ]


def test_routerai_selected_paid_model_is_only_allowed_by_policy():
    adapter = RouterAIAdapter("test-key")
    models = ["free/provider-chat", "paid/provider-chat"]

    with patch.object(adapter, "models", return_value=models), patch.object(
        adapter, "free_models", return_value=["free/provider-chat"]
    ):
        with patch.object(adapter, "_request", return_value={
            "choices": [{"message": {"content": "OK"}}]
        }) as request:
            assert adapter.analyze("paid/provider-chat", "test", allow_paid=False) == "OK"
            assert request.call_args.kwargs["payload"]["model"] == "free/provider-chat"

        with patch.object(adapter, "_request", return_value={
            "choices": [{"message": {"content": "OK"}}]
        }) as request:
            assert adapter.analyze("paid/provider-chat", "test", allow_paid=True) == "OK"
            assert request.call_args.kwargs["payload"]["model"] == "free/provider-chat"
